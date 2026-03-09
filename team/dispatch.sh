#!/bin/bash
# dispatch.sh - CEO 派任务给团队成员
# 用法: ./dispatch.sh <role> <task_id> "task description" [priority] [--bg]
#
# 角色: backend, frontend, reviewer, pm, researcher, devops, qa
# 优先级: P0_urgent, P1_high, P2_medium (默认), P3_low
# --bg: 后台运行（不阻塞终端）
#
# 示例:
#   ./dispatch.sh backend api-auth "实现用户认证 API" P1_high
#   ./dispatch.sh backend api-auth "实现用户认证 API" P1_high --bg
#   ./dispatch.sh researcher tech-eval "调研向量数据库方案" --bg

set -e

ROLE="${1:?用法: dispatch.sh <role> <task_id> \"description\" [priority] [--bg]}"
TASK_ID="${2:?请提供任务 ID}"
TASK_DESC="${3:?请提供任务描述}"

# 解析可选参数（priority 和 --bg 可以任意顺序）
BG_MODE=false
PRIORITY="P2_medium"
for arg in "${@:4}"; do
    case "$arg" in
        --bg) BG_MODE=true ;;
        P[0-3]*) PRIORITY="$arg" ;;
    esac
done

BASE_DIR="$HOME/Happycode2026"
TEAM_DIR="$BASE_DIR/team"
ROLE_DIR="$TEAM_DIR/roles/$ROLE"
TASK_FILE="$TEAM_DIR/tasks/active/${TASK_ID}.md"
LOG_FILE="$ROLE_DIR/workspace/${TASK_ID}.log.md"
RESULT_FILE="$ROLE_DIR/workspace/${TASK_ID}.result.md"

# 验证角色存在
if [ ! -d "$ROLE_DIR" ]; then
    echo "错误: 角色 '$ROLE' 不存在"
    echo "可用角色: backend, frontend, reviewer, pm, researcher, devops, qa, cmo, cfo"
    exit 1
fi

# 检查任务是否已存在
for dir in active review queue; do
    if [ -f "$TEAM_DIR/tasks/$dir/${TASK_ID}.md" ]; then
        echo "错误: 任务 $TASK_ID 已存在于 $dir/"
        exit 1
    fi
done

# 读取角色的 CLAUDE.md 作为系统指令
ROLE_INSTRUCTIONS="$ROLE_DIR/CLAUDE.md"
CONVENTIONS="$TEAM_DIR/shared/conventions.md"

# 创建任务文件
cat > "$TASK_FILE" << EOF
# Task: ${TASK_ID}
- Created: $(date '+%Y-%m-%d %H:%M:%S')
- Assigned: ${ROLE}
- Priority: ${PRIORITY}
- Status: in_progress

## Description
${TASK_DESC}

## Files
- Log: ${LOG_FILE}
- Result: ${RESULT_FILE}
EOF

echo "[$(date '+%H:%M:%S')] 派任务给 $ROLE: $TASK_ID"
echo "  描述: $TASK_DESC"
echo "  优先级: $PRIORITY"
echo "  模式: $([ "$BG_MODE" = true ] && echo '后台' || echo '前台')"

# 初始化日志
mkdir -p "$ROLE_DIR/workspace"
cat > "$LOG_FILE" << EOF
# Work Log: ${TASK_ID}
- Role: ${ROLE}
- Started: $(date '+%Y-%m-%d %H:%M:%S')
- Task: ${TASK_DESC}

---
EOF

# 构建角色感知的 prompt
WORKER_PROMPT="$(cat "$ROLE_INSTRUCTIONS")

---

# 团队规范
$(cat "$CONVENTIONS")

---

# 当前任务

**任务 ID**: ${TASK_ID}
**优先级**: ${PRIORITY}
**描述**: ${TASK_DESC}

## 你的工作协议

1. **理解任务**: 仔细阅读上面的任务描述
2. **写工作日志**: 每完成一个步骤，追加到 ${LOG_FILE}
   格式: - [时间] 做了什么
3. **执行任务**: 按照你的角色职责完成任务
4. **写结果报告**: 完成后写入 ${RESULT_FILE}，格式：

\`\`\`
# Result: ${TASK_ID}
- Role: ${ROLE}
- Completed: 时间
- Status: success/failed
- Priority: ${PRIORITY}

## Summary
3-5 句话总结

## Deliverables
具体交付物列表（文件路径、代码变更等）

## Details
详细内容

## Issues
遇到的问题（如果有）

## Next Steps
后续建议（如果有）
\`\`\`

## 重要规则
- 所有输出写文件，不要只打印到终端
- 日志要实时更新
- 结果文件必须包含 Status 行
- 用中文写日志和报告
- 完成后在任务文件中更新状态为 review

现在开始执行任务。"

# 获取角色对应的工具权限和预算
case "$ROLE" in
    backend)
        TOOLS="Read,Write,Edit,Bash,Glob,Grep,Agent,WebFetch,WebSearch"
        BUDGET=5.0
        ;;
    frontend)
        TOOLS="Read,Write,Edit,Bash,Glob,Grep,Agent,WebFetch"
        BUDGET=5.0
        ;;
    reviewer)
        TOOLS="Read,Bash,Glob,Grep,Agent"
        BUDGET=3.0
        ;;
    pm)
        TOOLS="Read,Write,Edit,Glob,Grep,WebSearch,WebFetch,Agent"
        BUDGET=3.0
        ;;
    researcher)
        TOOLS="Read,Write,Edit,Glob,Grep,WebSearch,WebFetch,Agent"
        BUDGET=3.0
        ;;
    devops)
        TOOLS="Read,Write,Edit,Bash,Glob,Grep,Agent"
        BUDGET=3.0
        ;;
    qa)
        TOOLS="Read,Write,Edit,Bash,Glob,Grep,Agent"
        BUDGET=3.0
        ;;
    cmo)
        TOOLS="Read,Write,Edit,Glob,Grep,WebSearch,WebFetch,Agent"
        BUDGET=3.0
        ;;
    cfo)
        TOOLS="Read,Write,Edit,Glob,Grep,Agent"
        BUDGET=2.0
        ;;
    *)
        TOOLS="Read,Write,Edit,Bash,Glob,Grep"
        BUDGET=2.0
        ;;
esac

# 执行函数
run_worker() {
    cd "$BASE_DIR"
    unset CLAUDECODE

    claude -p "$WORKER_PROMPT" \
        --allowedTools "$TOOLS" \
       "$BUDGET" \
        > "$ROLE_DIR/workspace/${TASK_ID}.stdout.log" 2>&1

    # 任务完成后更新状态
    if [ -f "$RESULT_FILE" ]; then
        if [ -f "$TASK_FILE" ]; then
            sed -i '' 's/Status: in_progress/Status: review/' "$TASK_FILE"
            mv "$TASK_FILE" "$TEAM_DIR/tasks/review/" 2>/dev/null || true
        fi
        echo "[$(date '+%H:%M:%S')] $ROLE 完成任务 $TASK_ID，等待验收"
    else
        if [ -f "$TASK_FILE" ]; then
            sed -i '' 's/Status: in_progress/Status: failed/' "$TASK_FILE"
            mv "$TASK_FILE" "$TEAM_DIR/tasks/failed/" 2>/dev/null || true
        fi
        echo "[$(date '+%H:%M:%S')] $ROLE 任务 $TASK_ID 可能失败，检查日志"
    fi
}

# 启动 worker
if [ "$BG_MODE" = true ]; then
    echo "[$(date '+%H:%M:%S')] 后台启动 worker..."
    run_worker &
    WORKER_PID=$!
    echo "[$(date '+%H:%M:%S')] Worker PID: $WORKER_PID"
    echo "  查看状态: team/dashboard.sh"
    echo "  查看日志: tail -f $LOG_FILE"
else
    echo "[$(date '+%H:%M:%S')] 前台启动 worker..."
    run_worker
fi
