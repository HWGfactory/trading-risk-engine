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
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from app import repository as repo
from app.conventions import Conventions, ContractSpec, TaxRule, load_conventions
from app.linear import LinearPosition, value_linear
from app.trades import Fill, InstrumentSpec as TradeSpec, PositionState, TradeResult, apply_trade
from app.portfolio import (BookItem, BookSummary, Totals, check_book_limits, limit_usage,
                           summarize_book)
from app.prices import PriceFetcher, PriceQuote, PriceUnavailable, fetch_latest_close
from app.schemas import (AppliedConventions, BookResponse, BookSummaryOut, BreachOut, ContractOut,
                         BookHistoryOut, HistoryRow, LatestValuationOut, LimitsOut,
                         LimitUsageOut, PositionOut, QuoteOut, ReconciliationOut, ReferenceOut,
                         RevaluedPosition, RevalueRequest, SnapshotResponse, SnapshotRow,
                         TaxRuleOut, TotalsOut, TraceStepOut, TradeCreate, TradeOut,
                         TradePreview, TradeResponse, TradeTerms, ValuationOut,
                         ValuationRequest, ValuationResponse)

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
    "side": "매매구분", "price": "체결가",
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


def resolve_terms_for_trade(req: TradeCreate, conv: Conventions):
    """체결 요청에서 거래승수·거래세 규칙·계약명세를 확정한다(설정 파일 기준)."""
    if req.asset_class == "EQUITY":
        assert req.market is not None
        return Decimal(1), conv.tax_rule(req.market), None
    assert req.contract_code is not None
    spec = conv.contract(req.contract_code)
    if not spec.is_on_tick(req.price):
        raise ValueError(f"체결가 {req.price}는 {spec.name} 호가단위 {spec.tick_size}의 배수가 아닙니다.")
    return spec.multiplier, None, spec


def _trade_out(row: sqlite3.Row) -> TradeOut:
    return TradeOut(
        id=int(row["id"]), instrument_id=int(row["instrument_id"]), symbol=row["symbol"],
        name=row["name"], asset_class=row["asset_class"], side=row["side"],
        quantity=int(row["quantity"]), price=Decimal(row["price"]),
        commission_rate=Decimal(row["commission_rate"]),
        closed_quantity=int(row["closed_quantity"]),
        realized_pnl=Decimal(int(row["realized_pnl"])),
        commission=Decimal(int(row["commission"])),
        transaction_tax=Decimal(int(row["transaction_tax"])),
        avg_price_after=Decimal(row["avg_price_after"]), qty_after=int(row["qty_after"]),
        traded_at=row["traded_at"],
    )


def position_from_row(row: sqlite3.Row, mark_price: Decimal, conv: Conventions) -> LinearPosition:
    """평가용 포지션. 진입가 자리에 이동평균 단가가 들어간다."""
    market = row["market"]
    net = int(row["net_quantity"])
    return LinearPosition(
        asset_class=row["asset_class"],
        direction="LONG" if net > 0 else "SHORT",
        quantity=abs(net),
        entry_price=Decimal(row["avg_price"]),
        mark_price=mark_price,
        multiplier=Decimal(row["multiplier"]),
        commission_rate=Decimal(row["commission_rate"]),
        tax_rule=conv.tax_rule(market) if market else None,
        margin_rate=Decimal(row["margin_rate"]) if row["margin_rate"] is not None else None,
        # 실제로 낸 진입 수수료를 쓴다. 추정하지 않는다.
        entry_commission_paid=Decimal(int(row["entry_cost"])),
    )


def instrument_spec(row: sqlite3.Row, conv: Conventions) -> TradeSpec:
    market = row["market"]
    return TradeSpec(
        asset_class=row["asset_class"],
        multiplier=Decimal(row["multiplier"]),
        tax_rule=conv.tax_rule(market) if market else None,
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
    net = int(row["net_quantity"])
    avg = Decimal(row["avg_price"])
    return PositionOut(
        id=row["id"], instrument_id=int(row["instrument_id"]),
        symbol=row["symbol"], name=row["name"], asset_class=row["asset_class"],
        market=row["market"], contract_code=row["contract_code"], multiplier=Decimal(row["multiplier"]),
        net_quantity=net, direction="LONG" if net >= 0 else "SHORT", quantity=abs(net),
        avg_price=avg, entry_price=avg,
        realized_pnl=Decimal(int(row["realized_pnl"])), entry_cost=Decimal(int(row["entry_cost"])),
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


def _apply_fill(conn: sqlite3.Connection, req: TradeCreate, conv: Conventions,
                *, persist: bool) -> tuple[sqlite3.Row, TradeResult, TradeSpec, int]:
    """체결 한 건을 해석한다. persist=False면 DB를 바꾸지 않고 결과만 계산한다(미리보기)."""
    multiplier, _, spec = resolve_terms_for_trade(req, conv)
    if persist:
        instrument_id = repo.upsert_instrument(
            conn, symbol=req.symbol, name=req.name or (spec.name if spec else None),
            asset_class=req.asset_class, market=req.market,
            contract_code=req.contract_code, multiplier=multiplier)
        pos_row = repo.get_or_create_position(conn, instrument_id=instrument_id)
    else:
        found = conn.execute(
            "SELECT id FROM instruments WHERE symbol = ? AND asset_class = ?",
            (req.symbol, req.asset_class)).fetchone()
        instrument_id = int(found["id"]) if found else 0
        pos_row = repo.get_or_create_position(conn, instrument_id=instrument_id) if instrument_id else None

    before = PositionState(
        net_quantity=int(pos_row["net_quantity"]) if pos_row else 0,
        avg_price=Decimal(pos_row["avg_price"]) if pos_row else Decimal(0),
        realized_pnl=Decimal(int(pos_row["realized_pnl"])) if pos_row else Decimal(0),
        entry_cost=Decimal(int(pos_row["entry_cost"])) if pos_row else Decimal(0),
    )
    tspec = TradeSpec(asset_class=req.asset_class, multiplier=multiplier,
                      tax_rule=conv.tax_rule(req.market) if req.market else None)
    result = apply_trade(before, Fill(req.side, req.quantity, req.price, req.commission_rate), tspec)
    return pos_row, result, tspec, instrument_id


@app.post("/api/trades", response_model=TradeResponse, status_code=201)
def create_trade(req: TradeCreate, conn: sqlite3.Connection = Depends(get_db),
                 conv: Conventions = Depends(get_conventions)) -> TradeResponse:
    """체결 입력. instrument upsert, 포지션 증분 갱신, 체결 저장을 한 트랜잭션으로 처리한다."""
    try:
        pos_row, result, _, instrument_id = _apply_fill(conn, req, conv, persist=True)
        repo.update_position(
            conn, position_id=int(pos_row["id"]),
            net_quantity=result.after.net_quantity, avg_price=result.after.avg_price,
            realized_pnl=result.after.realized_pnl, entry_cost=result.after.entry_cost,
            commission_rate=req.commission_rate, margin_rate=req.margin_rate)
        trade_id = repo.insert_trade(
            conn, instrument_id=instrument_id, side=req.side, quantity=req.quantity,
            price=req.price, commission_rate=req.commission_rate,
            closed_quantity=result.closed_quantity, realized_pnl=result.realized_delta,
            commission=result.commission, transaction_tax=result.transaction_tax,
            avg_price_after=result.after.avg_price, qty_after=result.after.net_quantity)
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    trade_row = conn.execute(
        """SELECT t.*, i.symbol, i.name, i.asset_class
           FROM trades t JOIN instruments i ON i.id = t.instrument_id WHERE t.id = ?""",
        (trade_id,)).fetchone()
    position = repo.find_position_by_instrument(conn, instrument_id)
    assert position is not None

    if result.closed_quantity and result.after.is_flat:
        message = f"{req.quantity}주를 청산해 포지션을 닫았습니다."
    elif result.closed_quantity and len(result.legs) == 2:
        side_word = "매도" if req.side == "SELL" else "매수"
        message = (f"{result.closed_quantity}주를 청산하고 남은 "
                   f"{req.quantity - result.closed_quantity}주로 {side_word} 포지션을 새로 잡았습니다.")
    elif result.closed_quantity:
        message = f"{result.closed_quantity}주를 부분 청산했습니다."
    else:
        message = f"평균단가가 {result.after.avg_price}가 되었습니다."

    return TradeResponse(
        trade=_trade_out(trade_row),
        position=position_out(position),
        trace=[TraceStepOut(**st.__dict__) for st in result.trace],
        realized_gross=result.realized_gross,
        message=message,
    )


@app.post("/api/trades/preview", response_model=TradePreview)
def preview_trade(req: TradeCreate, conn: sqlite3.Connection = Depends(get_db),
                  conv: Conventions = Depends(get_conventions)) -> TradePreview:
    """체결 전 미리보기. DB를 바꾸지 않는다."""
    try:
        pos_row, result, _, _ = _apply_fill(conn, req, conv, persist=False)
    finally:
        conn.rollback()
    return TradePreview(
        holds=result.before.net_quantity != 0,
        net_quantity_before=result.before.net_quantity,
        avg_price_before=result.before.avg_price,
        net_quantity_after=result.after.net_quantity,
        avg_price_after=result.after.avg_price,
        closed_quantity=result.closed_quantity,
        realized_gross=result.realized_gross,
        trace=[TraceStepOut(**st.__dict__) for st in result.trace],
    )


@app.get("/api/trades", response_model=list[TradeOut])
def list_trades(instrument_id: int | None = None,
                conn: sqlite3.Connection = Depends(get_db)) -> list[TradeOut]:
    return [_trade_out(r) for r in repo.list_trades(conn, instrument_id)]


@app.post("/api/positions/{position_id}/close", response_model=TradeResponse)
def close_position(position_id: int, conn: sqlite3.Connection = Depends(get_db),
                   conv: Conventions = Depends(get_conventions)) -> TradeResponse:
    """청산은 이제 '반대 방향 전량 체결'로 동작한다.

    예전처럼 상태만 CLOSED로 바꾸지 않는다. 체결이 한 건 쌓이고 실현손익이 확정된다.
    평가가격이 필요하므로 최근 평가가 있어야 한다.
    """
    row = repo.get_position(conn, position_id)
    if row is None or row["status"] != "OPEN" or int(row["net_quantity"]) == 0:
        raise HTTPException(status_code=404, detail=["열려 있는 포지션을 찾을 수 없습니다."])
    if row["mark_price"] is None:
        raise HTTPException(status_code=409, detail=[
            "청산 가격을 알 수 없습니다. 먼저 재평가해 평가가격을 확정하거나, 체결 입력으로 직접 청산하세요."])

    net = int(row["net_quantity"])
    req = TradeCreate(
        asset_class=row["asset_class"], side="SELL" if net > 0 else "BUY",
        symbol=row["symbol"], name=row["name"], quantity=abs(net),
        price=Decimal(row["mark_price"]), market=row["market"],
        contract_code=row["contract_code"], commission_rate=Decimal(row["commission_rate"]),
        margin_rate=Decimal(row["margin_rate"]) if row["margin_rate"] is not None else None,
    )
    return create_trade(req, conn, conv)


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
            direction="LONG" if int(row["net_quantity"]) > 0 else "SHORT",
            quantity=abs(int(row["net_quantity"])), entry_price=Decimal(row["avg_price"]),
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
    usage = limit_usage(overall, repo.largest_position_notional(conn), conv.limits)
    return BookSummaryOut(
        totals=TotalsOut.from_engine(overall),
        by_asset_class={k: TotalsOut.from_engine(v) for k, v in by_class.items()},
        breaches=[BreachOut.from_engine(b) for b in breaches],
        limit_usage=[LimitUsageOut.from_engine(u) for u in usage],
        last_valued_at=repo.last_valued_at(conn),
    )


# ---------- 일별 스냅샷 ----------

def seoul_today() -> str:
    """스냅샷 날짜는 Asia/Seoul 기준이다.

    SQLite의 datetime('now')는 UTC라서 한국 저녁에 찍으면 전날로 기록된다.
    """
    return datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()


@app.post("/api/book/snapshot", response_model=SnapshotResponse, status_code=201)
def take_snapshot(revise: bool = False, conn: sqlite3.Connection = Depends(get_db),
                  conv: Conventions = Depends(get_conventions)) -> SnapshotResponse:
    """오늘(한국 시간) 날짜로 스냅샷을 저장한다.

    이미 찍힌 날이면 409로 거절한다. 덮어쓰지 않는다.
    다시 찍어야 하면 ?revise=true로 정정본(revision +1)을 새 행으로 추가한다.
    이전 행은 그대로 남는다.
    """
    snapshot_date = seoul_today()
    existing = repo.snapshot_exists(conn, snapshot_date)
    if existing and not revise:
        raise HTTPException(status_code=409, detail=[
            f"{snapshot_date} 스냅샷이 이미 있습니다(정정본 {existing}). "
            "스냅샷은 덮어쓰지 않습니다. 다시 찍으려면 정정본으로 추가하세요."])
    revision = existing + 1

    rows: list[SnapshotRow] = []
    errors: list[str] = []
    for row in repo.list_open_positions(conn):
        pid, symbol = row["id"], row["symbol"]
        if row["mark_price"] is None:
            errors.append(f"#{pid} {symbol}: 평가 이력이 없어 스냅샷에 담지 못했습니다. 먼저 재평가하세요.")
            continue
        mark = Decimal(row["mark_price"])
        try:
            valuation = value_linear(position_from_row(row, mark, conv))
        except ValueError as exc:
            errors.append(f"#{pid} {symbol}: {exc}")
            continue
        realized = Decimal(int(row["realized_pnl"]))
        repo.insert_snapshot(
            conn, snapshot_date=snapshot_date, revision=revision,
            instrument_id=int(row["instrument_id"]), mark_price=mark,
            price_source=row["price_source"], net_quantity=int(row["net_quantity"]),
            avg_price=Decimal(row["avg_price"]), unrealized_pnl=valuation.net_pnl,
            realized_pnl_cumulative=realized, signed_exposure=valuation.signed_exposure)
        rows.append(SnapshotRow(
            instrument_id=int(row["instrument_id"]), symbol=symbol, name=row["name"],
            net_quantity=int(row["net_quantity"]), avg_price=Decimal(row["avg_price"]),
            mark_price=mark, price_source=row["price_source"],
            unrealized_pnl=valuation.net_pnl, realized_pnl_cumulative=realized,
            signed_exposure=valuation.signed_exposure))
    conn.commit()
    return SnapshotResponse(snapshot_date=snapshot_date, revision=revision,
                            rows=rows, errors=errors)


@app.get("/api/book/history", response_model=BookHistoryOut)
def book_history(conn: sqlite3.Connection = Depends(get_db)) -> BookHistoryOut:
    return BookHistoryOut(rows=[
        HistoryRow(
            snapshot_date=r["snapshot_date"], position_count=int(r["position_count"]),
            unrealized_pnl=Decimal(int(r["unrealized_pnl"])),
            realized_pnl_cumulative=Decimal(int(r["realized_pnl_cumulative"])),
            gross_exposure=Decimal(int(r["gross_exposure"])),
            net_exposure=Decimal(int(r["net_exposure"])),
        )
        for r in repo.book_history(conn)
    ])
