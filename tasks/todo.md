# Story 3.7 — FetchOrchestrator（ThreadPoolExecutor + fallback + continue-on-failure）

## Plan
- [ ] 新增 `src/tsic/fetching/orchestrator.py`
  - `FetchSummary` dataclass：彙整每檔 `FetchResult`，提供 `succeeded/skipped/failed`
    分類與計數、`render()` 產出「成功 N / 跳過 N / 失敗 N（附原因）」（AC-3）
  - `FetchOrchestrator(sources, repository, *, concurrency=3, timeout=None, validator)`
    - sources 依 `priority` 升冪排序；`available=False` 的來源跳過（AC-1）
    - `fetch_prices(symbols, start, end) -> FetchSummary`：以
      `ThreadPoolExecutor(max_workers=concurrency)` 並發；逐 future
      `result(timeout=...)` 做 future-level timeout 保護（不使用 signal）（AC-4）
    - `_fetch_symbol`：
      - resume start = `MAX(date)+1`（無資料則用傳入 start）（AC-5）
      - resume start > end → 跳過（已最新無新資料）（AC-3 skipped）
      - 依序試來源，raise 則記原因換下一來源（fallback）（AC-1）
      - 來源成功 → validate → upsert；寫入 >0=成功、=0=跳過
      - 全部來源失敗 → 失敗並附原因（continue-on-failure）（AC-2）
    - repo 存取以 `threading.Lock` 序列化（NFR-9；ADR-1 write-serialization）
- [ ] 更新 `src/tsic/fetching/__init__.py`：匯出 `FetchOrchestrator`、`FetchSummary`
- [ ] 新增 `tests/test_orchestrator.py`：AC-1~AC-5 + 邊界
- [ ] 驗證：`uv run pytest`、`uv run ruff check`

## Review
- 完成全部步驟；134 測試通過（124 原有 + 10 新增）、ruff 乾淨。
- AC-1：sources 依 `priority` 升冪試用，raise 即記錄原因換下一來源並成功寫入；
  `available=False` 來源直接跳過不算失敗。
- AC-2：單檔所有來源失敗→`FetchResult(success=False)` 附各來源原因，批次續跑其他檔。
- AC-3：`FetchSummary` 以每檔 `FetchResult` 衍生 succeeded/skipped/failed 三類，
  `render()` 產出「成功 N / 跳過 N / 失敗 N」+ 失敗原因；分類可斷言。
- AC-4：`ThreadPoolExecutor(max_workers=concurrency)`；逐 future `result(timeout=)`
  做 future-level timeout（無 signal），超時記為失敗、`shutdown(wait=False,
  cancel_futures=True)` 不被卡住的 worker 拖住整批。
- AC-5：resume start = `MAX(date)+1`（無資料用傳入 start）；start>end→skipped；
  靠 repo first-write-wins upsert 確保續傳無重複。
- 設計決策：
  - 沿用既有 `FetchResult` model（success/rows 衍生三態），不新增 model 欄位。
  - repo 存取以 `threading.Lock` 序列化（ADR-1 write-serialization、NFR-9）；
    實務上單一 sqlite 連線跨執行緒需 `check_same_thread=False`（docstring 已註明）。
  - `timeout` 預設 `None`（不限時）為可選保護，避免硬塞魔術數字。
- 限制：未接 CLI `fetch` 指令（本故事為 prereq，wiring 留待後續故事）；
  僅實作 `fetch_prices`，chips/fundamentals 編排不在本故事範圍。

## Story 3.8 — tsic fetch（已完成 2026-06-14）
- [x] 新增 `commandline/fetch_cmd.py`：解析代號（positional / --file / --all）、開 db、驅動 FetchOrchestrator、印摘要、退出碼
- [x] `app.py` 以真實命令取代 fetch stub
- [x] `database.connect` 加 `check_same_thread` 參數（orchestrator 跨執行緒共用單一連線必需）
- [x] `tests/test_fetch_cmd.py` 覆蓋 AC-1..AC-5 + 邊界
- [x] 更新 test_cli 的 quiet stub 測試改用 query
- 驗證：142 passed、ruff 全過、`python -m tsic fetch --help` 正常

### 設計決策
- `--all` 的「追蹤清單」採用與 `db status` 一致的定義（summary.symbol_latest_dates，即 db 內已有資料的代號），因 watchlist 表目前無任何寫入路徑。
- 退出碼：全部失敗才回 1；部分失敗回 0。
- `--start` 預設今日往前 365 天、`--end` 預設今日；新代號回補用，既有代號由 orchestrator 從 MAX(date)+1 續抓。
