-- 자기매매 포지션 평가 엔진 스키마 (SQLite 3.25+, 윈도 함수 사용)
-- 설계 원칙
--   * 가격·비율은 TEXT(Decimal 문자열)로 저장해 부동소수점 오차를 피한다.
--   * 금액은 원 단위 정수(INTEGER)로 저장해 SUM 집계가 정확하도록 한다.
--   * trades·valuations·daily_snapshots는 감사추적 테이블이다. INSERT만 허용한다.
--   * 포지션은 직접 입력받는 대상이 아니라 체결(trades)을 합쳐 만든 현재 상태다.
--     체결이 들어올 때마다 증분 갱신하며, 전체 재계산은 하지 않는다.

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

-- 체결 한 건이 한 행이다. 수정·삭제할 수 없다.
-- closed_quantity 이후 컬럼은 "이 체결이 만든 결과"를 그때 값 그대로 박아 둔 것이다.
-- 종목 상세 화면의 평균단가 변화 과정을 재계산 없이 그대로 읽기 위한 것이며,
-- 나중에 엔진이 바뀌어도 과거 체결이 남긴 숫자는 변하지 않는다.
CREATE TABLE IF NOT EXISTS trades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    instrument_id   INTEGER NOT NULL REFERENCES instruments(id),
    side            TEXT    NOT NULL CHECK (side IN ('BUY', 'SELL')),
    quantity        INTEGER NOT NULL CHECK (quantity > 0),   -- 항상 양수. 방향은 side가 정한다
    price           TEXT    NOT NULL,
    commission_rate TEXT    NOT NULL DEFAULT '0',
    closed_quantity INTEGER NOT NULL DEFAULT 0,   -- 이 체결 중 청산에 쓰인 수량
    realized_pnl    INTEGER NOT NULL DEFAULT 0,   -- 이 체결이 확정한 실현손익 (비용 차감 후)
    commission      INTEGER NOT NULL DEFAULT 0,   -- 이 체결의 수수료 (원 미만 절사)
    transaction_tax INTEGER NOT NULL DEFAULT 0,   -- 이 체결의 거래세 (매도만, 주식만)
    avg_price_after TEXT    NOT NULL DEFAULT '0', -- 이 체결 직후 평균단가
    qty_after       INTEGER NOT NULL DEFAULT 0,   -- 이 체결 직후 순수량 (매수 +, 매도 −)
    traded_at       TEXT    NOT NULL DEFAULT (datetime('now')),
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS ix_trades_instrument ON trades (instrument_id, traded_at, id);

CREATE TRIGGER IF NOT EXISTS trg_trades_no_update
BEFORE UPDATE ON trades
BEGIN
    SELECT RAISE(ABORT, 'trades는 감사추적 테이블이라 수정할 수 없습니다.');
END;

CREATE TRIGGER IF NOT EXISTS trg_trades_no_delete
BEFORE DELETE ON trades
BEGIN
    SELECT RAISE(ABORT, 'trades는 감사추적 테이블이라 삭제할 수 없습니다.');
END;

-- 체결을 합쳐 만든 현재 상태. 종목당 한 행이다.
-- 전량 청산 후 같은 종목을 다시 사면 이 행이 다시 OPEN이 되고 realized_pnl은 계속 누적된다.
-- 라운드별로 나눠 보려면 trades를 읽는다.
CREATE TABLE IF NOT EXISTS positions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    instrument_id   INTEGER NOT NULL UNIQUE REFERENCES instruments(id),
    net_quantity    INTEGER NOT NULL DEFAULT 0,    -- 매수 +, 매도 −. 0이면 CLOSED
    avg_price       TEXT    NOT NULL DEFAULT '0',  -- 이동평균법, 소수 4자리
    realized_pnl    INTEGER NOT NULL DEFAULT 0,    -- 원 단위 누적 (비용 차감 후)
    entry_cost      INTEGER NOT NULL DEFAULT 0,    -- 보유 수량에 대해 실제로 낸 진입 수수료 누적
    commission_rate TEXT    NOT NULL DEFAULT '0',  -- 평가 시 청산 비용 추정에 쓰는 직전 체결 수수료율
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

-- 일별 스냅샷. 덮어쓰지 않는다.
-- 같은 날 다시 찍으려면 정정본(revision +1)을 새 행으로 추가한다. 이전 행은 그대로 남는다.
-- snapshot_date는 Asia/Seoul 기준으로 파이썬에서 계산해 넘긴다.
-- SQLite의 datetime('now')는 UTC라서, 한국 저녁에 찍으면 전날로 기록되기 때문이다.
CREATE TABLE IF NOT EXISTS daily_snapshots (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date           TEXT    NOT NULL,          -- YYYY-MM-DD (Asia/Seoul)
    revision                INTEGER NOT NULL DEFAULT 1,
    instrument_id           INTEGER NOT NULL REFERENCES instruments(id),
    mark_price              TEXT    NOT NULL,
    price_source            TEXT    NOT NULL,
    net_quantity            INTEGER NOT NULL,
    avg_price               TEXT    NOT NULL,
    unrealized_pnl          INTEGER NOT NULL,
    realized_pnl_cumulative INTEGER NOT NULL,
    signed_exposure         INTEGER NOT NULL,
    created_at              TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    UNIQUE (snapshot_date, instrument_id, revision)
);

CREATE TRIGGER IF NOT EXISTS trg_snapshots_no_update
BEFORE UPDATE ON daily_snapshots
BEGIN
    SELECT RAISE(ABORT, 'daily_snapshots는 감사추적 테이블이라 수정할 수 없습니다. 정정본을 새로 추가하세요.');
END;

CREATE TRIGGER IF NOT EXISTS trg_snapshots_no_delete
BEFORE DELETE ON daily_snapshots
BEGIN
    SELECT RAISE(ABORT, 'daily_snapshots는 감사추적 테이블이라 삭제할 수 없습니다.');
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

-- 날짜·종목별 최신 정정본 스냅샷 1건
CREATE VIEW IF NOT EXISTS v_latest_snapshot AS
SELECT *
FROM (
    SELECT s.*,
           ROW_NUMBER() OVER (PARTITION BY s.snapshot_date, s.instrument_id
                              ORDER BY s.revision DESC, s.id DESC) AS rn
    FROM daily_snapshots s
)
WHERE rn = 1;

-- 일자별 북 집계 (최신 정정본 기준)
CREATE VIEW IF NOT EXISTS v_book_history AS
SELECT snapshot_date,
       COUNT(*)                        AS position_count,
       SUM(unrealized_pnl)             AS unrealized_pnl,
       SUM(realized_pnl_cumulative)    AS realized_pnl_cumulative,
       SUM(ABS(signed_exposure))       AS gross_exposure,
       SUM(signed_exposure)            AS net_exposure
FROM v_latest_snapshot
GROUP BY snapshot_date;
