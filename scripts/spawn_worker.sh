#!/bin/bash
# spawn_worker.sh - 启动一个 Worker Claude Code 进程
# 用法: ./spawn_worker.sh <task_id> <task_description>
#
# Worker 会：
# 1. 读取任务文件 vault/agents/tasks/<task_id>.md
# 2. 执行任务，过程写入 vault/agents/logs/<task_id>.log.md
# 3. 完成后写结果到 vault/agents/results/<task_id>.result.md

set -e

TASK_ID="${1:?用法: spawn_worker.sh <task_id> <task_description>}"
TASK_DESC="${2:?请提供任务描述}"

BASE_DIR="$HOME/Happycode2026"
TASK_FILE="$BASE_DIR/vault/agents/tasks/${TASK_ID}.md"
LOG_FILE="$BASE_DIR/vault/agents/logs/${TASK_ID}.log.md"
RESULT_FILE="$BASE_DIR/vault/agents/results/${TASK_ID}.result.md"

# 写入任务文件
cat > "$TASK_FILE" << EOF
# Task: ${TASK_ID}
- Created: $(date '+%Y-%m-%d %H:%M:%S')
- Status: pending

## Description
${TASK_DESC}
EOF

# 构建 worker prompt
WORKER_PROMPT="你是一个 Worker Agent，正在执行任务。

## 你的工作协议

1. **先读取任务**: 读取 ${TASK_FILE}
2. **写工作日志**: 每完成一个步骤，追加记录到 ${LOG_FILE}，格式：
   - [时间] 步骤描述
   - [时间] 发现/结果
3. **执行任务**: ${TASK_DESC}
4. **写最终结果**: 完成后写入 ${RESULT_FILE}，格式：
   # Result: ${TASK_ID}
   - Completed: 时间
   - Status: success/failed
   ## Summary (3-5句话总结)
   ## Details (详细内容)
   ## Errors (如果有)

## 重要规则
- 所有输出写文件，不要只输出到终端
- 日志要实时更新，不要最后才写
- 结果文件必须包含 Status 行
- 用中文写日志和结果

现在开始执行任务。"

# 标记开始
echo "# Worker Log: ${TASK_ID}" > "$LOG_FILE"
echo "- Started: $(date '+%Y-%m-%d %H:%M:%S')" >> "$LOG_FILE"
echo "" >> "$LOG_FILE"

# 启动 worker（后台运行，unset CLAUDECODE 允许嵌套）
cd "$BASE_DIR"
unset CLAUDECODE
claude -p "$WORKER_PROMPT" \
  --allowedTools "Read,Write,Edit,Bash,Glob,Grep,WebSearch,WebFetch,Agent" \
  > "$BASE_DIR/vault/agents/logs/${TASK_ID}.stdout.log" 2>&1

# 标记完成
echo "" >> "$LOG_FILE"
echo "- Worker process ended: $(date '+%Y-%m-%d %H:%M:%S')" >> "$LOG_FILE"
