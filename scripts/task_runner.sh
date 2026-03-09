#!/bin/bash
# Task Runner: Shell orchestrator for autonomous Claude Code evolution.
# Pulls tasks from the queue and executes each in a fresh `claude -p` session.
# Solves context exhaustion by keeping each task in its own short session.
#
# Usage: ./scripts/task_runner.sh [--max-tasks N] [--max-minutes M]
# Cron:  */15 * * * * /Users/tuanyou/Happycode2026/scripts/task_runner.sh --max-tasks 3

set -uo pipefail

PROJECT_DIR="/Users/tuanyou/Happycode2026"
VENV="$PROJECT_DIR/.venv/bin/python"
CLAUDE_BIN="/Users/tuanyou/.local/bin/claude"
LOCK_FILE="/tmp/happycode_task_runner.lock"
LOG_DIR="$PROJECT_DIR/vault/tasks/logs"
DATE=$(date +"%Y-%m-%d")
LOG_FILE="$LOG_DIR/runner-${DATE}.log"

# Defaults
MAX_TASKS=5
MAX_MINUTES=60
START_TIME=$(date +%s)

# Parse args
while [[ $# -gt 0 ]]; do
    case $1 in
        --max-tasks) MAX_TASKS="$2"; shift 2;;
        --max-minutes) MAX_MINUTES="$2"; shift 2;;
        *) shift;;
    esac
done

mkdir -p "$LOG_DIR"
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"; }

# Lock file to prevent concurrent runs
if [ -f "$LOCK_FILE" ]; then
    LOCK_PID=$(cat "$LOCK_FILE" 2>/dev/null)
    if kill -0 "$LOCK_PID" 2>/dev/null; then
        log "Another runner is active (PID $LOCK_PID), exiting"
        exit 0
    else
        log "Stale lock file found, removing"
        rm -f "$LOCK_FILE"
    fi
fi
echo $$ > "$LOCK_FILE"
trap 'rm -f "$LOCK_FILE"' EXIT

# Unset to avoid nesting issues
unset CLAUDECODE 2>/dev/null || true
export HOME="${HOME:-/Users/tuanyou}"
export PATH="/Users/tuanyou/.local/bin:$PATH"
export USER="${USER:-tuanyou}"

log "Task runner started (max_tasks=$MAX_TASKS, max_minutes=$MAX_MINUTES)"

# Clear stale running tasks first
"$VENV" -c "
from src.task_queue import TaskQueue
q = TaskQueue()
q.clear_stale_running()
" 2>/dev/null

TASKS_RUN=0

while [ $TASKS_RUN -lt $MAX_TASKS ]; do
    # Check time limit
    NOW=$(date +%s)
    ELAPSED=$(( (NOW - START_TIME) / 60 ))
    if [ $ELAPSED -ge $MAX_MINUTES ]; then
        log "Time limit reached ($ELAPSED min), stopping"
        break
    fi

    # Get next task from queue
    TASK_JSON=$("$VENV" -c "
import json
from src.task_queue import TaskQueue
q = TaskQueue()
t = q.next()
if t:
    q.mark_running(t.task_id)
    print(json.dumps(t.to_dict()))
else:
    print('null')
" 2>/dev/null)

    if [ "$TASK_JSON" = "null" ] || [ -z "$TASK_JSON" ]; then
        log "No pending tasks, exiting"
        break
    fi

    TASK_ID=$(echo "$TASK_JSON" | "$VENV" -c "import sys,json; print(json.load(sys.stdin)['task_id'])")
    TASK_TITLE=$(echo "$TASK_JSON" | "$VENV" -c "import sys,json; print(json.load(sys.stdin)['title'])")
    TASK_PROMPT=$(echo "$TASK_JSON" | "$VENV" -c "import sys,json; print(json.load(sys.stdin)['prompt'])")
    TASK_TIMEOUT=$(echo "$TASK_JSON" | "$VENV" -c "import sys,json; print(json.load(sys.stdin).get('timeout_seconds', 120))")

    log "Running task: $TASK_ID - $TASK_TITLE (timeout: ${TASK_TIMEOUT}s)"

    # Execute task in a fresh claude -p session
    TASK_OUTPUT_FILE="$LOG_DIR/task-${TASK_ID}-${DATE}.log"

    # Build the full prompt with project context
    FULL_PROMPT="You are working in ~/Happycode2026 project. Python venv at .venv/bin/python.

TASK: $TASK_TITLE

$TASK_PROMPT

IMPORTANT: Be concise. Complete the task and output only the result summary. Do not explain what you will do — just do it."

    # Run with timeout
    if timeout "${TASK_TIMEOUT}s" "$CLAUDE_BIN" -p "$FULL_PROMPT" \
        --allowedTools "Read,Write,Edit,Bash,Glob,Grep" \
        --permission-mode auto \
        --model sonnet \
        --max-turns 20 \
        > "$TASK_OUTPUT_FILE" 2>&1; then

        # Success: get last 500 chars as result summary
        RESULT=$(tail -c 500 "$TASK_OUTPUT_FILE")
        "$VENV" -c "
from src.task_queue import TaskQueue
q = TaskQueue()
q.mark_completed('$TASK_ID', '''$RESULT''')
" 2>/dev/null
        log "Task completed: $TASK_ID"
    else
        EXIT_CODE=$?
        ERROR="exit code $EXIT_CODE"
        if [ $EXIT_CODE -eq 124 ]; then
            ERROR="timeout after ${TASK_TIMEOUT}s"
        fi
        "$VENV" -c "
from src.task_queue import TaskQueue
q = TaskQueue()
q.mark_failed('$TASK_ID', '$ERROR')
" 2>/dev/null
        log "Task failed: $TASK_ID - $ERROR"
    fi

    TASKS_RUN=$((TASKS_RUN + 1))
done

log "Task runner finished: $TASKS_RUN tasks processed"

# Generate summary if any tasks were run
if [ $TASKS_RUN -gt 0 ]; then
    "$VENV" -c "
from src.task_queue import TaskQueue
q = TaskQueue()
print(q.format_status())
" 2>/dev/null >> "$LOG_FILE"
fi
