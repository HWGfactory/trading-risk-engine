"""선형 엔진 정답 케이스.

각 기대값은 METHODOLOGY.md의 손계산 예시와 같다. 엔진을 바꿨는데 여기가 깨지면
'계산이 달라졌다'는 뜻이므로, 근거 문서를 먼저 고친 뒤 테스트를 갱신한다.
"""
from decimal import Decimal as D

import pytest

from app.conventions import TaxRule, load_conventions
from app.linear import LinearPosition, value_linear

KOSPI = TaxRule("KOSPI", D("0.0005"), D("0.0015"))
KOSDAQ = TaxRule("KOSDAQ", D("0.0020"), D("0"))


def test_equity_long_kospi_with_costs():
    # 예시 A: 100주 70,000 매수 → 75,000 평가, 수수료 0.015%
    v = value_linear(LinearPosition("EQUITY", "LONG", 100, D("70000"), D("75000"),
                                    commission_rate=D("0.00015"), tax_rule=KOSPI))
    assert v.entry_notional == D("7000000")
    assert v.mark_notional == D("7500000")
    assert v.gross_pnl == D("500000")
    assert v.entry_commission == D("1050")      # 7,000,000 × 0.015%
    assert v.exit_commission == D("1125")       # 7,500,000 × 0.015%
    assert v.transaction_tax == D("15000")      # 7,500,000 × (0.05% + 0.15%)
    assert v.total_costs == D("17175")
    assert v.net_pnl == D("482825")
    assert v.return_on_notional == D("0.068975")
    assert v.signed_exposure == D("7500000")
    assert v.initial_margin is None


def test_equity_short_kosdaq_tax_on_entry_sale():
    # 예시 B: 공매도는 진입 시점 매도 대금에 거래세
    v = value_linear(LinearPosition("EQUITY", "SHORT", 50, D("20000"), D("18500"), tax_rule=KOSDAQ))
    assert v.gross_pnl == D("75000")
    assert v.transaction_tax == D("2000")       # 1,000,000 × 0.20%
    assert v.net_pnl == D("73000")
    assert v.signed_exposure == D("-925000")


def test_costs_truncate_below_one_won():
    # 예시 C
    v = value_linear(LinearPosition("EQUITY", "LONG", 1, D("12345"), D("12345"),
                                    commission_rate=D("0.00015"), tax_rule=KOSPI))
    assert v.entry_commission == D("1")         # 1.85175 → 1
    assert v.exit_commission == D("1")
    assert v.transaction_tax == D("24")         # 6.1725 → 6, 18.5175 → 18
    assert v.net_pnl == D("-26")


def test_kospi200_future_long_with_margin():
    # 예시 D
    v = value_linear(LinearPosition("FUTURE", "LONG", 2, D("350.00"), D("352.50"),
                                    multiplier=D("250000"), margin_rate=D("0.10")))
    assert v.entry_notional == D("175000000")
    assert v.gross_pnl == D("1250000")          # 2.5pt × 2계약 × 250,000
    assert v.transaction_tax == D("0")          # 파생상품 거래세 없음
    assert v.initial_margin == D("17500000")
    assert v.current_margin == D("17625000")
    assert v.return_on_margin == D("0.071429")


def test_mini_future_short_loss():
    v = value_linear(LinearPosition("FUTURE", "SHORT", 1, D("350.00"), D("351.00"), multiplier=D("50000")))
    assert v.gross_pnl == D("-50000")
    assert v.signed_exposure == D("-17550000")


def test_trace_ends_with_net_and_return():
    v = value_linear(LinearPosition("EQUITY", "LONG", 10, D("1000"), D("1100"), tax_rule=KOSPI))
    keys = [s.key for s in v.trace]
    assert keys[:3] == ["entry_notional", "mark_notional", "gross_pnl"]
    assert "net_pnl" in keys and keys[-1] == "return_on_notional"
    assert next(s.value for s in v.trace if s.key == "net_pnl") == v.net_pnl


@pytest.mark.parametrize("kwargs, message", [
    (dict(quantity=0), "수량"),
    (dict(entry_price=D("0")), "가격"),
    (dict(commission_rate=D("1")), "수수료율"),
    (dict(tax_rule=None), "시장"),
    (dict(margin_rate=D("0.1")), "증거금률"),
])
def test_invalid_equity_inputs(kwargs, message):
    base = dict(asset_class="EQUITY", direction="LONG", quantity=1, entry_price=D("100"),
                mark_price=D("100"), tax_rule=KOSPI)
    base.update(kwargs)
    with pytest.raises(ValueError, match=message):
        LinearPosition(**base)


def test_config_tax_rates_2026():
    """2026-01-01 양도분부터: 코스피 0.05%+농특세 0.15%, 코스닥 0.20% (합계 모두 0.20%)."""
    conv = load_conventions()
    assert conv.tax_rule("KOSPI").total == D("0.0020")
    assert conv.tax_rule("KOSDAQ").total == D("0.0020")
    assert conv.contract("KOSPI200_FUT").multiplier == D("250000")


# ---------- 근거 추적: TraceStep.inputs ----------
# 화면의 "근거 줄 ↔ 입력 칸 상호 강조"가 이 목록만 보고 동작한다.
# 프론트가 의존 관계를 추측하지 않도록 엔진이 직접 알려주는 값이므로 계약으로 고정한다.

def _steps(v):
    return {s.key: s for s in v.trace}


def test_trace_inputs_equity_long():
    v = value_linear(LinearPosition("EQUITY", "LONG", 100, D("70000"), D("75000"),
                                    commission_rate=D("0.00015"), tax_rule=KOSPI))
    s = _steps(v)
    assert s["entry_notional"].inputs == ("entry_price", "quantity", "multiplier")
    assert s["mark_notional"].inputs == ("mark_price", "quantity", "multiplier")
    assert s["gross_pnl"].inputs == ("entry_price", "mark_price", "quantity",
                                     "multiplier", "direction")
    assert s["commission"].inputs == ("entry_price", "mark_price", "quantity",
                                      "multiplier", "commission_rate")
    # 매수는 청산 매도 대금(=평가가)에 거래세가 붙는다
    assert s["transaction_tax"].inputs == ("mark_price", "quantity", "multiplier",
                                           "direction", "market", "tax_rate")
    # 순손익은 앞 단계 입력을 모두 물려받는다 (중복 없이, 등장 순서 유지)
    assert s["net_pnl"].inputs == ("entry_price", "quantity", "multiplier", "mark_price",
                                   "direction", "commission_rate", "market", "tax_rate")
    assert s["return_on_notional"].inputs == s["net_pnl"].inputs


def test_trace_inputs_equity_short_uses_entry_price_for_tax():
    # 공매도는 진입 매도 대금에 거래세 → 의존 입력이 entry_price로 바뀐다
    v = value_linear(LinearPosition("EQUITY", "SHORT", 50, D("20000"), D("18500"), tax_rule=KOSDAQ))
    assert _steps(v)["transaction_tax"].inputs == ("entry_price", "quantity", "multiplier",
                                                   "direction", "market", "tax_rate")


def test_trace_inputs_future_with_margin():
    v = value_linear(LinearPosition("FUTURE", "SHORT", 1, D("350"), D("352"),
                                    multiplier=D("250000"), margin_rate=D("0.1")))
    s = _steps(v)
    assert s["transaction_tax"].inputs == ("asset_class",)
    assert s["initial_margin"].inputs == ("entry_price", "quantity", "multiplier", "margin_rate")
    assert "margin_rate" in s["return_on_margin"].inputs


def test_every_trace_step_declares_inputs():
    # 근거 줄이 늘어나면 inputs도 함께 채우도록 강제한다
    v = value_linear(LinearPosition("EQUITY", "LONG", 100, D("70000"), D("75000"), tax_rule=KOSPI))
    for step in v.trace:
        assert step.inputs, f"{step.key}에 inputs가 비어 있다"
