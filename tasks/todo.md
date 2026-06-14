# Story 1.4 — Typer 根命令樹可在乾淨環境啟動

## Plan
- [ ] 建立 `src/tsic/commandline/__init__.py`
- [ ] 建立 `src/tsic/commandline/app.py`：Typer root app
  - root callback 帶全域 `--quiet` / `--verbose`，`no_args_is_help=True`
  - 註冊子命令 stub：fetch, query, analyze, db, watch, schedule, tui
  - 提供 `get_app()` 與 `main()` 入口
- [ ] 更新 `src/tsic/__main__.py`：改為呼叫 commandline app
- [ ] 新增 `tests/test_cli.py`：用 Typer CliRunner 驗證 AC-1~AC-4
- [ ] 驗證：`uv run python -m tsic --help` / `fetch --help` / 無子命令 / `uv run pytest` / `uv run ruff check`

## Review
- 全部步驟完成，14 個測試通過、ruff 乾淨、`uv sync --frozen` exit 0。
- AC-1~AC-4 皆驗證通過；AC-3 無子命令依 Typer `no_args_is_help` 慣例回傳 exit 2（顯示說明、無 traceback）。
- 子命令皆為 stub，待各功能 story 補實作。
