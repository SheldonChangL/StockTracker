# Story 2.1 — SQLite 連線初始化（自動建目錄、WAL、權限 600）

## Plan
- [ ] 建立 `src/tsic/storage/__init__.py`
- [ ] 建立 `src/tsic/storage/database.py`
  - `connect(db_path=None)`：注入路徑，預設 `settings.default_db_path()`，支援 `:memory:`
  - 自動建立 `~/.tsic/`（parents、exist_ok）與 db 檔（AC-1）
  - `PRAGMA journal_mode=WAL`、`foreign_keys=ON`、`busy_timeout`（AC-2 / ADR-1）
  - POSIX：新建檔靜默設為 `0o600`（AC-3）；既有檔權限錯誤則修正回 `0o600` 並記 warning（AC-4）
- [ ] 新增 `tests/test_database.py`：覆蓋 AC-1~AC-5
- [ ] 驗證：`uv run pytest`、`uv run ruff check`

## Review
- 全部步驟完成；21 個測試通過、ruff 乾淨。
- `connect()` 支援注入路徑與 `:memory:`，預設取 `settings.default_db_path()`。
- 新建檔靜默設 `0o600`；既有檔權限錯誤才修正並記 warning（避免首次建立誤報）。
- WAL 僅對 file db 啟用；`:memory:` 不建目錄/不處理權限。
