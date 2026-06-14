#!/usr/bin/env bash
#
# run.sh — 一鍵啟動 tsic。
#
# 無參數時：安裝依賴後啟動互動式 TUI。
# 有參數時：把所有參數原樣傳給 tsic（例如 ./run.sh fetch 2330）。
#
set -euo pipefail

cd "$(dirname "$0")"

if ! command -v uv >/dev/null 2>&1; then
  echo "找不到 uv，請先安裝：https://docs.astral.sh/uv/" >&2
  exit 1
fi

# 同步依賴（已是最新時很快）。
uv sync

if [ "$#" -eq 0 ]; then
  exec uv run tsic tui
else
  exec uv run tsic "$@"
fi
