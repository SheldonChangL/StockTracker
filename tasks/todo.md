# Story 7.3 — tsic schedule enable/disable（CLI 入口，注入平台與設定目錄）

## Plan
- [ ] 新增 `src/tsic/commandline/schedule_cmd.py`
  - `schedule_app` Typer 子命令群：`enable` / `disable`
  - 平台分流：`Linux` → `tsic.scheduling.cron`；`Darwin` → `tsic.scheduling.launchd`
  - 注入點（vertical 真實入口，但測試可注入）：
    - `--system`（hidden）覆寫 `platform.system()`（AC-1 注入平台判斷）
    - `--launchd-dir`（hidden）覆寫 `~/Library/LaunchAgents`（AC-2/AC-3）
    - `--crontab-file`（hidden）以檔案讀寫取代 `crontab -l/-`（Linux 測試隔離）
  - `--cron` 自訂排程，套用於 cron 路徑（AC-4）
  - 預設 crontab IO：`crontab -l` 讀、`crontab -` 寫（production）
  - enable/disable 皆 exit 0；不支援平台 → exit 1 + stderr
- [ ] `app.py`：以 `add_typer(schedule_app, name="schedule")` 取代 schedule stub
- [ ] `tests/test_cli.py`：quiet stub 測試改用仍是 stub 的 `tui`
- [ ] 新增 `tests/test_schedule_cmd.py`：AC-1~AC-4 + 不支援平台
- [ ] 驗證：`uv run pytest`、`uv run ruff check`

## Review
- 完成全部步驟；228 測試通過（216 原有 + 12 新增）、ruff 乾淨。
- AC-1：`schedule enable --system Linux` 以 `cron.enable` 寫入預設排程（`0 18 * * 1-5`）+
  marker block，exit 0，輸出「已啟用…」；既有 crontab 條目保留。
- AC-2：`--system Darwin` 改走 `launchd.enable(dir)`，於注入目錄寫出 `com.tsic.fetch.plist`。
- AC-3：`disable` 對應移除 cron block / plist，皆 exit 0。
- AC-4：`--cron "0 19 * * 1-5"` 沿用 `cron` 純函式 verbatim 套用。
- 不支援平台 → exit 1 + stderr。

### 設計決策
- 平台與目標位置以 hidden option 注入（`--system`/`--launchd-dir`/`--crontab-file`），
  測試以 CliRunner 全程驅動真實 CLI 而不碰使用者 crontab 或 ~/Library/LaunchAgents；
  hidden 不污染 `--help`。
- cron 為純字串轉換，CLI 自負 I/O：預設 `crontab -l` 讀、`crontab -` 寫；
  使用者無 crontab（`crontab -l` 非零）視為空字串，首次啟用即可運作。
- `--cron` 僅套用於 cron 路徑；launchd 以 hour/minute/weekdays 表達，
  將 cron 字串轉成 launchd 排程超出本故事範圍（見限制）。

### 限制 / Tester 重點
- macOS 路徑目前不解析 `--cron`（沿用 launchd 預設 18:00 Mon-Fri）；若需 macOS 自訂時間
  需後續故事擴充 launchd 入口。
- production crontab IO 走 subprocess，未在 CI 實際安裝 cron job；Tester 可於真實 Linux
  以 `uv run python -m tsic schedule enable` 後 `crontab -l` 驗證、disable 後確認移除。
