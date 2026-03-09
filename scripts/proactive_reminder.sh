#!/bin/bash
# Proactive reminder: checks pending tasks and unresolved errors, notifies via Feishu
set -euo pipefail

PROJECT_DIR="/Users/tuanyou/Happycode2026"
VENV_PYTHON="$PROJECT_DIR/.venv/bin/python"

cd "$PROJECT_DIR"
exec "$VENV_PYTHON" "$PROJECT_DIR/scripts/proactive_reminder.py"
