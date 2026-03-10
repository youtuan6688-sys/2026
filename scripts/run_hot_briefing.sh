#!/bin/bash
# Hot briefing: extract yesterday's group topics → search related news → send to groups
# Cron: 7:00 Beijing (15:00 PST)

cd /Users/tuanyou/Happycode2026
source .venv/bin/activate

echo "$(date) Starting hot briefing..."
python -m src.daily_hot_briefing 2>&1 | tee -a logs/hot_briefing.log
echo "$(date) Hot briefing complete."
