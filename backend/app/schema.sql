-- 자기매매 포지션 평가 엔진 스키마 (SQLite 3.25+, 윈도 함수 사용)
-- 설계 원칙
--   * 가격·비율은 TEXT(Decimal 문자열)로 저장해 부동소수점 오차를 피한다.
--   * 금액은 원 단위 정수(INTEGER)로 저장해 SUM 집계가 정확하도록 한다.
--   * valuations는 감사추적(audit trail) 테이블이다. INSERT만 허용한다.
--   * 포지션은 삭제하지 않고 CLOSED로 상태를 바꾼다(평가 이력 보존).

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS instruments (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol        TEXT    NOT NULL,                 -- 주식: 6자리 종목코드 / 선물: 사용자가 정한 월물 표기
    name          TEXT,
    asset_class   TEXT    NOT NULL CHECK (asset_class IN ('EQUITY', 'FUTURE')),
    market        TEXT             CHECK (market IN ('KOSPI', 'KOSDAQ')),
    contract_code TEXT,                             -- 선물 계약명세 키 (market_conventions.yaml)
    multiplier    TEXT    NOT NULL DEFAULT '1',
    currency      TEXT    NOT NULL DEFAULT 'KRW',
    created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (symbol, asset_class),
    CHECK ((asset_class = 'EQUITY' AND market IS NOT NULL)
        OR (asset_class = 'FUTURE' AND contract_code IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS positions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    instrument_id   INTEGER NOT NULL REFERENCES instruments(id),
    direction       TEXT    NOT NULL CHECK (direction IN ('LONG', 'SHORT')),
    quantity        INTEGER NOT NULL CHECK (quantity > 0),
    entry_price     TEXT    NOT NULL,
    commission_rate TEXT    NOT NULL DEFAULT '0',
    margin_rate     TEXT,
    status          TEXT    NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'CLOSED')),
    opened_at       TEXT    NOT NULL DEFAULT (datetime('now')),
    closed_at       TEXT
);

CREATE TABLE IF NOT EXISTS market_data (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    instrument_id INTEGER NOT NULL REFERENCES instruments(id),
    price_date    TEXT    NOT NULL,
    close_price   TEXT    NOT NULL,
    source        TEXT    NOT NULL,
    fetched_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (instrument_id, price_date, source)
);

CREATE TABLE IF NOT EXISTS valuations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id     INTEGER NOT NULL REFERENCES positions(id),
    run_id          TEXT    NOT NULL,               -- 같은 재평가 배치를 묶는 식별자
    valued_at       TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    mark_price      TEXT    NOT NULL,
    price_source    TEXT    NOT NULL,
    price_as_of     TEXT    NOT NULL,
    signed_exposure INTEGER NOT NULL,
    gross_pnl       INTEGER NOT NULL,
    total_costs     INTEGER NOT NULL,
    net_pnl         INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_valuations_position ON valuations (position_id, valued_at);

CREATE TRIGGER IF NOT EXISTS trg_valuations_no_update
BEFORE UPDATE ON valuations
BEGIN
    SELECT RAISE(ABORT, 'valuations는 감사추적 테이블이라 수정할 수 없습니다.');
END;

CREATE TRIGGER IF NOT EXISTS trg_valuations_no_delete
BEFORE DELETE ON valuations
BEGIN
    SELECT RAISE(ABORT, 'valuations는 감사추적 테이블이라 삭제할 수 없습니다.');
END;

-- 포지션별 최신 평가 1건
CREATE VIEW IF NOT EXISTS v_latest_valuation AS
SELECT *
FROM (
    SELECT v.*,
           ROW_NUMBER() OVER (PARTITION BY v.position_id
                              ORDER BY v.valued_at DESC, v.id DESC) AS rn
    FROM valuations v
)
WHERE rn = 1;

-- 상품군별 북 집계 (OPEN 포지션의 최신 평가 기준)
CREATE VIEW IF NOT EXISTS v_book_by_asset_class AS
SELECT i.asset_class,
       COUNT(*)                      AS position_count,
       SUM(ABS(lv.signed_exposure))  AS gross_exposure,
       SUM(lv.signed_exposure)       AS net_exposure,
       SUM(lv.gross_pnl)             AS gross_pnl,
       SUM(lv.total_costs)           AS total_costs,
       SUM(lv.net_pnl)               AS net_pnl
FROM v_latest_valuation lv
JOIN positions   p ON p.id = lv.position_id AND p.status = 'OPEN'
JOIN instruments i ON i.id = p.instrument_id
GROUP BY i.asset_class;
