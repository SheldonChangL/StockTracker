# Story 8.2 — 個股詳細頁（30 日 OHLCV + 籌碼/基本面摘要，FR-28）

## Plan
- [x] 新增 `src/tsic/tui/detail_view.py`（prereq，沿用 Story 8.1 純展示 + Textual App 風格）
  - 純展示函式：`ohlcv_rows`（取最近 30 交易日、最新在上）、`chip_summary`（無資料回傳「無資料」）、`fundamental_summary`（缺漏欄位以「—」呈現）
  - `StockDetail` 資料物件（注入式）、`DetailApp` 渲染：`id="detail-ohlcv"` 表格 + 籌碼/基本面摘要面板
- [x] 新增 `tests/test_detail_view.py`：AC-1~AC-4（含 Pilot 查詢 `#detail-ohlcv` 斷言列數 ≤ 30）
- [x] 驗證：`uv run pytest`、`uv run ruff check`

## Review
- 248 測試通過（237 原有 + 11 新增）、ruff 乾淨。
- AC-1：`DetailApp` 掛載 `DataTable(id="detail-ohlcv")`，欄位為 `OHLCV_COLUMNS`（日期+OHLCV）。
- AC-2：`chip_summary` 取最新一筆籌碼記錄組摘要；無資料回傳「無資料」而非報錯，面板正常渲染。
- AC-3：`fundamental_summary` 依固定欄位輸出，None/缺欄以「—」呈現；部分資料顯示可用值。
- AC-4：以 `run_test()` 的 Pilot 查 `#detail-ohlcv`，給 45 筆仍 `row_count == 30`（≤ 30）。

### 設計決策
- 與 Story 8.1 一致：展示規則為純函式（可單元測試），`DetailApp` 只渲染注入的 `StockDetail`，
  不含儲存邏輯、不自訂色彩/CSS（沿用 Textual 預設主題）。
- OHLCV 以最新日在上（descending）便於檢視近況；輸入沿用 `query_prices` 升冪、取尾 30 筆反轉。
- 籌碼面摘要採「最新一筆」淨流向；基本面欄位用 `(label, attr)` 對照表，None 一律映為「—」。

### 限制 / Tester 重點
- 本故事為 prereq：尚未串接 `TsicApp` 的選股導航與真實 repository 取數（留待後續 wiring 故事）。
  儲存層目前無 chip/fundamental 的讀取 repository 方法；資料以 `StockDetail` 注入。
- `Fundamental.pb` / `dividend_yield` 預設為 0.0（非 None），故不會被視為缺漏；
  缺漏判定僅針對 None（period/eps/pe_ratio_qtr_end/revenue/gross_margin 等 Optional 欄位）。
