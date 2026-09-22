"""북(Book) 집계와 리스크 한도 점검."""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from app.conventions import RiskLimits
from app.linear import RATIO, LinearValuation, fmt


@dataclass(frozen=True)
class BookItem:
    ref: str            # 화면 표시용 식별자 (예: "#3 005930")
    asset_class: str
    valuation: LinearValuation


@dataclass
class Totals:
    position_count: int = 0
    gross_exposure: Decimal = Decimal(0)
    net_exposure: Decimal = Decimal(0)
    gross_pnl: Decimal = Decimal(0)
    total_costs: Decimal = Decimal(0)
    net_pnl: Decimal = Decimal(0)

    def add(self, v: LinearValuation) -> None:
        self.position_count += 1
        self.gross_exposure += abs(v.signed_exposure)
        self.net_exposure += v.signed_exposure
        self.gross_pnl += v.gross_pnl
        self.total_costs += v.total_costs
        self.net_pnl += v.net_pnl


@dataclass(frozen=True)
class LimitBreach:
    code: str
    message: str
    limit: Decimal
    actual: Decimal


@dataclass(frozen=True)
class LimitUsage:
    """한도 대비 사용률. 화면에서 계산하지 않도록 엔진이 비율까지 내려준다."""
    code: str
    label: str
    used: Decimal
    limit: Decimal
    ratio: Decimal   # used ÷ limit, 소수점 6자리 반올림


@dataclass(frozen=True)
class BookSummary:
    totals: Totals
    by_asset_class: dict[str, Totals] = field(default_factory=dict)
    breaches: tuple[LimitBreach, ...] = ()


def check_book_limits(totals: Totals, limits: RiskLimits) -> list[LimitBreach]:
    breaches: list[LimitBreach] = []
    if totals.gross_exposure > limits.max_gross_exposure:
        breaches.append(LimitBreach(
            "GROSS_EXPOSURE",
            f"북 총노출 {fmt(totals.gross_exposure)}원이 한도 {fmt(limits.max_gross_exposure)}원을 넘었습니다.",
            limits.max_gross_exposure, totals.gross_exposure))
    if totals.net_pnl < -limits.max_loss:
        breaches.append(LimitBreach(
            "LOSS_LIMIT",
            f"북 평가손실 {fmt(-totals.net_pnl)}원이 손실한도 {fmt(limits.max_loss)}원을 넘었습니다.",
            limits.max_loss, -totals.net_pnl))
    return breaches


def check_position_limits(items: Iterable[BookItem], limits: RiskLimits) -> list[LimitBreach]:
    breaches: list[LimitBreach] = []
    for item in items:
        notional = abs(item.valuation.signed_exposure)
        if notional > limits.max_position_notional:
            breaches.append(LimitBreach(
                "POSITION_NOTIONAL",
                f"{item.ref} 명목금액 {fmt(notional)}원이 단일 포지션 한도 "
                f"{fmt(limits.max_position_notional)}원을 넘었습니다.",
                limits.max_position_notional, notional))
    return breaches


def limit_usage(totals: Totals, largest_notional: Decimal, limits: RiskLimits) -> list[LimitUsage]:
    """총노출·손실·단일 포지션 세 한도의 사용률.

    손실 한도는 손실일 때만 소진된다(이익은 0으로 본다).
    단일 포지션은 북에서 가장 큰 명목금액(largest_notional)을 기준으로 한다.
    """
    largest = largest_notional
    loss = -totals.net_pnl if totals.net_pnl < 0 else Decimal(0)
    rows = [
        ("GROSS_EXPOSURE", "총노출 한도", totals.gross_exposure, limits.max_gross_exposure),
        ("LOSS_LIMIT", "손실 한도", loss, limits.max_loss),
        ("POSITION_NOTIONAL", "단일 포지션 한도", largest, limits.max_position_notional),
    ]
    return [
        LimitUsage(code, label, used, cap,
                   (used / cap).quantize(RATIO, rounding=ROUND_HALF_UP) if cap > 0 else Decimal(0))
        for code, label, used, cap in rows
    ]


def summarize_book(items: Sequence[BookItem], limits: RiskLimits) -> BookSummary:
    totals = Totals()
    by_class: dict[str, Totals] = {}
    for item in items:
        totals.add(item.valuation)
        by_class.setdefault(item.asset_class, Totals()).add(item.valuation)
    breaches = check_position_limits(items, limits) + check_book_limits(totals, limits)
    return BookSummary(totals=totals, by_asset_class=by_class, breaches=tuple(breaches))
