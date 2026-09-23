"""시연·스크린샷용 예시 북을 체결로 쌓는다.

실행 (backend 폴더에서):
    .venv\\Scripts\\python -m scripts.seed_demo

왜 TestClient인가
    uvicorn을 띄우지 않고 앱을 같은 프로세스 안에서 호출한다. 서버 없이 한 번에 실행되면서도
    요청이 실제 API를 그대로 지나가므로 호가단위 검증, 거래승수 조회, 한국어 오류 응답,
    감사추적 INSERT 같은 규칙이 전부 적용된다. DB에 직접 INSERT하면 이 검증을 건너뛰게 된다.

중복 방지
    이미 열린 포지션이 있으면 아무것도 하지 않고 종료한다. 여러 번 실행해도 안전하다.

숫자에 대한 주의
    아래 체결가와 선물 평가가격은 **예시값이다.** 실제 체결가나 정산가가 아니다.
    주식 평가가격만 무료 시세(pykrx → FinanceDataReader)에서 실제 종가를 받아온다.
    이 북은 화면을 보여주기 위한 것이지 손익을 주장하기 위한 것이 아니다.
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# TestClient가 httpx를 쓴다고 알리는 안내다. 오류가 아니라서 출력만 지운다.
warnings.filterwarnings("ignore", message=r"Using .httpx.")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

# 분할 매수와 부분 청산이 화면에 보이도록 순서대로 쌓는다.
# 삼성전자: 두 번에 나눠 사고 일부를 되판다 → 평균단가와 실현손익이 둘 다 생긴다.
TRADES = [
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
FUTURE_MARKS = {"K200 2026-12": "404.60", "미니 K200 2026-12": "404.60"}


def main() -> int:
    with TestClient(app) as client:
        existing = client.get("/api/positions").json()
        if existing:
            print(f"이미 열린 포지션이 {len(existing)}건 있습니다. 아무것도 하지 않고 종료합니다.")
            print("초기화하려면 backend/data/trading.db 를 지우고 다시 실행하세요.")
            return 0

        for body in TRADES:
            r = client.post("/api/trades", json=body)
            if r.status_code != 201:
                print(f"[실패] {body['symbol']}: HTTP {r.status_code} {r.json().get('detail')}")
                return 1
            out = r.json()
            side = "매수" if body["side"] == "BUY" else "매도"
            pos = out["position"]
            print(f"[체결] {body.get('name') or body['symbol']:<16} {side} "
                  f"{body['quantity']:>4} @ {body['price']:>9}  "
                  f"→ 순수량 {pos['net_quantity']:>5}, 평균단가 {pos['avg_price']}")
            if out["trade"]["closed_quantity"]:
                print(f"         청산 {out['trade']['closed_quantity']}주, "
                      f"실현손익 {out['trade']['realized_pnl']} (비용 전 {out['realized_gross']})")

        symbols = {p["symbol"]: p["id"] for p in client.get("/api/positions").json()}
        marks = {str(symbols[s]): price for s, price in FUTURE_MARKS.items() if s in symbols}
        print("\n재평가 중입니다. 주식 시세를 조회하므로 수 초 걸릴 수 있습니다.")
        r = client.post("/api/book/revalue", json={"marks": marks})
        if r.status_code != 200:
            print(f"[실패] 재평가: HTTP {r.status_code} {r.json().get('detail')}")
            return 1

        run = r.json()
        for err in run["errors"]:
            print(f"  [경고] {err}")
        for row in run["positions"]:
            print(f"  {row['name'] or row['symbol']:<16} 평가가 {row['mark_price']:>10}"
                  f"  평가손익 {row['valuation']['net_pnl']:>12}  ({row['price_source']})")

        t = run["totals"]
        print(f"\n총노출 {t['gross_exposure']}  순노출 {t['net_exposure']}  평가손익 {t['net_pnl']}")
        realized = sum(int(p["realized_pnl"]) for p in client.get("/api/positions").json())
        print(f"실현손익 누적 {realized}")
        print(f"엔진·SQL 대사: {run['reconciliation']['status']}")
        for b in run["breaches"]:
            print(f"  [한도] {b['message']}")

        snap = client.post("/api/book/snapshot")
        if snap.status_code == 201:
            print(f"\n{snap.json()['snapshot_date']} 스냅샷을 저장했습니다.")
        elif snap.status_code == 409:
            print(f"\n스냅샷: {snap.json()['detail'][0]}")

        print("\n예시 북을 만들었습니다. 체결가와 선물 평가가격은 예시값입니다.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
