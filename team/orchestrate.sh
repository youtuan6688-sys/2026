#!/bin/bash
# orchestrate.sh - CEO 编排复杂任务（多角色并行/串行）
#
# 用法:
#   ./orchestrate.sh parallel <plan_file>   # 并行执行计划中的所有任务
#   ./orchestrate.sh pipeline <plan_file>   # 串行流水线（上一步完成才做下一步）
#   ./orchestrate.sh status <plan_id>       # 查看编排状态
#
# 计划文件格式 (YAML-like):
#   plan_id: feature-chat
#   tasks:
#     - role: pm
#       id: chat-prd
#       desc: "写聊天功能 PRD"
#       priority: P1_high
#     - role: backend
#       id: chat-api
#       desc: "实现聊天 API"
#       depends: chat-prd
#     - role: frontend
#       id: chat-ui
#       desc: "实现聊天界面"
#       depends: chat-prd
#     - role: reviewer
#       id: chat-review
#       desc: "审查聊天功能代码"
#       depends: chat-api,chat-ui

set -e

MODE="${1:?用法: orchestrate.sh <parallel|pipeline|status> <plan_file|plan_id>}"
ARG="${2:?请提供计划文件或 plan_id}"

BASE_DIR="$HOME/Happycode2026"
TEAM_DIR="$BASE_DIR/team"
DISPATCH="$TEAM_DIR/dispatch.sh"

# 简单解析计划文件（提取 role, id, desc, priority）
parse_plan() {
    local plan_file="$1"
    local task_count=0
    local current_role="" current_id="" current_desc="" current_priority="" current_depends=""

    PLAN_ID=""
    TASK_ROLES=()
    TASK_IDS=()
    TASK_DESCS=()
    TASK_PRIORITIES=()
    TASK_DEPENDS=()

    while IFS= read -r line; do
        # 去掉前后空格
        line=$(echo "$line" | sed 's/^[[:space:]]*//' | sed 's/[[:space:]]*$//')

        case "$line" in
            plan_id:*)
                PLAN_ID=$(echo "$line" | sed 's/plan_id:[[:space:]]*//')
                ;;
            "- role:"*)
                # 保存前一个任务
                if [ -n "$current_id" ]; then
                    TASK_ROLES+=("$current_role")
                    TASK_IDS+=("$current_id")
                    TASK_DESCS+=("$current_desc")
                    TASK_PRIORITIES+=("${current_priority:-P2_medium}")
                    TASK_DEPENDS+=("${current_depends:-none}")
                fi
                current_role=$(echo "$line" | sed 's/- role:[[:space:]]*//')
                current_id="" current_desc="" current_priority="" current_depends=""
                ;;
            id:*)
                current_id=$(echo "$line" | sed 's/id:[[:space:]]*//')
                ;;
            desc:*)
                current_desc=$(echo "$line" | sed 's/desc:[[:space:]]*//' | tr -d '"')
                ;;
            priority:*)
                current_priority=$(echo "$line" | sed 's/priority:[[:space:]]*//')
                ;;
            depends:*)
                current_depends=$(echo "$line" | sed 's/depends:[[:space:]]*//')
                ;;
        esac
    done < "$plan_file"

    # 保存最后一个任务
    if [ -n "$current_id" ]; then
        TASK_ROLES+=("$current_role")
        TASK_IDS+=("$current_id")
        TASK_DESCS+=("$current_desc")
        TASK_PRIORITIES+=("${current_priority:-P2_medium}")
        TASK_DEPENDS+=("${current_depends:-none}")
    fi
}

# 等待任务完成
wait_for_task() {
    local task_id="$1"
    local max_wait=600  # 最多等 10 分钟
    local elapsed=0

    while [ $elapsed -lt $max_wait ]; do
        if [ -f "$TEAM_DIR/tasks/review/${task_id}.md" ] || \
           [ -f "$TEAM_DIR/tasks/done/${task_id}.md" ]; then
            return 0
        fi
        if [ -f "$TEAM_DIR/tasks/failed/${task_id}.md" ]; then
            return 1
        fi
        sleep 5
        elapsed=$((elapsed + 5))
    done
    return 2  # 超时
}

# 检查依赖是否完成
check_depends() {
    local depends="$1"
    if [ "$depends" = "none" ]; then
        return 0
    fi

    IFS=',' read -ra DEP_IDS <<< "$depends"
    for dep in "${DEP_IDS[@]}"; do
        if [ ! -f "$TEAM_DIR/tasks/review/${dep}.md" ] && \
           [ ! -f "$TEAM_DIR/tasks/done/${dep}.md" ]; then
            return 1
        fi
    done
    return 0
}

case "$MODE" in
    parallel)
        parse_plan "$ARG"
        echo "=== 并行编排: $PLAN_ID ==="
        echo "任务数: ${#TASK_IDS[@]}"
        echo ""

        PIDS=()
        for i in "${!TASK_IDS[@]}"; do
            echo "启动: [${TASK_ROLES[$i]}] ${TASK_IDS[$i]} - ${TASK_DESCS[$i]}"
            "$DISPATCH" "${TASK_ROLES[$i]}" "${TASK_IDS[$i]}" "${TASK_DESCS[$i]}" "${TASK_PRIORITIES[$i]}" --bg
            PIDS+=($!)
        done

        echo ""
        echo "所有任务已后台启动"
        echo "查看状态: $TEAM_DIR/dashboard.sh"
        ;;

    pipeline)
        parse_plan "$ARG"
        echo "=== 流水线编排: $PLAN_ID ==="
        echo "任务数: ${#TASK_IDS[@]}"
        echo ""

        # 按依赖关系分层执行
        COMPLETED=()

        while [ ${#COMPLETED[@]} -lt ${#TASK_IDS[@]} ]; do
            LAUNCHED_THIS_ROUND=false

            for i in "${!TASK_IDS[@]}"; do
                task_id="${TASK_IDS[$i]}"

                # 跳过已完成的
                if [[ " ${COMPLETED[*]} " =~ " $task_id " ]]; then
                    continue
                fi

                # 跳过正在执行的
                if [ -f "$TEAM_DIR/tasks/active/${task_id}.md" ]; then
                    continue
                fi

                # 检查依赖
                if check_depends "${TASK_DEPENDS[$i]}"; then
                    echo "[$(date '+%H:%M:%S')] 启动: [${TASK_ROLES[$i]}] $task_id"
                    "$DISPATCH" "${TASK_ROLES[$i]}" "$task_id" "${TASK_DESCS[$i]}" "${TASK_PRIORITIES[$i]}" --bg
                    LAUNCHED_THIS_ROUND=true
                fi
            done

            # 等待一轮，检查完成情况
            sleep 10

            # 更新完成列表
            for i in "${!TASK_IDS[@]}"; do
                task_id="${TASK_IDS[$i]}"
                if [[ " ${COMPLETED[*]} " =~ " $task_id " ]]; then
                    continue
                fi
                if [ -f "$TEAM_DIR/tasks/review/${task_id}.md" ] || \
                   [ -f "$TEAM_DIR/tasks/done/${task_id}.md" ]; then
                    COMPLETED+=("$task_id")
                    echo "[$(date '+%H:%M:%S')] 完成: $task_id"
                fi
                if [ -f "$TEAM_DIR/tasks/failed/${task_id}.md" ]; then
                    COMPLETED+=("$task_id")
                    echo "[$(date '+%H:%M:%S')] 失败: $task_id"
                fi
            done
        done

        echo ""
        echo "=== 流水线完成 ==="
        ;;

    status)
        PLAN_ID="$ARG"
        echo "=== 编排状态: $PLAN_ID ==="
        "$TEAM_DIR/dashboard.sh"
        ;;

    *)
        echo "未知模式: $MODE"
        echo "用法: orchestrate.sh <parallel|pipeline|status> <plan_file|plan_id>"
        exit 1
        ;;
esac
