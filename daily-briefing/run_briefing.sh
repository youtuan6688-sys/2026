#!/bin/zsh
# Daily Briefing Runner - searches for OpenClaw & Claude updates
# Cron: 7am Beijing time = 3pm PST (during PST) / 4pm PDT (during PDT)

# Load user's shell configuration to get environment variables
[ -f ~/.zshrc ] && source ~/.zshrc

set -uo pipefail

PROJECT_DIR="/Users/tuanyou/Happycode2026/daily-briefing"
REPORTS_DIR="$PROJECT_DIR/reports"
LOGS_DIR="$PROJECT_DIR/logs"
PROMPT_FILE="$PROJECT_DIR/prompts/briefing.md"
VENV="/Users/tuanyou/Happycode2026/.venv/bin/python"

DATE=$(date +"%Y-%m-%d")
REPORT_FILE="$REPORTS_DIR/${DATE}.md"
LOG_FILE="$LOGS_DIR/${DATE}.log"

mkdir -p "$REPORTS_DIR" "$LOGS_DIR"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"; }

log "Briefing started"

# Read prompt and add date
PROMPT="今天是 ${DATE}。

$(cat "$PROMPT_FILE")"

# Unset to avoid nesting error
unset CLAUDECODE 2>/dev/null || true

# Ensure HOME, PATH and USER are set (cron doesn't set HOME/USER, which breaks claude auth)
export HOME="${HOME:-/Users/tuanyou}"
export PATH="/Users/tuanyou/.local/bin:$PATH"
export USER="${USER:-tuanyou}"

# Debug: Check environment
log "DEBUG: HOME=$HOME, USER=$USER, ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY:+set}${ANTHROPIC_API_KEY:-unset}"
log "DEBUG: claude binary: $(which claude)"
log "DEBUG: CLAUDECODE=${CLAUDECODE:-unset}"

# Run Claude Code with web search (explicitly unset CLAUDECODE to avoid nesting)
env -u CLAUDECODE claude -p "$PROMPT" \
    --allowedTools "WebSearch,WebFetch" \
    > "$REPORT_FILE" 2>> "$LOG_FILE"

# Check exit code
EXIT_CODE=$?
if [ $EXIT_CODE -ne 0 ]; then
    log "DEBUG: claude command failed with exit code $EXIT_CODE"
    log "DEBUG: Report file size: $(wc -c < "$REPORT_FILE")"
else
    log "DEBUG: claude command succeeded, report size: $(wc -c < "$REPORT_FILE")"
fi

if [ $? -eq 0 ] && [ -s "$REPORT_FILE" ]; then
    log "Report generated: $REPORT_FILE ($(wc -c < "$REPORT_FILE") bytes)"

    # Prepend system health + overnight error report
    HEALTH_SECTION=""
    HEALTH_RESULT=$($VENV /Users/tuanyou/Happycode2026/scripts/health_check.py 2>/dev/null)
    if [ -n "$HEALTH_RESULT" ]; then
        HEALTH_SECTION="## System Health\n\`\`\`\n${HEALTH_RESULT}\n\`\`\`\n\n"
    fi

    # Check pending actions from nightly review
    PENDING_FILE="/Users/tuanyou/Happycode2026/vault/memory/pending-actions.md"
    PENDING_SECTION=""
    if [ -f "$PENDING_FILE" ] && [ -s "$PENDING_FILE" ]; then
        PENDING_CONTENT=$(tail -30 "$PENDING_FILE")
        PENDING_SECTION="## Overnight Actions Pending\n${PENDING_CONTENT}\n\n"
    fi

    # Check overnight error summary
    ERROR_SECTION=""
    ERROR_SUMMARY=$($VENV -c "
import sys; sys.path.insert(0, '/Users/tuanyou/Happycode2026')
from src.utils.error_tracker import ErrorTracker
t = ErrorTracker()
stats = t.get_stats()
if stats['total'] > 0:
    print(f\"Errors: {stats['total']} total, {stats['unresolved']} unresolved\")
    fixes = t.get_fix_suggestions()
    for f in fixes:
        print(f\"  [{f['error_type']}] {f['count']}x - {'auto-fixable' if f.get('auto') else 'manual'}: {f['fix']}\")
else:
    print('No errors recorded.')
" 2>/dev/null)
    if [ -n "$ERROR_SUMMARY" ] && [ "$ERROR_SUMMARY" != "No errors recorded." ]; then
        ERROR_SECTION="## Error Report\n${ERROR_SUMMARY}\n\n"
    fi

    # Combine health + errors + main report
    if [ -n "$HEALTH_SECTION" ] || [ -n "$ERROR_SECTION" ] || [ -n "$PENDING_SECTION" ]; then
        COMBINED_FILE="${REPORT_FILE%.md}_full.md"
        printf "%b%b%b---\n\n" "$HEALTH_SECTION" "$ERROR_SECTION" "$PENDING_SECTION" > "$COMBINED_FILE"
        cat "$REPORT_FILE" >> "$COMBINED_FILE"
        mv "$COMBINED_FILE" "$REPORT_FILE"
        log "Added health/error/pending sections to report"
    fi

    # Send to Feishu
    cd /Users/tuanyou/Happycode2026
    $VENV "$PROJECT_DIR/notify_feishu.py" "$REPORT_FILE" >> "$LOG_FILE" 2>&1

    # Digest key findings into long-term memory
    DIGEST_FILE="/Users/tuanyou/Happycode2026/vault/memory/briefing-digest.md"
    DIGEST_PROMPT="Read the following daily briefing report and extract a concise bullet-point summary (max 10 bullets) of the most important findings. Output ONLY the bullet points, no headers or preamble. Focus on: new tools, version updates, actionable skills, key numbers.

Report:
$(cat "$REPORT_FILE")"

    DIGEST=$(claude -p "$DIGEST_PROMPT" 2>> "$LOG_FILE")
    if [ -n "$DIGEST" ]; then
        printf "\n## %s\n%s\n" "$DATE" "$DIGEST" >> "$DIGEST_FILE"
        log "Digest appended to memory"
    fi

    # Self-evolution: check if briefing found actionable tools/skills to install
    EVOLVE_PROMPT="你是一个自我进化的 AI 助手。阅读以下简报，判断是否有值得立即行动的事项（新工具安装、配置更新、Skill 安装等）。

如果有，输出一个简短的行动计划（每项一行，格式：- [action] 描述）。
如果没有值得行动的，输出 '无需行动'。

只输出行动计划，不要解释。

简报:
$(cat "$REPORT_FILE")"

    ACTIONS=$(claude -p "$EVOLVE_PROMPT" 2>> "$LOG_FILE")
    if [ -n "$ACTIONS" ] && [ "$ACTIONS" != "无需行动" ]; then
        LEARNINGS_FILE="/Users/tuanyou/Happycode2026/vault/memory/learnings.md"
        PENDING_FILE="/Users/tuanyou/Happycode2026/vault/memory/pending-actions.md"
        printf "\n## %s - 简报行动建议\n%s\n" "$DATE" "$ACTIONS" >> "$LEARNINGS_FILE"
        log "Evolution suggestions appended to learnings"

        # Auto-execute safe actions (skill installs, config updates)
        EXEC_PROMPT="你是一个自我进化的 AI 助手。以下是建议的行动，请判断哪些可以安全自动执行。

安全操作（可自动执行）：
- 安装 Claude Code Skill (npx skills add ...)
- 更新记忆文件
- 添加 MCP server 配置

不安全操作（只记录到 pending-actions.md 等人确认）：
- 修改系统配置
- 删除文件
- 安装系统级软件
- 任何不可逆操作

行动列表:
$ACTIONS

对每个行动输出：
EXEC: <要自动执行的 shell 命令>
或
DEFER: <描述，等人确认>

只输出以上格式。"

        EXEC_RESULT=$(claude -p "$EXEC_PROMPT" \
            --allowedTools "Bash,Read,Write,Edit" \
            2>> "$LOG_FILE")
        log "Auto-evolution result: $EXEC_RESULT"

        # Save deferred actions for user review
        DEFERRED=$(echo "$EXEC_RESULT" | grep "^DEFER:" || true)
        if [ -n "$DEFERRED" ]; then
            printf "\n## %s - 待确认行动\n%s\n" "$DATE" "$DEFERRED" >> "$PENDING_FILE"
            log "Deferred actions saved to pending-actions.md"
        fi

        # Execute safe actions
        echo "$EXEC_RESULT" | grep "^EXEC:" | while read -r line; do
            CMD=$(echo "$line" | sed 's/^EXEC: //')
            log "Auto-executing: $CMD"
            eval "$CMD" >> "$LOG_FILE" 2>&1 || log "FAILED: $CMD"
        done
    fi

    # Deep absorption: extract actionable knowledge from report
    log "Starting deep absorption..."
    $VENV "$PROJECT_DIR/deep_absorb.py" "$REPORT_FILE" >> "$LOG_FILE" 2>&1
    if [ $? -eq 0 ]; then
        log "Deep absorption completed"
    else
        log "Deep absorption failed (non-fatal)"
    fi

    log "Briefing completed"
else
    log "Briefing FAILED"
fi
