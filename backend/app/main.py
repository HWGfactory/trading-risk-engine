"""FastAPI 진입점.

실행: (backend 폴더에서) uvicorn app.main:app --reload --port 8000
문서: http://127.0.0.1:8000/docs
"""
from __future__ import annotations

import os
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from app import repository as repo
from app.conventions import Conventions, ContractSpec, TaxRule, load_conventions
from app.linear import LinearPosition, value_linear
from app.portfolio import BookItem, BookSummary, Totals, check_book_limits, summarize_book
from app.prices import PriceFetcher, PriceQuote, PriceUnavailable, fetch_latest_close
from app.schemas import (AppliedConventions, BookResponse, BookSummaryOut, BreachOut, ContractOut,
                         LatestValuationOut, LimitsOut, PositionCreate, PositionOut, QuoteOut,
                         ReconciliationOut, ReferenceOut, RevaluedPosition, RevalueRequest,
                         TaxRuleOut, TotalsOut, TradeTerms, ValuationOut, ValuationRequest,
                         ValuationResponse)

BACKEND_DIR = Path(__file__).resolve().parent.parent


def db_path() -> Path:
    return Path(os.getenv("TRE_DB_PATH") or BACKEND_DIR / "data" / "trading.db")


@asynccontextmanager
async def lifespan(_: FastAPI):
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = repo.connect(path)
    repo.init_db(conn)
    conn.close()
    yield


app = FastAPI(title="PI 데스크 포지션 평가 엔진", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- 의존성 (테스트에서 override) ----------

def get_db() -> Iterator[sqlite3.Connection]:
    conn = repo.connect(db_path())
    try:
        yield conn
    finally:
        conn.close()


def get_conventions() -> Conventions:
    return load_conventions()


def get_price_fetcher() -> PriceFetcher:
    return fetch_latest_close


# ---------- 오류 응답 ----------

FIELD_LABELS = {
    "asset_class": "상품", "direction": "방향", "quantity": "수량", "entry_price": "진입가",
    "mark_price": "평가가격", "market": "시장", "contract_code": "계약", "symbol": "종목",
    "commission_rate": "수수료율", "margin_rate": "증거금률", "marks": "평가가격",
}


def _korean_message(err: dict) -> str:
    ctx = err.get("ctx") or {}
    t = err.get("type", "")
    if t == "greater_than":
        return f"{ctx.get('gt')}보다 커야 합니다."
    if t == "greater_than_equal":
        return f"{ctx.get('ge')} 이상이어야 합니다."
    if t == "less_than":
        return f"{ctx.get('lt')}보다 작아야 합니다."
    if t == "less_than_equal":
        return f"{ctx.get('le')} 이하여야 합니다."
    if t == "missing":
        return "필수 입력입니다."
    if t in ("decimal_parsing", "int_parsing", "int_from_float", "decimal_type"):
        return "숫자로 입력하세요."
    if t == "decimal_max_places":
        return f"소수점 {ctx.get('decimal_places')}자리까지 입력할 수 있습니다."
    if t == "literal_error":
        return "허용되지 않은 값입니다."
    return str(err.get("msg", "")).removeprefix("Value error, ")


@app.exception_handler(RequestValidationError)
async def _validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    messages = []
    for err in exc.errors():
        field = next((p for p in reversed(err["loc"]) if isinstance(p, str) and p != "body"), None)
        label = FIELD_LABELS.get(field or "", field)
        msg = _korean_message(err)
        messages.append(f"{label}: {msg}" if label else msg)
    return JSONResponse(status_code=422, content={"detail": messages})


@app.exception_handler(ValueError)
async def _value_error_handler(_: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": [str(exc)]})


@app.exception_handler(PriceUnavailable)
async def _price_handler(_: Request, exc: PriceUnavailable) -> JSONResponse:
    return JSONResponse(status_code=502, content={"detail": [str(exc)]})


# ---------- 공통 도우미 ----------

def resolve_terms(terms: TradeTerms, conv: Conventions,
                  mark_price: Decimal | None = None) -> tuple[Decimal, TaxRule | None, ContractSpec | None]:
    """상품 조건에서 거래승수·거래세 규칙·계약명세를 확정한다(모두 설정 파일 기준)."""
    if terms.asset_class == "EQUITY":
        assert terms.market is not None
        return Decimal(1), conv.tax_rule(terms.market), None
    assert terms.contract_code is not None
    spec = conv.contract(terms.contract_code)
    for label, price in (("진입가", terms.entry_price), ("평가가격", mark_price)):
        if price is not None and not spec.is_on_tick(price):
            raise ValueError(f"{label} {price}는 {spec.name} 호가단위 {spec.tick_size}의 배수가 아닙니다.")
    return spec.multiplier, None, spec


def position_from_row(row: sqlite3.Row, mark_price: Decimal, conv: Conventions) -> LinearPosition:
    market = row["market"]
    return LinearPosition(
        asset_class=row["asset_class"],
        direction=row["direction"],
        quantity=int(row["quantity"]),
        entry_price=Decimal(row["entry_price"]),
        mark_price=mark_price,
        multiplier=Decimal(row["multiplier"]),
        commission_rate=Decimal(row["commission_rate"]),
        tax_rule=conv.tax_rule(market) if market else None,
        margin_rate=Decimal(row["margin_rate"]) if row["margin_rate"] is not None else None,
    )


def position_out(row: sqlite3.Row) -> PositionOut:
    latest = None
    if row["valued_at"] is not None:
        latest = LatestValuationOut(
            valued_at=row["valued_at"], mark_price=Decimal(row["mark_price"]),
            price_source=row["price_source"], price_as_of=row["price_as_of"],
            signed_exposure=Decimal(row["signed_exposure"]), gross_pnl=Decimal(row["gross_pnl"]),
            total_costs=Decimal(row["total_costs"]), net_pnl=Decimal(row["net_pnl"]),
        )
    return PositionOut(
        id=row["id"], symbol=row["symbol"], name=row["name"], asset_class=row["asset_class"],
        market=row["market"], contract_code=row["contract_code"], multiplier=Decimal(row["multiplier"]),
        direction=row["direction"], quantity=row["quantity"], entry_price=Decimal(row["entry_price"]),
        commission_rate=Decimal(row["commission_rate"]),
        margin_rate=Decimal(row["margin_rate"]) if row["margin_rate"] is not None else None,
        opened_at=row["opened_at"], latest=latest,
    )


def totals_from_sql(rows: list[sqlite3.Row]) -> tuple[Totals, dict[str, Totals]]:
    by_class: dict[str, Totals] = {}
    overall = Totals()
    for r in rows:
        t = Totals(
            position_count=int(r["position_count"]),
            gross_exposure=Decimal(r["gross_exposure"]), net_exposure=Decimal(r["net_exposure"]),
            gross_pnl=Decimal(r["gross_pnl"]), total_costs=Decimal(r["total_costs"]),
            net_pnl=Decimal(r["net_pnl"]),
        )
        by_class[r["asset_class"]] = t
        for field in ("gross_exposure", "net_exposure", "gross_pnl", "total_costs", "net_pnl"):
            setattr(overall, field, getattr(overall, field) + getattr(t, field))
        overall.position_count += t.position_count
    return overall, by_class


def reconcile(engine_summary: BookSummary, sql_by_class: dict[str, Totals]) -> ReconciliationOut:
    """엔진(Python) 집계와 DB(SQL 뷰) 집계를 대사한다."""
    engine_by_class = engine_summary.by_asset_class
    if engine_by_class.keys() != sql_by_class.keys():
        return ReconciliationOut(status="MISMATCHED", detail="상품군 구성이 다릅니다.")
    for cls, t in engine_by_class.items():
        s = sql_by_class[cls]
        for field in ("position_count", "gross_exposure", "net_exposure", "gross_pnl", "total_costs", "net_pnl"):
            if getattr(t, field) != getattr(s, field):
                return ReconciliationOut(
                    status="MISMATCHED",
                    detail=f"{cls} {field}: 엔진 {getattr(t, field)} ≠ SQL {getattr(s, field)}")
    return ReconciliationOut(status="MATCHED", detail="엔진 집계와 SQL 뷰 집계가 일치합니다.")


# ---------- 라우트 ----------

@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/reference", response_model=ReferenceOut)
def reference(conv: Conventions = Depends(get_conventions)) -> ReferenceOut:
    return ReferenceOut(
        verified_as_of=conv.verified_as_of,
        default_commission_rate=conv.default_commission_rate,
        contracts=[ContractOut(code=c.code, name=c.name, multiplier=c.multiplier, tick_size=c.tick_size)
                   for c in conv.contracts.values()],
        tax_rules=[TaxRuleOut(market=r.market, securities_tax=r.securities_tax,
                              rural_special_tax=r.rural_special_tax, total=r.total)
                   for r in conv.tax_rules.values()],
        tax_source=conv.tax_source,
        contract_source=conv.contract_source,
        limits=LimitsOut(**conv.limits.__dict__),
    )


@app.get("/api/market/quote/{ticker}", response_model=QuoteOut)
def quote(ticker: str, fetch: PriceFetcher = Depends(get_price_fetcher)) -> QuoteOut:
    q = fetch(ticker)
    return QuoteOut(ticker=q.ticker, name=q.name, close=q.close, as_of=q.as_of,
                    source=q.source, is_stale=q.is_stale(date.today()))


@app.post("/api/valuation/linear", response_model=ValuationResponse)
def value_single(req: ValuationRequest, conv: Conventions = Depends(get_conventions)) -> ValuationResponse:
    multiplier, tax_rule, spec = resolve_terms(req, conv, req.mark_price)
    valuation = value_linear(LinearPosition(
        asset_class=req.asset_class, direction=req.direction, quantity=req.quantity,
        entry_price=req.entry_price, mark_price=req.mark_price, multiplier=multiplier,
        commission_rate=req.commission_rate, tax_rule=tax_rule, margin_rate=req.margin_rate,
    ))
    return ValuationResponse(
        valuation=ValuationOut.from_engine(valuation),
        applied=AppliedConventions(
            multiplier=multiplier,
            contract_name=spec.name if spec else None,
            tax_market=tax_rule.market if tax_rule else None,
            tax_rate_total=tax_rule.total if tax_rule else None,
            tax_source=conv.tax_source if tax_rule else None,
            contract_source=conv.contract_source if spec else None,
            verified_as_of=conv.verified_as_of,
        ),
    )


@app.get("/api/positions", response_model=list[PositionOut])
def list_positions(conn: sqlite3.Connection = Depends(get_db)) -> list[PositionOut]:
    return [position_out(r) for r in repo.list_open_positions(conn)]


@app.post("/api/positions", response_model=PositionOut, status_code=201)
def create_position(req: PositionCreate, conn: sqlite3.Connection = Depends(get_db),
                    conv: Conventions = Depends(get_conventions)) -> PositionOut:
    multiplier, _, spec = resolve_terms(req, conv)
    instrument_id = repo.upsert_instrument(
        conn, symbol=req.symbol, name=req.name or (spec.name if spec else None),
        asset_class=req.asset_class, market=req.market,
        contract_code=req.contract_code, multiplier=multiplier)
    position_id = repo.create_position(
        conn, instrument_id=instrument_id, direction=req.direction, quantity=req.quantity,
        entry_price=req.entry_price, commission_rate=req.commission_rate, margin_rate=req.margin_rate)
    conn.commit()
    row = repo.get_position(conn, position_id)
    assert row is not None
    return position_out(row)


@app.post("/api/positions/{position_id}/close", status_code=204)
def close_position(position_id: int, conn: sqlite3.Connection = Depends(get_db)) -> Response:
    if not repo.close_position(conn, position_id):
        raise HTTPException(status_code=404, detail=["열려 있는 포지션을 찾을 수 없습니다."])
    conn.commit()
    return Response(status_code=204)


@app.post("/api/book/revalue", response_model=BookResponse)
def revalue_book(req: RevalueRequest, conn: sqlite3.Connection = Depends(get_db),
                 conv: Conventions = Depends(get_conventions),
                 fetch: PriceFetcher = Depends(get_price_fetcher)) -> BookResponse:
    run_id = uuid.uuid4().hex[:12]
    today = date.today()
    quotes: dict[str, PriceQuote] = {}
    items: list[BookItem] = []
    results: list[RevaluedPosition] = []
    errors: list[str] = []

    for row in repo.list_open_positions(conn):
        pid, symbol = row["id"], row["symbol"]
        try:
            if pid in req.marks:
                mark, source, as_of, stale = req.marks[pid], "수동 입력", today, False
            elif row["asset_class"] == "EQUITY":
                if symbol not in quotes:
                    quotes[symbol] = fetch(symbol)
                q = quotes[symbol]
                mark, source, as_of, stale = q.close, q.source, q.as_of, q.is_stale(today)
            else:
                errors.append(f"#{pid} {symbol}: 선물은 평가가격을 직접 입력해야 합니다.")
                continue
            if row["contract_code"]:
                spec = conv.contract(row["contract_code"])
                if not spec.is_on_tick(mark):
                    raise ValueError(f"평가가격 {mark}는 호가단위 {spec.tick_size}의 배수가 아닙니다.")
            valuation = value_linear(position_from_row(row, mark, conv))
        except (ValueError, PriceUnavailable) as exc:
            errors.append(f"#{pid} {symbol}: {exc}")
            continue

        repo.save_price(conn, instrument_id=row["instrument_id"], price_date=as_of.isoformat(),
                        close_price=mark, source=source)
        repo.insert_valuation(conn, position_id=pid, run_id=run_id, mark_price=mark,
                              price_source=source, price_as_of=as_of.isoformat(), valuation=valuation)
        items.append(BookItem(f"#{pid} {symbol}", row["asset_class"], valuation))
        results.append(RevaluedPosition(
            position_id=pid, symbol=symbol, name=row["name"], asset_class=row["asset_class"],
            direction=row["direction"], quantity=row["quantity"], entry_price=Decimal(row["entry_price"]),
            mark_price=mark, price_source=source, price_as_of=as_of, price_is_stale=stale,
            valuation=ValuationOut.from_engine(valuation)))
    conn.commit()

    summary = summarize_book(items, conv.limits)
    if errors:
        reconciliation = ReconciliationOut(
            status="SKIPPED", detail="평가하지 못한 포지션이 있어 대사를 건너뜁니다.")
    else:
        _, sql_by_class = totals_from_sql(repo.book_by_asset_class(conn))
        reconciliation = reconcile(summary, sql_by_class)

    return BookResponse(
        run_id=run_id,
        positions=results,
        totals=TotalsOut.from_engine(summary.totals),
        by_asset_class={k: TotalsOut.from_engine(v) for k, v in summary.by_asset_class.items()},
        breaches=[BreachOut.from_engine(b) for b in summary.breaches],
        reconciliation=reconciliation,
        errors=errors,
    )


@app.get("/api/book/summary", response_model=BookSummaryOut)
def book_summary(conn: sqlite3.Connection = Depends(get_db),
                 conv: Conventions = Depends(get_conventions)) -> BookSummaryOut:
    overall, by_class = totals_from_sql(repo.book_by_asset_class(conn))
    breaches = check_book_limits(overall, conv.limits)
    return BookSummaryOut(
        totals=TotalsOut.from_engine(overall),
        by_asset_class={k: TotalsOut.from_engine(v) for k, v in by_class.items()},
        breaches=[BreachOut.from_engine(b) for b in breaches],
    )
