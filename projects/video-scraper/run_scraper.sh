#!/bin/bash
# 视频抓取调度器入口 — 可由 launchd/cron 调用
# Usage: ./run_scraper.sh [once|loop [interval_sec]]

set -o pipefail

PROJECT_DIR="/Users/tuanyou/Happycode2026"
SCRAPER_DIR="$PROJECT_DIR/projects/video-scraper"
VENV="$PROJECT_DIR/.venv/bin/python"
LOG_DIR="$SCRAPER_DIR/logs"
DATE=$(date +"%Y-%m-%d")

mkdir -p "$LOG_DIR"

# 加载环境变量
[ -f "$PROJECT_DIR/.env" ] && { set -a; source "$PROJECT_DIR/.env"; set +a; }

export HOME="${HOME:-/Users/tuanyou}"
export PATH="/Users/tuanyou/.local/bin:/opt/homebrew/bin:$PATH"

# 全局超时 2 小时（防僵尸）
SCRIPT_TIMEOUT=7200
( sleep $SCRIPT_TIMEOUT && kill -TERM $$ 2>/dev/null ) &
WATCHDOG_PID=$!
trap "kill $WATCHDOG_PID 2>/dev/null" EXIT

cd "$SCRAPER_DIR"
$VENV orchestrator.py "${1:-once}" "${2:-3600}" >> "$LOG_DIR/$DATE.log" 2>&1
