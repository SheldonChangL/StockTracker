# Story 2.2 — schema 建表、meta 與版本化 migration

## Plan
- [ ] 建立 `src/tsic/storage/schema.sql`：v1 DDL
  - `daily_prices`：欄位依 `models.DailyPrice`，PK `(symbol, date)`，index `(symbol, date DESC)`，`adjusted INTEGER NOT NULL DEFAULT 0`（AC-1 / AC-4）
  - `chip_flows`、`fundamentals`：欄位依 models，PK `(symbol, date)`
  - `watchlist`：最小 schema `symbol TEXT PRIMARY KEY`（models 無 Watchlist、§3 未在 repo）
  - `meta`：`key TEXT PK, value TEXT`
- [ ] 建立 `src/tsic/storage/migrations.py`
  - `SCHEMA_VERSION = 1`、`migrate(conn)` 版本化、冪等（AC-3）
  - 套用 v1：執行 schema.sql + seed `adjust_policy='raw'`，寫入 `schema_version='1'`（AC-2）
- [ ] 新增 `tests/test_migrations.py`：覆蓋 AC-1~AC-4
- [ ] 驗證：`uv run pytest`、`uv run ruff check`

## Review
- 全部步驟完成；29 個測試通過（21 原有 + 8 新增）、ruff 乾淨。
- `migrate(conn)` 版本化、冪等：以 `meta.schema_version` gate，已是最新則 no-op；重跑不重建表、不報錯，既有資料列保留。
- `schema.sql` 欄位對齊 `tsic.models`；`daily_prices` PK `(symbol, date)`、index `(symbol, date DESC)`、`adjusted INTEGER NOT NULL DEFAULT 0`。
- v1 seed `adjust_policy='raw'` 用 `INSERT OR IGNORE`，重跑不覆蓋 operator 變更。
- 假設：`watchlist` 採最小 schema（`symbol` PK），因 models 無 `Watchlist`、§3 未在 repo。
