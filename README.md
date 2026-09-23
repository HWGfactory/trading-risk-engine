# PI 데스크 포지션 평가 엔진

증권사 자기매매(PI) 데스크의 포지션을 넣으면 손익과 거래비용을 계산하고
**모든 숫자 옆에 그 숫자가 나온 산식과 대입값을 함께 보여주는** 웹 도구입니다.

**데모:** https://frontend-wongihong.vercel.app
(무료 서버라 한동안 접속이 없었다면 깨어나는 데 최대 1분 걸립니다)

![홈 화면](docs/screenshots/home-desktop-light.png)

## 왜 만들었나

평가 도구가 내놓는 숫자는 "왜 이 값인가"에 답할 수 있어야 믿을 수 있습니다.
이 도구는 예측이나 추천을 하지 않습니다. 주어진 포지션을 정해진 규칙대로 평가하고,
그 과정을 누구나 따라가며 검산할 수 있게 보여주는 데 집중했습니다.

## 기능

### 1. 시가평가 엔진 · `backend/app/linear.py`

주식과 선물의 명목금액, 평가손익, 수수료, 증권거래세, 순손익, 수익률을 계산합니다.
I/O가 없는 순수 함수 `value_linear()` 하나가 전부를 담당합니다.

- 모든 금액은 `Decimal`로 계산합니다. 비용은 원 미만 절사(`floor_won`), 명목금액과 손익은 원 단위 반올림(`round_won`)입니다.
- 거래세는 매도 대금에만 붙습니다. 매수 포지션은 평가가 기준 청산 대금에, 매도 포지션은 진입 대금에 부과하고, 선물은 0원입니다.
- 체결 이력이 있는 포지션은 진입 수수료를 추정하지 않고 실제로 낸 금액(`entry_commission_paid`)을 씁니다.
- 선물은 증거금률을 넣으면 개시증거금과 증거금 대비 수익률까지 계산합니다.

### 2. 근거 추적 · `TraceStep` → `frontend/src/trace.ts`

계산 단계마다 엔진이 `TraceStep(key, label, formula, value, inputs)`를 남깁니다.
`inputs`는 그 값에 쓰인 입력 칸 목록이며, 화면은 이 목록만 보고 근거 줄과 입력 칸을 서로 강조합니다.
의존 관계를 프론트가 추측하지 않습니다.

![근거 추적](docs/screenshots/state-trace-highlight.png)

위 화면은 `거래세` 줄을 짚은 모습입니다. 매수 포지션의 거래세는 평가가격에 붙기 때문에 진입가는 강조되지 않습니다.
순손익처럼 앞 단계를 합친 값은 앞서 쓰인 입력을 모두 물려받습니다.

### 3. 체결 기반 포지션 · `backend/app/trades.py`

포지션은 직접 입력하지 않고 체결을 쌓아 만듭니다. `apply_trade()`가 체결 한 건을 받아 포지션을 증분 갱신하며,
실현손익은 이동평균법으로 계산합니다.

| 경우 | 처리 |
|---|---|
| 같은 방향 추가 (`_increase`) | 평균단가를 가중평균으로 갱신 (소수 4자리 반올림) |
| 반대 방향, 보유 이내 (`_reduce`) | 평균단가 유지, 실현손익 확정, 진입 비용을 청산 비중만큼 안분 차감 |
| 반대 방향, 보유 초과 (`_flip`) | 한 체결 안에서 전량 청산 후 남은 수량으로 신규 진입 |

방향 전환 체결은 비용을 체결 전체 기준으로 먼저 계산하고, 절사로 생기는 1원 차이를 청산 다리에 붙입니다.
두 다리 비용의 합이 실제로 낸 금액과 항상 같습니다.
각 체결에는 직후의 평균단가·순수량·실현손익을 함께 저장해, 종목 상세 화면이 재계산 없이 변화 과정을 보여줍니다.

### 4. 엔진·SQL 대사 · `reconcile()` in `backend/app/main.py`

북을 재평가할 때마다 합계를 두 경로로 따로 냅니다.
Python 엔진의 집계(`summarize_book`)와 SQL 뷰의 집계(`v_book_by_asset_class`)를
상품군별 6개 항목(건수, 총노출, 순노출, 평가손익, 비용, 순손익)에서 1원 단위까지 비교하고, 결과를 `MATCHED` / `MISMATCHED`로 화면에 표시합니다.

### 5. 감사추적 · `backend/app/schema.sql`

- `trades`, `valuations`, `daily_snapshots`는 INSERT만 됩니다. UPDATE와 DELETE는 트리거가 `RAISE(ABORT)`로 막습니다.
- 가격·비율은 Decimal 문자열(TEXT), 금액은 원 단위 INTEGER로 저장해 `SUM` 집계에 오차가 없습니다.
- 일별 스냅샷은 덮어쓰지 않습니다. 같은 날 다시 찍으면 정정본(`revision + 1`)을 새 행으로 추가하고, 뷰 `v_latest_snapshot`이 최신 정정본을 고릅니다.
- 스냅샷 날짜는 `Asia/Seoul` 기준으로 파이썬에서 계산합니다(SQLite `datetime('now')`는 UTC라 한국 저녁에 전날로 찍힙니다).

### 6. 시세 수집 · `backend/app/prices.py`

`fetch_latest_close()`가 pykrx에서 수정종가를 가져오고, 실패하거나 10초 안에 응답이 없으면 FinanceDataReader로 넘어갑니다.
두 소스가 모두 실패하면 소스별 실패 사유를 모아 한국어 오류로 돌려줍니다. 가져온 가격은 출처·기준일과 함께 저장합니다.

### 7. 시장 관행 설정 · `backend/config/market_conventions.yaml`

세율(코스피·코스닥 증권거래세와 농특세), 선물 계약승수, 호가단위를 코드가 아닌 이 파일 한 곳에 둡니다.
값마다 출처(`source`)와 확인한 날짜(`verified_as_of`)를 적고, 부동소수점 오차를 피하려고 숫자를 문자열로 적습니다.
선물 평가가격은 이 파일의 호가단위 배수인지 검사합니다.

### 8. 손계산과 테스트

[METHODOLOGY.md](METHODOLOGY.md)에 산식과 손계산 예시를 적고, pytest는 그 손계산 결과를 기대값으로 그대로 씁니다.
엔진, 체결, 북 집계, API 통합, 시세 폴백까지 70여 개 테스트가 있습니다.

## 기술 스택

- **백엔드:** Python 3.11, FastAPI, Pydantic v2, sqlite3 (ORM 없음)
- **시세:** pykrx, FinanceDataReader
- **프론트:** React 19, TypeScript, Vite, motion
- **배포:** Vercel(프론트), Render(백엔드)

## 직접 실행하기 (Windows)

Python 3.11 이상과 Node 20.19 이상이 필요합니다.

```powershell
npm install
npm run setup   # 최초 1회: 가상환경, 의존성, 예시 데이터
npm run dev     # http://localhost:5173
```

## 더 보기

- [METHODOLOGY.md](METHODOLOGY.md): 산식, 세율 출처, 손계산 예시
- [DESIGN.md](DESIGN.md): 색·글꼴·모션을 정한 이유
- [docs/screenshots](docs/screenshots): 모든 화면과 상태 (라이트·다크, 데스크톱·모바일)
