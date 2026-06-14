# Story 2.3 — [prereq] 寫入前驗證器 validator

## Plan
- [x] 建立 `src/tsic/fetching/__init__.py`（新 fetching 套件）
- [x] 建立 `src/tsic/fetching/validator.py`
  - `validate_price(price) -> ValidationResult`：date 合法性、OHLCV ≥ 0、close > 0（AC-1~3）
  - `validate_prices(prices) -> BatchValidation`：回傳有效清單 + 每筆無效一條 warning（並 log）（AC-4）
- [x] 新增 `tests/test_validator.py`：覆蓋 AC-1~AC-4 + 邊界
- [x] 驗證：`uv run pytest`、`uv run ruff check`

## Review
- 全部步驟完成；37 個測試通過（29 原有 + 8 新增）、ruff 乾淨。
- 契約：`ValidationResult(valid, reasons)` 單筆（含 `reason` 合併字串）；`BatchValidation(valid, warnings)` 批次，`len(warnings)` == 無效筆數，可斷言。
- date 用 `datetime.date.fromisoformat` 判定真實日曆日，擋下 `2026-13-40`。
- OHLCV（open/high/low/close/volume）須 ≥ 0；close 另須 > 0（close=0 / 負值皆拒絕）。
- warning 同時回傳清單並走 `logging.warning`，對齊 storage 層觀測性慣例。
- 假設：採 `fetching/validator.py` 模組位置（依 Story Reference）；單筆 API 命名 `validate_price`（依 AC-1），批次補 `validate_prices`。
