"""SQLite 접근 계층. ORM 없이 SQL을 직접 쓴다(쿼리가 곧 문서가 되도록)."""
from __future__ import annotations

import sqlite3
from decimal import Decimal
from pathlib import Path

from app.linear import LinearValuation

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()


def _as_int(x: Decimal) -> int:
    """원 단위로 확정된 Decimal만 정수로 저장한다."""
    if x != x.to_integral_value():
        raise ValueError(f"원 단위가 아닌 금액은 저장할 수 없습니다: {x}")
    return int(x)


def upsert_instrument(conn: sqlite3.Connection, *, symbol: str, name: str | None, asset_class: str,
                      market: str | None, contract_code: str | None, multiplier: Decimal) -> int:
    conn.execute(
        """
        INSERT INTO instruments (symbol, name, asset_class, market, contract_code, multiplier)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT (symbol, asset_class) DO UPDATE SET
            name          = COALESCE(excluded.name, instruments.name),
            market        = excluded.market,
            contract_code = excluded.contract_code,
            multiplier    = excluded.multiplier
        """,
        (symbol, name, asset_class, market, contract_code, str(multiplier)),
    )
    row = conn.execute(
        "SELECT id FROM instruments WHERE symbol = ? AND asset_class = ?", (symbol, asset_class)
    ).fetchone()
    return int(row["id"])


def get_or_create_position(conn: sqlite3.Connection, *, instrument_id: int) -> sqlite3.Row:
    """종목당 한 행. 없으면 빈 포지션을 만든다."""
    conn.execute(
        "INSERT INTO positions (instrument_id) VALUES (?) ON CONFLICT (instrument_id) DO NOTHING",
        (instrument_id,),
    )
    return conn.execute(
        "SELECT * FROM positions WHERE instrument_id = ?", (instrument_id,)
    ).fetchone()


def update_position(conn: sqlite3.Connection, *, position_id: int, net_quantity: int,
                    avg_price: Decimal, realized_pnl: Decimal, entry_cost: Decimal,
                    commission_rate: Decimal, margin_rate: Decimal | None) -> None:
    """체결 반영 후 상태를 증분 갱신한다. 수량이 0이면 CLOSED로 닫는다."""
    closed = net_quantity == 0
    conn.execute(
        """
        UPDATE positions
           SET net_quantity    = ?,
               avg_price       = ?,
               realized_pnl    = ?,
               entry_cost      = ?,
               commission_rate = ?,
               margin_rate     = ?,
               status          = ?,
               closed_at       = CASE WHEN ? THEN datetime('now') ELSE NULL END,
               opened_at       = CASE WHEN net_quantity = 0 AND ? <> 0
                                      THEN datetime('now') ELSE opened_at END
         WHERE id = ?
        """,
        (net_quantity, str(avg_price), _as_int(realized_pnl), _as_int(entry_cost),
         str(commission_rate), None if margin_rate is None else str(margin_rate),
         "CLOSED" if closed else "OPEN", closed, net_quantity, position_id),
    )


def insert_trade(conn: sqlite3.Connection, *, instrument_id: int, side: str, quantity: int,
                 price: Decimal, commission_rate: Decimal, closed_quantity: int,
                 realized_pnl: Decimal, commission: Decimal, transaction_tax: Decimal,
                 avg_price_after: Decimal, qty_after: int) -> int:
    cur = conn.execute(
        """
        INSERT INTO trades (instrument_id, side, quantity, price, commission_rate,
                            closed_quantity, realized_pnl, commission, transaction_tax,
                            avg_price_after, qty_after)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (instrument_id, side, quantity, str(price), str(commission_rate), closed_quantity,
         _as_int(realized_pnl), _as_int(commission), _as_int(transaction_tax),
         str(avg_price_after), qty_after),
    )
    return int(cur.lastrowid)


def list_trades(conn: sqlite3.Connection, instrument_id: int | None = None) -> list[sqlite3.Row]:
    sql = """
        SELECT t.*, i.symbol, i.name, i.asset_class, i.market, i.contract_code, i.multiplier
        FROM trades t
        JOIN instruments i ON i.id = t.instrument_id
    """
    if instrument_id is None:
        return conn.execute(sql + " ORDER BY t.traded_at, t.id").fetchall()
    return conn.execute(sql + " WHERE t.instrument_id = ? ORDER BY t.traded_at, t.id",
                        (instrument_id,)).fetchall()


_POSITION_SELECT = """
    SELECT p.id, p.net_quantity, p.avg_price, p.realized_pnl, p.entry_cost,
           p.commission_rate, p.margin_rate, p.status, p.opened_at,
           i.id AS instrument_id, i.symbol, i.name, i.asset_class, i.market, i.contract_code, i.multiplier,
           lv.valued_at, lv.mark_price, lv.price_source, lv.price_as_of,
           lv.signed_exposure, lv.gross_pnl, lv.total_costs, lv.net_pnl
    FROM positions p
    JOIN instruments i ON i.id = p.instrument_id
    LEFT JOIN v_latest_valuation lv ON lv.position_id = p.id
"""


def list_open_positions(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(_POSITION_SELECT + " WHERE p.status = 'OPEN' ORDER BY p.id").fetchall()


def get_position(conn: sqlite3.Connection, position_id: int) -> sqlite3.Row | None:
    return conn.execute(_POSITION_SELECT + " WHERE p.id = ?", (position_id,)).fetchone()


def find_position_by_instrument(conn: sqlite3.Connection, instrument_id: int) -> sqlite3.Row | None:
    return conn.execute(_POSITION_SELECT + " WHERE p.instrument_id = ?", (instrument_id,)).fetchone()


def save_price(conn: sqlite3.Connection, *, instrument_id: int, price_date: str,
               close_price: Decimal, source: str) -> None:
    conn.execute(
        """
        INSERT INTO market_data (instrument_id, price_date, close_price, source)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (instrument_id, price_date, source) DO UPDATE SET
            close_price = excluded.close_price,
            fetched_at  = datetime('now')
        """,
        (instrument_id, price_date, str(close_price), source),
    )


def insert_valuation(conn: sqlite3.Connection, *, position_id: int, run_id: str, mark_price: Decimal,
                     price_source: str, price_as_of: str, valuation: LinearValuation) -> None:
    conn.execute(
        """
        INSERT INTO valuations (position_id, run_id, mark_price, price_source, price_as_of,
                                signed_exposure, gross_pnl, total_costs, net_pnl)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (position_id, run_id, str(mark_price), price_source, price_as_of,
         _as_int(valuation.signed_exposure), _as_int(valuation.gross_pnl),
         _as_int(valuation.total_costs), _as_int(valuation.net_pnl)),
    )


def book_by_asset_class(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM v_book_by_asset_class ORDER BY asset_class").fetchall()


def largest_position_notional(conn: sqlite3.Connection) -> Decimal:
    """열린 포지션 중 최신 평가 기준 명목금액이 가장 큰 값. 평가 이력이 없으면 0."""
    row = conn.execute(
        """
        SELECT MAX(ABS(lv.signed_exposure)) AS largest
        FROM v_latest_valuation lv
        JOIN positions p ON p.id = lv.position_id AND p.status = 'OPEN'
        """
    ).fetchone()
    return Decimal(row["largest"]) if row and row["largest"] is not None else Decimal(0)


def last_valued_at(conn: sqlite3.Connection) -> str | None:
    """열린 포지션에 대한 마지막 평가 시각. 평가 이력이 없으면 None."""
    row = conn.execute(
        """
        SELECT MAX(v.valued_at) AS last_at
        FROM valuations v
        JOIN positions p ON p.id = v.position_id AND p.status = 'OPEN'
        """
    ).fetchone()
    return row["last_at"] if row and row["last_at"] else None


# ---------- 일별 스냅샷 ----------

def snapshot_exists(conn: sqlite3.Connection, snapshot_date: str) -> int:
    """해당 날짜에 이미 찍힌 스냅샷의 최대 정정본 번호. 없으면 0."""
    row = conn.execute(
        "SELECT COALESCE(MAX(revision), 0) AS rev FROM daily_snapshots WHERE snapshot_date = ?",
        (snapshot_date,),
    ).fetchone()
    return int(row["rev"])


def insert_snapshot(conn: sqlite3.Connection, *, snapshot_date: str, revision: int,
                    instrument_id: int, mark_price: Decimal, price_source: str,
                    net_quantity: int, avg_price: Decimal, unrealized_pnl: Decimal,
                    realized_pnl_cumulative: Decimal, signed_exposure: Decimal) -> None:
    conn.execute(
        """
        INSERT INTO daily_snapshots (snapshot_date, revision, instrument_id, mark_price,
                                     price_source, net_quantity, avg_price, unrealized_pnl,
                                     realized_pnl_cumulative, signed_exposure)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (snapshot_date, revision, instrument_id, str(mark_price), price_source,
         net_quantity, str(avg_price), _as_int(unrealized_pnl),
         _as_int(realized_pnl_cumulative), _as_int(signed_exposure)),
    )


def book_history(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM v_book_history ORDER BY snapshot_date").fetchall()


def realized_pnl_total(conn: sqlite3.Connection) -> Decimal:
    """열린 포지션과 닫힌 포지션을 모두 포함한 실현손익 누적."""
    row = conn.execute("SELECT COALESCE(SUM(realized_pnl), 0) AS total FROM positions").fetchone()
    return Decimal(int(row["total"]))
