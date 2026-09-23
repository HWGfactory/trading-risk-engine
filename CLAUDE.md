# Trading Risk Engine (PI 데스크 포지션 평가 엔진)

## 프로젝트 개요
증권사 자기매매(PI) 데스크가 보유한 포지션을 입력하면
시가평가·손익·거래비용·리스크 한도를 계산하고, 모든 숫자의 계산 근거(산식·대입값)를 함께 보여주는 웹 도구.
자본시장 SW/AI 컨설턴트 지원용 포트폴리오. "정확하고 근거 있는 값"이 최우선 가치다.

- 예측·추천(무엇을 사면 이익인가)은 하지 않는다. 주어진 포지션을 정해진 모델로 평가만 한다.
- 시세는 무료 소스(pykrx → FinanceDataReader 폴백)만 쓴다. 증권사 계좌 API(KIS 등)는 쓰지 않는다.

## 기술 스택
- 백엔드: Python 3.11+, FastAPI, Pydantic v2, sqlite3(표준 라이브러리, ORM 없음), PyYAML, pytest
- 시세: pykrx 1.2.9+ (네이버 수정주가 경로, 로그인 불필요), FinanceDataReader
- 프론트: React 19 + TypeScript 6 + Vite 8 (Tailwind 없음, src/index.css 한 파일에 디자인 토큰)
- 모션: motion (motion/react). 아이콘: @phosphor-icons/react 한 가족만
- 글꼴: 자체 호스팅. 라틴·숫자는 geist 패키지의 가변 woff2, 한글은 @fontsource/ibm-plex-sans-kr
  (unicode-range 조각 배포판). Google Fonts <link>를 쓰지 않는다
- 스크린샷: 설치된 Chrome을 headless로 쓴다. Playwright를 설치하지 않는다
- 계산 라이브러리(2단계부터): QuantLib-Python

## 실행 (Windows PowerShell)
```
npm install     # 루트 런처 의존성 (최초 1회)
npm run setup   # 가상환경, 의존성, DB 이전, 예시 북 (멱등)
npm run dev     # 백엔드(8000)와 프론트(5173) 동시 실행, Ctrl+C 한 번에 둘 다 종료
```
브라우저: http://localhost:5173  /  API 문서: http://127.0.0.1:8000/docs

그 밖의 명령: `npm run check`(테스트·빌드·린트), `npm run seed`, `npm run migrate`.
개별 실행이 필요하면 README의 "수동 실행" 절을 본다.

실행 관련해 알아둘 것
- 런처는 파이썬 실행 파일 경로를 셸 문자열로 조립하지 않는다. npm 스크립트는 Windows에서
  `cmd /d /s /c` 로 실행되는데 따옴표와 슬래시 처리가 어긋나기 때문이다.
  scripts/run-python.mjs 가 Node에서 인자 배열로 직접 넘긴다. 경로에 공백이 있어도 안전하다.
- 프론트는 백엔드 포트가 열린 뒤에 시작한다(scripts/wait-for-api.mjs).
  먼저 뜨면 첫 화면이 프록시 오류를 띄운다.
- `npm run dev` 는 실행 전에 이전 개발 서버가 남긴 포트를 정리한다(scripts/free-ports.mjs).
  uvicorn --reload 의 작업 프로세스가 고아로 남아 포트를 쥐는 일이 실제로 반복됐다.
- Windows의 `python` / `python3` 는 Microsoft Store 스텁일 수 있다. 가상환경 생성은 `py -3`.

## 파일 구조
```
backend/
  config/market_conventions.yaml  세율·계약승수·호가단위·리스크 한도 (근거·확인일 포함)
  app/
    main.py         FastAPI 라우트, 의존성, 오류 응답(한국어), 엔진·SQL 대사
    schemas.py      요청·응답 스키마 (Decimal은 JSON 문자열)
    settings.py     배포 환경변수 (CORS, PORT, DEMO_MODE, AUTO_SEED)
    demo_seed.py    시작 시 DB가 비어 있으면 예시 북 생성
    conventions.py  YAML 로더 (UTF-8 고정)
    linear.py       주식·선물 평가 엔진 (순수 함수, I/O 없음)
    trades.py       체결 기반 포지션 엔진 (이동평균법, 순수 함수)
    portfolio.py    북 집계, 한도 점검
    prices.py       시세 어댑터 (pykrx → FDR, 소스별 10초 제한)
    repository.py   SQL 접근 계층
    schema.sql      테이블·뷰·감사 트리거
  tests/            pytest (엔진 정답 케이스, API 통합, 시세 폴백)
scripts/              루트 런처 (Node, 의존성 없음)
  setup.mjs           최초 준비 (멱등)
  run-python.mjs      가상환경 파이썬 실행 (셸을 거치지 않음)
  wait-for-api.mjs    백엔드 포트를 기다린다
  free-ports.mjs      이전 개발 서버가 남긴 포트 정리
backend/
  scripts/
    seed_demo.py          시연용 예시 북 (TestClient로 API를 그대로 통과)
    migrate_to_trades.py  기존 positions를 체결 기반 구조로 이전
    shoot_screenshots.py  문서용 스크린샷 (Chrome headless)
    shoot_states.py       빈 북·로딩·오류·근거 추적·대사 상태 스크린샷
frontend/
  public/shot.html  스크린샷용 보조 페이지 (정확한 뷰포트 크기의 iframe)
  src/
    App.tsx           셸, 라우트별 페이지, 평가 상태
    router.ts         해시 라우팅 (#/ , #/valuation , #/book)
    theme.ts          라이트·다크 선택 (시스템 기본 + localStorage)
    trace.ts          근거 추적 상태 (TraceStep.inputs만 보고 동작)
    api.ts            fetch 래퍼, 오류 메시지 정규화
    types.ts          백엔드 schemas.py와 1:1 대응 타입
    format.ts         표시용 포맷, 퍼센트↔비율 문자열 변환
    fonts.css         자체 호스팅 @font-face
    index.css         디자인 토큰과 전체 스타일 (DESIGN.md가 근거)
    components/
      Nav.tsx                 워드마크·메뉴·테마 전환
      Home.tsx                홈 (히어로, 오늘의 북, 증거 섹션)
      MiniEvaluator.tsx       홈 히어로의 실제 평가기
      DealTicket.tsx          매매 전표 입력
      ValuationStatement.tsx  결과·계산 근거 표
      BookView.tsx            북 현황·재평가·대사·손익 추이
      PositionDetail.tsx      종목별 체결 이력과 평균단가 변화
      AnimatedWon.tsx         숫자 전환 (마지막 프레임은 백엔드 문자열 그대로)
      WakeGate.tsx            잠든 백엔드가 깨어날 때까지 안내 + 재시도
render.yaml         백엔드 배포 설정 (Render)
frontend/.env.example  프론트 환경변수 설명
DESIGN.md           색·글꼴·간격·모션의 결정과 근거
METHODOLOGY.md      산식과 근거, 손계산 예시 (테스트 기대값의 출처)
docs/screenshots/   문서용 스크린샷 (3화면 x 1280/375 x 라이트/다크 + 상태 5종)
```

## 데이터 모델
포지션은 직접 입력받는 값이 아니라 **체결(trades)을 합쳐 만든 현재 상태**다.

```
trades          체결 한 건이 한 행. append-only. 그때의 결과값(평균단가·실현손익)을 함께 박아 둔다
  ↓ 증분 갱신 (전체 재계산 아님)
positions       종목당 한 행. net_quantity 부호가 방향, avg_price는 이동평균, realized_pnl은 누적
  ↓ 재평가
valuations      평가 이력. append-only
  ↓ 하루 한 번
daily_snapshots 일별 스냅샷. append-only. 같은 날 다시 찍으면 정정본(revision)을 새 행으로
```

실현손익은 **이동평균법**이다(FIFO 아님). 규칙과 손계산 예시는 METHODOLOGY.md 7장에 있다.

## 개발 규칙 (반드시 지킬 것)
1. 금액·가격·비율 계산에 float 금지. 백엔드는 Decimal, 프론트는 계산하지 않고 표시만 한다.
2. 비용(수수료·세금)은 원 미만 절사, 명목금액·손익은 원 단위 반올림(ROUND_HALF_UP).
3. 세율·승수·호가단위·한도 같은 숫자는 config/market_conventions.yaml에만 둔다. 코드 하드코딩 금지.
   값을 바꾸면 verified_as_of와 source도 갱신한다.
4. linear.py 등 엔진 모듈은 순수 함수로 유지한다(네트워크·DB 접근 금지).
5. 새 계산을 추가하면 세 가지를 함께 한다:
   (a) TraceStep으로 계산 근거 남기기 (b) METHODOLOGY.md에 산식·출처·손계산 예시 추가
   (c) 그 손계산 값을 기대값으로 하는 pytest 추가
6. DB: 가격·비율은 TEXT(Decimal 문자열), 금액은 원 단위 INTEGER.
   valuations는 감사추적 테이블이라 INSERT만 한다(트리거가 UPDATE/DELETE 차단). 포지션은 삭제하지 않고 CLOSED 처리.
7. SQL은 repository.py에만 둔다. 파라미터 바인딩(?)만 사용하고 문자열 포매팅으로 SQL을 만들지 않는다.
8. 파일 입출력은 항상 encoding="utf-8" (Windows 기본 cp949 문제 방지).
9. types.ts는 schemas.py와 항상 같이 고친다.
10. 화면 문구는 한국어, 문장형. 한국 시장 관행대로 매수·이익은 빨강(--gain), 매도·손실은 파랑(--loss).
    두 색은 의미 전달에만 쓴다. 숫자는 tabular-nums.
11. 커밋 전 확인: `python -m pytest` 전부 통과, `npm run build`와 `npm run lint` 오류 0.
12. 디자인은 DESIGN.md를 따른다. 특히 세 가지를 지킨다.
    (a) 빨강은 매수·이익, 파랑은 매도·손실 전용이다. 강조색·포커스·오류에 쓰지 않는다.
        오류와 경고는 오커(--alert) 계열이고, 색만이 아니라 아이콘과 문구로도 구분한다.
    (b) 반경은 컨트롤 6px(--r-control), 패널 10px(--r-panel) 둘뿐이다. z-index는 정의된 4단계만 쓴다.
    (c) 모션은 transform과 opacity만 애니메이션하고 무한 반복을 쓰지 않는다.
        prefers-reduced-motion에서는 이동만 없애고 상태 변화는 남긴다.
13. 화면 문구에 엠대시(U+2014)와 엔대시(U+2013)를 쓰지 않는다. 음수 부호(U+2212)는 수학 기호라 허용한다.
    값이 없을 때는 format.ts의 EMPTY('-')를 쓴다.
14. 근거 줄을 추가하면 TraceStep의 inputs도 함께 채운다. 화면의 근거 추적이 그 목록만 보고 동작한다.
15. 포지션 상태를 직접 쓰지 않는다. 체결을 넣고 trades.py가 갱신하게 한다.
    평균단가는 소수 4자리 반올림, 실현손익은 원 단위다.
16. 날짜가 필요한 곳은 Asia/Seoul 기준으로 파이썬에서 계산한다.
    SQLite의 datetime('now')는 UTC라서 한국 저녁에 찍으면 전날로 기록된다.
17. 배포 환경에서 달라지는 값은 app/settings.py에만 둔다. 환경변수를 코드 곳곳에서 읽지 않는다.
    환경변수를 하나도 주지 않으면 로컬 개발 설정으로 동작해야 한다.
18. API 주소는 frontend/src/api.ts 한 곳에서만 다룬다. 컴포넌트는 주소를 알 필요가 없다.

## 알아둘 제약
- pykrx는 import 시 "KRX 로그인 실패" 안내를 출력하지만 오류가 아니다. 수정주가 조회는 로그인 없이 된다.
  종목명 조회는 KRX 원천이라 실패할 수 있고, 실패해도 평가는 계속된다.
  KRX 원천 데이터가 필요해지면 data.krx.co.kr 계정을 만들어 환경변수 KRX_ID, KRX_PW를 설정한다.
- 수정주가 기준이므로 진입 이후 액면분할·무상증자가 있었다면 진입가도 수정 기준으로 환산해야 한다.
- 선물 시세는 무료 소스가 없어 평가가격을 수동 입력한다.
- 리스크 한도 값은 데모용 예시다(회사별 내부 기준).

## 로드맵
- [x] 1단계: 주식·선물(선형 상품) 시가평가·손익·비용, 북 집계, 한도 점검, 엔진·SQL 대사, 감사추적
- [ ] 2단계: 옵션 QuantLib 블랙-숄즈-머튼 이론가, 그릭스(Delta·Gamma·Vega·Theta·Rho), 내재변동성,
      시장가 대비 고평가/저평가 표시. 코스피200 옵션 승수는 YAML에 추가(KRX 명세 확인 후).
      무위험이자율은 한국은행 ECOS(ecos-reader)에서 CD 91일물 등으로 가져온다(API 키 필요).
- [ ] 3단계: 채권 QuantLib FixedRateBond로 가격, 수정듀레이션, DV01. 할인금리는 ECOS 국고채 수익률.
- [ ] 4단계: 북 VaR pykrx 일별 수익률로 모수적 VaR(95%/99%)와 역사적 VaR, 한도 점검에 VaR 한도 추가.
- [ ] 5단계: AI Claude API로 북 리스크 코멘트 초안 생성(숫자는 엔진 값만 인용, LLM이 숫자를 만들지 않도록 검증),
      계산 엔진을 MCP 서버로 감싸 에이전트가 도구로 호출하게 만들기.
