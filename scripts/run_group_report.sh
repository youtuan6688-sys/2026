#!/bin/bash
# Creative daily group report: sonnet highlights → DeepSeek story → Gemini images → Feishu
# Replaces daily-briefing/group_chat_summary.py with richer content
# Cron: run at 22:00 Beijing (06:00 PST) — before daily_evolution archives the buffer

cd /Users/tuanyou/Happycode2026
source .venv/bin/activate

echo "$(date) Starting creative group report..."
python -m src.daily_group_report 2>&1 | tee -a logs/group_report.log
echo "$(date) Group report complete."
