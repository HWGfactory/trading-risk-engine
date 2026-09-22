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
- 계산 라이브러리(2단계부터): QuantLib-Python

## 실행 (Windows PowerShell)
백엔드 (터미널 1)
```
cd backend
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m pytest
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```
프론트 (터미널 2, Node 20.19+ 또는 22.12+)
```
cd frontend
npm install
npm run dev
```
브라우저: http://localhost:5173  /  API 문서: http://127.0.0.1:8000/docs

## 파일 구조
```
backend/
  config/market_conventions.yaml  세율·계약승수·호가단위·리스크 한도 (근거·확인일 포함)
  app/
    main.py         FastAPI 라우트, 의존성, 오류 응답(한국어), 엔진·SQL 대사
    schemas.py      요청·응답 스키마 (Decimal은 JSON 문자열)
    conventions.py  YAML 로더 (UTF-8 고정)
    linear.py       주식·선물 평가 엔진 (순수 함수, I/O 없음)
    portfolio.py    북 집계, 한도 점검
    prices.py       시세 어댑터 (pykrx → FDR, 소스별 10초 제한)
    repository.py   SQL 접근 계층
    schema.sql      테이블·뷰·감사 트리거
  tests/            pytest (엔진 정답 케이스, API 통합, 시세 폴백)
frontend/src/
  App.tsx           헤더·탭·전역 상태
  api.ts            fetch 래퍼, 오류 메시지 정규화
  types.ts          백엔드 schemas.py와 1:1 대응 타입
  format.ts         표시용 포맷, 퍼센트↔비율 문자열 변환
  components/
    DealTicket.tsx          매매 전표 입력
    ValuationStatement.tsx  결과·계산 근거 표
    BookView.tsx            북 현황·재평가·대사
METHODOLOGY.md      산식과 근거, 손계산 예시 (테스트 기대값의 출처)
```

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

## 알아둘 제약
- pykrx는 import 시 "KRX 로그인 실패" 안내를 출력하지만 오류가 아니다. 수정주가 조회는 로그인 없이 된다.
  종목명 조회는 KRX 원천이라 실패할 수 있고, 실패해도 평가는 계속된다.
  KRX 원천 데이터가 필요해지면 data.krx.co.kr 계정을 만들어 환경변수 KRX_ID, KRX_PW를 설정한다.
- 수정주가 기준이므로 진입 이후 액면분할·무상증자가 있었다면 진입가도 수정 기준으로 환산해야 한다.
- 선물 시세는 무료 소스가 없어 평가가격을 수동 입력한다.
- 리스크 한도 값은 데모용 예시다(회사별 내부 기준).

## 로드맵
- [x] 1단계: 주식·선물(선형 상품) 시가평가·손익·비용, 북 집계, 한도 점검, 엔진·SQL 대사, 감사추적
- [ ] 2단계: 옵션 — QuantLib 블랙-숄즈-머튼 이론가, 그릭스(Delta·Gamma·Vega·Theta·Rho), 내재변동성,
      시장가 대비 고평가/저평가 표시. 코스피200 옵션 승수는 YAML에 추가(KRX 명세 확인 후).
      무위험이자율은 한국은행 ECOS(ecos-reader)에서 CD 91일물 등으로 가져온다(API 키 필요).
- [ ] 3단계: 채권 — QuantLib FixedRateBond로 가격, 수정듀레이션, DV01. 할인금리는 ECOS 국고채 수익률.
- [ ] 4단계: 북 VaR — pykrx 일별 수익률로 모수적 VaR(95%/99%)와 역사적 VaR, 한도 점검에 VaR 한도 추가.
- [ ] 5단계: AI — Claude API로 북 리스크 코멘트 초안 생성(숫자는 엔진 값만 인용, LLM이 숫자를 만들지 않도록 검증),
      계산 엔진을 MCP 서버로 감싸 에이전트가 도구로 호출하게 만들기.
