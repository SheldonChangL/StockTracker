-- tsic storage schema, version 1 (Story 2.2).
--
-- Column names and types mirror the shared dataclasses in ``tsic.models`` so
-- that the storage layer never redefines its own schema. All statements use
-- ``IF NOT EXISTS`` so the script is safe to run against an already-migrated
-- database (idempotency is also gated by ``migrations.SCHEMA_VERSION``).

-- Daily OHLCV records. ``adjusted`` is a flag (0 = raw, 1 = adjusted), not a
-- price value. PRIMARY KEY (symbol, date) per §3 Data Model.
CREATE TABLE IF NOT EXISTS daily_prices (
    symbol   TEXT    NOT NULL,
    date     TEXT    NOT NULL,
    open     REAL    NOT NULL,
    high     REAL    NOT NULL,
    low      REAL    NOT NULL,
    close    REAL    NOT NULL,
    volume   INTEGER NOT NULL,
    source   TEXT    NOT NULL,
    adjusted INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (symbol, date)
);

-- Read pattern is "latest rows for a symbol first", hence date DESC.
CREATE INDEX IF NOT EXISTS idx_daily_prices_symbol_date
    ON daily_prices (symbol, date DESC);

-- Institutional net-flow (籌碼面) per symbol per trading day.
CREATE TABLE IF NOT EXISTS chip_flows (
    symbol      TEXT    NOT NULL,
    date        TEXT    NOT NULL,
    foreign_net INTEGER NOT NULL,
    trust_net   INTEGER NOT NULL,
    dealer_net  INTEGER NOT NULL,
    source      TEXT    NOT NULL,
    PRIMARY KEY (symbol, date)
);

-- Per-symbol fundamental (基本面) snapshot for a given date.
CREATE TABLE IF NOT EXISTS fundamentals (
    symbol         TEXT NOT NULL,
    date           TEXT NOT NULL,
    eps            REAL NOT NULL,
    pe             REAL NOT NULL,
    pb             REAL NOT NULL,
    dividend_yield REAL NOT NULL,
    source         TEXT NOT NULL,
    PRIMARY KEY (symbol, date)
);

-- Symbols the user is tracking. Minimal schema: §3 defines no extra columns
-- and there is no Watchlist dataclass yet, so only the symbol key is stored.
CREATE TABLE IF NOT EXISTS watchlist (
    symbol TEXT PRIMARY KEY NOT NULL
);

-- Key/value store for schema versioning and operational policy flags.
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY NOT NULL,
    value TEXT NOT NULL
);
