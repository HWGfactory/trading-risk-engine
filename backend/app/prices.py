"""무료 시세 소스 어댑터: pykrx(1순위) → FinanceDataReader(2순위).

pykrx 1.2.x 참고
- get_market_ohlcv(fromdate, todate, ticker)는 기본값 adjusted=True로 네이버 수정주가를 쓴다.
  이 경로는 KRX 로그인 없이 동작한다.
- KRX 원천 데이터(비수정주가, 종목명 조회 등)는 환경변수 KRX_ID / KRX_PW 로그인이 필요하다.
  로그인 정보가 없으면 import 시 안내 메시지를 출력하지만 오류는 아니다.

수정주가 주의
- 평가가격(최근 종가)은 수정 여부와 무관하게 같다.
- 과거 진입가와 비교할 때 그 사이 액면분할·무상증자가 있었다면 수정주가 기준으로 진입가도 환산해야 한다.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

TICKER_RE = re.compile(r"^[0-9A-Z]{6}$")
STALE_AFTER_DAYS = 5      # 연휴 감안. 이보다 오래된 종가는 거래정지 등을 의심한다.
SOURCE_TIMEOUT_SEC = 10   # 외부 소스가 응답하지 않아도 API가 멈추지 않도록 소스별 제한시간을 둔다.

_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="price-source")


@dataclass(frozen=True)
class PriceQuote:
    ticker: str
    name: str | None
    close: Decimal
    as_of: date
    source: str

    def is_stale(self, today: date) -> bool:
        return (today - self.as_of).days > STALE_AFTER_DAYS


class PriceUnavailable(Exception):
    """모든 시세 소스에서 가격을 받지 못했을 때."""


PriceFetcher = Callable[[str], PriceQuote]


def normalize_ticker(ticker: str) -> str:
    t = ticker.strip().upper()
    if not TICKER_RE.match(t):
        raise ValueError("종목코드는 6자리여야 합니다 (예: 005930).")
    return t


def fetch_latest_close(ticker: str, today: date | None = None, lookback_days: int = 14) -> PriceQuote:
    ticker = normalize_ticker(ticker)
    today = today or date.today()
    start = today - timedelta(days=lookback_days)

    errors: list[str] = []
    for label, source in (("pykrx", _from_pykrx), ("FinanceDataReader", _from_fdr)):
        try:
            quote = _POOL.submit(source, ticker, start, today).result(timeout=SOURCE_TIMEOUT_SEC)
        except FutureTimeout:
            errors.append(f"{label}: {SOURCE_TIMEOUT_SEC}초 안에 응답 없음")
            continue
        except Exception as exc:  # 외부 라이브러리 예외는 형태가 제각각이라 넓게 받는다
            errors.append(f"{label}: {exc}")
            continue
        if quote is not None:
            return quote
        errors.append(f"{label}: 데이터 없음")
    raise PriceUnavailable(f"{ticker} 시세를 가져오지 못했습니다 ({'; '.join(errors)}).")


def _from_pykrx(ticker: str, start: date, end: date) -> PriceQuote | None:
    from pykrx import stock  # 지연 import: import 시점에 KRX 로그인 안내를 출력하기 때문

    df = stock.get_market_ohlcv(start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), ticker)
    if df is None or df.empty:
        return None
    close = Decimal(str(int(df["종가"].iloc[-1])))
    if close <= 0:
        return None
    return PriceQuote(ticker, _lookup_name(ticker), close, df.index[-1].date(), "pykrx (네이버 수정주가)")


def _from_fdr(ticker: str, start: date, end: date) -> PriceQuote | None:
    import FinanceDataReader as fdr

    df = fdr.DataReader(ticker, start.isoformat(), end.isoformat())
    if df is None or df.empty:
        return None
    close = Decimal(str(int(df["Close"].iloc[-1])))
    if close <= 0:
        return None
    return PriceQuote(ticker, None, close, df.index[-1].date(), "FinanceDataReader")


def _lookup_name(ticker: str) -> str | None:
    """종목명은 KRX 원천이라 로그인이 없으면 실패할 수 있다. 실패해도 평가는 계속한다."""
    try:
        from pykrx import stock

        name = stock.get_market_ticker_name(ticker)
    except Exception:
        return None
    return name if isinstance(name, str) and name else None
