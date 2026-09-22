"""시세 어댑터: 네트워크 없이 폴백·검증 로직만 확인한다."""
from datetime import date
from decimal import Decimal

import pytest

from app import prices
from app.prices import PriceQuote, PriceUnavailable, fetch_latest_close, normalize_ticker


def test_ticker_normalized_and_validated():
    assert normalize_ticker(" 005930 ") == "005930"
    assert normalize_ticker("0126z0") == "0126Z0"
    with pytest.raises(ValueError, match="6자리"):
        normalize_ticker("5930")


def test_falls_back_to_second_source(monkeypatch):
    quote = PriceQuote("005930", None, Decimal("75000"), date(2026, 9, 21), "FinanceDataReader")
    monkeypatch.setattr(prices, "_from_pykrx", lambda *a: (_ for _ in ()).throw(RuntimeError("blocked")))
    monkeypatch.setattr(prices, "_from_fdr", lambda *a: quote)
    assert fetch_latest_close("005930") == quote


def test_all_sources_fail(monkeypatch):
    monkeypatch.setattr(prices, "_from_pykrx", lambda *a: None)
    monkeypatch.setattr(prices, "_from_fdr", lambda *a: None)
    with pytest.raises(PriceUnavailable, match="pykrx: 데이터 없음; FinanceDataReader: 데이터 없음"):
        fetch_latest_close("005930")


def test_stale_quote_flag():
    q = PriceQuote("005930", None, Decimal("1"), date(2026, 9, 1), "t")
    assert q.is_stale(date(2026, 9, 22))
    assert not q.is_stale(date(2026, 9, 4))
