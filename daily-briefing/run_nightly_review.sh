#!/bin/bash
# Nightly Self-Review: audit knowledge base quality, clean low-value entries, update memory
# Cron: 11pm PST = 3pm Beijing next day (low-activity window)

set -uo pipefail

PROJECT_DIR="/Users/tuanyou/Happycode2026"
LOGS_DIR="$PROJECT_DIR/daily-briefing/logs"
DATE=$(date +"%Y-%m-%d")
LOG_FILE="$LOGS_DIR/nightly-${DATE}.log"

mkdir -p "$LOGS_DIR"
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"; }

log "Nightly review started"

# Unset to avoid nesting error
unset CLAUDECODE 2>/dev/null || true
export HOME="${HOME:-/Users/tuanyou}"
export PATH="/Users/tuanyou/.local/bin:$PATH"
export USER="${USER:-tuanyou}"

# Step 1: Audit knowledge base articles
VAULT_DIR="$PROJECT_DIR/vault"
ARTICLES=$(find "$VAULT_DIR/articles" "$VAULT_DIR/social" -name "*.md" -type f 2>/dev/null | sort)
ARTICLE_COUNT=$(echo "$ARTICLES" | wc -l | tr -d ' ')

log "Found $ARTICLE_COUNT articles to review"

# Build article list for Claude
ARTICLE_LIST=""
for f in $ARTICLES; do
    TITLE=$(grep "^title:" "$f" 2>/dev/null | head -1 | sed 's/^title: "//' | sed 's/"$//')
    SUMMARY=$(grep "^  " "$f" 2>/dev/null | head -1 | sed 's/^  //')
    FNAME=$(basename "$f")
    ARTICLE_LIST="$ARTICLE_LIST\n- $FNAME | $TITLE | $SUMMARY"
done

REVIEW_PROMPT="你是知识库管理员。审查以下文章列表，找出低价值或误入的文章。

文章列表:
$(echo -e "$ARTICLE_LIST")

请输出:
1. 建议删除的文章（文件名 + 原因），格式: DELETE: filename | reason
2. 知识库整体质量评分 (1-10)
3. 改进建议（一句话）

只输出以上内容，不要其他解释。"

REVIEW=$(claude -p "$REVIEW_PROMPT" 2>> "$LOG_FILE")
log "Review result: $REVIEW"

# Step 2: Auto-delete articles marked for deletion (only if explicitly tagged)
echo "$REVIEW" | grep "^DELETE:" | while read -r line; do
    FNAME=$(echo "$line" | sed 's/^DELETE: //' | cut -d'|' -f1 | tr -d ' ')
    FPATH=$(find "$VAULT_DIR" -name "$FNAME" -type f 2>/dev/null | head -1)
    if [ -n "$FPATH" ] && [ -f "$FPATH" ]; then
        mv "$FPATH" "$VAULT_DIR/.trash/" 2>/dev/null || mkdir -p "$VAULT_DIR/.trash" && mv "$FPATH" "$VAULT_DIR/.trash/"
        log "Moved to trash: $FNAME"
    fi
done

# Step 3: Check memory file sizes and compress if needed
for MEM_FILE in "$VAULT_DIR/memory/decisions.md" "$VAULT_DIR/memory/learnings.md" "$VAULT_DIR/memory/briefing-digest.md"; do
    if [ -f "$MEM_FILE" ]; then
        SIZE=$(wc -c < "$MEM_FILE" | tr -d ' ')
        if [ "$SIZE" -gt 5000 ]; then
            log "Memory file $(basename $MEM_FILE) is ${SIZE} bytes, compressing..."
            COMPRESS_PROMPT="压缩以下记忆文件，保留最重要的信息，删除过时或重复内容。保持相同的 Markdown 格式。输出压缩后的完整文件内容。

$(cat "$MEM_FILE")"
            COMPRESSED=$(claude -p "$COMPRESS_PROMPT" 2>> "$LOG_FILE")
            if [ -n "$COMPRESSED" ] && [ ${#COMPRESSED} -gt 100 ]; then
                cp "$MEM_FILE" "${MEM_FILE}.bak"
                echo "$COMPRESSED" > "$MEM_FILE"
                log "Compressed $(basename $MEM_FILE): ${SIZE} -> $(wc -c < "$MEM_FILE" | tr -d ' ') bytes"
            fi
        fi
    fi
done

# Step 4: Append review summary to learnings
LEARNINGS_FILE="$VAULT_DIR/memory/learnings.md"
SCORE=$(echo "$REVIEW" | grep -oE '[0-9]+/10' | head -1)
if [ -n "$SCORE" ]; then
    printf "\n## %s - 夜间审查\n- 知识库质量: %s\n- 文章总数: %s\n" "$DATE" "$SCORE" "$ARTICLE_COUNT" >> "$LEARNINGS_FILE"
    log "Review score recorded: $SCORE"
fi

# Step 5: Health check + auto-heal
log "Running health check..."
HEALTH_RESULT=$("$PROJECT_DIR/.venv/bin/python" "$PROJECT_DIR/scripts/health_check.py" 2>> "$LOG_FILE")
HEALTH_EXIT=$?
log "Health check result (exit=$HEALTH_EXIT): $HEALTH_RESULT"

if [ $HEALTH_EXIT -ne 0 ]; then
    # Health issues found — save to pending actions for morning report
    PENDING_FILE="$VAULT_DIR/memory/pending-actions.md"
    printf "\n## %s - Health Check Issues\n\`\`\`\n%s\n\`\`\`\n" "$DATE" "$HEALTH_RESULT" >> "$PENDING_FILE"
    log "Health issues saved to pending-actions.md"
fi

# Step 5b: Error log dedup + analysis
log "Deduplicating error log..."
"$PROJECT_DIR/.venv/bin/python" -c "
import sys; sys.path.insert(0, '$PROJECT_DIR')
from src.utils.error_tracker import ErrorTracker
t = ErrorTracker()
n = t.auto_resolve_duplicates()
fixes = t.get_fix_suggestions()
print(f'Deduped {n} errors')
for f in fixes:
    print(f'  [{f[\"error_type\"]}] {f[\"count\"]}x - fix: {f[\"fix\"]}')
" 2>> "$LOG_FILE" | while read -r line; do log "$line"; done

# Step 5c: Error log analysis and auto-fix suggestions
ERROR_LOG="$VAULT_DIR/logs/error_log.json"
if [ -f "$ERROR_LOG" ] && [ -s "$ERROR_LOG" ]; then
    ERROR_COUNT=$(python3 -c "import json; d=json.load(open('$ERROR_LOG')); print(len(d))" 2>/dev/null || echo "0")
    UNRESOLVED=$(python3 -c "import json; d=json.load(open('$ERROR_LOG')); print(sum(1 for e in d if not e.get('resolved')))" 2>/dev/null || echo "0")
    log "Error log: $ERROR_COUNT total, $UNRESOLVED unresolved"

    if [ "$UNRESOLVED" -gt 0 ]; then
        # Get recent unresolved errors for analysis
        RECENT_ERRORS=$(python3 -c "
import json
d=json.load(open('$ERROR_LOG'))
unresolved=[e for e in d if not e.get('resolved')][-20:]
for e in unresolved:
    print(f\"[{e.get('severity','?')}] {e.get('error_type','')} in {e.get('source','')}: {e.get('message','')[:100]}\")
" 2>/dev/null || echo "")

        if [ -n "$RECENT_ERRORS" ]; then
            ERROR_PROMPT="你是一个自我修复系统。分析以下错误日志，找出：
1. 重复出现的模式（可能是系统性问题）
2. 可自动修复的问题（建议具体的 fix）
3. 需要人工介入的问题

错误列表:
$RECENT_ERRORS

输出格式:
PATTERN: <描述重复模式> | <出现次数> | <建议修复>
AUTOFIX: <具体操作描述>
HUMAN: <需要人工处理的问题>

如果没有可分析的，输出: NO_ISSUES
只输出以上格式。"

            ERROR_ANALYSIS=$(claude -p "$ERROR_PROMPT" 2>> "$LOG_FILE")
            log "Error analysis: $ERROR_ANALYSIS"

            # Save analysis results
            if ! echo "$ERROR_ANALYSIS" | grep -q "NO_ISSUES"; then
                printf "\n## %s - 错误分析\n%s\n" "$DATE" "$ERROR_ANALYSIS" >> "$LEARNINGS_FILE"

                # Execute autofix suggestions
                echo "$ERROR_ANALYSIS" | grep "^AUTOFIX:" | while read -r line; do
                    FIX=$(echo "$line" | sed 's/^AUTOFIX: //')
                    log "Auto-fix suggestion: $FIX"
                done

                # Save human-required items to pending
                HUMAN_ITEMS=$(echo "$ERROR_ANALYSIS" | grep "^HUMAN:" || true)
                if [ -n "$HUMAN_ITEMS" ]; then
                    PENDING_FILE="$VAULT_DIR/memory/pending-actions.md"
                    printf "\n## %s - 错误需人工处理\n%s\n" "$DATE" "$HUMAN_ITEMS" >> "$PENDING_FILE"
                fi
            fi
        fi
    fi
else
    log "No error log found or empty"
fi

# Step 6: Re-index vector store (articles + memory)
log "Re-indexing vector store..."
cd "$PROJECT_DIR"
"$PROJECT_DIR/.venv/bin/python" "$PROJECT_DIR/scripts/reindex_vault.py" >> "$LOG_FILE" 2>&1
log "Vector store re-indexed"

# Step 7: Scan for new tools/skills/MCP servers
TOOL_SCAN_PROMPT="你是 Claude Code 生态的工具扫描员。检查以下已安装工具列表，然后建议是否需要更新或安装新工具。

当前已安装工具 (tools.md):
$(cat "$VAULT_DIR/memory/tools.md" 2>/dev/null | head -80)

请输出:
1. 是否有工具需要更新？
2. 是否发现值得安装的新工具？（只推荐高价值、社区验证过的）
3. 格式: ACTION: install/update | tool_name | reason

如果没有建议，输出: NO_ACTION
只输出以上内容。"

TOOL_RESULT=$(claude -p "$TOOL_SCAN_PROMPT" 2>> "$LOG_FILE")
log "Tool scan result: $TOOL_RESULT"

# Save tool suggestions to pending-actions if any
if ! echo "$TOOL_RESULT" | grep -q "NO_ACTION"; then
    PENDING_FILE="$VAULT_DIR/memory/pending-actions.md"
    printf "\n## %s - 工具扫描建议\n%s\n" "$DATE" "$TOOL_RESULT" >> "$PENDING_FILE"
    log "Tool suggestions saved to pending-actions.md"
fi

log "Nightly review completed"
