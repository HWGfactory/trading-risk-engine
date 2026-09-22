"""API 통합 테스트: 네트워크 없이 가짜 시세로 전 흐름을 검증한다."""
import sqlite3
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.main import app, get_price_fetcher
from app.prices import PriceQuote, normalize_ticker

FAKE_CLOSES = {"005930": Decimal("75000"), "035720": Decimal("40000")}


def fake_fetch(ticker: str) -> PriceQuote:
    t = normalize_ticker(ticker)
    return PriceQuote(t, None, FAKE_CLOSES[t], date.today(), "테스트 시세")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("TRE_DB_PATH", str(tmp_path / "test.db"))
    app.dependency_overrides[get_price_fetcher] = lambda: fake_fetch
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_single_valuation_matches_engine(client):
    r = client.post("/api/valuation/linear", json={
        "asset_class": "EQUITY", "direction": "LONG", "quantity": 100, "market": "KOSPI",
        "entry_price": "70000", "mark_price": "75000", "commission_rate": "0.00015"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["valuation"]["net_pnl"] == "482825"
    assert body["applied"]["tax_rate_total"] == "0.0020"
    assert body["valuation"]["trace"][0]["key"] == "entry_notional"


def test_future_multiplier_comes_from_config(client):
    r = client.post("/api/valuation/linear", json={
        "asset_class": "FUTURE", "direction": "LONG", "quantity": 2, "contract_code": "KOSPI200_FUT",
        "entry_price": "350.00", "mark_price": "352.50", "margin_rate": "0.1"})
    assert r.status_code == 200, r.text
    assert r.json()["applied"]["multiplier"] == "250000"
    assert r.json()["valuation"]["gross_pnl"] == "1250000"


def test_off_tick_future_price_rejected(client):
    r = client.post("/api/valuation/linear", json={
        "asset_class": "FUTURE", "direction": "LONG", "quantity": 1, "contract_code": "KOSPI200_FUT",
        "entry_price": "350.03", "mark_price": "352.50"})
    assert r.status_code == 400
    assert "호가단위" in r.json()["detail"][0]


def test_validation_messages_are_korean(client):
    r = client.post("/api/valuation/linear", json={
        "asset_class": "EQUITY", "direction": "LONG", "quantity": 0, "market": "KOSPI",
        "entry_price": "70000", "mark_price": "75000"})
    assert r.status_code == 422
    assert r.json()["detail"] == ["수량: 0보다 커야 합니다."]


def test_book_flow_revalue_and_reconcile(client):
    eq = client.post("/api/positions", json={
        "asset_class": "EQUITY", "direction": "LONG", "quantity": 100, "market": "KOSPI",
        "symbol": "005930", "name": "삼성전자", "entry_price": "70000", "commission_rate": "0.00015"})
    fut = client.post("/api/positions", json={
        "asset_class": "FUTURE", "direction": "SHORT", "quantity": 1, "contract_code": "KOSPI200_FUT",
        "symbol": "K200 2026-12", "entry_price": "350.00"})
    assert eq.status_code == 201 and fut.status_code == 201
    fut_id = fut.json()["id"]

    # 선물 평가가격이 없으면 해당 포지션만 오류, 대사는 건너뜀
    r = client.post("/api/book/revalue", json={})
    assert r.status_code == 200
    assert len(r.json()["errors"]) == 1
    assert r.json()["reconciliation"]["status"] == "SKIPPED"

    # 선물 평가가격을 넣으면 전체 평가 + SQL 뷰 대사 일치
    r = client.post("/api/book/revalue", json={"marks": {str(fut_id): "352.00"}})
    body = r.json()
    assert body["errors"] == []
    assert body["reconciliation"]["status"] == "MATCHED"
    assert body["totals"]["net_pnl"] == str(482825 - 500000)

    summary = client.get("/api/book/summary").json()
    assert summary["totals"]["net_pnl"] == body["totals"]["net_pnl"]

    positions = client.get("/api/positions").json()
    assert {p["latest"]["price_source"] for p in positions} == {"테스트 시세", "수동 입력"}


def test_close_position_keeps_history(client):
    p = client.post("/api/positions", json={
        "asset_class": "EQUITY", "direction": "LONG", "quantity": 1, "market": "KOSDAQ",
        "symbol": "035720", "entry_price": "39000"}).json()
    client.post("/api/book/revalue", json={})
    assert client.post(f"/api/positions/{p['id']}/close").status_code == 204
    assert client.get("/api/positions").json() == []
    assert client.post(f"/api/positions/{p['id']}/close").status_code == 404
    assert client.get("/api/book/summary").json()["totals"]["position_count"] == 0


def test_valuations_table_is_append_only(tmp_path):
    from app import repository as repo
    conn = repo.connect(tmp_path / "audit.db")
    repo.init_db(conn)
    conn.execute("INSERT INTO instruments (symbol, asset_class, market) VALUES ('005930','EQUITY','KOSPI')")
    conn.execute("INSERT INTO positions (instrument_id, direction, quantity, entry_price) VALUES (1,'LONG',1,'1')")
    conn.execute("""INSERT INTO valuations (position_id, run_id, mark_price, price_source, price_as_of,
                    signed_exposure, gross_pnl, total_costs, net_pnl) VALUES (1,'r','1','t','2026-01-01',1,0,0,0)""")
    with pytest.raises(sqlite3.IntegrityError, match="감사추적"):
        conn.execute("UPDATE valuations SET net_pnl = 999")
    with pytest.raises(sqlite3.IntegrityError, match="감사추적"):
        conn.execute("DELETE FROM valuations")


# ---------- 홈 "오늘의 북"이 쓰는 필드 ----------

def test_summary_exposes_limit_usage_and_last_valued_at(client):
    """한도 사용률과 마지막 평가 시각은 백엔드가 Decimal로 계산해 내려준다(프론트 계산 금지)."""
    empty = client.get("/api/book/summary").json()
    assert {u["code"] for u in empty["limit_usage"]} == {
        "GROSS_EXPOSURE", "LOSS_LIMIT", "POSITION_NOTIONAL"}
    assert all(u["ratio"] == "0.000000" for u in empty["limit_usage"])
    assert empty["last_valued_at"] is None

    client.post("/api/positions", json={
        "asset_class": "EQUITY", "direction": "LONG", "quantity": 100, "market": "KOSPI",
        "symbol": "005930", "entry_price": "70000", "commission_rate": "0.00015"})
    client.post("/api/book/revalue", json={})

    s = client.get("/api/book/summary").json()
    usage = {u["code"]: u for u in s["limit_usage"]}
    # 평가 명목 7,500,000, 설정 한도는 config/market_conventions.yaml 값을 그대로 쓴다
    assert usage["GROSS_EXPOSURE"]["used"] == "7500000"
    assert usage["POSITION_NOTIONAL"]["used"] == "7500000"
    assert usage["LOSS_LIMIT"]["used"] == "0"        # 이익이므로 손실 한도는 소진되지 않는다
    ref = client.get("/api/reference").json()["limits"]
    assert usage["GROSS_EXPOSURE"]["limit"] == ref["max_gross_exposure"]
    assert usage["POSITION_NOTIONAL"]["limit"] == ref["max_position_notional"]
    assert s["last_valued_at"] is not None


def test_trace_steps_carry_inputs_over_api(client):
    """근거 추적용 inputs가 JSON 계약에 포함된다."""
    body = client.post("/api/valuation/linear", json={
        "asset_class": "EQUITY", "direction": "LONG", "quantity": 100, "market": "KOSPI",
        "entry_price": "70000", "mark_price": "75000", "commission_rate": "0.00015"}).json()
    trace = {s["key"]: s for s in body["valuation"]["trace"]}
    assert trace["entry_notional"]["inputs"] == ["entry_price", "quantity", "multiplier"]
    assert trace["transaction_tax"]["inputs"][0] == "mark_price"
    assert all(s["inputs"] for s in body["valuation"]["trace"])
