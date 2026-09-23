"""체결 기반 포지션 엔진 정답 케이스.

각 기대값은 METHODOLOGY.md의 손계산 예시 F~K와 같다. 엔진을 바꿨는데 여기가 깨지면
'계산이 달라졌다'는 뜻이므로, 근거 문서를 먼저 고친 뒤 테스트를 갱신한다.
"""
from decimal import Decimal as D

import pytest

from app.conventions import TaxRule
from app.trades import Fill, InstrumentSpec, PositionState, apply_trade

KOSPI = TaxRule("KOSPI", D("0.0005"), D("0.0015"))
EQUITY = InstrumentSpec("EQUITY", D(1), KOSPI)
EQUITY_FREE = InstrumentSpec("EQUITY", D(1), TaxRule("KOSPI", D(0), D(0)))
K200 = InstrumentSpec("FUTURE", D("250000"), None)

FLAT = PositionState()


def buy(state, qty, price, rate=D(0), spec=EQUITY_FREE):
    return apply_trade(state, Fill("BUY", qty, D(str(price)), rate), spec)


def sell(state, qty, price, rate=D(0), spec=EQUITY_FREE):
    return apply_trade(state, Fill("SELL", qty, D(str(price)), rate), spec)


# ---------- 예시 F: 분할 매수 (규칙 1) ----------

def test_f_average_up_on_second_buy():
    s = buy(FLAT, 100, 70000).after
    assert s.net_quantity == 100
    assert s.avg_price == D("70000")

    s = buy(s, 50, 76000).after
    # (100 × 70,000 + 50 × 76,000) ÷ 150 = 72,000
    assert s.avg_price == D("72000")
    assert s.net_quantity == 150
    assert s.realized_pnl == D(0)      # 증가에는 실현손익이 없다


# ---------- 예시 G: 부분 청산 (규칙 2) ----------

def test_g_partial_close_keeps_average_price():
    s = buy(buy(FLAT, 100, 70000).after, 50, 76000).after
    r = sell(s, 60, 80000)

    # (80,000 − 72,000) × 60 × 1 = 480,000
    assert r.realized_gross == D("480000")
    assert r.realized_delta == D("480000")     # 수수료·세금 0인 케이스
    assert r.closed_quantity == 60
    assert r.after.net_quantity == 90
    assert r.after.avg_price == D("72000")     # 청산은 평균단가를 바꾸지 않는다


# ---------- 예시 H: 전량 청산 (규칙 2, 손실) ----------

def test_h_full_close_sets_closed_state():
    s = sell(buy(buy(FLAT, 100, 70000).after, 50, 76000).after, 60, 80000).after
    r = sell(s, 90, 71000)

    # (71,000 − 72,000) × 90 × 1 = −90,000
    assert r.realized_gross == D("-90000")
    assert r.after.net_quantity == 0
    assert r.after.is_flat
    assert r.after.avg_price == D(0)           # 수량이 0이면 평균단가도 0
    assert r.after.realized_pnl == D("390000")  # 480,000 − 90,000


# ---------- 예시 I: 방향 전환 (규칙 3) ----------

def test_i_flip_closes_then_opens_at_fill_price():
    s = buy(FLAT, 100, 70000).after
    r = sell(s, 150, 75000)

    # 먼저 100주를 청산해 (75,000 − 70,000) × 100 = 500,000 확정
    assert r.realized_gross == D("500000")
    assert r.closed_quantity == 100
    # 남은 50주는 새 매도 포지션, 평균단가는 이번 체결가
    assert r.after.net_quantity == -50
    assert r.after.avg_price == D("75000")
    # 한 체결이 청산 다리와 진입 다리로 쪼개진다
    assert [leg.kind for leg in r.legs] == ["CLOSE", "OPEN"]
    assert [leg.quantity for leg in r.legs] == [100, 50]


def test_i_flip_from_short_to_long():
    s = sell(FLAT, 10, 1000).after
    assert s.net_quantity == -10
    r = buy(s, 25, 900)
    # 매도 포지션 청산: (평균 1,000 − 체결 900) × 10 = +1,000
    assert r.realized_gross == D("1000")
    assert r.after.net_quantity == 15
    assert r.after.avg_price == D("900")


# ---------- 예시 J: 선물 거래승수 ----------

def test_j_futures_multiplier_applies_to_realized():
    s = buy(FLAT, 2, "350.00", spec=K200).after
    assert s.avg_price == D("350")
    r = sell(s, 1, "352.50", spec=K200)

    # (352.50 − 350.00) × 1 × 250,000 = 625,000
    assert r.realized_gross == D("625000")
    assert r.after.net_quantity == 1
    assert r.after.avg_price == D("350")       # 남은 1계약의 평균단가는 그대로


def test_j_futures_have_no_transaction_tax():
    s = buy(FLAT, 2, "350.00", rate=D("0.00003"), spec=K200).after
    r = sell(s, 2, "352.50", rate=D("0.00003"), spec=K200)
    assert r.transaction_tax == D(0)           # 파생은 증권거래세 대상이 아니다


# ---------- 예시 K: 비용 차감 (원 미만 절사) ----------

def test_k_costs_are_floored_and_deducted():
    s = buy(buy(FLAT, 100, 70000).after, 50, 76000).after   # 150주 @72,000
    r = sell(s, 60, 80333, rate=D("0.00015"), spec=EQUITY)

    # 체결금액 80,333 × 60 = 4,819,980
    leg = r.legs[0]
    assert leg.notional == D("4819980")
    assert r.commission == D("722")            # 722.997 → 절사
    # 증권거래세 2,409.99 → 2,409 / 농특세 7,229.97 → 7,229
    assert r.transaction_tax == D("9638")
    # (80,333 − 72,000) × 60 = 499,980
    assert r.realized_gross == D("499980")
    # 진입 수수료 0인 상태라 안분액도 0
    assert r.realized_delta == D("499980") - D("722") - D("9638")
    assert r.realized_delta == D("489620")


# ---------- 진입 비용 안분 (승인된 정책) ----------

def test_entry_commission_is_carried_and_allocated_on_close():
    """전량 청산되면 진입 수수료가 실현손익에 정확히 반영되어야 한다.

    이 처리를 빼면 진입 수수료가 어느 숫자에도 남지 않고 사라진다.
    """
    rate = D("0.00015")
    r_in = buy(FLAT, 100, 70000, rate=rate, spec=EQUITY)
    assert r_in.after.entry_cost == D("1050")      # 7,000,000 × 0.015%
    assert r_in.after.realized_pnl == D(0)         # 진입은 실현손익을 만들지 않는다

    r_out = sell(r_in.after, 100, 80000, rate=rate, spec=EQUITY)
    # 청산 수수료 1,200 / 거래세 4,000 + 12,000 = 16,000
    assert r_out.commission == D("1200")
    assert r_out.transaction_tax == D("16000")
    # 실현손익 = 1,000,000 − 1,200 − 16,000 − 1,050 = 981,750
    assert r_out.realized_delta == D("981750")
    assert r_out.after.entry_cost == D(0)          # 전량 청산했으므로 남은 진입 비용 없음


def test_entry_cost_allocated_pro_rata_on_partial_close():
    rate = D("0.00015")
    s = buy(FLAT, 100, 70000, rate=rate, spec=EQUITY_FREE).after
    assert s.entry_cost == D("1050")
    r = sell(s, 40, 80000, rate=D(0), spec=EQUITY_FREE)
    # 비용 전 (80,000 − 70,000) × 40 = 400,000, 진입 비용 안분 1,050 × 40 ÷ 100 = 420
    assert r.realized_gross == D("400000")
    assert r.realized_delta == D("400000") - D("420")
    assert r.after.entry_cost == D("630")          # 1,050 − 420


def test_flip_splits_costs_by_leg():
    """전환 체결은 다리별로 비용을 계산한다. 합은 전체 기준과 같아야 한다."""
    rate = D("0.00015")
    s = buy(FLAT, 100, 70000, spec=EQUITY).after
    r = sell(s, 150, 75000, rate=rate, spec=EQUITY)

    close_leg, open_leg = r.legs
    assert close_leg.quantity == 100 and open_leg.quantity == 50
    assert close_leg.commission == D("1125")       # 7,500,000 × 0.015%
    assert open_leg.commission == D("562")         # 3,750,000 × 0.015% = 562.5 → 절사
    assert r.commission == D("1687")               # 11,250,000 × 0.015% = 1,687.5 → 절사와 일치
    # 청산 다리의 비용만 실현손익에서 차감한다
    assert r.realized_delta == D("500000") - close_leg.cost
    # 진입 다리의 비용은 새 포지션이 들고 간다
    assert r.after.entry_cost == open_leg.cost


# ---------- 계약 ----------

def test_every_trace_step_declares_inputs():
    r = sell(buy(FLAT, 100, 70000, rate=D("0.00015"), spec=EQUITY).after,
             60, 80000, rate=D("0.00015"), spec=EQUITY)
    assert r.trace
    for step in r.trace:
        assert step.inputs, f"{step.key}에 inputs가 비어 있다"


def test_fill_rejects_bad_input():
    with pytest.raises(ValueError):
        Fill("BUY", 0, D("100"))
    with pytest.raises(ValueError):
        Fill("BUY", 1, D("0"))
