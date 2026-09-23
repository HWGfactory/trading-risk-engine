"""구 스키마 DB를 체결 기반 구조로 옮기는 마이그레이션 검증.

포지션 id 보존과 외래키 무결성이 핵심이다. 기존 valuations가 계속 유효해야 한다.
"""
import sqlite3

import pytest

from app import repository as repo
from scripts.migrate_to_trades import has_column, main as migrate

# 체결 기반으로 바뀌기 전의 스키마. 마이그레이션 입력을 만들기 위한 것이다.
OLD_SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE instruments (
    id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL, name TEXT,
    asset_class TEXT NOT NULL, market TEXT, contract_code TEXT,
    multiplier TEXT NOT NULL DEFAULT '1', currency TEXT NOT NULL DEFAULT 'KRW',
    created_at TEXT NOT NULL DEFAULT (datetime('now')), UNIQUE (symbol, asset_class));
CREATE TABLE positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instrument_id INTEGER NOT NULL REFERENCES instruments(id),
    direction TEXT NOT NULL, quantity INTEGER NOT NULL, entry_price TEXT NOT NULL,
    commission_rate TEXT NOT NULL DEFAULT '0', margin_rate TEXT,
    status TEXT NOT NULL DEFAULT 'OPEN',
    opened_at TEXT NOT NULL DEFAULT (datetime('now')), closed_at TEXT);
CREATE TABLE market_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instrument_id INTEGER NOT NULL REFERENCES instruments(id),
    price_date TEXT NOT NULL, close_price TEXT NOT NULL, source TEXT NOT NULL,
    fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (instrument_id, price_date, source));
CREATE TABLE valuations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id INTEGER NOT NULL REFERENCES positions(id),
    run_id TEXT NOT NULL, valued_at TEXT NOT NULL DEFAULT (datetime('now')),
    mark_price TEXT NOT NULL, price_source TEXT NOT NULL, price_as_of TEXT NOT NULL,
    signed_exposure INTEGER NOT NULL, gross_pnl INTEGER NOT NULL,
    total_costs INTEGER NOT NULL, net_pnl INTEGER NOT NULL);
"""


@pytest.fixture
def old_db(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(OLD_SCHEMA)
    conn.execute("INSERT INTO instruments (symbol, name, asset_class, market) "
                 "VALUES ('005930','삼성전자','EQUITY','KOSPI')")
    conn.execute("INSERT INTO instruments (symbol, asset_class, contract_code, multiplier) "
                 "VALUES ('K200 2026-12','FUTURE','KOSPI200_FUT','250000')")
    conn.execute("INSERT INTO positions (id, instrument_id, direction, quantity, entry_price, "
                 "commission_rate) VALUES (1,1,'LONG',100,'70000','0.00015')")
    conn.execute("INSERT INTO positions (id, instrument_id, direction, quantity, entry_price, "
                 "commission_rate, status, closed_at) "
                 "VALUES (2,2,'SHORT',3,'350.00','0.00003','CLOSED','2026-01-02 00:00:00')")
    # 기존 평가 이력. 마이그레이션 후에도 그대로 유효해야 한다.
    for pid in (1, 2):
        conn.execute("""INSERT INTO valuations (position_id, run_id, mark_price, price_source,
                        price_as_of, signed_exposure, gross_pnl, total_costs, net_pnl)
                        VALUES (?, 'run1', '75000', '테스트', '2026-01-01', 1, 2, 3, 4)""", (pid,))
    conn.commit()
    conn.close()
    monkeypatch.setenv("TRE_DB_PATH", str(path))
    return path


def test_migration_preserves_ids_and_history(old_db):
    assert migrate() == 0

    conn = repo.connect(old_db)
    assert not has_column(conn, "positions", "direction")   # 새 구조로 바뀌었다

    positions = {r["id"]: r for r in conn.execute("SELECT * FROM positions ORDER BY id")}
    assert set(positions) == {1, 2}                          # id 보존
    assert positions[1]["net_quantity"] == 100               # LONG -> +
    assert positions[1]["avg_price"] == "70000"
    assert positions[1]["entry_cost"] == 1050                # 7,000,000 x 0.015%
    assert positions[2]["net_quantity"] == 0                 # CLOSED는 수량 0
    assert positions[2]["status"] == "CLOSED"

    trades = conn.execute("SELECT * FROM trades ORDER BY id").fetchall()
    assert [t["side"] for t in trades] == ["BUY", "SELL"]     # LONG->BUY, SHORT->SELL
    assert [t["quantity"] for t in trades] == [100, 3]

    # 기존 평가 이력이 그대로 있고 참조도 살아 있다
    assert conn.execute("SELECT COUNT(*) c FROM valuations").fetchone()["c"] == 2
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_migration_is_idempotent(old_db):
    assert migrate() == 0
    before = repo.connect(old_db).execute("SELECT COUNT(*) c FROM trades").fetchone()["c"]

    # 다시 실행해도 체결이 중복으로 쌓이지 않는다
    assert migrate() == 0
    conn = repo.connect(old_db)
    assert conn.execute("SELECT COUNT(*) c FROM trades").fetchone()["c"] == before
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_migration_on_fresh_db_does_nothing(tmp_path, monkeypatch):
    path = tmp_path / "fresh.db"
    conn = repo.connect(path)
    repo.init_db(conn)
    conn.close()
    monkeypatch.setenv("TRE_DB_PATH", str(path))
    assert migrate() == 0                                     # 이미 새 구조라 건너뛴다
