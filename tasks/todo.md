# Story 2.4 — [prereq] Repository 增量 upsert、MAX(date) 與 adjusted/raw invariant

## Plan
- [x] 建立 `src/tsic/storage/repository.py`
  - `DataPollutionError`：同 symbol 混存 adjusted/raw 時拋出（AC-3）
  - `PriceRepository(conn)`：包裝既有 `sqlite3.Connection`
  - `upsert_prices(prices) -> int`：`INSERT OR IGNORE`，首寫優先、回傳實際新增筆數（AC-1）
  - `latest_date(symbol) -> str | None`：`MAX(date)`，無資料回 None（AC-2）
  - `query_prices(symbol, start, end) -> list[DailyPrice]`：依 date 升冪排序（AC-4）
- [x] 新增 `tests/test_repository.py`：覆蓋 AC-1~AC-4 + 邊界
- [x] 驗證：`uv run pytest`、`uv run ruff check`

## Review
- 全部步驟完成；51 個測試通過（37 原有 + 14 新增）、ruff 乾淨。
- 契約：`PriceRepository(conn)` 接受「已 migrate」的連線、不自行管理 lifecycle，沿用 migrations/database 的 conn-injection 慣例。
- AC-1：`INSERT OR IGNORE` 首寫優先，回傳 `cursor.rowcount` 即實際新增筆數；重寫同 key 不覆寫。
- AC-2：`SELECT MAX(date) ... WHERE symbol=?`，無資料回 `None`，不會跨 symbol 洩漏。
- AC-3：寫入前檢查 invariant（批次內 + DB 既有），混存即整批拒絕並拋 `DataPollutionError`，未寫入任何列。
- AC-4：`date BETWEEN ? AND ?`（雙邊含括）+ `ORDER BY date ASC`，由 `(symbol, date)` index 服務。
- 假設：模組 `storage/repository.py`（依 Story Reference）；方法命名 `upsert_prices`/`latest_date`/`query_prices`（依 AC 文字）；invariant 違反採整批 reject（非部分寫入）以維持價格基準一致。
