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
