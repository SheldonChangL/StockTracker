# StockTracker (`tsic`)

> **t**aiwan **s**tock **i**nteractive **c**onsole — 在終端機抓取、快取、查詢與分析台股行情的工具。

`tsic` 把多個行情來源整合成一條管線：抓取每日 OHLCV 行情 → 存入本機 SQLite 快取 → 以表格／JSON／CSV 查詢 → 交給本機 AI CLI 做分析，並提供互動式 TUI 與排程自動更新。所有資料都存在本機（預設 `~/.tsic/data.db`）。

## 功能

| 指令 | 說明 |
|------|------|
| `tsic fetch <symbols…>` | 並行抓取股票行情並寫入本機快取（支援 `--file` 清單與 `--all`）。 |
| `tsic query <symbol>` | 從快取讀取指定日期區間，輸出 `table` / `json` / `csv`。 |
| `tsic analyze <symbol>` | 把快取資料整理成 Markdown，餵給偵測到的 AI CLI 做分析。 |
| `tsic watch add/remove/list` | 管理追蹤清單（watchlist）。 |
| `tsic db status / clean` | 檢視本機快取狀態、刪除指定股票的資料。 |
| `tsic schedule enable/disable` | 在 Linux（cron）或 macOS（launchd）上開關自動更新。 |
| `tsic tui` | 啟動互動式終端機介面。 |

行情來源包含 TWSE、Yahoo Finance（yfinance）、MOPS 與 Fugle。Fugle 需設定環境變數 `TSIC_FUGLE_API_KEY`（金鑰只從環境變數讀取，不會寫進任何設定檔）。

## 需求

- Python >= 3.11
- [uv](https://docs.astral.sh/uv/)（套件與虛擬環境管理）

## 快速開始

```bash
# 用啟動腳本一鍵安裝依賴並進入 TUI
./run.sh

# 或傳入任意子指令給腳本
./run.sh fetch 2330 2317
./run.sh query 2330 --format table
```

`run.sh` 會自動以 `uv sync` 安裝依賴，沒有參數時啟動 TUI，有參數時直接執行對應的 `tsic` 子指令。

## 手動使用

```bash
uv sync                      # 安裝依賴
uv run tsic --help           # 查看所有指令
uv run tsic fetch 2330       # 抓取台積電行情
uv run tsic query 2330       # 查詢快取
uv run tsic tui              # 啟動 TUI
```

預設資料庫路徑為 `~/.tsic/data.db`，多數指令可用 `--db-path` 覆寫。

## 開發

```bash
uv run pytest                # 跑測試
uv run ruff check            # 靜態檢查
uv run ruff format           # 格式化
```

## 專案結構

```
src/tsic/
├── commandline/   # Typer 子指令（fetch / query / analyze / db / watch / schedule）
├── sources/       # 行情來源（TWSE / yfinance / MOPS / Fugle）
├── fetching/      # 並行抓取的 orchestrator 與驗證
├── storage/       # SQLite schema、migration、repository、summary
├── ai/            # AI CLI 偵測、Markdown 格式化、管線
├── scheduling/    # cron（Linux）與 launchd（macOS）排程
├── tui/           # Textual 互動介面
└── ratelimit/     # token bucket 速率限制
```
