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


class PositionCreate(TradeTerms):
    symbol: str = Field(min_length=1, max_length=40)
    name: str | None = Field(default=None, max_length=80)

    @model_validator(mode="after")
    def _check_symbol(self) -> PositionCreate:
        if self.asset_class == "EQUITY":
            self.symbol = normalize_ticker(self.symbol)
        else:
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
    direction: Direction
    quantity: int
    entry_price: Decimal
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
