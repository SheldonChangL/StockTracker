# Story 2.5 — `tsic db clean <代號>` 安全刪除某檔資料

## Plan
- [ ] 新增 `src/tsic/storage/maintenance.py`
  - `DATA_TABLES`：`("daily_prices", "chip_flows", "fundamentals")`
  - `count_symbol_records(conn, symbol) -> int`：三表合計筆數
  - `delete_symbol(conn, symbol) -> int`：刪除三表該 symbol 所有列、commit、回傳刪除總數
- [ ] 新增 `src/tsic/commandline/db_cmd.py`
  - `db_app` Typer 子群組（`db` 命令群）
  - `clean(symbol, --db-path)`：connect+migrate → count → 確認提示 → 刪除/取消
  - 提示文字（AC-3）：`將刪除 {代號} 共 {N} 筆記錄，確認？(y/N)`，預設 N
  - 輸入 `n`/Enter → 輸出取消訊息、不刪除、exit 0（AC-1）
  - 輸入 `y` → 刪除三表、輸出結果、exit 0（AC-2）
- [ ] 修改 `src/tsic/commandline/app.py`：移除 `db` stub，改用 `app.add_typer(db_app, name="db")`
- [ ] 新增 `tests/test_db_cmd.py`：AC-1~AC-3 + 邊界（0 筆、僅刪指定 symbol、提示預設 N）
- [ ] 新增 `tests/test_maintenance.py`：count/delete 行為
- [ ] 驗證：`uv run pytest`、`uv run ruff check`

## Review
- 全部步驟完成；62 個測試通過（51 原有 + 11 新增）、ruff 乾淨；CLI 端對端三情境（n / Enter / y）皆驗證 exit 0。
- AC-1：輸入 `n` 或直接 Enter → `typer.confirm(default=False)` 回 False，輸出「已取消…」、不刪除、exit 0。
- AC-2：輸入 `y` → `delete_symbol` 刪除 `daily_prices`/`chip_flows`/`fundamentals` 三表該 symbol 所有列（單一 commit）、exit 0。
- AC-3：提示文字為 `將刪除 {代號} 共 {N} 筆記錄，確認？(y/N)`（click 預設加 `: ` 後綴），`show_default=False` 避免重複 `[y/N]`，預設 N。
- 架構：`db` 由 stub `@app.command` 改為 `app.add_typer(db_app)` 子群組；刪除/計數放在 `storage/maintenance.py`，沿用 conn-injection 慣例（不自行管 lifecycle）。
- 假設與決策：
  - 「資料」範圍 = 三張 per-symbol 資料表，`meta`/`watchlist` 不在刪除範圍。
  - 新增 `--db-path` 選項供測試注入暫存 DB；未指定時用 `settings.default_db_path()`。
  - `clean` 內呼叫 `migrations.migrate` 確保表存在（idempotent），N=0 仍照常提示。
