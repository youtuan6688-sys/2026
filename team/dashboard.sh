#!/bin/bash
# dashboard.sh - 团队任务看板
# 用法: ./dashboard.sh [role]
#
# 不带参数显示全部，带角色名只显示该角色

BASE_DIR="$HOME/Happycode2026/team"

show_tasks() {
    local dir="$1"
    local label="$2"
    local count=0

    if [ -d "$dir" ] && [ "$(ls -A "$dir" 2>/dev/null)" ]; then
        for f in "$dir"/*.md; do
            [ -f "$f" ] || continue
            task_id=$(basename "$f" .md)
            assigned=$(grep -m1 "Assigned:" "$f" 2>/dev/null | sed 's/.*: //')
            priority=$(grep -m1 "Priority:" "$f" 2>/dev/null | sed 's/.*: //')
            desc=$(grep -m1 "^##" "$f" 2>/dev/null | head -1)

            # 如果指定了角色筛选
            if [ -n "$FILTER_ROLE" ] && [ "$assigned" != "$FILTER_ROLE" ]; then
                continue
            fi

            printf "  %-20s %-10s %-12s %s\n" "$task_id" "${assigned:-?}" "${priority:-?}" "${desc:-}"
            count=$((count + 1))
        done
    fi

    if [ $count -eq 0 ]; then
        echo "  (空)"
    fi
}

FILTER_ROLE="$1"

echo "╔══════════════════════════════════════════════╗"
echo "║        HappyCode 团队任务看板               ║"
echo "║        $(date '+%Y-%m-%d %H:%M:%S')              ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

if [ -n "$FILTER_ROLE" ]; then
    echo "筛选角色: $FILTER_ROLE"
    echo ""
fi

echo "─── 执行中 (Active) ───"
show_tasks "$BASE_DIR/tasks/active" "active"
echo ""

echo "─── 待验收 (Review) ───"
show_tasks "$BASE_DIR/tasks/review" "review"
echo ""

echo "─── 排队中 (Queue) ───"
show_tasks "$BASE_DIR/tasks/queue" "queue"
echo ""

echo "─── 已完成 (Done) ───"
show_tasks "$BASE_DIR/tasks/done" "done"
echo ""

echo "─── 失败 (Failed) ───"
show_tasks "$BASE_DIR/tasks/failed" "failed"
echo ""

# 角色工作量统计
echo "─── 团队状态 ───"
for role in backend frontend reviewer pm researcher devops qa cmo cfo; do
    role_dir="$BASE_DIR/roles/$role/workspace"
    if [ -d "$role_dir" ]; then
        active=$(ls "$role_dir"/*.log.md 2>/dev/null | wc -l | tr -d ' ')
        done=$(ls "$role_dir"/*.result.md 2>/dev/null | wc -l | tr -d ' ')
        printf "  %-12s 日志: %-3s  完成: %-3s\n" "$role" "$active" "$done"
    else
        printf "  %-12s (空闲)\n" "$role"
    fi
done
