#!/bin/zsh
# InStreet 社区巡检 - 每日北京时间 1:00 (PST 9:00)
# launchd: com.happycode.instreet-patrol

[ -f ~/.zshrc ] && source ~/.zshrc

set -o pipefail

PROJECT_DIR="/Users/tuanyou/Happycode2026"
VENV="$PROJECT_DIR/.venv/bin/python"
SCRIPT="$PROJECT_DIR/scripts/instreet_patrol.py"
LOG_DIR="$PROJECT_DIR/vault/logs/instreet-patrol"

mkdir -p "$LOG_DIR"

DATE=$(date +"%Y-%m-%d")
LOG_FILE="$LOG_DIR/${DATE}-run.log"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"; }

# Load .env
ENV_FILE="$PROJECT_DIR/.env"
if [ -f "$ENV_FILE" ]; then
    set -a
    source "$ENV_FILE"
    set +a
fi

export HOME="${HOME:-/Users/tuanyou}"
export PATH="/Users/tuanyou/.local/bin:/opt/homebrew/bin:$PATH"
export USER="${USER:-tuanyou}"

log "InStreet patrol started"

cd "$PROJECT_DIR"
$VENV "$SCRIPT" >> "$LOG_FILE" 2>&1
EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    log "Patrol completed successfully"
else
    log "Patrol failed with exit code $EXIT_CODE"
fi
