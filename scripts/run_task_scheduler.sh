#!/bin/bash
# Run the scheduled task executor
cd /Users/tuanyou/Happycode2026
source .venv/bin/activate
exec python -m src.task_scheduler
