# HappyCode2026 一键部署指南

> **给 AI 的说明**：这份文档让你能在一台全新 Mac 上完整复刻 HappyCode2026 系统——一个基于飞书 Bot + Claude Code + Obsidian 的自进化 AI 助手。按顺序执行即可。

---

## 系统概述

```
┌─────────────────────────────────────────────────────┐
│                   HappyCode2026                      │
│                                                      │
│  飞书 Bot (24/7)          每日简报 (cron 3pm PST)     │
│  ├── 消息路由              ├── Web 搜索              │
│  ├── URL → 知识库          ├── AI 分析               │
│  ├── 文件分析              ├── 飞书推送              │
│  ├── /image 出图           └── 记忆沉淀              │
│  ├── /music 音乐                                     │
│  ├── /ecom 电商            定时任务 (12个 launchd)    │
│  └── /video 视频分析       ├── 每日进化              │
│                            ├── 群日报                │
│  知识库 (Obsidian vault)   ├── 热搜简报              │
│  ├── 文章/社交/文档        ├── 视频爬取              │
│  ├── ChromaDB 向量库       └── 每周综合              │
│  └── SQLite 索引                                     │
│                                                      │
│  长期记忆 (vault/memory/)                            │
│  ├── profile.md  用户画像                            │
│  ├── tools.md    工具清单                            │
│  ├── decisions.md 决策记录                           │
│  ├── learnings.md 经验积累                           │
│  └── patterns.md  模式识别                           │
└─────────────────────────────────────────────────────┘
```

---

## 前提条件

| 条件 | 要求 |
|------|------|
| 操作系统 | macOS 13+ (launchd 定时任务依赖 macOS) |
| Python | 3.11+ |
| Node.js | 20+ (MCP server 依赖) |
| Homebrew | 已安装 |
| Claude Code | 已安装 (`npm install -g @anthropic-ai/claude-code`) |
| Claude Max 订阅 | 用于 `claude -p` 命令行调用 |

---

## 第 1 步：克隆项目

```bash
cd ~
git clone https://github.com/YOUR_USERNAME/Happycode2026.git
cd Happycode2026
```

---

## 第 2 步：创建 Python 虚拟环境 & 安装依赖

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e .

# 额外运行时依赖
pip install yt-dlp faster-whisper google-generativeai

# Playwright 浏览器
playwright install chromium
```

---

## 第 3 步：安装系统工具

```bash
brew install ffmpeg jq pandoc wget htop tmux scrcpy
```

---

## 第 4 步：配置环境变量

复制模板并填入你的密钥：

```bash
cp .env.example .env
```

编辑 `.env`，填入以下内容：

```env
# ===== 飞书 App =====
# 在 https://open.feishu.cn 创建企业自建应用
# 需要权限：im:message, im:chat, docx:document, bitable:app, sheets:spreadsheet, contact:user.id
FEISHU_APP_ID=cli_xxxxxxxxxxxx
FEISHU_APP_SECRET=your_feishu_app_secret_here
FEISHU_ENCRYPT_KEY=
FEISHU_VERIFICATION_TOKEN=
FEISHU_USER_OPEN_ID=ou_xxxxxxxxxxxx

# ===== AI API (Deepseek，OpenAI 兼容格式) =====
# https://platform.deepseek.com 注册获取
AI_API_KEY=sk-your_deepseek_api_key_here
AI_BASE_URL=https://api.deepseek.com
AI_MODEL=deepseek-chat

# ===== Gemini API =====
# https://aistudio.google.com/apikey 获取
GEMINI_API_KEY=AIzaSyXXXXXXXXXXXXXXXXXXXXXXXXXXXXX

# ===== Brave Search API =====
# https://brave.com/search/api/ 获取免费 tier
BRAVE_API_KEY=BSAxxxxxxxxxxxxxxxxxxxxxxxxx

# ===== 路径（一般不需要改） =====
VAULT_PATH=/Users/YOUR_USERNAME/Happycode2026/vault
LOG_LEVEL=INFO
```

> **⚠️ 安全提醒**：`.env` 已在 `.gitignore` 中，永远不要提交到 Git。

---

## 第 5 步：初始化数据目录

```bash
# 创建所有必要目录
mkdir -p vault/{memory,articles,social,docs,checkpoints,logs,agents,tasks}
mkdir -p vault/memory/{contacts,groups}
mkdir -p data/{chromadb,daily_buffer,group_reports,hot_briefings,video_raw,video_breakdowns,video_trending}
mkdir -p logs
mkdir -p daily-briefing/{reports,logs}
mkdir -p projects/viral-video-analyzer/{config,prompts,src,data/{raw,analyzed,reports},logs,tests,docs}
```

---

## 第 6 步：初始化记忆文件

这些文件定义了 AI 助手的「人格」和运行上下文。根据你的需求修改内容。

### vault/memory/profile.md
```bash
cat > vault/memory/profile.md << 'PROFILE'
# User Profile

## 身份
- 昵称：[你的昵称]
- 角色：[你的职业/角色]
- 审美偏好：[你的风格偏好]
- 内容方向：[你关注的领域]
- 平台：[你活跃的平台]

## 工作风格
- 核心原则：AI 主动进化，用户按需调用（不要反复提问，主动准备）
- 沟通：中文为主，直接简洁
- 偏好：先做再问，结果导向
PROFILE
```

### vault/memory/tools.md
```bash
cat > vault/memory/tools.md << 'TOOLS'
# Tools & Setup

## Active Services
- Feishu Bot: running on Mac, 24/7 WebSocket listener
- Daily Briefing: cron 3pm PST, web search + AI analysis + Feishu notify
- Knowledge Base: Obsidian vault + ChromaDB vector store

## MCP Servers
- filesystem, sequential-thinking, memory, happycode-knowledge
- context7, chrome-devtools, brave-search, github, lark-mcp

## CLI Tools
- claude (Claude Code CLI)
- yt-dlp, ffmpeg, pandoc, jq, tmux, scrcpy

## Self-Evolution Rules
- 学到新知识 → 更新 vault/memory/ 对应文件
- 同一操作重复 3 次 → 封装成 Skill
- 记忆文件 > 5KB → 压缩旧条目
- 每日简报后 → 提取要点到 briefing-digest.md
TOOLS
```

### vault/memory/decisions.md & learnings.md
```bash
cat > vault/memory/decisions.md << 'EOF'
# Key Decisions
(初始化为空，系统运行后自动积累)
EOF

cat > vault/memory/learnings.md << 'EOF'
# Learnings
(初始化为空，系统运行后自动积累)
EOF

cat > vault/memory/briefing-digest.md << 'EOF'
# Briefing Digest
(每日简报后自动追加)
EOF

cat > vault/memory/patterns.md << 'EOF'
# Patterns
(系统运行后自动识别和记录)
EOF
```

---

## 第 7 步：配置 Claude Code

### 7a. 全局 CLAUDE.md

```bash
mkdir -p ~/.claude
cat > ~/.claude/CLAUDE.md << 'CLAUDEMD'
# Global Claude Code Config

## Identity
你是用户的个人 AI 助手，运行在 Mac 上。你通过飞书 bot 接收指令，也通过 cron 执行定时任务。你有长期记忆，能自我进化。

## Memory System
长期记忆存在 Obsidian vault 里。每次任务开始前，先读取相关记忆文件：
- ~/Happycode2026/vault/memory/profile.md — 用户身份、偏好、工作风格
- ~/Happycode2026/vault/memory/tools.md — 当前工具、服务、定时任务
- ~/Happycode2026/vault/memory/decisions.md — 关键决策记录
- ~/Happycode2026/vault/memory/learnings.md — 经验和技巧
- ~/Happycode2026/vault/memory/briefing-digest.md — 每日简报要点

## Self-Evolution
- 学到新知识时，主动更新 vault/memory/ 里的对应文件
- 发现新工具/Skill/MCP，评估后建议安装，记录到 tools.md
- 同一类操作重复 3 次以上时，考虑封装成 Claude Code Skill
- 记忆文件超过 5KB 时，主动压缩旧条目

## Rules
- 用中文沟通，除非被要求用英文
- 直接、简洁，跳过不必要的解释
- 优先编辑现有文件，不要创建多余文件
- 不要猜测，不确定就问

## Scheduled Tasks
- 每日简报 (7am Beijing = 3pm PST): 搜索生态更新，生成报告，发飞书
- 飞书 bot (24/7): 响应用户消息——执行任务、保存记忆、知识库问答、URL 解析

## Project: Happycode2026
- Path: ~/Happycode2026
- Python 3.11 venv at .venv/
- Config in .env, settings in config/settings.py
- Bot code: src/ (main.py, message_router.py, feishu_listener.py, feishu_sender.py)
- Briefing: daily-briefing/ (run_briefing.sh, prompts/briefing.md)
- Knowledge base: vault/ (articles/, social/, memory/)
CLAUDEMD
```

### 7b. Claude Code settings

```bash
cat > ~/.claude/settings.json << 'SETTINGS'
{
  "permissions": {
    "deny": [
      "Bash(rm -rf /*)",
      "Bash(rm -rf ~/)"
    ],
    "defaultMode": "bypassPermissions"
  },
  "hasTrustDialogAccepted": true,
  "skipDangerousModePermissionPrompt": true
}
SETTINGS
```

### 7c. Claude Code 规则文件

```bash
mkdir -p ~/.claude/rules/common

# AI 编码纪律
cat > ~/.claude/rules/common/ai-coding-discipline.md << 'EOF'
# AI Coding Discipline
## 1. Describe Before Coding — 先描述方案再动手
## 2. Clarify Ambiguous Requirements — 不确定就问
## 3. Edge Cases After Implementation — 完成后列出边界情况
## 4. Split Large Changes — 改 3+ 文件时先拆子任务
## 5. Reflect on Corrections — 被纠正时反思根因
EOF

# 编码风格
cat > ~/.claude/rules/common/coding-style.md << 'EOF'
# Coding Style
- ALWAYS create new objects, NEVER mutate existing ones (immutability)
- MANY SMALL FILES > FEW LARGE FILES (200-400 lines, 800 max)
- ALWAYS handle errors explicitly at every level
- ALWAYS validate at system boundaries
- Functions < 50 lines, Files < 800 lines, No deep nesting > 4 levels
EOF

# Git 工作流
cat > ~/.claude/rules/common/git-workflow.md << 'EOF'
# Git Workflow
Commit format: <type>: <description>
Types: feat, fix, refactor, docs, test, chore, perf, ci
EOF

# 安全
cat > ~/.claude/rules/common/security.md << 'EOF'
# Security
- NEVER hardcode secrets
- ALWAYS use env vars or secret manager
- Validate all user inputs
- Parameterized queries for SQL
- Sanitize HTML for XSS prevention
EOF
```

---

## 第 8 步：配置 MCP Servers

在项目根目录创建 `.mcp.json`（或通过 Claude Code UI 安装）：

```bash
cat > ~/Happycode2026/.mcp.json << 'MCP'
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@anthropic-ai/mcp-filesystem"],
      "env": {}
    },
    "sequential-thinking": {
      "command": "npx",
      "args": ["-y", "@anthropic-ai/mcp-sequential-thinking"],
      "env": {}
    },
    "memory": {
      "command": "npx",
      "args": ["-y", "@anthropic-ai/mcp-memory"],
      "env": {}
    },
    "brave-search": {
      "command": "npx",
      "args": ["-y", "@anthropic-ai/mcp-brave-search"],
      "env": {
        "BRAVE_API_KEY": "YOUR_BRAVE_API_KEY"
      }
    },
    "github": {
      "command": "npx",
      "args": ["-y", "@anthropic-ai/mcp-github"],
      "env": {
        "GITHUB_PERSONAL_ACCESS_TOKEN": "YOUR_GITHUB_TOKEN"
      }
    },
    "context7": {
      "command": "npx",
      "args": ["-y", "@anthropic-ai/mcp-context7"],
      "env": {}
    },
    "lark-mcp": {
      "command": "npx",
      "args": ["-y", "lark-mcp"],
      "env": {
        "FEISHU_APP_ID": "YOUR_FEISHU_APP_ID",
        "FEISHU_APP_SECRET": "YOUR_FEISHU_APP_SECRET"
      }
    },
    "happycode-knowledge": {
      "command": "python",
      "args": ["-m", "src.mcp_server"],
      "cwd": "/Users/YOUR_USERNAME/Happycode2026",
      "env": {}
    }
  }
}
MCP
```

> **注意**：MCP 中的 API KEY 占位符需要替换成你 `.env` 中对应的值。

---

## 第 9 步：安装 launchd 定时服务

以下脚本会安装所有 12 个定时任务。将 `YOUR_USERNAME` 替换为你的 macOS 用户名。

```bash
PROJECT_DIR="$HOME/Happycode2026"
AGENTS_DIR="$HOME/Library/LaunchAgents"
PYTHON="$PROJECT_DIR/.venv/bin/python"
CLAUDE="$HOME/.local/bin/claude"

mkdir -p "$AGENTS_DIR"

# --- 1. 主服务：飞书 Bot (24/7 keep-alive) ---
cat > "$AGENTS_DIR/com.happycode.knowledge.plist" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.happycode.knowledge</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON</string><string>-m</string><string>src.main</string>
    </array>
    <key>WorkingDirectory</key><string>$PROJECT_DIR</string>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>StandardOutPath</key><string>$PROJECT_DIR/logs/service.log</string>
    <key>StandardErrorPath</key><string>$PROJECT_DIR/logs/service.err</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
EOF

# --- 2. 每日简报 (3pm PST = 7am 北京) ---
cat > "$AGENTS_DIR/com.happycode.daily-briefing.plist" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.happycode.daily-briefing</string>
    <key>ProgramArguments</key>
    <array><string>$PROJECT_DIR/daily-briefing/run_briefing.sh</string></array>
    <key>WorkingDirectory</key><string>$PROJECT_DIR</string>
    <key>StartCalendarInterval</key>
    <dict><key>Hour</key><integer>15</integer><key>Minute</key><integer>0</integer></dict>
    <key>StandardOutPath</key><string>$PROJECT_DIR/daily-briefing/logs/briefing-launchd.log</string>
    <key>StandardErrorPath</key><string>$PROJECT_DIR/daily-briefing/logs/briefing-launchd.err</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key><string>$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
        <key>HOME</key><string>$HOME</string>
    </dict>
</dict>
</plist>
EOF

# --- 3. 每日进化 ---
cat > "$AGENTS_DIR/com.happycode.daily-evolution.plist" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.happycode.daily-evolution</string>
    <key>ProgramArguments</key>
    <array><string>/bin/bash</string><string>$PROJECT_DIR/scripts/run_daily_evolution.sh</string></array>
    <key>WorkingDirectory</key><string>$PROJECT_DIR</string>
    <key>StartCalendarInterval</key>
    <dict><key>Hour</key><integer>16</integer><key>Minute</key><integer>0</integer></dict>
    <key>StandardOutPath</key><string>$PROJECT_DIR/logs/daily_evolution.log</string>
    <key>StandardErrorPath</key><string>$PROJECT_DIR/logs/daily_evolution.err</string>
    <key>EnvironmentVariables</key>
    <dict><key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string></dict>
</dict>
</plist>
EOF

# --- 4. 夜间审查 (11pm PST) ---
cat > "$AGENTS_DIR/com.happycode.nightly-review.plist" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.happycode.nightly-review</string>
    <key>ProgramArguments</key>
    <array><string>/bin/bash</string><string>$PROJECT_DIR/daily-briefing/run_nightly_review.sh</string></array>
    <key>WorkingDirectory</key><string>$PROJECT_DIR</string>
    <key>StartCalendarInterval</key>
    <dict><key>Hour</key><integer>23</integer><key>Minute</key><integer>0</integer></dict>
    <key>StandardOutPath</key><string>$PROJECT_DIR/logs/nightly_review.log</string>
    <key>StandardErrorPath</key><string>$PROJECT_DIR/logs/nightly_review.err</string>
    <key>EnvironmentVariables</key>
    <dict><key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string></dict>
</dict>
</plist>
EOF

# --- 5. 群日报 (6am PST = 10pm 北京) ---
cat > "$AGENTS_DIR/com.happycode.group-summary.plist" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.happycode.group-summary</string>
    <key>ProgramArguments</key>
    <array><string>/bin/bash</string><string>$PROJECT_DIR/scripts/run_group_report.sh</string></array>
    <key>WorkingDirectory</key><string>$PROJECT_DIR</string>
    <key>StartCalendarInterval</key>
    <dict><key>Hour</key><integer>6</integer><key>Minute</key><integer>0</integer></dict>
    <key>StandardOutPath</key><string>$PROJECT_DIR/logs/group_report.log</string>
    <key>StandardErrorPath</key><string>$PROJECT_DIR/logs/group_report.err</string>
    <key>EnvironmentVariables</key>
    <dict><key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string></dict>
</dict>
</plist>
EOF

# --- 6. 热搜简报 ---
cat > "$AGENTS_DIR/com.happycode.hot-briefing.plist" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.happycode.hot-briefing</string>
    <key>ProgramArguments</key>
    <array><string>$PYTHON</string><string>$PROJECT_DIR/src/daily_hot_briefing.py</string></array>
    <key>WorkingDirectory</key><string>$PROJECT_DIR</string>
    <key>StartCalendarInterval</key>
    <dict><key>Hour</key><integer>14</integer><key>Minute</key><integer>30</integer></dict>
    <key>StandardOutPath</key><string>$PROJECT_DIR/logs/hot_briefing.log</string>
    <key>StandardErrorPath</key><string>$PROJECT_DIR/logs/hot_briefing.err</string>
    <key>EnvironmentVariables</key>
    <dict><key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string></dict>
</dict>
</plist>
EOF

# --- 7. 每周综合 (周日 11:03pm) ---
cat > "$AGENTS_DIR/com.happycode.weekly-synthesis.plist" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.happycode.weekly-synthesis</string>
    <key>ProgramArguments</key>
    <array><string>$PYTHON</string><string>$PROJECT_DIR/scripts/weekly_synthesis.py</string></array>
    <key>WorkingDirectory</key><string>$PROJECT_DIR</string>
    <key>StartCalendarInterval</key>
    <dict><key>Weekday</key><integer>0</integer><key>Hour</key><integer>23</integer><key>Minute</key><integer>3</integer></dict>
    <key>StandardOutPath</key><string>$PROJECT_DIR/logs/weekly_synthesis.log</string>
    <key>StandardErrorPath</key><string>$PROJECT_DIR/logs/weekly_synthesis.err</string>
    <key>EnvironmentVariables</key>
    <dict><key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string></dict>
</dict>
</plist>
EOF

# --- 8. 视频爬取 ---
cat > "$AGENTS_DIR/com.happycode.video-crawl.plist" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.happycode.video-crawl</string>
    <key>ProgramArguments</key>
    <array><string>/bin/bash</string><string>$PROJECT_DIR/scripts/daily_video_crawl.sh</string></array>
    <key>WorkingDirectory</key><string>$PROJECT_DIR</string>
    <key>StartCalendarInterval</key>
    <dict><key>Hour</key><integer>13</integer><key>Minute</key><integer>0</integer></dict>
    <key>StandardOutPath</key><string>$PROJECT_DIR/logs/video_crawl.log</string>
    <key>StandardErrorPath</key><string>$PROJECT_DIR/logs/video_crawl.err</string>
    <key>EnvironmentVariables</key>
    <dict><key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string></dict>
</dict>
</plist>
EOF

# --- 9-12. 其他服务（task-scheduler, task-runner, instreet-patrol, weekly-prompt-learning）---
for svc in task-scheduler task-runner instreet-patrol weekly-prompt-learning; do
cat > "$AGENTS_DIR/com.happycode.${svc}.plist" << INNER
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.happycode.${svc}</string>
    <key>ProgramArguments</key>
    <array><string>$PYTHON</string><string>$PROJECT_DIR/scripts/${svc//-/_}.py</string></array>
    <key>WorkingDirectory</key><string>$PROJECT_DIR</string>
    <key>StartCalendarInterval</key>
    <dict><key>Hour</key><integer>14</integer><key>Minute</key><integer>0</integer></dict>
    <key>StandardOutPath</key><string>$PROJECT_DIR/logs/${svc}.log</string>
    <key>StandardErrorPath</key><string>$PROJECT_DIR/logs/${svc}.err</string>
    <key>EnvironmentVariables</key>
    <dict><key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string></dict>
</dict>
</plist>
INNER
done

# 加载所有服务
for plist in "$AGENTS_DIR"/com.happycode.*.plist; do
    launchctl unload "$plist" 2>/dev/null
    launchctl load "$plist"
    echo "Loaded: $(basename "$plist")"
done

echo "✅ All 12 launchd services installed!"
```

---

## 第 10 步：验证安装

```bash
# 检查服务状态
launchctl list | grep happycode

# 检查 bot 日志
tail -f ~/Happycode2026/logs/service.log

# 手动测试 bot
source .venv/bin/activate
python -m src.main  # 应该看到 "Feishu listener started"

# 手动测试简报
./daily-briefing/run_briefing.sh

# 检查知识库
python scripts/health_check.py
```

---

## 核心代码架构

```
src/
├── main.py                 # 入口：启动 feishu_listener
├── feishu_listener.py      # WebSocket 长连接监听飞书消息
├── message_router.py       # 消息路由（7 个 Mixin 组合）
│   ├── IntentMixin         # 意图分类（正则 + RAG）
│   ├── ContextMixin        # 上下文构建（历史 + 记忆）
│   ├── CommandsMixin       # 斜杠命令（/help, /status, /checkpoint...）
│   ├── SessionsMixin       # Tmux 会话管理
│   ├── DocsMixin           # 飞书文档处理
│   ├── FilesMixin          # 文件分析 + Excel
│   └── ClaudeMixin         # Claude API 调用
├── feishu_sender.py        # 飞书发消息（文本/卡片/图片/文件）
├── feishu_docs.py          # 飞书文档 API
├── feishu_bitable.py       # 飞书多维表格 API
├── feishu_sheets.py        # 飞书电子表格 API
├── brain.py                # AI 推理核心
├── quota_tracker.py        # API 配额管理
├── contact_memory.py       # 联系人数据库
├── ai/
│   ├── analyzer.py         # Claude/Deepseek 分析器
│   └── embeddings.py       # 向量嵌入（sentence-transformers）
├── storage/
│   ├── obsidian_writer.py  # 写入 Obsidian vault
│   ├── vector_store.py     # ChromaDB 向量库
│   └── content_index.py    # SQLite 内容索引
├── parsers/                # 平台解析器（微信/小红书/抖音/Twitter/飞书）
├── music/handler.py        # /music 命令
├── image/handler.py        # /image 命令（Gemini 出图）
├── video/handler.py        # /video 命令（视频分析）
├── ecom/handler.py         # /ecom 命令（电商运营）
└── utils/                  # 工具函数

config/
├── settings.py             # Pydantic 配置（从 .env 加载）
├── prompts.py              # AI prompt 模板
├── ecom_prompts.py         # 电商专用 prompt
├── workflows.yaml          # 多步骤工作流定义
└── watch_list.yaml         # GitHub 监控列表

daily-briefing/
├── run_briefing.sh         # 每日简报主脚本
├── deep_absorb.py          # 深度知识提取
├── notify_feishu.py        # 发送到飞书
└── prompts/briefing.md     # 简报 prompt

scripts/
├── claude_runner.py        # Claude CLI 封装（stream-json + 超时 + 断点续传）
├── health_check.py         # 系统健康检查
├── ecom_auto_scan.py       # 电商自动扫描
└── reindex_vault.py        # 重建知识库索引
```

---

## 飞书 Bot 消息处理流程

```
飞书消息 → WebSocket → feishu_listener.py (去重 + 排队)
  → message_router.py
    ├── URL? → 抓取 → AI 分析 → 存 vault → 索引 → 回复确认
    ├── /命令? → 路由到对应 handler
    ├── 文件? → 下载 → 分析 → 回复结果
    ├── @提问? → RAG 知识库检索 → AI 回答
    └── 其他 → 意图分类 → 智能回复
```

---

## 飞书 App 配置清单

在 [飞书开放平台](https://open.feishu.cn) 创建应用时需要：

### 权限列表
```
im:message                    # 收发消息
im:message:send_as_bot        # 以 bot 身份发消息
im:chat                       # 群聊信息
im:chat:readonly              # 读群聊
contact:user.id:readonly      # 用户 ID
docx:document                 # 文档读写
bitable:app                   # 多维表格
sheets:spreadsheet            # 电子表格
drive:drive                   # 云文档
wiki:wiki:readonly            # 知识库
```

### 事件订阅
```
im.message.receive_v1         # 接收消息事件
```

### Bot 配置
- 开启「机器人」能力
- 消息接收方式：**长连接 (WebSocket)**（不需要公网 IP）

---

## API Key 获取指南

| 服务 | 获取地址 | 用途 | 免费额度 |
|------|---------|------|---------|
| 飞书 App | https://open.feishu.cn | Bot 消息收发 + 文档 API | 免费 |
| Deepseek | https://platform.deepseek.com | 主力 AI（文本分析/问答） | 按量计费，很便宜 |
| Gemini | https://aistudio.google.com/apikey | 出图 + 视频理解 | 免费 tier 1000次/天 |
| Brave Search | https://brave.com/search/api/ | Web 搜索 | 免费 2000次/月 |
| Claude Max | https://claude.ai | Claude Code CLI (`claude -p`) | 订阅制 $100/月 |
| GitHub Token | https://github.com/settings/tokens | MCP GitHub 插件 | 免费 |

---

## 故障排查

```bash
# Bot 不响应？
launchctl list | grep happycode.knowledge  # 检查服务状态
tail -50 ~/Happycode2026/logs/service.err  # 查错误日志

# 简报没发？
tail -50 ~/Happycode2026/daily-briefing/logs/$(date +%Y-%m-%d).log

# 知识库搜索不到？
cd ~/Happycode2026 && python scripts/reindex_vault.py  # 重建索引

# ChromaDB 损坏？
rm -rf data/chromadb && python scripts/reindex_vault.py  # 重建向量库
```

---

## 一键安装脚本

将以上所有步骤合并为一个脚本，保存在 `scripts/full_deploy.sh`。执行：

```bash
cd ~/Happycode2026
chmod +x scripts/full_deploy.sh
./scripts/full_deploy.sh
```

脚本会自动完成：环境检查 → 虚拟环境 → 依赖安装 → 目录创建 → 记忆初始化 → 服务安装 → 健康检查。

唯一需要手动做的是：**填写 `.env` 中的 API Keys**。

---

## 进化机制说明

系统有 3 层自动进化：

1. **每日简报** → 搜索最新工具/技术 → 提取要点 → 自动评估是否需要行动 → 安全操作自动执行，高风险操作记录到 `pending-actions.md` 等人确认
2. **夜间审查** → 清理 vault 冗余 → 压缩记忆 → 整理知识图谱
3. **模式检测** → 重复操作自动识别 → 建议封装为 Skill/Workflow

**这不是一个静态系统，它会随着使用不断生长。**
