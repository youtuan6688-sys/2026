# Tools & Setup

## Active Services
- Feishu Bot (BOT_知识库0302): app_id=cli_a92e7aa038f89bcd, running on Mac Studio
  - Natural language: auto-detect intent (execute task / save memory / Q&A)
  - Send URL: Parse + AI analyze + save to Obsidian
  - SPA 页面(wolai/notion/语雀)自动用 Playwright 浏览器渲染
  - Legacy shortcuts: /claude, /c, /remember, /r still work
  - launchd service: com.happycode.knowledge
- Daily Briefing: launchd `15:00 PST` (7am Beijing)
  - Script: ~/Happycode2026/daily-briefing/run_briefing.sh
  - Auto-sends to Feishu, digests key findings into memory

## Scheduled Tasks (launchd)
| 任务 | PST | 北京 | 脚本 |
|------|-----|------|------|
| group-summary | 06:00 | 22:00 | scripts/run_group_report.sh |
| daily-briefing | 15:00 | 07:00 | daily-briefing/run_briefing.sh |
| hot-briefing | 15:05 | 07:05 | scripts/run_hot_briefing.sh |
| daily-evolution | 07:00 | 23:00 | scripts/run_daily_evolution.sh |
| nightly-review | 23:00 | 15:00 | daily-briefing/run_nightly_review.sh |
| weekly-synthesis | Sun 23:03 | Mon 15:03 | scripts/run_weekly_synthesis.sh |
| knowledge (bot) | always | always | src/main.py |

## Self-Evolution Rules
- Learn something new → write to vault/memory/
- Daily briefing finds new tools → evaluate and suggest
- Pattern repeats 3+ times → consider creating a Skill
- Memory files > 5KB → summarize and compress old entries

## AI Configuration
- Claude CLI (Max 订阅) for all AI calls
- Observer: --model sonnet (haiku 因 adaptive thinking 不兼容)
- Gemini: API + 手机 APP 零成本出图 (devices/oppo-PDYM20/)
  - 手机出图: uiautomator2 操控 Gemini App，每张 60-90s，零费用
  - Prompt 模板库: devices/oppo-PDYM20/config/image_style.py（17 场景，8 风格）
- Opus 4.6: 默认 medium effort，复杂任务用 "ultrathink"

## MCP Servers (Active)
filesystem, sequential-thinking, memory, happycode-knowledge, context7, chrome-devtools, github, brave-search, lark-mcp

## GitHub
- Repo: git@github.com:youtuan6688-sys/2026.git (public)
- 一键部署: DEPLOY.md + scripts/full_deploy.sh

## ADB 设备
- OPPO PDYM20 (Android 12), Serial: EUVW6TOJN7D6IFZ5
- 用途: 视频录屏 fallback + Gemini 零成本出图 + 小红书

## CLI Tools
ffmpeg, yt-dlp, camoufox-cli, scrcpy, jq, pandoc, tmux, node/npm, python3.11

## Skills (Installed)
Recall, continuous-learning-v2, /china-ecommerce, /xiaohongshu, /wechat-oa, /carousel-engine, /agents-orchestrator, video-breakdown-bitable

## Bitable
- Ticket Tracker: app=YR13bqL1Sanqkosn8gOcbYTfnNb, table=tbl6xkquKuEBrb3K
- Commands: /ticket create|list|update|setup, /bt

## InStreet 社区
- Username: happycode_bot
- 用途：学习龙虾生态 Skill、社区讨论
