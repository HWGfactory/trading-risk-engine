"""API 요청·응답 스키마 (Pydantic v2).

Decimal 값은 JSON에서 문자열로 직렬화된다(정밀도 보존). 프론트는 표시 직전에만 숫자로 바꾼다.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

from app.linear import LinearValuation
from app.portfolio import LimitBreach, LimitUsage, Totals
from app.prices import normalize_ticker

AssetClass = Literal["EQUITY", "FUTURE"]
Direction = Literal["LONG", "SHORT"]
Market = Literal["KOSPI", "KOSDAQ"]

Price = Annotated[Decimal, Field(gt=0, max_digits=18, decimal_places=4)]
Rate = Annotated[Decimal, Field(ge=0, lt=Decimal("0.01"), decimal_places=8)]


# ---------- 요청 ----------

class TradeTerms(BaseModel):
    asset_class: AssetClass
    direction: Direction
    quantity: int = Field(gt=0, le=10_000_000)
    entry_price: Price
    market: Market | None = None          # 주식 필수
    contract_code: str | None = None      # 선물 필수
    commission_rate: Rate = Decimal("0")
    margin_rate: Annotated[Decimal, Field(gt=0, le=1, decimal_places=6)] | None = None

    @model_validator(mode="after")
    def _check_terms(self) -> TradeTerms:
        if self.asset_class == "EQUITY":
            if self.market is None:
                raise ValueError("주식은 시장(KOSPI/KOSDAQ)을 선택해야 합니다.")
            if self.margin_rate is not None:
                raise ValueError("증거금률은 선물에만 적용합니다.")
            self.contract_code = None
        else:
            if not self.contract_code:
                raise ValueError("선물은 계약 종류를 선택해야 합니다.")
            self.market = None
        return self


class ValuationRequest(TradeTerms):
    mark_price: Price


class TradeCreate(BaseModel):
    """체결 입력. 포지션을 직접 만들지 않고 체결을 쌓는다."""
    asset_class: AssetClass
    side: Literal["BUY", "SELL"]
    symbol: str = Field(min_length=1, max_length=40)
    name: str | None = Field(default=None, max_length=80)
    quantity: int = Field(gt=0, le=10_000_000)
    price: Price
    market: Market | None = None          # 주식 필수
    contract_code: str | None = None      # 선물 필수
    commission_rate: Rate = Decimal("0")
    margin_rate: Annotated[Decimal, Field(gt=0, le=1, decimal_places=6)] | None = None

    @model_validator(mode="after")
    def _check(self) -> TradeCreate:
        if self.asset_class == "EQUITY":
            if self.market is None:
                raise ValueError("주식은 시장(KOSPI/KOSDAQ)을 선택해야 합니다.")
            if self.margin_rate is not None:
                raise ValueError("증거금률은 선물에만 적용합니다.")
            self.contract_code = None
            self.symbol = normalize_ticker(self.symbol)
        else:
            if not self.contract_code:
                raise ValueError("선물은 계약 종류를 선택해야 합니다.")
            self.market = None
            self.symbol = self.symbol.strip()
        return self


class RevalueRequest(BaseModel):
    marks: dict[int, Price] = Field(default_factory=dict)  # position_id → 평가가격(수동)


# ---------- 응답 ----------

class TraceStepOut(BaseModel):
    key: str
    label: str
    formula: str
    value: Decimal
    inputs: list[str]   # 이 값이 의존하는 입력·설정값 (화면의 근거 추적용)


class ValuationOut(BaseModel):
    entry_notional: Decimal
    mark_notional: Decimal
    signed_exposure: Decimal
    gross_pnl: Decimal
    entry_commission: Decimal
    exit_commission: Decimal
    transaction_tax: Decimal
    total_costs: Decimal
    net_pnl: Decimal
    return_on_notional: Decimal
    initial_margin: Decimal | None
    current_margin: Decimal | None
    return_on_margin: Decimal | None
    trace: list[TraceStepOut]

    @classmethod
    def from_engine(cls, v: LinearValuation) -> ValuationOut:
        data = {k: getattr(v, k) for k in cls.model_fields if k != "trace"}
        return cls(**data, trace=[TraceStepOut(**s.__dict__) for s in v.trace])


class AppliedConventions(BaseModel):
    multiplier: Decimal
    contract_name: str | None
    tax_market: str | None
    tax_rate_total: Decimal | None
    tax_source: str | None
    contract_source: str | None
    verified_as_of: str


class ValuationResponse(BaseModel):
    valuation: ValuationOut
    applied: AppliedConventions


class QuoteOut(BaseModel):
    ticker: str
    name: str | None
    close: Decimal
    as_of: date
    source: str
    is_stale: bool


class ContractOut(BaseModel):
    code: str
    name: str
    multiplier: Decimal
    tick_size: Decimal


class TaxRuleOut(BaseModel):
    market: str
    securities_tax: Decimal
    rural_special_tax: Decimal
    total: Decimal


class LimitsOut(BaseModel):
    max_position_notional: Decimal
    max_gross_exposure: Decimal
    max_loss: Decimal


class ReferenceOut(BaseModel):
    verified_as_of: str
    default_commission_rate: Decimal
    contracts: list[ContractOut]
    tax_rules: list[TaxRuleOut]
    tax_source: str
    contract_source: str
    limits: LimitsOut


class LatestValuationOut(BaseModel):
    valued_at: str
    mark_price: Decimal
    price_source: str
    price_as_of: str
    signed_exposure: Decimal
    gross_pnl: Decimal
    total_costs: Decimal
    net_pnl: Decimal


class PositionOut(BaseModel):
    id: int
    symbol: str
    name: str | None
    asset_class: AssetClass
    market: Market | None
    contract_code: str | None
    multiplier: Decimal
    # 체결을 합쳐 만든 현재 상태
    net_quantity: int          # 매수 +, 매도 −
    direction: Direction       # net_quantity 부호에서 파생한 표시용 값
    quantity: int              # abs(net_quantity)
    avg_price: Decimal         # 이동평균 단가 (예전 entry_price 자리)
    entry_price: Decimal       # avg_price와 같은 값. 기존 화면 호환용
    realized_pnl: Decimal      # 원 단위 누적 (비용 차감 후)
    entry_cost: Decimal        # 보유분에 대해 실제로 낸 진입 수수료
    commission_rate: Decimal
    margin_rate: Decimal | None
    opened_at: str
    latest: LatestValuationOut | None


class TotalsOut(BaseModel):
    position_count: int
    gross_exposure: Decimal
    net_exposure: Decimal
    gross_pnl: Decimal
    total_costs: Decimal
    net_pnl: Decimal

    @classmethod
    def from_engine(cls, t: Totals) -> TotalsOut:
        return cls(**t.__dict__)


class BreachOut(BaseModel):
    code: str
    message: str
    limit: Decimal
    actual: Decimal

    @classmethod
    def from_engine(cls, b: LimitBreach) -> BreachOut:
        return cls(**b.__dict__)


class RevaluedPosition(BaseModel):
    position_id: int
    symbol: str
    name: str | None
    asset_class: AssetClass
    direction: Direction
    quantity: int
    entry_price: Decimal
    mark_price: Decimal
    price_source: str
    price_as_of: date
    price_is_stale: bool
    valuation: ValuationOut


class ReconciliationOut(BaseModel):
    status: Literal["MATCHED", "MISMATCHED", "SKIPPED"]
    detail: str


class BookResponse(BaseModel):
    run_id: str
    positions: list[RevaluedPosition]
    totals: TotalsOut
    by_asset_class: dict[str, TotalsOut]
    breaches: list[BreachOut]
    reconciliation: ReconciliationOut
    errors: list[str]


class LimitUsageOut(BaseModel):
    code: str
    label: str
    used: Decimal
    limit: Decimal
    ratio: Decimal

    @classmethod
    def from_engine(cls, u: LimitUsage) -> LimitUsageOut:
        return cls(**u.__dict__)


class BookSummaryOut(BaseModel):
    """SQL 뷰(v_book_by_asset_class)에서 읽은 마지막 평가 기준 집계."""
    totals: TotalsOut
    by_asset_class: dict[str, TotalsOut]
    breaches: list[BreachOut]
    limit_usage: list[LimitUsageOut]
    last_valued_at: str | None


# ---------- 체결과 스냅샷 ----------

class TradeOut(BaseModel):
    id: int
    instrument_id: int
    symbol: str
    name: str | None
    asset_class: AssetClass
    side: Literal["BUY", "SELL"]
    quantity: int
    price: Decimal
    commission_rate: Decimal
    closed_quantity: int        # 이 체결 중 청산에 쓰인 수량
    realized_pnl: Decimal       # 이 체결이 확정한 실현손익 (비용 차감 후)
    commission: Decimal
    transaction_tax: Decimal
    avg_price_after: Decimal    # 이 체결 직후 평균단가
    qty_after: int              # 이 체결 직후 순수량
    traded_at: str


class TradeResponse(BaseModel):
    """체결 결과. 이 체결이 포지션을 어떻게 바꿨는지 근거와 함께 돌려준다."""
    trade: TradeOut
    position: PositionOut
    trace: list[TraceStepOut]
    realized_gross: Decimal     # 비용 차감 전
    message: str


class TradePreview(BaseModel):
    """체결 전 미리보기. 이미 보유 중이면 이번 체결 후 평균단가가 어떻게 되는지 보여준다."""
    holds: bool
    net_quantity_before: int
    avg_price_before: Decimal
    net_quantity_after: int
    avg_price_after: Decimal
    closed_quantity: int
    realized_gross: Decimal
    trace: list[TraceStepOut]


class SnapshotRow(BaseModel):
    instrument_id: int
    symbol: str
    name: str | None
    net_quantity: int
    avg_price: Decimal
    mark_price: Decimal
    price_source: str
    unrealized_pnl: Decimal
    realized_pnl_cumulative: Decimal
    signed_exposure: Decimal


class SnapshotResponse(BaseModel):
    snapshot_date: str          # Asia/Seoul 기준
    revision: int
    rows: list[SnapshotRow]
    errors: list[str]


class HistoryRow(BaseModel):
    snapshot_date: str
    position_count: int
    unrealized_pnl: Decimal
    realized_pnl_cumulative: Decimal
    gross_exposure: Decimal
    net_exposure: Decimal


class BookHistoryOut(BaseModel):
    rows: list[HistoryRow]
