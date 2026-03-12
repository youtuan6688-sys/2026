#!/bin/bash
# Weekly Prompt Learning Task
# Runs every Monday at 2am PST (6pm Beijing Monday)
# Fetches latest prompts from awesome-nano-banana-pro-prompts
# and updates local template library

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$PROJECT_DIR/logs"
LOG_FILE="$LOG_DIR/weekly_prompt_learning_$(date +%Y%m%d).log"

mkdir -p "$LOG_DIR"

# Source environment
source ~/.zshrc 2>/dev/null || true
[ -f "$PROJECT_DIR/.env" ] && source "$PROJECT_DIR/.env"

exec > >(tee -a "$LOG_FILE") 2>&1
echo "=== Weekly Prompt Learning: $(date) ==="

# Activate venv
source "$PROJECT_DIR/.venv/bin/activate" 2>/dev/null || true

# Run Claude to analyze and update prompts
claude --print -p "
你是 Happycode2026 的 prompt 进化系统。执行以下任务：

1. **搜索最新 prompt 技巧**：
   - 搜索 GitHub awesome-nano-banana-pro-prompts 仓库的最新更新
   - 搜索 X/Twitter 上关于 Gemini image generation 的高赞教程
   - 搜索小红书/知乎上的 Gemini 出图技巧分享

2. **分析并提取**：
   - 提取新发现的 prompt 模式、风格关键词、构图技巧
   - 与现有模板库 devices/oppo-PDYM20/config/image_style.py 对比

3. **更新模板库**：
   - 如果发现高质量的新场景模板，添加到 SCENE_TEMPLATES
   - 如果发现更好的风格描述词，更新 STYLE_BASES
   - 保持向后兼容，不删除现有模板

4. **记录学习成果**：
   - 更新 vault/memory/tools.md 中的出图相关条目
   - 生成简短的学习报告

注意：只更新确实有价值的内容，不要为了更新而更新。
" 2>&1

echo "=== Done: $(date) ==="
