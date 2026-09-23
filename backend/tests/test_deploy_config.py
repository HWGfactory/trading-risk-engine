"""배포 설정: 환경변수, 데모 모드, 자동 시드.

환경변수를 하나도 주지 않으면 지금까지와 똑같이 동작해야 한다.
"""
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import demo_seed, settings
from app import repository as repo
from app.main import app, get_price_fetcher
from tests.test_api import fake_fetch


# ---------- 환경변수 ----------

def test_allowed_origins_defaults_to_localhost(monkeypatch):
    monkeypatch.delenv("ALLOWED_ORIGINS", raising=False)
    assert settings.allowed_origins() == list(settings.DEFAULT_ORIGINS)


def test_allowed_origins_parses_comma_separated(monkeypatch):
    monkeypatch.setenv(
        "ALLOWED_ORIGINS",
        " https://a.vercel.app , https://b.vercel.app/ ")
    # 공백과 끝 슬래시를 정리한다. CORS는 정확히 일치해야 통과하기 때문이다.
    assert settings.allowed_origins() == ["https://a.vercel.app", "https://b.vercel.app"]


def test_port_defaults_and_reads_env(monkeypatch):
    monkeypatch.delenv("PORT", raising=False)
    assert settings.port() == 8000
    monkeypatch.setenv("PORT", "10000")
    assert settings.port() == 10000
    monkeypatch.setenv("PORT", "이상한값")
    assert settings.port() == 8000      # 잘못된 값이면 기본값으로 돈다


@pytest.mark.parametrize("raw,expected", [
    ("1", True), ("true", True), ("TRUE", True), ("yes", True), ("on", True),
    ("0", False), ("false", False), ("", False), ("아무거나", False),
])
def test_demo_mode_flag(monkeypatch, raw, expected):
    monkeypatch.setenv("DEMO_MODE", raw)
    assert settings.demo_mode() is expected


def test_auto_seed_follows_demo_mode_unless_set(monkeypatch):
    monkeypatch.delenv("AUTO_SEED", raising=False)
    monkeypatch.setenv("DEMO_MODE", "true")
    assert settings.auto_seed() is True      # 데모면 기본으로 함께 켜진다
    monkeypatch.setenv("AUTO_SEED", "false")
    assert settings.auto_seed() is False     # 명시하면 그 값을 따른다


# ---------- 데모 모드 ----------

def test_reference_reports_demo_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("TRE_DB_PATH", str(tmp_path / "a.db"))
    monkeypatch.setenv("AUTO_SEED", "false")

    monkeypatch.delenv("DEMO_MODE", raising=False)
    with TestClient(app) as c:
        assert c.get("/api/reference").json()["demo_mode"] is False

    monkeypatch.setenv("DEMO_MODE", "true")
    with TestClient(app) as c:
        assert c.get("/api/reference").json()["demo_mode"] is True


def test_demo_mode_caps_new_positions(tmp_path, monkeypatch):
    monkeypatch.setenv("TRE_DB_PATH", str(tmp_path / "b.db"))
    monkeypatch.setenv("AUTO_SEED", "false")
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("DEMO_MAX_POSITIONS", "2")
    app.dependency_overrides[get_price_fetcher] = lambda: fake_fetch

    def buy(symbol, market="KOSPI"):
        return app_client.post("/api/trades", json={
            "asset_class": "EQUITY", "side": "BUY", "quantity": 1, "market": market,
            "symbol": symbol, "price": "1000"})

    with TestClient(app) as app_client:
        assert buy("005930").status_code == 201
        assert buy("035720").status_code == 201
        # 상한에 걸린 새 종목은 거절한다
        blocked = buy("247540")
        assert blocked.status_code == 409
        assert "데모 환경" in blocked.json()["detail"][0]
        # 이미 들고 있는 종목에 더하는 것은 막지 않는다
        assert buy("005930").status_code == 201
    app.dependency_overrides.clear()


def test_no_cap_when_demo_mode_off(tmp_path, monkeypatch):
    monkeypatch.setenv("TRE_DB_PATH", str(tmp_path / "c.db"))
    monkeypatch.setenv("AUTO_SEED", "false")
    monkeypatch.delenv("DEMO_MODE", raising=False)
    monkeypatch.setenv("DEMO_MAX_POSITIONS", "1")
    with TestClient(app) as c:
        for sym in ("005930", "035720", "247540"):
            r = c.post("/api/trades", json={
                "asset_class": "EQUITY", "side": "BUY", "quantity": 1, "market": "KOSPI",
                "symbol": sym, "price": "1000"})
            assert r.status_code == 201


# ---------- 자동 시드 ----------

def test_seed_creates_demo_book(tmp_path):
    conn = repo.connect(tmp_path / "seed.db")
    repo.init_db(conn)
    assert demo_seed.is_empty(conn)

    made = demo_seed.seed(conn)
    assert made == len(demo_seed.DEMO_TRADES)
    assert not demo_seed.is_empty(conn)

    positions = {r["symbol"]: r for r in repo.list_open_positions(conn)}
    # 분할 매수와 부분 청산이 반영된 상태여야 화면에 평균단가와 실현손익이 보인다
    samsung = positions["005930"]
    assert int(samsung["net_quantity"]) == 400
    assert samsung["avg_price"] == "274400.0000"
    assert int(samsung["realized_pnl"]) == 595469
    assert len(positions) == 4


def test_startup_seeds_empty_db_when_enabled(tmp_path, monkeypatch):
    db = tmp_path / "auto.db"
    monkeypatch.setenv("TRE_DB_PATH", str(db))
    monkeypatch.setenv("AUTO_SEED", "true")
    # 시드 직후의 백그라운드 평가는 네트워크를 쓰므로 테스트에서는 끈다
    monkeypatch.setattr(demo_seed, "revalue_in_background", lambda _path: None)

    with TestClient(app) as c:
        assert len(c.get("/api/positions").json()) == 4

    # 두 번째 기동에서는 이미 데이터가 있으므로 건너뛴다(중복 생성 없음)
    with TestClient(app) as c:
        assert len(c.get("/api/trades").json()) == len(demo_seed.DEMO_TRADES)


def test_startup_does_not_seed_when_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("TRE_DB_PATH", str(tmp_path / "off.db"))
    monkeypatch.setenv("AUTO_SEED", "false")
    monkeypatch.delenv("DEMO_MODE", raising=False)
    with TestClient(app) as c:
        assert c.get("/api/positions").json() == []


def test_seed_goes_through_the_same_validation(tmp_path):
    """시드도 라우트와 같은 경로를 쓴다. 호가단위 검증이 그대로 적용된다."""
    from app.conventions import load_conventions
    from app.main import book_trade
    from app.schemas import TradeCreate

    conn = repo.connect(tmp_path / "v.db")
    repo.init_db(conn)
    bad = TradeCreate(asset_class="FUTURE", side="BUY", symbol="K200", quantity=1,
                      price="350.03", contract_code="KOSPI200_FUT")
    with pytest.raises(ValueError, match="호가단위"):
        book_trade(conn, bad, load_conventions())
