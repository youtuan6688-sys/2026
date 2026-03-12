#!/bin/bash
# Daily video trending crawl + auto-analysis
# launchd: com.happycode.video-crawl (10:00 PST daily)

PROJECT_DIR="/Users/tuanyou/Happycode2026"
cd "$PROJECT_DIR" || exit 1

source .venv/bin/activate

# Load env (disable set -e to avoid exit on .env quirks)
set -a
source .env 2>/dev/null || true
set +a

echo "$(date) — Starting daily video crawl"

python scripts/run_daily_video_crawl.py

echo "$(date) — Daily video crawl finished"
