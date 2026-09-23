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
    eq = client.post("/api/trades", json={
        "asset_class": "EQUITY", "side": "BUY", "quantity": 100, "market": "KOSPI",
        "symbol": "005930", "name": "삼성전자", "price": "70000", "commission_rate": "0.00015"})
    fut = client.post("/api/trades", json={
        "asset_class": "FUTURE", "side": "SELL", "quantity": 1, "contract_code": "KOSPI200_FUT",
        "symbol": "K200 2026-12", "price": "350.00"})
    assert eq.status_code == 201, eq.text
    assert fut.status_code == 201, fut.text
    fut_id = fut.json()["position"]["id"]

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


def test_close_position_now_books_an_offsetting_trade(client):
    """청산은 상태만 바꾸지 않고 반대 방향 전량 체결로 동작한다."""
    p = client.post("/api/trades", json={
        "asset_class": "EQUITY", "side": "BUY", "quantity": 1, "market": "KOSDAQ",
        "symbol": "035720", "price": "39000"}).json()["position"]
    client.post("/api/book/revalue", json={})

    r = client.post(f"/api/positions/{p['id']}/close")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["trade"]["side"] == "SELL"        # 반대 방향 체결이 쌓인다
    assert body["trade"]["closed_quantity"] == 1
    assert body["position"]["net_quantity"] == 0

    assert client.get("/api/positions").json() == []
    assert client.post(f"/api/positions/{p['id']}/close").status_code == 404
    assert client.get("/api/book/summary").json()["totals"]["position_count"] == 0
    # 체결 이력은 매수 1건 + 청산 매도 1건
    assert len(client.get("/api/trades").json()) == 2


def test_valuations_table_is_append_only(tmp_path):
    from app import repository as repo
    conn = repo.connect(tmp_path / "audit.db")
    repo.init_db(conn)
    conn.execute("INSERT INTO instruments (symbol, asset_class, market) VALUES ('005930','EQUITY','KOSPI')")
    conn.execute("INSERT INTO positions (instrument_id, net_quantity, avg_price) VALUES (1,1,'1')")
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

    client.post("/api/trades", json={
        "asset_class": "EQUITY", "side": "BUY", "quantity": 100, "market": "KOSPI",
        "symbol": "005930", "price": "70000", "commission_rate": "0.00015"})
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


# ---------- 체결 기반 흐름 ----------

def test_trade_flow_average_then_partial_close(client):
    """분할 매수 -> 부분 청산. 화면이 쓰는 값이 API로 그대로 나오는지 확인한다."""
    def buy(qty, price):
        return client.post("/api/trades", json={
            "asset_class": "EQUITY", "side": "BUY", "quantity": qty, "market": "KOSPI",
            "symbol": "005930", "name": "삼성전자", "price": price})

    assert buy(100, "70000").status_code == 201
    r = buy(50, "76000")
    assert r.status_code == 201, r.text
    pos = r.json()["position"]
    assert pos["avg_price"] == "72000.0000"      # (100x70,000 + 50x76,000) / 150
    assert pos["net_quantity"] == 150
    assert pos["realized_pnl"] == "0"

    r = client.post("/api/trades", json={
        "asset_class": "EQUITY", "side": "SELL", "quantity": 60, "market": "KOSPI",
        "symbol": "005930", "price": "80000"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["realized_gross"] == "480000"     # (80,000 - 72,000) x 60
    assert body["position"]["net_quantity"] == 90
    assert body["position"]["avg_price"] == "72000.0000"   # 청산은 평균단가를 바꾸지 않는다
    assert body["trade"]["closed_quantity"] == 60
    assert "부분 청산" in body["message"]

    trades = client.get("/api/trades").json()
    assert [t["side"] for t in trades] == ["BUY", "BUY", "SELL"]
    assert [t["qty_after"] for t in trades] == [100, 150, 90]


def test_oversell_flips_direction_rather_than_rejecting(client):
    """보유 수량을 넘는 반대 방향 체결은 거절이 아니라 방향 전환이다(규칙 3).

    이 앱은 공매도 포지션을 지원하므로, 100주 보유 중 150주 매도는
    100주 청산 + 50주 신규 매도로 해석하는 것이 맞다.
    """
    client.post("/api/trades", json={
        "asset_class": "EQUITY", "side": "BUY", "quantity": 100, "market": "KOSPI",
        "symbol": "005930", "price": "70000"})
    r = client.post("/api/trades", json={
        "asset_class": "EQUITY", "side": "SELL", "quantity": 150, "market": "KOSPI",
        "symbol": "005930", "price": "75000"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["realized_gross"] == "500000"              # 100주분만 실현
    assert body["position"]["net_quantity"] == -50         # 남은 50주는 매도 포지션
    assert body["position"]["avg_price"] == "75000.0000"   # 평균단가는 이번 체결가
    assert body["trade"]["closed_quantity"] == 100
    assert "새로 잡았습니다" in body["message"]


def test_trade_preview_does_not_persist(client):
    client.post("/api/trades", json={
        "asset_class": "EQUITY", "side": "BUY", "quantity": 100, "market": "KOSPI",
        "symbol": "005930", "price": "70000"})
    r = client.post("/api/trades/preview", json={
        "asset_class": "EQUITY", "side": "BUY", "quantity": 50, "market": "KOSPI",
        "symbol": "005930", "price": "76000"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["holds"] is True
    assert body["avg_price_before"] == "70000.0000"
    assert body["avg_price_after"] == "72000.0000"
    # 미리보기는 저장하지 않는다
    assert client.get("/api/positions").json()[0]["net_quantity"] == 100
    assert len(client.get("/api/trades").json()) == 1


def test_close_rejects_unknown_and_unvalued_positions(client):
    assert client.post("/api/positions/999/close").status_code == 404

    p = client.post("/api/trades", json={
        "asset_class": "EQUITY", "side": "BUY", "quantity": 10, "market": "KOSPI",
        "symbol": "005930", "price": "70000"}).json()["position"]
    # 평가 이력이 없으면 청산 가격을 알 수 없다
    r = client.post(f"/api/positions/{p['id']}/close")
    assert r.status_code == 409
    assert "재평가" in r.json()["detail"][0]


def test_futures_tick_size_is_enforced_on_trades(client):
    r = client.post("/api/trades", json={
        "asset_class": "FUTURE", "side": "BUY", "quantity": 1,
        "contract_code": "KOSPI200_FUT", "symbol": "K200 2026-12", "price": "350.03"})
    assert r.status_code == 400
    assert "호가단위" in r.json()["detail"][0]


# ---------- 스냅샷 ----------

def test_snapshot_rejects_duplicate_and_allows_revision(client):
    client.post("/api/trades", json={
        "asset_class": "EQUITY", "side": "BUY", "quantity": 100, "market": "KOSPI",
        "symbol": "005930", "price": "70000"})
    client.post("/api/book/revalue", json={})

    first = client.post("/api/book/snapshot")
    assert first.status_code == 201, first.text
    assert first.json()["revision"] == 1
    assert len(first.json()["rows"]) == 1

    # 같은 날 다시 찍으면 거절한다. 덮어쓰지 않는다.
    dup = client.post("/api/book/snapshot")
    assert dup.status_code == 409
    assert "이미 있습니다" in dup.json()["detail"][0]

    # 정정본은 새 행으로 추가된다. 이전 행은 그대로 남는다.
    revised = client.post("/api/book/snapshot?revise=true")
    assert revised.status_code == 201
    assert revised.json()["revision"] == 2

    history = client.get("/api/book/history").json()["rows"]
    assert len(history) == 1                       # 같은 날이므로 한 줄
    assert history[0]["position_count"] == 1       # 최신 정정본만 센다


def test_snapshot_date_uses_seoul_time(client):
    from app.main import seoul_today
    client.post("/api/trades", json={
        "asset_class": "EQUITY", "side": "BUY", "quantity": 1, "market": "KOSPI",
        "symbol": "005930", "price": "70000"})
    client.post("/api/book/revalue", json={})
    r = client.post("/api/book/snapshot").json()
    # SQLite의 datetime('now')는 UTC라서 한국 저녁에 찍으면 전날로 기록된다
    assert r["snapshot_date"] == seoul_today()


def test_snapshots_are_append_only(tmp_path):
    from app import repository as repo
    conn = repo.connect(tmp_path / "snap.db")
    repo.init_db(conn)
    conn.execute("INSERT INTO instruments (symbol, asset_class, market) VALUES ('005930','EQUITY','KOSPI')")
    conn.execute("""INSERT INTO daily_snapshots (snapshot_date, revision, instrument_id, mark_price,
                    price_source, net_quantity, avg_price, unrealized_pnl,
                    realized_pnl_cumulative, signed_exposure)
                    VALUES ('2026-01-02',1,1,'1','t',1,'1',0,0,1)""")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE daily_snapshots SET unrealized_pnl = 1 WHERE id = 1")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM daily_snapshots WHERE id = 1")


def test_trades_are_append_only(tmp_path):
    from app import repository as repo
    conn = repo.connect(tmp_path / "tr.db")
    repo.init_db(conn)
    conn.execute("INSERT INTO instruments (symbol, asset_class, market) VALUES ('005930','EQUITY','KOSPI')")
    conn.execute("""INSERT INTO trades (instrument_id, side, quantity, price, avg_price_after, qty_after)
                    VALUES (1,'BUY',1,'100','100',1)""")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE trades SET quantity = 2 WHERE id = 1")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM trades WHERE id = 1")


def test_preview_reports_direction_flip(client):
    """방향 전환 여부와 수량을 백엔드가 내려준다. 화면이 계산하지 않는다."""
    client.post("/api/trades", json={
        "asset_class": "EQUITY", "side": "BUY", "quantity": 100, "market": "KOSPI",
        "symbol": "005930", "price": "70000"})

    # 보유 수량 이내면 전환이 아니다
    r = client.post("/api/trades/preview", json={
        "asset_class": "EQUITY", "side": "SELL", "quantity": 60, "market": "KOSPI",
        "symbol": "005930", "price": "75000"}).json()
    assert r["flips"] is False
    assert r["opened_quantity"] == 0
    assert r["closed_quantity"] == 60

    # 보유 수량을 넘으면 전환이다
    r = client.post("/api/trades/preview", json={
        "asset_class": "EQUITY", "side": "SELL", "quantity": 150, "market": "KOSPI",
        "symbol": "005930", "price": "75000"}).json()
    assert r["flips"] is True
    assert r["closed_quantity"] == 100      # 매수 100주가 청산되고
    assert r["opened_quantity"] == 50       # 매도 50주가 새로 생긴다
    assert r["direction_before"] == "LONG"
    assert r["direction_after"] == "SHORT"
