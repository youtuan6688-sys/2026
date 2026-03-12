#!/bin/bash
# HappyCode2026 一键部署脚本
# 用法: ./scripts/full_deploy.sh
# 前提: macOS, Homebrew, Python 3.11+, Node.js 20+, Claude Code CLI

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="$PROJECT_DIR/.venv/bin/python"
AGENTS_DIR="$HOME/Library/LaunchAgents"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
fail() { echo -e "${RED}[✗]${NC} $1"; exit 1; }

echo ""
echo "=========================================="
echo "  HappyCode2026 一键部署"
echo "=========================================="
echo ""

# ============================================
# Step 1: 环境检查
# ============================================
echo "--- Step 1: 环境检查 ---"

command -v python3 >/dev/null || fail "Python3 未安装"
PYVER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
log "Python $PYVER"

command -v node >/dev/null || fail "Node.js 未安装"
log "Node.js $(node --version)"

command -v brew >/dev/null || fail "Homebrew 未安装"
log "Homebrew OK"

command -v claude >/dev/null || warn "Claude Code CLI 未安装 — 请运行: npm install -g @anthropic-ai/claude-code"
[ -f "$PROJECT_DIR/.env" ] || warn ".env 文件不存在 — 稍后需要手动创建"

# ============================================
# Step 2: 系统工具
# ============================================
echo ""
echo "--- Step 2: 安装系统工具 ---"

for tool in ffmpeg jq pandoc wget htop tmux; do
    if command -v "$tool" >/dev/null 2>&1; then
        log "$tool 已安装"
    else
        brew install "$tool"
        log "$tool 安装完成"
    fi
done

# ============================================
# Step 3: Python 虚拟环境
# ============================================
echo ""
echo "--- Step 3: Python 虚拟环境 ---"

if [ ! -d "$PROJECT_DIR/.venv" ]; then
    python3 -m venv "$PROJECT_DIR/.venv"
    log "虚拟环境创建完成"
else
    log "虚拟环境已存在"
fi

source "$PROJECT_DIR/.venv/bin/activate"

pip install --quiet -e "$PROJECT_DIR"
pip install --quiet yt-dlp google-generativeai
log "Python 依赖安装完成"

# Install playwright browsers (non-fatal)
"$PYTHON" -m playwright install chromium 2>/dev/null && log "Playwright 浏览器安装完成" || warn "Playwright 安装跳过（可后续手动安装）"

# ============================================
# Step 4: 创建目录结构
# ============================================
echo ""
echo "--- Step 4: 创建目录结构 ---"

dirs=(
    vault/memory vault/articles vault/social vault/docs
    vault/checkpoints vault/logs vault/agents vault/tasks
    vault/memory/contacts vault/memory/groups
    data/chromadb data/daily_buffer data/group_reports
    data/hot_briefings data/video_raw data/video_breakdowns data/video_trending
    logs
    daily-briefing/reports daily-briefing/logs
    projects/viral-video-analyzer/src
)

for d in "${dirs[@]}"; do
    mkdir -p "$PROJECT_DIR/$d"
done
log "目录结构创建完成 (${#dirs[@]} 个目录)"

# ============================================
# Step 5: 初始化记忆文件（仅在不存在时）
# ============================================
echo ""
echo "--- Step 5: 初始化记忆文件 ---"

init_file() {
    local filepath="$1"
    local content="$2"
    if [ ! -f "$filepath" ]; then
        echo "$content" > "$filepath"
        log "创建 $(basename "$filepath")"
    else
        log "$(basename "$filepath") 已存在，跳过"
    fi
}

init_file "$PROJECT_DIR/vault/memory/profile.md" "# User Profile
## 身份
(请填写你的身份信息)

## 工作风格
- 核心原则：AI 主动进化，用户按需调用"

init_file "$PROJECT_DIR/vault/memory/tools.md" "# Tools & Setup
## Active Services
- Feishu Bot: 24/7 WebSocket listener
- Daily Briefing: cron 3pm PST"

init_file "$PROJECT_DIR/vault/memory/decisions.md" "# Key Decisions"
init_file "$PROJECT_DIR/vault/memory/learnings.md" "# Learnings"
init_file "$PROJECT_DIR/vault/memory/briefing-digest.md" "# Briefing Digest"
init_file "$PROJECT_DIR/vault/memory/patterns.md" "# Patterns"

# ============================================
# Step 6: .env 模板
# ============================================
echo ""
echo "--- Step 6: 环境变量 ---"

if [ ! -f "$PROJECT_DIR/.env" ]; then
    if [ -f "$PROJECT_DIR/.env.example" ]; then
        cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
        # Replace vault path placeholder with actual path
        sed -i '' "s|/Users/YOUR_USERNAME/Happycode2026/vault|$PROJECT_DIR/vault|" "$PROJECT_DIR/.env"
        warn ".env 已从 .env.example 复制 — 请编辑填入你的 API Keys!"
    else
        fail ".env.example 不存在，请检查项目是否完整"
    fi
else
    log ".env 已存在"
fi

# ============================================
# Step 7: Claude Code 配置
# ============================================
echo ""
echo "--- Step 7: Claude Code 配置 ---"

mkdir -p ~/.claude/rules/common

if [ ! -f ~/.claude/CLAUDE.md ]; then
    cat > ~/.claude/CLAUDE.md << 'CLAUDEEOF'
# Global Claude Code Config

## Identity
你是用户的个人 AI 助手，运行在 Mac 上。你通过飞书 bot 接收指令，也通过 cron 执行定时任务。你有长期记忆，能自我进化。

## Memory System
长期记忆存在 Obsidian vault 里。每次任务开始前，先读取相关记忆文件：
- ~/Happycode2026/vault/memory/profile.md
- ~/Happycode2026/vault/memory/tools.md
- ~/Happycode2026/vault/memory/decisions.md
- ~/Happycode2026/vault/memory/learnings.md
- ~/Happycode2026/vault/memory/briefing-digest.md

## Self-Evolution
- 学到新知识时，主动更新 vault/memory/
- 同一类操作重复 3 次以上时，封装成 Skill
- 记忆文件超过 5KB 时，压缩旧条目

## Rules
- 用中文沟通，除非被要求用英文
- 直接、简洁，跳过不必要的解释
- 优先编辑现有文件，不要创建多余文件
CLAUDEEOF
    log "~/.claude/CLAUDE.md 创建完成"
else
    log "~/.claude/CLAUDE.md 已存在"
fi

if [ ! -f ~/.claude/settings.json ]; then
    cat > ~/.claude/settings.json << 'SETTINGSEOF'
{
  "permissions": {
    "deny": ["Bash(rm -rf /*)", "Bash(rm -rf ~/)"],
    "defaultMode": "allowEdits"
  },
  "hasTrustDialogAccepted": true
}
SETTINGSEOF
    log "~/.claude/settings.json 创建完成（安全模式: allowEdits）"
else
    log "~/.claude/settings.json 已存在"
fi

# ============================================
# Step 8: 安装 launchd 服务
# ============================================
echo ""
echo "--- Step 8: 安装 launchd 服务 ---"

mkdir -p "$AGENTS_DIR"

install_plist() {
    local name="$1"
    local hour="$3"
    local minute="$4"
    local keep_alive="${5:-false}"
    local logbase="${6:-$PROJECT_DIR/logs/$name}"
    local plist_path="$AGENTS_DIR/com.happycode.${name}.plist"

    # Build ProgramArguments array from remaining positional args in $2
    # $2 is a space-separated list of program arguments
    local prog_args=""
    for arg in $2; do
        prog_args="${prog_args}
        <string>${arg}</string>"
    done

    if [ "$keep_alive" = "true" ]; then
        cat > "$plist_path" << PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.happycode.${name}</string>
    <key>ProgramArguments</key>
    <array>${prog_args}
    </array>
    <key>WorkingDirectory</key><string>$PROJECT_DIR</string>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>StandardOutPath</key><string>${logbase}.log</string>
    <key>StandardErrorPath</key><string>${logbase}.err</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key><string>$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
        <key>HOME</key><string>$HOME</string>
    </dict>
</dict>
</plist>
PLISTEOF
    else
        cat > "$plist_path" << PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.happycode.${name}</string>
    <key>ProgramArguments</key>
    <array>${prog_args}
    </array>
    <key>WorkingDirectory</key><string>$PROJECT_DIR</string>
    <key>StartCalendarInterval</key>
    <dict><key>Hour</key><integer>${hour}</integer><key>Minute</key><integer>${minute}</integer></dict>
    <key>StandardOutPath</key><string>${logbase}.log</string>
    <key>StandardErrorPath</key><string>${logbase}.err</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key><string>$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
        <key>HOME</key><string>$HOME</string>
    </dict>
</dict>
</plist>
PLISTEOF
    fi

    launchctl unload "$plist_path" 2>/dev/null || true
    launchctl load "$plist_path"
    log "服务 com.happycode.${name} 已安装"
}

# 主服务 (keep-alive)
install_plist "knowledge" \
    "$PYTHON -m src.main" \
    0 0 true "$PROJECT_DIR/logs/service"

# 定时任务
install_plist "daily-briefing" \
    "$PROJECT_DIR/daily-briefing/run_briefing.sh" \
    15 0 false "$PROJECT_DIR/daily-briefing/logs/briefing-launchd"

install_plist "nightly-review" \
    "/bin/bash $PROJECT_DIR/daily-briefing/run_nightly_review.sh" \
    23 0

install_plist "daily-evolution" \
    "/bin/bash $PROJECT_DIR/scripts/run_daily_evolution.sh" \
    16 0

install_plist "group-summary" \
    "/bin/bash $PROJECT_DIR/scripts/run_group_report.sh" \
    6 0

install_plist "hot-briefing" \
    "$PYTHON $PROJECT_DIR/src/daily_hot_briefing.py" \
    14 30

install_plist "weekly-synthesis" \
    "$PYTHON $PROJECT_DIR/scripts/weekly_synthesis.py" \
    23 3

install_plist "video-crawl" \
    "/bin/bash $PROJECT_DIR/scripts/daily_video_crawl.sh" \
    13 0

log "所有 launchd 服务安装完成"

# ============================================
# Step 9: 健康检查
# ============================================
echo ""
echo "--- Step 9: 健康检查 ---"

# Check .env has real keys
if grep -q "xxxxxxxxxxxx\|your_.*_here" "$PROJECT_DIR/.env" 2>/dev/null; then
    warn "⚠️  .env 中仍有占位符 — 请编辑 $PROJECT_DIR/.env 填入真实 API Keys"
fi

# Check service running
if launchctl list 2>/dev/null | grep -q "happycode.knowledge"; then
    log "主服务 (knowledge) 运行中"
else
    warn "主服务未启动 — 可能需要先填写 .env"
fi

# Check vault
VAULT_FILES=$(find "$PROJECT_DIR/vault/memory" -name "*.md" 2>/dev/null | wc -l | tr -d ' ')
log "记忆文件: ${VAULT_FILES} 个"

echo ""
echo "=========================================="
echo "  部署完成！"
echo "=========================================="
echo ""
echo "下一步："
echo "  1. 编辑 .env 填入 API Keys:  nano $PROJECT_DIR/.env"
echo "  2. 编辑用户档案:             nano $PROJECT_DIR/vault/memory/profile.md"
echo "  3. 重启主服务:               launchctl unload ~/Library/LaunchAgents/com.happycode.knowledge.plist && launchctl load ~/Library/LaunchAgents/com.happycode.knowledge.plist"
echo "  4. 查看日志:                 tail -f $PROJECT_DIR/logs/service.log"
echo ""
echo "有用的命令："
echo "  查看所有服务:  launchctl list | grep happycode"
echo "  停止所有服务:  for p in ~/Library/LaunchAgents/com.happycode.*.plist; do launchctl unload \"\$p\"; done"
echo "  手动测试 bot:  cd $PROJECT_DIR && source .venv/bin/activate && python -m src.main"
echo ""
