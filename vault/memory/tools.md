# Tools & Setup

## Active Services
- Feishu Bot (BOT_知识库0302): app_id=cli_a92e7aa038f89bcd, running on Mac Studio
  - Natural language: auto-detect intent (execute task / save memory / Q&A)
  - Send URL: Parse + AI analyze + save to Obsidian
  - Legacy shortcuts: /claude, /c, /remember, /r still work
  - launchd service: com.happycode.knowledge (已合并 feishu-bot 到 knowledge 服务)
- Daily Briefing: cron `0 15 * * *` (3pm PST = 7am Beijing)
  - Script: ~/Happycode2026/daily-briefing/run_briefing.sh
  - Reports: ~/Happycode2026/daily-briefing/reports/
  - Prompt: ~/Happycode2026/daily-briefing/prompts/briefing.md
  - Auto-sends to Feishu, digests key findings into memory
  - Searches: OpenClaw, Claude ecosystem, new Skills, MCP servers, CLAUDE.md configs

## Scheduled Tasks
- **7am Beijing (3pm PST)**: Daily briefing -- web search + report + Feishu notify + memory digest + evolution suggestions
  - Status: Fixed on 2026-03-08 (嵌套 Claude 调用问题已解决)
  - Issue: Claude Code 会话内无法执行 `claude -p` 嵌套调用，导致空输出
  - Solution: cron 直接运行日报脚本，环境变量通过 ~/.zshrc 加载
  - Verify: Run outside Claude Code session
- **11pm PST**: Nightly review -- audit knowledge base quality, clean low-value articles, compress memory files
- **Always running**: Feishu bot via launchd -- responds to messages 24/7
- **System Health Check**: Every 2 hours (启用于 2026-03-08, job_id: 75a29e63)
- **Sunday 11:03pm PST**: Weekly knowledge synthesis -- 跨来源知识综合、质量评估、进化建议
  - Script: scripts/weekly_synthesis.py via scripts/run_weekly_synthesis.sh
  - launchd: com.happycode.weekly-synthesis
  - 输出: vault/logs/weekly-synthesis-{date}.md + memory/knowledge-synthesis.md

## Self-Evolution Rules
- When you learn something new and useful, write it to vault/memory/ files
- When daily briefing finds new tools/skills, evaluate and suggest installation
- When a pattern repeats 3+ times, consider creating a Claude Code Skill for it
- When memory files grow too large (>5KB per file), summarize and compress old entries
- Read vault/memory/ files at the start of every task for context

## Knowledge Pipeline (2026-03-10 优化)
- **来源**: 日报(web search) + 用户发链接(Feishu) + 群聊观察 + GitHub watch list
- **提取**: deep_absorb.py → trends/learnings/tools/actions (去重写入)
- **评分**: score_vault_articles() 对文章打 1-10 分（可复用性/深度/时效/相关性）
- **综合**: synthesize_knowledge() 每日跨来源连接，找知识缺口
- **周报**: weekly_synthesis.py 每周日汇总，评估知识质量，建议下周方向
- **群聊→知识**: daily_evolution.py 现在同时从私聊+群聊提取知识
- **防重**: _append_section() 按 section header 去重，run_briefing.sh 不再重复写 learnings

## AI Configuration
- 所有 AI 分析走 Claude CLI（Max 订阅），不调外部 API
- analyzer.py 用 --model haiku 做文章分析（降本），--json-schema 保证结构化输出
- claude_runner.py 用 --permission-mode auto 避免嵌套调用卡死
- Gemini: API Key 已配置在 .env，用于视频理解（视频拆解）+ 画图（Imagen API）
  - **手机 APP 出图（零成本优先）**: devices/oppo-PDYM20/scripts/gemini_image.py
    - ADB + uiautomator2 操控手机 Gemini Pro，每张 60-90s，零 API 费用
    - 支持：单图/批量/重试/迭代编辑（用嘴改图）/会话日志
    - Prompt 模板库: devices/oppo-PDYM20/config/image_style.py（17 个场景模板，8 种风格基底）
    - 六要素框架：背景→主体→环境→技术参数→风格→情感氛围
    - 叙述性描述 > 关键词堆叠（效果提升 85%）
  - **API 出图（高质量兜底）**: google-generativeai SDK，Imagen 3 / Gemini 2.0 Flash
- **Opus 4.6 effort**: 默认 medium effort，复杂推理/架构任务需在 prompt 中加 "ultrathink" 触发 high effort

## Tmux Session 管理
- src/tmux_manager.py: 管理持久 Claude 会话（loop、长任务等）
- 飞书命令: /loop <间隔> [提示], /loop stop, /session list/stop/output
- tmux session 前缀: hc- (如 hc-loop-60m)
  - 生图接口: gemini-2.0-flash 或 imagen-3，通过 google-generativeai SDK 调用
  - 用途: 视觉交付、封面生成、UI 设计稿、营销素材

## Claude Code Config
- Path: ~/.local/bin/claude
- Key flags used: -p (print mode), --allowedTools, --max-budget-usd
- All AI calls route through Claude Max subscription (no external API)

## GitHub
- Repo: git@github.com:youtuan6688-sys/2026.git (public)
- SSH Key: ~/.ssh/id_ed25519 (ed25519, added 2026-03-12)
- 一键部署文档: DEPLOY.md + scripts/full_deploy.sh
- 朋友可 clone 后运行 `./scripts/full_deploy.sh` 一键部署

## MCP Servers (Installed)
- filesystem: 读写本地文件系统
- sequential-thinking: 结构化推理
- memory: 知识图谱（实体+关系）
- happycode-knowledge: Obsidian 知识库搜索（语义+全文）
- crawl4ai: 网页爬取→Markdown，支持动态页面
- playwright: 浏览器自动化、截图、表单填写（Chromium 已安装）
- context7: 拉取最新库文档，防止 API 幻觉
- chrome-devtools: Chrome DevTools 调试、性能分析、网络检查、CSS 审查（操控已打开的 Chrome）
- github: GitHub API 全量操作（PR/Issue/搜索/文件读写）
- brave-search: Brave Web 搜索
- fetch: HTTP 请求
- lark-mcp: 飞书官方 API（文档/表格/日历/消息/Wiki）

### MCP 上下文消耗（已解决）
- Claude Code 内置 ToolSearch 延迟加载，12 个 server 的工具定义被 deferred 为 stub
- 实际消耗远低于 Tw93 文章说的 "5 server = 12.5%"（那是无 ToolSearch 的旧场景）
- 可安全扩展到 20+ MCP server，ToolSearch 会自动管理
- Bot 侧（claude -p subprocess）不经过 ToolSearch，bot 扩展能力应靠 Python API 或 Skill 化

## InStreet 社区账号 (2026-03-11)
- Username: happycode_bot
- Agent ID: d18f33eb-a85d-4743-94b8-e134d9414942
- API Key: sk_inst_56c0a11c70e6e01b374e3ae7e5aa2b06
- Profile: https://instreet.coze.site/u/happycode_bot
- Base URL: https://instreet.coze.site/api/v1/
- 用途：学习龙虾生态 Skill、参与社区讨论、跨平台 Agent 协作
- 已关注：aha_lobster（龙虾教教主）
- 心跳频率建议：每 4-6h 检查通知+回复评论

## ADB 设备 (Android 手机)
- 型号: OPPO PDYM20 (Android 12)
- Serial: EUVW6TOJN7D6IFZ5
- 已安装: 抖音 (com.ss.android.ugc.aweme) + 抖音极速版 (com.ss.android.ugc.aweme.lite) + Gemini
- 用途:
  - 视频录屏 fallback: yt-dlp 失败时，ADB deeplink 打开抖音 + scrcpy 录屏 → Gemini 分析
  - Gemini 零成本出图: uiautomator2 操控 Gemini App（devices/oppo-PDYM20/scripts/）
  - 小红书录屏: 同理可扩展（待实现）
- 流程固化在: `src/video/downloader.py:_adb_record_video()`

## MCP Servers (Worth Adding)
- DeepWiki: structured docs for any GitHub repo
- Excalidraw: generate architecture diagrams from prompts

## CLI Tools (Installed via Homebrew)
- ffmpeg 8.0: 音视频处理（转码、剪辑、提取音频）
- yt-dlp 2026.3: 视频下载（YouTube、B站、抖音等）— 抖音需 cookies，fallback 到 ADB
- scrcpy 3.3.4: Android 手机投屏/录屏（用于抖音视频录制 fallback）
- jq 1.8: JSON 处理和查询
- pandoc 3.9: 文档格式转换（Markdown↔HTML↔PDF↔DOCX）
- wget 1.25: 文件下载
- htop 3.4: 系统资源监控
- tmux: 终端复用
- node/npm: JavaScript 运行时
- python3.11: Python 运行时

## Skills (Installed)
- Recall: 搜索所有历史对话（`/recall`）
- continuous-learning-v2: 自动从会话提取可复用模式
- `/china-ecommerce`: 中国电商运营（淘宝/天猫/拼多多/京东/抖音）— 来源: agency-agents
- `/xiaohongshu`: 小红书运营（内容策略/社区运营/种草转化）— 来源: agency-agents
- `/wechat-oa`: 微信公众号运营（内容营销/私域流量）— 来源: agency-agents
- `/carousel-engine`: 轮播图增长引擎（TikTok/Instagram 自动生成发布）— 来源: agency-agents
- `/agents-orchestrator`: Agent 编排器（PM→架构→开发QA循环→集成）— 来源: agency-agents
- `video-breakdown-bitable`: 视频拆解→飞书多维表格（逐秒脚本表+整体诊断表，陈总三维度场景分析）— 来源: learned

## Skills & Tools (Worth Installing)
- find-skills: discover which installed skill fits your current need
- obra/superpowers: 14 dev lifecycle skills (brainstorming -> code review)
- skillsmp.com: 80,000+ Claude skills library
- mcpservers.org/claude-skills: plug-and-play skills

## Skill Development Patterns
- Create from example: paste good output -> let Claude convert to reusable skill
- Create from screenshot: upload screenshot -> Claude replicates -> convert to skill
- Version control: copy & create new version when optimizing, don't edit in-use skill
- Encapsulate solutions into skills for reuse (e.g. video-chapter-splitter pattern)

## Evolution Roadmap (2026-03-05)
Priority order for self-evolution:

1. **Self-Repair + Error Learning** (immediate)
   - Error logging to vault/logs/error_log.json
   - Nightly audit adds error review → auto-fix → learnings.md update
   - Morning Feishu report: what was fixed, what was learned

2. **n8n Workflow Engine** (this week)
   - Install n8n-mcp (github.com/czlonkowski/n8n-mcp)
   - Migrate cron tasks to n8n for visual workflows + error retry
   - New: RSS monitoring → auto-summary → knowledge base → Feishu notify

3. **Agent Teams** (this week)
   - Enable CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1
   - Complex tasks auto-split into multi-agent parallel execution
   - Use for: code review, large features, competing hypothesis debugging

4. **Multi-Channel Triggers** (next)
   - Gmail MCP → email classification + scoring + draft replies
   - GitHub watch → release/issue auto-summary → knowledge base
   - Google Calendar MCP → daily schedule + meeting prep
   - Message tiering: batch normal, instant urgent

5. **Knowledge Base Active Evolution** (next)
   - RSS auto-ingest with quality scoring
   - Knowledge graph via MCP Memory for article relationships
   - Stale content detection and archiving
   - Gap analysis: user questions vs knowledge coverage

6. **Skill Auto-Generation** (later)
   - Track operation frequency per task type
   - Auto-propose skill creation when pattern repeats 3+ times
   - Skill effectiveness tracking
   - Periodic skill audit


### 2026-03-10 - 飞书云文档自动化（新能力）
- **lark-openapi-mcp** (github.com/larksuite/lark-openapi-mcp): 飞书官方 MCP Server，支持文档/表格/日历/消息全链路
  - 可直接加入 Claude Code MCP 配置，`npx @larksuiteoapi/lark-mcp` 一行启动
  - 预设工具集：im/docx/bitable/calendar/wiki
  - 限制：不支持文件上传下载、不支持编辑已有文档
  - **建议**：优先集成，打通 AI → 飞书文档自动化
- 六大场景：自动日报生成、AI研究助手、会议协调、Bitable项目管理、模板填充导出、AI客服
- 详见：vault/articles/2026-03-10-飞书云文档BOT自动化完全指南-feishu-doc-automation.md

### 2026-03-10 - 新发现工具
- mcp2cli (https://github.com/knowsuchagency/mcp2cli): 将 MCP Server 转为 CLI 降低 99% token 成本 — 可直接用
- ClaudeClaw (https://github.com/moazbuilds/claudeclaw): 轻量后台守护进程，定时任务+消息响应，比 OpenClaw 轻量 — 需适配
- claude-code-action v1.0 (https://github.com/anthropics/claude-code-action): GitHub Actions 官方集成，自动 PR 代码审查 — 需适配
- awesome-agent-skills (https://github.com/VoltAgent/awesome-agent-skills): 500+ 跨工具兼容 Agent Skills 目录 — 可直接用
- awesome-claude-skills (https://chat2anyllm.github.io/awesome-claude-skills/): 24370个 Skills 在线搜索目录 — 可直接用
- Trail of Bits Claude Code Config (https://github.com/trailofbits/claude-code-config): 安全公司 opinionated CLAUDE.md 模板 — 参考


### 2026-03-11 - Gemini 出图工具（GitHub）
- minimaxir/gemimg: 一行代码 Python Gemini 出图库 — 可直接用（API 出图时替代手写 SDK 调用）
- YouMind-OpenLab/awesome-nano-banana-pro-prompts: 10000+ Gemini prompt 库 — 参考学习
- pauhu/gemini-image-prompting-handbook: JSON Schema 结构化 prompt 指南 — 参考
- nano-banana-pro-prompts-recommend-skill: Claude Code Skill，一句话推荐 prompt — 可安装
- GoogleCloudPlatform/generative-ai: 官方 Notebook 教程 — 参考

### 2026-03-11 - 新发现工具
- last30days-skill (https://github.com/mvanhorn/last30days-skill): 一键搜索 Reddit/X/YouTube/HN/Polymarket/Web 生成 30 天话题摘要 — 可直接用
- Google Workspace CLI gws (https://github.com/googleworkspace/cli): `gws mcp` 启动 MCP server，操控 Gmail/Calendar/Drive/Sheets/Docs — 需适配（需 Google OAuth 配置）
- claude-code-mcp (https://github.com/steipete/claude-code-mcp): 将 Claude Code 作为 MCP server 嵌入其他 agent，实现 agent 嵌套 — 参考
- OpenClaw v2026.3.8 (https://github.com/openclaw/openclaw): 内存热插拔 + Context Engine 插件 + ACP 来源追踪，修复 12+ 安全漏洞 — 需适配
- alirezarezvani/claude-skills (https://github.com/alirezarezvani/claude-skills): 180+ production-ready skills 覆盖工程/营销/合规 — 参考


### 2026-03-12 - 新发现工具
- mcp2cli (pip install mcp2cli): MCP Server token 节省工具，将 MCP 调用路由到 CLI 减少 token 消耗 — 需适配
- Claude Code v2.1.74: autoMemoryDirectory + modelOverrides 新功能 — 可直接用（npm update -g @anthropic-ai/claude-code）
- ContextEngine (OpenClaw 插件): 280K+ stars 项目的插件架构，适合扩展 Claude 上下文管理 — 参考
