#!/bin/bash
# Daily evolution: analyze the day's conversations with opus
# Triggered by cron at 7:00 PST (23:00 Beijing)

cd /Users/tuanyou/Happycode2026
source .venv/bin/activate

echo "$(date) Starting daily evolution..."
python -m src.daily_evolution 2>&1 | tee -a logs/daily_evolution.log
echo "$(date) Daily evolution complete."
