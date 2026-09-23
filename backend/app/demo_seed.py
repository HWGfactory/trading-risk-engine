"""시작할 때 DB가 비어 있으면 예시 북을 만든다.

왜 필요한가
    Render 무료 플랜은 재시작할 때마다 디스크가 초기화된다. 시드가 없으면
    방문자가 늘 빈 화면을 본다.

무엇을 쓰는가
    scripts/seed_demo.py 와 같은 체결 목록을 쓴다. 목록은 여기 한 곳에만 둔다.
    저장은 라우트와 같은 book_trade()를 거치므로 호가단위 검증 같은 규칙이 그대로 적용된다.

숫자에 대한 주의
    체결가와 선물 평가가격은 예시값이다. 실제 체결가나 정산가가 아니다.
    주식 평가가격만 무료 시세에서 실제 종가를 받아온다.
"""
from __future__ import annotations

import logging
import sqlite3
import threading
from decimal import Decimal

log = logging.getLogger("uvicorn.error")

# 분할 매수와 부분 청산이 들어 있어야 평균단가와 실현손익이 화면에 보인다.
DEMO_TRADES: list[dict] = [
    {"asset_class": "EQUITY", "side": "BUY", "market": "KOSPI",
     "symbol": "005930", "name": "삼성전자",
     "quantity": 300, "price": "268000", "commission_rate": "0.00015"},
    {"asset_class": "EQUITY", "side": "BUY", "market": "KOSPI",
     "symbol": "005930", "name": "삼성전자",
     "quantity": 200, "price": "284000", "commission_rate": "0.00015"},
    # 여기까지 평균단가 (300x268,000 + 200x284,000) / 500 = 274,400
    {"asset_class": "EQUITY", "side": "SELL", "market": "KOSPI",
     "symbol": "005930", "name": "삼성전자",
     "quantity": 100, "price": "281000", "commission_rate": "0.00015"},
    # 부분 청산: (281,000 - 274,400) x 100 = 660,000 (비용 전). 잔량 400, 평균단가 유지
    {"asset_class": "EQUITY", "side": "SELL", "market": "KOSDAQ",
     "symbol": "247540", "name": "에코프로비엠",
     "quantity": 300, "price": "138500", "commission_rate": "0.00015"},
    {"asset_class": "FUTURE", "side": "SELL", "contract_code": "KOSPI200_FUT",
     "symbol": "K200 2026-12",
     "quantity": 4, "price": "402.75", "commission_rate": "0.00003", "margin_rate": "0.105"},
    {"asset_class": "FUTURE", "side": "BUY", "contract_code": "MINI_KOSPI200_FUT",
     "symbol": "미니 K200 2026-12",
     "quantity": 12, "price": "401.90", "commission_rate": "0.00003", "margin_rate": "0.075"},
]

# 선물은 무료 시세 소스가 없어 평가가격을 수동 입력한다. 아래도 예시값이다.
FUTURE_MARKS = {"K200 2026-12": Decimal("404.60"), "미니 K200 2026-12": Decimal("404.60")}


def is_empty(conn: sqlite3.Connection) -> bool:
    return int(conn.execute("SELECT COUNT(*) AS c FROM trades").fetchone()["c"]) == 0


def seed(conn: sqlite3.Connection) -> int:
    """체결만 만든다. 네트워크를 쓰지 않으므로 시작이 느려지지 않는다."""
    # 순환 임포트를 피하려고 여기서 가져온다. main이 이 모듈을 부르기 때문이다.
    from app.conventions import load_conventions
    from app.main import book_trade
    from app.schemas import TradeCreate

    conv = load_conventions()
    made = 0
    for body in DEMO_TRADES:
        book_trade(conn, TradeCreate(**body), conv)
        made += 1
    return made


def revalue_in_background(db_path: str) -> None:
    """시드 직후 한 번만 평가해 본다.

    주식 시세 조회는 네트워크를 쓰고 클라우드 IP에서는 느리거나 막힐 수 있다.
    그래서 시작을 막지 않도록 별도 스레드에서 돌리고, 실패해도 앱은 그대로 뜬다.
    실패하면 화면에 "아직 평가하지 않음"으로 보이고 사용자가 재평가를 누르면 된다.
    """
    def run() -> None:
        from app import repository as repo
        from app.main import RevalueRequest, revalue_book
        from app.conventions import load_conventions
        from app.prices import fetch_latest_close

        worker = repo.connect(db_path)
        try:
            marks = {}
            for row in repo.list_open_positions(worker):
                mark = FUTURE_MARKS.get(row["symbol"])
                if mark is not None:
                    marks[int(row["id"])] = mark
            result = revalue_book(RevalueRequest(marks=marks), worker,
                                  load_conventions(), fetch_latest_close)
            if result.errors:
                for err in result.errors:
                    log.warning("시드 평가 경고: %s", err)
            log.info("시드 평가 완료. 대사 %s", result.reconciliation.status)
        except Exception as exc:  # noqa: BLE001
            log.warning("시드 평가를 건너뜁니다(%s). 화면에서 전체 재평가를 누르면 됩니다.", exc)
        finally:
            worker.close()

    threading.Thread(target=run, name="demo-seed-revalue", daemon=True).start()
