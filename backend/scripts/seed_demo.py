"""시연·스크린샷용 예시 북을 만든다.

실행 (backend 폴더에서):
    .venv\\Scripts\\python -m scripts.seed_demo

왜 TestClient인가
    uvicorn을 띄우지 않고 앱을 같은 프로세스 안에서 호출한다. 서버 없이 한 번에 실행되면서도
    요청이 실제 API를 그대로 지나가므로 호가단위 검증, 거래승수 조회, 한국어 오류 응답,
    감사추적 INSERT 같은 규칙이 전부 적용된다. DB에 직접 INSERT하면 이 검증을 건너뛰게 된다.

중복 방지
    이미 열린 포지션이 있으면 아무것도 하지 않고 종료한다. 여러 번 실행해도 안전하다.

숫자에 대한 주의
    아래 진입가와 선물 평가가격은 **예시값이다.** 실제 체결가나 정산가가 아니다.
    주식 평가가격만 무료 시세(pykrx → FinanceDataReader)에서 실제 종가를 받아온다.
    이 북은 화면을 보여주기 위한 것이지 손익을 주장하기 위한 것이 아니다.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

# 빨강·파랑(매수·매도), 주식·선물, 자동 시세·수동 평가가격이 모두 한 화면에 나오도록 구성했다.
# 손익 부호도 섞여야 화면의 두 의미색이 같이 보이므로, 매수 하나는 손실 쪽에 둔다.
POSITIONS = [
    {
        "asset_class": "EQUITY", "direction": "LONG", "market": "KOSPI",
        "symbol": "005930", "name": "삼성전자",
        "quantity": 500, "entry_price": "282000",     # 예시 진입가 (현재가보다 높아 평가손실)
        "commission_rate": "0.00015",
    },
    {
        "asset_class": "EQUITY", "direction": "SHORT", "market": "KOSDAQ",
        "symbol": "247540", "name": "에코프로비엠",
        "quantity": 300, "entry_price": "138500",     # 예시 진입가
        "commission_rate": "0.00015",
    },
    {
        "asset_class": "FUTURE", "direction": "SHORT", "contract_code": "KOSPI200_FUT",
        "symbol": "K200 2026-12",
        "quantity": 4, "entry_price": "402.75",       # 예시 진입가, 호가단위 0.05 배수
        "commission_rate": "0.00003", "margin_rate": "0.105",
    },
    {
        "asset_class": "FUTURE", "direction": "LONG", "contract_code": "MINI_KOSPI200_FUT",
        "symbol": "미니 K200 2026-12",
        "quantity": 12, "entry_price": "401.90",      # 예시 진입가, 호가단위 0.02 배수
        "commission_rate": "0.00003", "margin_rate": "0.075",
    },
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

        created: dict[str, int] = {}
        for body in POSITIONS:
            r = client.post("/api/positions", json=body)
            if r.status_code != 201:
                print(f"[실패] {body['symbol']}: HTTP {r.status_code} {r.json().get('detail')}")
                return 1
            p = r.json()
            created[p["symbol"]] = p["id"]
            side = "매수" if body["direction"] == "LONG" else "매도"
            print(f"[생성] #{p['id']} {p['name'] or p['symbol']} {side} "
                  f"{body['quantity']} @ {body['entry_price']}")

        marks = {str(created[sym]): price for sym, price in FUTURE_MARKS.items() if sym in created}
        print("\n재평가 중입니다. 주식 시세를 조회하므로 수 초 걸릴 수 있습니다.")
        r = client.post("/api/book/revalue", json={"marks": marks})
        if r.status_code != 200:
            print(f"[실패] 재평가: HTTP {r.status_code} {r.json().get('detail')}")
            return 1

        run = r.json()
        for err in run["errors"]:
            print(f"  [경고] {err}")
        for row in run["positions"]:
            print(f"  {row['name'] or row['symbol']:<14} 평가가 {row['mark_price']:>10}"
                  f"  순손익 {row['valuation']['net_pnl']:>12}  ({row['price_source']})")

        t = run["totals"]
        print(f"\n총노출 {t['gross_exposure']}  순노출 {t['net_exposure']}  순손익 {t['net_pnl']}")
        print(f"엔진·SQL 대사: {run['reconciliation']['status']}")
        for b in run["breaches"]:
            print(f"  [한도] {b['message']}")

        print("\n예시 북을 만들었습니다. 진입가와 선물 평가가격은 예시값입니다.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
