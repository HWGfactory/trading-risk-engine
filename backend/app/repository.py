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


def create_position(conn: sqlite3.Connection, *, instrument_id: int, direction: str, quantity: int,
                    entry_price: Decimal, commission_rate: Decimal, margin_rate: Decimal | None) -> int:
    cur = conn.execute(
        """
        INSERT INTO positions (instrument_id, direction, quantity, entry_price, commission_rate, margin_rate)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (instrument_id, direction, quantity, str(entry_price), str(commission_rate),
         None if margin_rate is None else str(margin_rate)),
    )
    return int(cur.lastrowid)


_POSITION_SELECT = """
    SELECT p.id, p.direction, p.quantity, p.entry_price, p.commission_rate, p.margin_rate,
           p.status, p.opened_at,
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


def close_position(conn: sqlite3.Connection, position_id: int) -> bool:
    cur = conn.execute(
        "UPDATE positions SET status = 'CLOSED', closed_at = datetime('now') WHERE id = ? AND status = 'OPEN'",
        (position_id,),
    )
    return cur.rowcount == 1


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
