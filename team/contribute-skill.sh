#!/bin/bash
# contribute-skill.sh - Worker 贡献新技能到共享技能库
# 用法: ./contribute-skill.sh <skill_name> <skill_file>
#
# 示例:
#   ./contribute-skill.sh api-pagination /tmp/pagination-pattern.md
#   ./contribute-skill.sh error-retry team/roles/backend/workspace/retry-pattern.md
#
# Worker 在任务中发现可复用模式时，用此脚本提交到共享技能库。
# CEO 可通过 review 决定是否保留。

set -euo pipefail

SKILL_NAME="${1:?用法: contribute-skill.sh <skill_name> <skill_file>}"
SKILL_FILE="${2:?请提供技能文件路径}"

SKILLS_DIR="$HOME/Happycode2026/team/shared/skills"
PENDING_DIR="$HOME/Happycode2026/team/shared/skills/pending"
TARGET="$SKILLS_DIR/${SKILL_NAME}.md"
PENDING_TARGET="$PENDING_DIR/${SKILL_NAME}.md"

# 验证源文件存在
if [ ! -f "$SKILL_FILE" ]; then
    echo "错误: 文件不存在: $SKILL_FILE"
    exit 1
fi

# 检查是否已存在同名技能
if [ -f "$TARGET" ]; then
    echo "警告: 技能 '$SKILL_NAME' 已存在于 $SKILLS_DIR/"
    echo "放入 pending/ 目录等待 CEO 审核是否合并"
fi

# 创建 pending 目录
mkdir -p "$PENDING_DIR"

# 添加元信息头
{
    echo "# 共享技能: ${SKILL_NAME}"
    echo ""
    echo "<!-- contributed: $(date '+%Y-%m-%d %H:%M:%S') -->"
    echo "<!-- status: pending_review -->"
    echo ""
    cat "$SKILL_FILE"
} > "$PENDING_TARGET"

echo "技能已提交: $PENDING_TARGET"
echo "等待 CEO 审核后移入 $SKILLS_DIR/"
echo ""
echo "CEO 审核命令:"
echo "  通过: mv '$PENDING_TARGET' '$TARGET'"
echo "  拒绝: rm '$PENDING_TARGET'"
