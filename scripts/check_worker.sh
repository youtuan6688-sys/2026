#!/bin/bash
# check_worker.sh - 检查 Worker 状态
# 用法: ./check_worker.sh <task_id>  — 查看特定任务
#       ./check_worker.sh             — 列出所有任务

BASE_DIR="$HOME/Happycode2026/vault/agents"

if [ -z "$1" ]; then
    echo "=== Active Tasks ==="
    for f in "$BASE_DIR/tasks/"*.md 2>/dev/null; do
        [ -f "$f" ] || continue
        task_id=$(basename "$f" .md)
        if [ -f "$BASE_DIR/results/${task_id}.result.md" ]; then
            status="DONE"
        elif [ -f "$BASE_DIR/logs/${task_id}.log.md" ]; then
            status="RUNNING"
        else
            status="PENDING"
        fi
        echo "  [$status] $task_id"
    done
else
    TASK_ID="$1"
    echo "=== Task: $TASK_ID ==="

    if [ -f "$BASE_DIR/results/${TASK_ID}.result.md" ]; then
        echo "[STATUS: COMPLETED]"
        echo ""
        cat "$BASE_DIR/results/${TASK_ID}.result.md"
    elif [ -f "$BASE_DIR/logs/${TASK_ID}.log.md" ]; then
        echo "[STATUS: RUNNING]"
        echo ""
        echo "--- Latest Log ---"
        tail -20 "$BASE_DIR/logs/${TASK_ID}.log.md"
    else
        echo "[STATUS: NOT FOUND]"
    fi
fi
