"""선형 상품(주식·선물) 시가평가·손익 엔진.

원칙
- 금액 계산에 float을 쓰지 않는다. 모든 값은 Decimal.
- 비용(수수료·세금)은 원 미만 절사, 명목금액·손익은 원 단위 반올림.
- 계산 단계마다 TraceStep을 남겨 화면에서 '근거'로 보여준다.
- 이 모듈은 I/O(네트워크·DB)를 하지 않는 순수 함수로 유지한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from typing import Literal

from app.conventions import TaxRule

AssetClass = Literal["EQUITY", "FUTURE"]
Direction = Literal["LONG", "SHORT"]

WON = Decimal("1")
RATIO = Decimal("0.000001")


def floor_won(x: Decimal) -> Decimal:
    """원 미만 절사 (비용 항목)."""
    return x.quantize(WON, rounding=ROUND_DOWN)


def round_won(x: Decimal) -> Decimal:
    """원 단위 반올림 (명목금액·손익)."""
    return x.quantize(WON, rounding=ROUND_HALF_UP)


def fmt(x: Decimal | int) -> str:
    """근거 문자열용 숫자 표기."""
    x = Decimal(x)
    text = f"{x:,.0f}" if x == x.to_integral_value() else f"{x.normalize():,f}"
    return text.replace("-", "−")


def pct(rate: Decimal) -> str:
    return f"{(rate * 100).normalize():f}%"


@dataclass(frozen=True)
class LinearPosition:
    asset_class: AssetClass
    direction: Direction
    quantity: int                       # 주식: 주, 선물: 계약
    entry_price: Decimal
    mark_price: Decimal                 # 평가가격(종가 또는 수동 입력)
    multiplier: Decimal = Decimal(1)    # 주식 1, 선물은 계약명세의 거래승수
    commission_rate: Decimal = Decimal(0)
    tax_rule: TaxRule | None = None     # 주식이면 필수
    margin_rate: Decimal | None = None  # 선물이면 선택
    # 실제로 낸 진입 수수료. 체결 기반 포지션은 이 값을 알고 있으므로 추정하지 않는다.
    # None이면 예전처럼 진입 명목금액 × 수수료율로 추정한다.
    entry_commission_paid: Decimal | None = None

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError("수량은 1 이상이어야 합니다.")
        if self.entry_price <= 0 or self.mark_price <= 0:
            raise ValueError("가격은 0보다 커야 합니다.")
        if self.multiplier <= 0:
            raise ValueError("거래승수는 0보다 커야 합니다.")
        if not (Decimal(0) <= self.commission_rate < Decimal(1)):
            raise ValueError("수수료율은 0 이상 1 미만이어야 합니다.")
        if self.asset_class == "EQUITY":
            if self.tax_rule is None:
                raise ValueError("주식은 거래세 산정을 위해 시장(KOSPI/KOSDAQ)이 필요합니다.")
            if self.margin_rate is not None:
                raise ValueError("증거금률은 선물에만 적용합니다.")
        if self.margin_rate is not None and not (Decimal(0) < self.margin_rate <= Decimal(1)):
            raise ValueError("증거금률은 0 초과 1 이하여야 합니다.")


@dataclass(frozen=True)
class TraceStep:
    """계산 한 단계의 근거.

    inputs는 이 값이 어떤 입력·설정값에서 나왔는지를 엔진이 직접 알려주는 목록이다.
    화면의 근거 추적(근거 줄 ↔ 입력 칸 상호 강조)이 이 목록만 보고 동작하므로,
    프론트가 의존 관계를 추측하지 않는다.

    식별자는 전표 입력 필드명(entry_price, mark_price, quantity, direction,
    commission_rate, margin_rate, market)과 설정값 키(multiplier, tax_rate,
    asset_class)를 쓴다.
    """
    key: str
    label: str
    formula: str
    value: Decimal
    inputs: tuple[str, ...] = ()


@dataclass(frozen=True)
class LinearValuation:
    entry_notional: Decimal
    mark_notional: Decimal
    signed_exposure: Decimal     # 매수 +, 매도 − (평가 명목 기준)
    gross_pnl: Decimal           # 비용 차감 전 평가손익
    entry_commission: Decimal
    exit_commission: Decimal     # 평가가로 청산한다고 가정한 추정치
    transaction_tax: Decimal
    total_costs: Decimal
    net_pnl: Decimal
    return_on_notional: Decimal
    initial_margin: Decimal | None
    current_margin: Decimal | None
    return_on_margin: Decimal | None
    trace: tuple[TraceStep, ...]


def value_linear(pos: LinearPosition) -> LinearValuation:
    is_long = pos.direction == "LONG"
    sign = Decimal(1) if is_long else Decimal(-1)
    qty = Decimal(pos.quantity)
    mult = pos.multiplier
    steps: list[TraceStep] = []

    entry_notional = round_won(pos.entry_price * qty * mult)
    steps.append(TraceStep(
        "entry_notional", "진입 명목금액",
        f"진입가 {fmt(pos.entry_price)} × 수량 {fmt(qty)} × 승수 {fmt(mult)}", entry_notional,
        ("entry_price", "quantity", "multiplier")))

    mark_notional = round_won(pos.mark_price * qty * mult)
    steps.append(TraceStep(
        "mark_notional", "평가 명목금액",
        f"평가가 {fmt(pos.mark_price)} × 수량 {fmt(qty)} × 승수 {fmt(mult)}", mark_notional,
        ("mark_price", "quantity", "multiplier")))

    gross_pnl = round_won(sign * (pos.mark_price - pos.entry_price) * qty * mult)
    steps.append(TraceStep(
        "gross_pnl", "평가손익 (비용 전)",
        f"({fmt(pos.mark_price)} − {fmt(pos.entry_price)}) × {fmt(qty)} × {fmt(mult)}"
        f" × {'(+1, 매수)' if is_long else '(−1, 매도)'}", gross_pnl,
        ("entry_price", "mark_price", "quantity", "multiplier", "direction")))

    rate = pos.commission_rate
    exit_commission = floor_won(mark_notional * rate)
    if pos.entry_commission_paid is not None:
        # 체결 이력이 있으면 실제로 낸 금액을 쓴다. 추정보다 정확하다.
        entry_commission = pos.entry_commission_paid
        entry_text = f"진입 실제 {fmt(entry_commission)}"
    else:
        entry_commission = floor_won(entry_notional * rate)
        entry_text = f"진입 {fmt(entry_notional)} × {pct(rate)}"
    steps.append(TraceStep(
        "commission", "수수료",
        f"{entry_text} + 청산 추정 {fmt(mark_notional)} × {pct(rate)}, 원 미만 절사",
        entry_commission + exit_commission,
        ("entry_price", "mark_price", "quantity", "multiplier", "commission_rate")))

    if pos.asset_class == "EQUITY":
        rule = pos.tax_rule
        assert rule is not None  # __post_init__에서 보장
        # 거래세는 매도 대금에 부과: 매수 포지션은 청산 매도(평가가 기준 추정), 매도 포지션은 진입 시점
        taxable = mark_notional if is_long else entry_notional
        leg = "청산 매도 대금" if is_long else "진입 매도 대금"
        securities_tax = floor_won(taxable * rule.securities_tax)
        rural_tax = floor_won(taxable * rule.rural_special_tax)
        transaction_tax = securities_tax + rural_tax
        formula = f"{leg} {fmt(taxable)} × 증권거래세 {pct(rule.securities_tax)}"
        if rule.rural_special_tax > 0:
            formula += f" + {fmt(taxable)} × 농특세 {pct(rule.rural_special_tax)}"
        # 과세 대상 금액이 매수는 평가가, 매도는 진입가에서 나오므로 의존 입력도 달라진다.
        taxed_price = "mark_price" if is_long else "entry_price"
        steps.append(TraceStep("transaction_tax", f"거래세 ({rule.market})",
                               formula + ", 원 미만 절사", transaction_tax,
                               (taxed_price, "quantity", "multiplier", "direction",
                                "market", "tax_rate")))
    else:
        transaction_tax = Decimal(0)
        steps.append(TraceStep("transaction_tax", "거래세",
                               "파생상품은 증권거래세 대상이 아님", transaction_tax,
                               ("asset_class",)))

    # 순손익 이후 단계는 앞 단계 전부를 합친 결과라, 앞서 쓰인 입력을 모두 물려받는다.
    upstream = tuple(dict.fromkeys(i for s in steps for i in s.inputs))

    total_costs = entry_commission + exit_commission + transaction_tax
    net_pnl = gross_pnl - total_costs
    steps.append(TraceStep("net_pnl", "순손익",
                           f"평가손익 {fmt(gross_pnl)} − 비용 {fmt(total_costs)}", net_pnl,
                           upstream))

    return_on_notional = (net_pnl / entry_notional).quantize(RATIO, rounding=ROUND_HALF_UP)
    steps.append(TraceStep("return_on_notional", "명목 대비 수익률",
                           f"{fmt(net_pnl)} ÷ {fmt(entry_notional)}", return_on_notional,
                           upstream))

    initial_margin = current_margin = return_on_margin = None
    if pos.asset_class == "FUTURE" and pos.margin_rate is not None:
        initial_margin = round_won(entry_notional * pos.margin_rate)
        current_margin = round_won(mark_notional * pos.margin_rate)
        return_on_margin = (net_pnl / initial_margin).quantize(RATIO, rounding=ROUND_HALF_UP)
        steps.append(TraceStep("initial_margin", "개시증거금 (진입 기준)",
                               f"{fmt(entry_notional)} × {pct(pos.margin_rate)}", initial_margin,
                               ("entry_price", "quantity", "multiplier", "margin_rate")))
        steps.append(TraceStep("return_on_margin", "증거금 대비 수익률",
                               f"{fmt(net_pnl)} ÷ {fmt(initial_margin)}", return_on_margin,
                               upstream + ("margin_rate",)))

    return LinearValuation(
        entry_notional=entry_notional,
        mark_notional=mark_notional,
        signed_exposure=sign * mark_notional,
        gross_pnl=gross_pnl,
        entry_commission=entry_commission,
        exit_commission=exit_commission,
        transaction_tax=transaction_tax,
        total_costs=total_costs,
        net_pnl=net_pnl,
        return_on_notional=return_on_notional,
        initial_margin=initial_margin,
        current_margin=current_margin,
        return_on_margin=return_on_margin,
        trace=tuple(steps),
    )
