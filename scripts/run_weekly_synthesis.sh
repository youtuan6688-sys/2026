#!/bin/zsh
# Weekly knowledge synthesis — runs every Sunday 11pm PST
[ -f ~/.zshrc ] && source ~/.zshrc

set -o pipefail

PROJECT_DIR="/Users/tuanyou/Happycode2026"
VENV="$PROJECT_DIR/.venv/bin/python"
LOG_FILE="$PROJECT_DIR/logs/weekly-synthesis.log"

mkdir -p "$PROJECT_DIR/logs"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"; }

# Load .env
ENV_FILE="$PROJECT_DIR/.env"
if [ -f "$ENV_FILE" ]; then
    set -a
    source "$ENV_FILE"
    set +a
fi

export HOME="${HOME:-/Users/tuanyou}"
export PATH="/Users/tuanyou/.local/bin:$PATH"
export USER="${USER:-tuanyou}"
unset CLAUDECODE 2>/dev/null || true

log "Weekly synthesis started"

$VENV "$PROJECT_DIR/scripts/weekly_synthesis.py" >> "$LOG_FILE" 2>&1

if [ $? -eq 0 ]; then
    log "Weekly synthesis completed"
else
    log "Weekly synthesis FAILED"
fi
