#!/bin/bash
# review.sh - CEO 验收任务
# 用法: ./review.sh <task_id> [approve|reject] [comment]
#
# 示例:
#   ./review.sh api-auth                    # 查看任务结果
#   ./review.sh api-auth approve            # 通过
#   ./review.sh api-auth reject "缺少测试"   # 打回

TASK_ID="${1:?用法: review.sh <task_id> [approve|reject] [comment]}"
ACTION="$2"
COMMENT="$3"

BASE_DIR="$HOME/Happycode2026/team"
TASK_FILE="$BASE_DIR/tasks/review/${TASK_ID}.md"

# 检查任务是否在待验收
if [ ! -f "$TASK_FILE" ]; then
    echo "任务 $TASK_ID 不在待验收队列"
    echo ""
    echo "检查其他状态:"
    for dir in active queue done failed; do
        if [ -f "$BASE_DIR/tasks/$dir/${TASK_ID}.md" ]; then
            echo "  找到: tasks/$dir/${TASK_ID}.md"
        fi
    done
    exit 1
fi

# 获取角色
ROLE=$(grep -m1 "Assigned:" "$TASK_FILE" | sed 's/.*: //')
RESULT_FILE="$BASE_DIR/roles/$ROLE/workspace/${TASK_ID}.result.md"
LOG_FILE="$BASE_DIR/roles/$ROLE/workspace/${TASK_ID}.log.md"

# 如果没有 action，显示详情
if [ -z "$ACTION" ]; then
    echo "═══ 任务验收: $TASK_ID ═══"
    echo ""

    echo "── 任务信息 ──"
    cat "$TASK_FILE"
    echo ""

    if [ -f "$RESULT_FILE" ]; then
        echo "── 交付结果 ──"
        cat "$RESULT_FILE"
    else
        echo "── 结果文件不存在 ──"
    fi

    echo ""
    echo "── 工作日志（最后 20 行）──"
    if [ -f "$LOG_FILE" ]; then
        tail -20 "$LOG_FILE"
    else
        echo "(无日志)"
    fi

    echo ""
    echo "操作: review.sh $TASK_ID approve  或  review.sh $TASK_ID reject \"原因\""
    exit 0
fi

# 执行操作
NOW=$(date '+%Y-%m-%d %H:%M:%S')

case "$ACTION" in
    approve)
        sed -i '' 's/Status: review/Status: approved/' "$TASK_FILE"
        echo "- Reviewed: $NOW" >> "$TASK_FILE"
        echo "- Review: APPROVED" >> "$TASK_FILE"
        [ -n "$COMMENT" ] && echo "- Comment: $COMMENT" >> "$TASK_FILE"
        mv "$TASK_FILE" "$BASE_DIR/tasks/done/"
        echo "✓ 任务 $TASK_ID 已通过验收"
        ;;

    reject)
        sed -i '' 's/Status: review/Status: rejected/' "$TASK_FILE"
        echo "- Reviewed: $NOW" >> "$TASK_FILE"
        echo "- Review: REJECTED" >> "$TASK_FILE"
        echo "- Reason: ${COMMENT:-未说明}" >> "$TASK_FILE"
        mv "$TASK_FILE" "$BASE_DIR/tasks/queue/"
        echo "✗ 任务 $TASK_ID 已打回，原因: ${COMMENT:-未说明}"
        echo "  任务已移回队列，等待重新分配"
        ;;

    *)
        echo "未知操作: $ACTION"
        echo "用法: review.sh $TASK_ID [approve|reject]"
        exit 1
        ;;
esac
