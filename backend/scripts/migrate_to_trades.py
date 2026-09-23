"""기존 positions 행을 체결(trades) 기반 구조로 옮긴다.

실행 (backend 폴더에서):
    .venv\\Scripts\\python -m scripts.migrate_to_trades

하는 일
    1. DB 파일을 .bak으로 복사한다.
    2. 기존 positions 각 행을 trades 1건으로 바꾼다(LONG이면 BUY, SHORT면 SELL).
    3. positions를 새 컬럼 구성으로 다시 만들되 **id를 보존한다.**
       기존 valuations.position_id가 그대로 유효해야 하기 때문이다.
    4. valuations와 market_data는 손대지 않는다.

이미 옮긴 DB에 다시 실행하면 아무것도 하지 않는다.
"""
from __future__ import annotations

import shutil
import sqlite3
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import repository as repo  # noqa: E402
from app.main import db_path  # noqa: E402


def has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return any(r["name"] == column for r in conn.execute(f"PRAGMA table_info({table})"))


def main() -> int:
    path = db_path()
    if not path.exists():
        print(f"DB가 없습니다: {path}")
        print("새로 만들면 이미 새 구조이므로 옮길 것이 없습니다.")
        return 0

    conn = repo.connect(path)
    if not has_column(conn, "positions", "direction"):
        print("이미 체결 기반 구조입니다. 아무것도 하지 않았습니다.")
        return 0

    backup = path.with_suffix(path.suffix + ".bak")
    shutil.copy2(path, backup)
    print(f"백업: {backup}")

    old = conn.execute("SELECT * FROM positions ORDER BY id").fetchall()
    print(f"옮길 포지션 {len(old)}건")

    # 새 구조 적용 (trades, daily_snapshots, 트리거, 뷰가 함께 생긴다).
    # executescript는 암묵적으로 커밋하므로 트랜잭션 밖에서 먼저 돌린다.
    conn.executescript(repo.SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()

    # PRAGMA legacy_alter_table = ON 이 필요한 이유
    #   SQLite 3.25부터 ALTER TABLE ... RENAME 은 다른 테이블의 FK 참조까지 따라서 고쳐 준다.
    #   여기서는 그게 문제가 된다. positions를 갈아끼우려고 새 테이블을 만들고 이름을 바꾸는데,
    #   그 과정에서 valuations.position_id 의 참조 대상이 중간 테이블 이름으로 바뀌어 버린다.
    #   legacy_alter_table을 켜면 옛 동작(이름만 바꾸고 참조는 그대로)으로 돌아가 이 문제가 없다.
    #
    # 위험: 이 플래그는 SQLite를 옛 동작으로 되돌리는 것이라, 참조가 어긋난 채로 남아도
    #   SQLite가 알려주지 않는다. 그래서 마지막에 PRAGMA foreign_key_check 로 직접 검사하고,
    #   한 건이라도 걸리면 되돌린다. 검사 없이 이 플래그만 쓰면 안 된다.
    #
    # 두 PRAGMA 모두 트랜잭션 밖에서 설정해야 적용된다.
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("PRAGMA legacy_alter_table = ON")

    try:
        conn.execute("BEGIN")
        conn.executescript("""
            CREATE TABLE positions_new (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                instrument_id   INTEGER NOT NULL UNIQUE REFERENCES instruments(id),
                net_quantity    INTEGER NOT NULL DEFAULT 0,
                avg_price       TEXT    NOT NULL DEFAULT '0',
                realized_pnl    INTEGER NOT NULL DEFAULT 0,
                entry_cost      INTEGER NOT NULL DEFAULT 0,
                commission_rate TEXT    NOT NULL DEFAULT '0',
                margin_rate     TEXT,
                status          TEXT    NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','CLOSED')),
                opened_at       TEXT    NOT NULL DEFAULT (datetime('now')),
                closed_at       TEXT
            );
        """)

        for row in old:
            qty = int(row["quantity"])
            side = "BUY" if row["direction"] == "LONG" else "SELL"
            signed = qty if row["direction"] == "LONG" else -qty
            price = Decimal(row["entry_price"])
            rate = Decimal(row["commission_rate"])
            # 기존 데이터에는 체결 수수료가 남아 있지 않다. 진입 명목금액 기준으로 추정해 채운다.
            notional = (price * Decimal(qty)).quantize(Decimal(1))
            entry_cost = int((notional * rate).to_integral_value(rounding="ROUND_DOWN"))
            closed = row["status"] == "CLOSED"

            conn.execute(
                """INSERT INTO positions_new (id, instrument_id, net_quantity, avg_price, realized_pnl,
                                          entry_cost, commission_rate, margin_rate, status,
                                          opened_at, closed_at)
                   VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?)""",
                (row["id"], row["instrument_id"], 0 if closed else signed,
                 "0" if closed else str(price), 0 if closed else entry_cost,
                 str(rate), row["margin_rate"], row["status"], row["opened_at"], row["closed_at"]),
            )
            conn.execute(
                """INSERT INTO trades (instrument_id, side, quantity, price, commission_rate,
                                       closed_quantity, realized_pnl, commission, transaction_tax,
                                       avg_price_after, qty_after, traded_at)
                   VALUES (?, ?, ?, ?, ?, 0, 0, ?, 0, ?, ?, ?)""",
                (row["instrument_id"], side, qty, str(price), str(rate),
                 entry_cost, str(price), signed, row["opened_at"]),
            )
            print(f"  #{row['id']} {row['direction']} {qty} @ {price} -> 체결 1건")

        conn.execute("DROP TABLE positions")
        conn.execute("ALTER TABLE positions_new RENAME TO positions")

        # legacy_alter_table을 켠 채 테이블을 갈아끼웠으므로 참조가 성한지 직접 확인한다.
        # 커밋 전에 검사해야 문제가 있을 때 되돌릴 수 있다.
        broken = conn.execute("PRAGMA foreign_key_check").fetchall()
        if broken:
            raise RuntimeError(
                "외래키 참조가 깨졌습니다: "
                + ", ".join(f"{r[0]} 행 {r[1]} → {r[2]}" for r in broken[:5])
            )

        conn.commit()
        conn.execute("PRAGMA legacy_alter_table = OFF")
        conn.execute("PRAGMA foreign_keys = ON")
        print("외래키 무결성 검사 통과 (PRAGMA foreign_key_check)")
    except Exception as exc:  # noqa: BLE001
        conn.rollback()
        conn.execute("PRAGMA legacy_alter_table = OFF")
        print(f"[실패] {exc}")
        print("변경을 되돌렸습니다(rollback).")
        print(f"그래도 DB가 이상하면 백업에서 복구하세요: copy {backup} {path}")
        return 1

    print(f"\n완료. 체결 {len(old)}건, 포지션 {len(old)}건을 옮겼습니다.")
    print("valuations와 market_data는 그대로 보존했습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
