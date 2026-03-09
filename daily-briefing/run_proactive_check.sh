#!/bin/bash
# Proactive Check: review pending actions and remind user via Feishu
# Cron: 9am Beijing (5pm PST) - after daily briefing, before end of workday

set -uo pipefail

PROJECT_DIR="/Users/tuanyou/Happycode2026"
PENDING_FILE="$PROJECT_DIR/vault/memory/pending-actions.md"
LOGS_DIR="$PROJECT_DIR/daily-briefing/logs"
DATE=$(date +"%Y-%m-%d")
LOG_FILE="$LOGS_DIR/proactive-${DATE}.log"
VENV="$PROJECT_DIR/.venv/bin/python"

mkdir -p "$LOGS_DIR"
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"; }

log "Proactive check started"

# Unset to avoid nesting error
unset CLAUDECODE 2>/dev/null || true
export PATH="/Users/tuanyou/.local/bin:$PATH"

# Check if there are pending actions
if [ ! -f "$PENDING_FILE" ] || [ ! -s "$PENDING_FILE" ]; then
    log "No pending actions, skipping"
    exit 0
fi

PENDING=$(cat "$PENDING_FILE")

# Generate a concise reminder
REMIND_PROMPT="你是 Tuan You 的 AI 助手。以下是待确认的行动建议。

生成一条简短的飞书提醒消息（不超过500字）：
1. 列出待确认的行动（最多5条）
2. 对每条说明为什么建议执行
3. 用户可以回复「执行 X」来确认

待确认行动:
$PENDING

只输出提醒消息，不要其他内容。"

REMINDER=$(claude -p "$REMIND_PROMPT" 2>> "$LOG_FILE")

if [ -n "$REMINDER" ]; then
    cd "$PROJECT_DIR"
    # Reuse the notify script's sender
    $VENV -c "
import sys
sys.path.insert(0, '$PROJECT_DIR')
from config.settings import settings
from src.feishu_sender import FeishuSender
sender = FeishuSender(settings)
sender.send_text('ou_6199e18f2fa15ea297ec4cdd515630f3', '''$REMINDER''')
print('Reminder sent')
" >> "$LOG_FILE" 2>&1
    log "Proactive reminder sent"
else
    log "Failed to generate reminder"
fi

log "Proactive check completed"
