# PI 데스크 포지션 평가 엔진

증권사 자기매매(PI) 포지션의 시가평가·손익·거래비용·리스크 한도를 계산하고,
모든 결과 숫자 옆에 산식과 대입값을 함께 보여주는 웹 도구입니다.

## 주요 기능
- 주식·선물 포지션 평가: 평가손익, 수수료, 2026년 기준 증권거래세, 순손익, 수익률, 선물 증거금
- 계산 근거 표: 각 단계의 산식·대입값·결과를 한 줄씩 표시
- 북 현황: 포지션 저장, 일괄 재평가(주식은 무료 시세 자동 조회), 총노출·순노출, 한도 점검
- 엔진·SQL 대사: Python 집계와 SQL 뷰 집계가 일치하는지 매번 자동 확인
- 감사추적: 평가 이력은 수정·삭제 불가(DB 트리거)

## 기술 스택
Python · FastAPI · SQLite(직접 SQL, 윈도 함수 뷰) · pykrx · pytest / React · TypeScript · Vite

## 실행 방법 (Windows)
```powershell
# 백엔드
cd backend
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m pytest
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000

# 프론트 (새 터미널)
cd frontend
npm install
npm run dev
```
http://localhost:5173 에 접속합니다.

## 계산 근거
산식, 세율 출처, 손계산 예시는 [METHODOLOGY.md](METHODOLOGY.md)에 있습니다.
테스트의 기대값은 모두 이 문서의 손계산 값입니다.

## 로드맵
옵션(블랙-숄즈·그릭스), 채권(듀레이션·DV01), 북 VaR, Claude API 리스크 코멘트, MCP 서버화
