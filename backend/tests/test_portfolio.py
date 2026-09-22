from decimal import Decimal as D

from app.conventions import RiskLimits, TaxRule
from app.linear import LinearPosition, value_linear
from app.portfolio import BookItem, summarize_book

KOSPI = TaxRule("KOSPI", D("0.0005"), D("0.0015"))
LIMITS = RiskLimits(max_position_notional=D("100000000"), max_gross_exposure=D("150000000"),
                    max_loss=D("1000000"))


def _items():
    eq = value_linear(LinearPosition("EQUITY", "LONG", 100, D("70000"), D("75000"), tax_rule=KOSPI))
    fut = value_linear(LinearPosition("FUTURE", "SHORT", 1, D("350"), D("352"), multiplier=D("250000")))
    return [BookItem("#1 005930", "EQUITY", eq), BookItem("#2 K200", "FUTURE", fut)]


def test_book_totals_net_and_gross():
    s = summarize_book(_items(), LIMITS)
    assert s.totals.position_count == 2
    assert s.totals.gross_exposure == D("7500000") + D("88000000")
    assert s.totals.net_exposure == D("7500000") - D("88000000")
    assert s.totals.net_pnl == (D("500000") - D("15000")) + D("-500000")
    assert set(s.by_asset_class) == {"EQUITY", "FUTURE"}


def test_no_breach_within_limits():
    assert summarize_book(_items(), LIMITS).breaches == ()


def test_breaches_detected():
    tight = RiskLimits(max_position_notional=D("50000000"), max_gross_exposure=D("90000000"),
                       max_loss=D("10000"))
    codes = {b.code for b in summarize_book(_items(), tight).breaches}
    assert codes == {"POSITION_NOTIONAL", "GROSS_EXPOSURE", "LOSS_LIMIT"}


# ---------- 한도 사용률 ----------
# 기대값은 METHODOLOGY.md의 손계산과 같다. 화면은 이 비율을 그대로 표시만 한다.

def test_limit_usage_ratios():
    from app.portfolio import limit_usage
    s = summarize_book(_items(), LIMITS)
    # 총노출 95,500,000 ÷ 150,000,000 = 0.636666...  → 0.636667
    # 순손익 −15,000 (손실) → 손실 15,000 ÷ 1,000,000 = 0.015
    # 최대 단일 포지션 88,000,000 ÷ 100,000,000 = 0.88
    largest = max(abs(i.valuation.signed_exposure) for i in _items())
    assert largest == D("88000000")
    usage = {u.code: u for u in limit_usage(s.totals, largest, LIMITS)}
    assert usage["GROSS_EXPOSURE"].used == D("95500000")
    assert usage["GROSS_EXPOSURE"].ratio == D("0.636667")
    assert usage["LOSS_LIMIT"].used == D("15000")
    assert usage["LOSS_LIMIT"].ratio == D("0.015000")
    assert usage["POSITION_NOTIONAL"].used == D("88000000")
    assert usage["POSITION_NOTIONAL"].ratio == D("0.880000")


def test_limit_usage_profit_does_not_consume_loss_limit():
    from app.portfolio import limit_usage
    eq = value_linear(LinearPosition("EQUITY", "LONG", 100, D("70000"), D("75000"), tax_rule=KOSPI))
    s = summarize_book([BookItem("#1 005930", "EQUITY", eq)], LIMITS)
    assert s.totals.net_pnl > 0
    usage = {u.code: u for u in limit_usage(s.totals, D("7500000"), LIMITS)}
    assert usage["LOSS_LIMIT"].used == D("0")
    assert usage["LOSS_LIMIT"].ratio == D("0")


def test_limit_usage_empty_book_is_all_zero():
    from app.portfolio import limit_usage
    s = summarize_book([], LIMITS)
    for u in limit_usage(s.totals, D("0"), LIMITS):
        assert u.used == D("0") and u.ratio == D("0")
