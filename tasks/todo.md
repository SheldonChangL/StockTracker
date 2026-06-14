# Story 8.4 — 使用者啟動 `tsic tui` 並用鍵盤操作（FR-26/FR-29）

## Plan
- [ ] `src/tsic/tui/app.py`：加入 `f`/`a`/`q` 鍵綁定與動作
  - `Analyzer` Protocol（注入式分析接縫）
  - `action_fetch_selected`（f）：對游標選取的股票跑單股背景更新 worker
  - `action_analyze_selected`（a）：對選取股票以預設問題跑 AI 分析 worker（注入 analyzer）
  - `q` → 內建 `action_quit`
  - 重構共用 `_fetch(symbols)` worker body，保留 `action_update`（u）行為
- [ ] `src/tsic/tui/launcher.py`（prod wiring）
  - `StorageWatchlistSource`（WatchlistRepository + PriceRepository → WatchlistRow）
  - `CacheAnalyzer`（cache → to_markdown + 預設 build_prompt → pipe.run）
  - `build_app(conn, ...)` 與 `launch(db_path)`
- [ ] `src/tsic/commandline/app.py`：`tui` 由 stub 改為真實啟動；移除已無用的 `_stub`
- [ ] 測試
  - `tests/test_tui_keys.py`：AC-1（f→worker）、AC-2（a→analyzer 被呼叫、預設問題）、AC-3（q→結束）、AC-4（build_app headless run_test 不拋例外）
  - `tests/test_cli.py`：更新 tui 不再是 stub
- [ ] 驗證：`uv run pytest`、`uv run ruff check`

## Review
- 260 測試通過（原 248 + test_tui_keys.py 新增 7 + test_cli 調整），ruff 乾淨。
- AC-1：`f` → `action_fetch_selected` 取游標列代號，跑與 `u` 共用的 threaded fetch worker，但只更新選取股票（gated 測試斷言 worker 在途且僅 fetch `2330`）。
- AC-2：`a` → `action_analyze_selected` 在 worker 上跑注入的 `Analyzer`；提供 fake analyzer 斷言被呼叫，並以真實 `CacheAnalyzer`+fake runner 驗證走預設 `build_prompt` 問題的真實分析路徑。
- AC-3：`q` 綁定 Textual 內建 `action_quit`，press 後 `is_running` 為 False。
- AC-4：`build_app` 以 migrated 連線組裝（StorageWatchlistSource + orchestrator + analyzer），headless `run_test()` 不拋例外，watchlist 正確渲染。

### 設計決策
- 沿用 8.1/8.3 的「注入式接縫」風格：app 不含儲存/分析邏輯，僅依賴 `WatchlistSource`、`UpdateRunner`、新增的 `Analyzer` Protocol。
- 重構共用 `_fetch(symbols)`，`u`（全部）與 `f`（選取）共用同一 threaded worker 與進度回報；`u` 行為與既有 8.3 測試不變。
- production wiring 集中在 `tui/launcher.py`，`CacheAnalyzer` 直接重用 Story 5.x 的 to_markdown/build_prompt/pipe.run，`tui` CLI 改為真實啟動並移除已無用的 `_stub`。

### 限制 / Tester 重點
- `launch()` 與分析/抓取 worker 共用單一 `check_same_thread=False` 連線；寫入經 orchestrator 鎖序列化，但 `CacheAnalyzer`/watchlist 讀取與 orchestrator 寫入併發在極端情況下仍有 SQLite 競爭風險（V1 單人本機可接受）。
- `StorageWatchlistSource` 以整段歷史查詢計算 row_count/最新收盤，名稱欄無資料來源固定為「—」。
- AC-4 真實 `uv run python -m tsic tui` 需 TTY；CI 以 `run_test()` headless 驗證（符合 story 指定）。
