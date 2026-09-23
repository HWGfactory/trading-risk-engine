"""체결(trade) 기반 포지션 계산 엔진.

원칙
- 포지션은 직접 입력받는 값이 아니라 체결을 합쳐 만든 결과다.
- 실현손익은 이동평균법(moving average)으로 계산한다. 선입선출(FIFO)이 아니다.
  근거는 METHODOLOGY.md에 적었다.
- 금액 계산에 float을 쓰지 않는다. 평균단가는 소수 4자리 반올림, 금액은 원 단위,
  비용은 원 미만 절사.
- 이 모듈은 I/O(네트워크·DB)를 하지 않는 순수 함수로 유지한다.

세 규칙
  규칙 1 (증가)  같은 방향 추가 체결. 평균단가를 가중평균으로 갱신한다. 실현손익 없음.
  규칙 2 (청산)  반대 방향, 보유 수량 이내. 평균단가는 그대로 두고 수량만 줄인다.
  규칙 3 (전환)  반대 방향, 보유 수량 초과. 규칙 2로 전량 청산한 뒤 남은 수량이
                 새 포지션이 되고 평균단가는 이번 체결가가 된다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from typing import Literal

from app.conventions import TaxRule
from app.linear import TraceStep, floor_won, fmt, pct, round_won

Side = Literal["BUY", "SELL"]

PRICE4 = Decimal("0.0001")


def round_price(x: Decimal) -> Decimal:
    """평균단가는 나눗셈 결과라 딱 떨어지지 않는다. 소수 4자리 반올림."""
    return x.quantize(PRICE4, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class InstrumentSpec:
    """체결을 해석하는 데 필요한 종목 정보. 전부 설정 파일에서 온 값이다."""
    asset_class: str                  # EQUITY | FUTURE
    multiplier: Decimal = Decimal(1)
    tax_rule: TaxRule | None = None   # 주식만


@dataclass(frozen=True)
class Fill:
    """체결 한 건. quantity는 항상 양수이고 방향은 side가 정한다."""
    side: Side
    quantity: int
    price: Decimal
    commission_rate: Decimal = Decimal(0)

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError("체결 수량은 1 이상이어야 합니다.")
        if self.price <= 0:
            raise ValueError("체결가는 0보다 커야 합니다.")

    @property
    def signed_quantity(self) -> int:
        return self.quantity if self.side == "BUY" else -self.quantity


@dataclass(frozen=True)
class PositionState:
    """체결을 적용하기 전후의 포지션 상태.

    net_quantity 부호가 방향이다(매수 +, 매도 −). 0이면 보유하지 않는다.
    entry_cost는 '지금 보유한 수량에 대해 실제로 낸 진입 수수료' 누적이다.
    """
    net_quantity: int = 0
    avg_price: Decimal = Decimal(0)
    realized_pnl: Decimal = Decimal(0)
    entry_cost: Decimal = Decimal(0)

    @property
    def is_flat(self) -> bool:
        return self.net_quantity == 0


@dataclass(frozen=True)
class Leg:
    """한 체결이 쪼개진 다리. 전환 체결은 청산 다리와 진입 다리로 나뉜다."""
    kind: Literal["CLOSE", "OPEN"]
    quantity: int
    notional: Decimal
    commission: Decimal
    transaction_tax: Decimal

    @property
    def cost(self) -> Decimal:
        return self.commission + self.transaction_tax


@dataclass
class TradeResult:
    before: PositionState
    after: PositionState
    legs: list[Leg]
    realized_delta: Decimal = Decimal(0)      # 이 체결이 확정한 실현손익 (비용 차감 후)
    realized_gross: Decimal = Decimal(0)      # 비용 차감 전
    closed_quantity: int = 0
    trace: tuple[TraceStep, ...] = field(default_factory=tuple)

    @property
    def commission(self) -> Decimal:
        return sum((leg.commission for leg in self.legs), Decimal(0))

    @property
    def transaction_tax(self) -> Decimal:
        return sum((leg.transaction_tax for leg in self.legs), Decimal(0))


def _leg_costs(quantity: int, fill: Fill, spec: InstrumentSpec,
               kind: Literal["CLOSE", "OPEN"]) -> Leg:
    """다리 하나의 비용.

    전환 체결은 청산 다리와 진입 다리로 쪼개고, 각 다리의 체결금액에 대해 따로 계산한다.
    절사를 다리별로 하므로 전체 금액 기준으로 한 번 절사한 값과 최대 1원 차이가 날 수 있다.
    """
    notional = round_won(fill.price * Decimal(quantity) * spec.multiplier)
    commission = floor_won(notional * fill.commission_rate)

    tax = Decimal(0)
    # 거래세는 매도 대금에만, 주식에만 붙는다. 파생은 증권거래세 대상이 아니다.
    if fill.side == "SELL" and spec.asset_class == "EQUITY" and spec.tax_rule is not None:
        rule = spec.tax_rule
        tax = floor_won(notional * rule.securities_tax) + floor_won(notional * rule.rural_special_tax)

    return Leg(kind=kind, quantity=quantity, notional=notional,
               commission=commission, transaction_tax=tax)


def apply_trade(state: PositionState, fill: Fill, spec: InstrumentSpec) -> TradeResult:
    """체결 한 건을 포지션에 반영한다. 증분 갱신이며 전체 재계산을 하지 않는다."""
    steps: list[TraceStep] = []
    held = abs(state.net_quantity)
    same_direction = state.is_flat or (state.net_quantity > 0) == (fill.side == "BUY")

    if same_direction:
        return _increase(state, fill, spec, steps)
    if fill.quantity <= held:
        return _reduce(state, fill, spec, steps, closing=fill.quantity)
    return _flip(state, fill, spec, steps, closing=held)


def _increase(state: PositionState, fill: Fill, spec: InstrumentSpec,
              steps: list[TraceStep]) -> TradeResult:
    """규칙 1. 같은 방향 추가 체결."""
    leg = _leg_costs(fill.quantity, fill, spec, "OPEN")
    held = abs(state.net_quantity)
    total = held + fill.quantity

    if state.is_flat:
        avg = round_price(fill.price)
        steps.append(TraceStep(
            "avg_price", "평균단가 (신규)",
            f"체결가 {fmt(fill.price)}", avg,
            ("price", "side")))
    else:
        avg = round_price(
            (Decimal(held) * state.avg_price + Decimal(fill.quantity) * fill.price) / Decimal(total))
        steps.append(TraceStep(
            "avg_price", "평균단가 (가중평균)",
            f"(기존 {fmt(held)} × {fmt(state.avg_price)} + 추가 {fmt(fill.quantity)} × {fmt(fill.price)})"
            f" ÷ {fmt(total)}, 소수 4자리 반올림",
            avg,
            ("quantity", "avg_price", "price")))

    steps.append(TraceStep(
        "commission", "수수료 (진입)",
        f"체결금액 {fmt(leg.notional)} × {pct(fill.commission_rate)}, 원 미만 절사",
        leg.commission,
        ("price", "quantity", "multiplier", "commission_rate")))

    sign = 1 if fill.side == "BUY" else -1
    after = PositionState(
        net_quantity=sign * total,
        avg_price=avg,
        realized_pnl=state.realized_pnl,
        # 진입 수수료는 실현손익에 넣지 않고 누적해 둔다. 청산할 때 비중만큼 차감한다.
        entry_cost=state.entry_cost + leg.commission + leg.transaction_tax,
    )
    return TradeResult(before=state, after=after, legs=[leg], trace=tuple(steps))


def _reduce(state: PositionState, fill: Fill, spec: InstrumentSpec,
            steps: list[TraceStep], *, closing: int) -> TradeResult:
    """규칙 2. 반대 방향 체결, 보유 수량 이내. 평균단가는 바뀌지 않는다."""
    leg = _leg_costs(closing, fill, spec, "CLOSE")
    held = abs(state.net_quantity)
    was_long = state.net_quantity > 0

    diff = (fill.price - state.avg_price) if was_long else (state.avg_price - fill.price)
    gross = round_won(diff * Decimal(closing) * spec.multiplier)
    steps.append(TraceStep(
        "realized_gross", "실현손익 (비용 전)",
        (f"(체결가 {fmt(fill.price)} − 평균단가 {fmt(state.avg_price)})" if was_long
         else f"(평균단가 {fmt(state.avg_price)} − 체결가 {fmt(fill.price)})")
        + f" × 청산수량 {fmt(closing)} × 승수 {fmt(spec.multiplier)}",
        gross,
        ("price", "avg_price", "quantity", "multiplier", "side")))

    # 보유분의 진입 수수료 중 청산 비중만큼을 함께 차감한다.
    # 이걸 빼먹으면 전량 청산된 종목의 진입 수수료가 어느 숫자에도 남지 않는다.
    allocated_entry = round_won(state.entry_cost * Decimal(closing) / Decimal(held))
    steps.append(TraceStep(
        "entry_cost_allocated", "진입 비용 안분",
        f"보유분 진입 비용 {fmt(state.entry_cost)} × {fmt(closing)} ÷ {fmt(held)}",
        allocated_entry,
        ("quantity", "commission_rate")))

    steps.append(TraceStep(
        "close_cost", "청산 비용",
        f"수수료 {fmt(leg.commission)}"
        + (f" + 거래세 {fmt(leg.transaction_tax)}" if leg.transaction_tax else "")
        + ", 원 미만 절사",
        leg.cost,
        ("price", "quantity", "multiplier", "commission_rate", "market", "tax_rate")))

    net = gross - leg.cost - allocated_entry
    steps.append(TraceStep(
        "realized_net", "실현손익 (비용 후)",
        f"{fmt(gross)} − 청산 비용 {fmt(leg.cost)} − 진입 비용 안분 {fmt(allocated_entry)}",
        net,
        ("price", "avg_price", "quantity", "multiplier", "side",
         "commission_rate", "market", "tax_rate")))

    remaining = held - closing
    sign = 1 if was_long else -1
    after = PositionState(
        net_quantity=sign * remaining,
        # 전량 청산이면 평균단가를 0으로 둔다. 남아 있으면 그대로 유지한다.
        avg_price=Decimal(0) if remaining == 0 else state.avg_price,
        realized_pnl=state.realized_pnl + net,
        entry_cost=state.entry_cost - allocated_entry,
    )
    return TradeResult(before=state, after=after, legs=[leg], realized_delta=net,
                       realized_gross=gross, closed_quantity=closing, trace=tuple(steps))


def _flip(state: PositionState, fill: Fill, spec: InstrumentSpec,
          steps: list[TraceStep], *, closing: int) -> TradeResult:
    """규칙 3. 반대 방향 체결, 보유 수량 초과. 한 체결 안에서 청산과 진입이 순서대로 일어난다."""
    closed = _reduce(state, fill, spec, steps, closing=closing)

    opening_qty = fill.quantity - closing
    open_leg = _leg_costs(opening_qty, fill, spec, "OPEN")
    avg = round_price(fill.price)
    sign = 1 if fill.side == "BUY" else -1

    steps.append(TraceStep(
        "avg_price", "평균단가 (방향 전환)",
        f"기존 {fmt(closing)} 전량 청산 후 남은 {fmt(opening_qty)}의 평균단가는 이번 체결가 {fmt(fill.price)}",
        avg,
        ("price", "quantity", "side")))
    steps.append(TraceStep(
        "commission", "수수료 (진입 다리)",
        f"체결금액 {fmt(open_leg.notional)} × {pct(fill.commission_rate)}, 원 미만 절사",
        open_leg.commission,
        ("price", "quantity", "multiplier", "commission_rate")))

    after = PositionState(
        net_quantity=sign * opening_qty,
        avg_price=avg,
        realized_pnl=closed.after.realized_pnl,
        entry_cost=open_leg.commission + open_leg.transaction_tax,
    )
    return TradeResult(before=state, after=after, legs=[closed.legs[0], open_leg],
                       realized_delta=closed.realized_delta, realized_gross=closed.realized_gross,
                       closed_quantity=closing, trace=tuple(steps))
