# Happycode2026 Project Contract

## What Is This
飞书 AI Bot（「小叼毛」），运行在 Mac Studio 上，24/7 在线。
核心能力：智能对话 + 知识管理 + 自我进化 + 群运营 + 定时任务。

## Build & Run
- Python 3.11, venv at `.venv/`
- Activate: `source .venv/bin/activate`
- Run bot: `python src/main.py`
- Run briefing: `bash daily-briefing/run_briefing.sh`
- Config: `.env` (secrets) + `config/settings.py` (app config)
- GitHub: https://github.com/youtuan6688-sys/2026

## Architecture

### Message Flow
```
feishu_listener.py (WebSocket)
  → message_router.py (路由分发, 意图检测)
    → router_claude.py (Claude 执行, 长任务续接)
    → router_commands.py (斜杠命令)
    → router_files.py (文件分析)
    → router_docs.py (飞书文档)
    → router_sessions.py (Session/Loop)
  → feishu_sender.py (发消息, 带重试)
```

### Module Map
| 目录 | 职责 |
|------|------|
| `src/` | Bot 核心代码 |
| `src/main.py` | 启动入口（组件初始化 + 遗弃任务恢复 + 向量库自动重建） |
| `src/message_router.py` | 主路由（Mixin 架构，组合 6 个子 mixin） |
| `src/router_context.py` | 上下文构建（历史 + 记忆 + RAG，按意图选择记忆文件） |
| `src/router_intent.py` | 意图检测 + RAG 查询 + 关键词降级搜索 |
| `src/router_claude.py` | Claude 执行（群聊/私聊/长任务续接/fallback） |
| `src/long_task.py` | 多步长任务管理（检查点 + 崩溃恢复） |
| `src/quota_tracker.py` | Claude 配额追踪 + 限流学习 + 自动降级 |
| `src/daily_evolution.py` | 每日进化（人设/联系人/知识/模式/能力/待办） |
| `src/group_memory.py` | 群画像 + 观察笔记 + 话题追踪（每30天刷新） |
| `src/contact_memory.py` | 联系人档案 + 扩展档案注入 + 动态群列表 |
| `src/memory_compressor.py` | 记忆文件自动压缩（超阈值时 sonnet 摘要） |
| `src/pattern_detector.py` | 行为模式检测（重复操作 3 次自动学习） |
| `src/feishu_sender.py` | 发消息/上传文件/图片（带 2 次重试 + 指数退避） |
| `src/feishu_listener.py` | WebSocket 监听（消息去重 + 新人欢迎） |
| `src/storage/vector_store.py` | ChromaDB 向量搜索（带 LRU 缓存） |
| `src/checkpoint.py` | 任务检查点管理 |
| `scripts/claude_runner.py` | Claude CLI 封装（session resume + 超时重试） |
| `scripts/weekly_synthesis.py` | 周度知识综合 + 记忆压缩 |
| `scripts/reindex_vault.py` | 向量库全量重建 |
| `vault/` | Obsidian 知识库（articles/, social/, docs/, memory/） |
| `vault/memory/` | 长期记忆（profile, tools, decisions, learnings, patterns） |
| `daily-briefing/` | 每日简报系统 |
| `config/` | 配置（settings.py） |
| `data/` | 运行时数据（quota, buffer, long_task, kb_usage） |

### Key Mechanisms
- **记忆注入**：三层加载（Index → Summary → Full），按意图关键词选择文件
- **长任务**：自动续接最多 10 步，每步保存摘要，崩溃后通知用户恢复
- **RAG**：ChromaDB + bge-small-zh 嵌入，LRU 缓存，失败降级关键词搜索
- **进化**：每日从对话中提取知识/偏好/模式，自动压缩超龄记忆
- **配额**：自动学习 Claude 限流阈值，接近时降级到 DeepSeek
- **请求追踪**：Feishu message_id 作 request_id，`[req:xxx]` 贯穿日志

### Scheduled Tasks (launchd)
| 任务 | 时间 | 脚本 |
|------|------|------|
| 每日简报 | 北京 7:00 (PST 15:00) | daily-briefing/run_briefing.sh |
| 群日报 | 北京 22:00 (PST 06:00) | scripts/run_group_report.sh |
| 每日进化 | PST 23:00 | scripts/run_evolution.sh |
| 夜间审查 | PST 23:30 | scripts/run_nightly_review.sh |
| 周度综合 | 周日 PST 23:00 | scripts/run_weekly_synthesis.sh |
| 晨间跟进 | PST 07:00 | scripts/run_morning_followup.py |
| Bot 自启 | 开机 | com.happycode.bot.plist |

## Coding Conventions
- Language: Python 3.11, type hints encouraged
- Use `logging` module, never `print()` for production code
- Config via `os.getenv()` or `config/settings.py`, never hardcode
- Chinese comments OK, docstrings in English or Chinese
- Immutable patterns preferred: return new dicts, don't mutate in-place
- Claude CLI 调用必须加 `--output-format text`（防 thinking 泄露）

## Safety Rails

### NEVER
- Commit `.env` or any file containing API keys/tokens
- Run `rm -rf` on vault/ or src/ directories
- Push to main without testing bot startup
- Modify feishu webhook verification logic without explicit approval
- Send test messages to production Feishu groups without confirmation
- 删除 MCP/配置 without explicit user confirmation

### ALWAYS
- Validate Feishu webhook signatures before processing
- Handle API errors with try/except and logging
- Test bot startup (`python src/main.py`) after code changes
- Back up vault/memory/ before bulk modifications
- Feishu API 调用使用重试机制（已内置）

## Verification
- Bot changes: `python src/main.py` starts without errors
- Router changes: verify message classification with test messages
- Knowledge base: check vault/ file created with correct frontmatter
- Briefing: `bash daily-briefing/run_briefing.sh` completes successfully

## Engineering Audit
- 首次审计：2026-03-14（37 项问题，P0-P3 全部修复）
- 审计日志：vault/logs/engineering-audit-2026-03-14.md
- 下次检核：2026-03-28
- 修复记录：见 git log（68471cb → 2dec731，8 个 commits）

## Compact Instructions
When compressing context, preserve in priority order:
1. Architecture decisions and module boundaries (NEVER summarize away)
2. Modified files and their key changes
3. Current task status (what's done, what's pending)
4. Feishu bot state (PID, running/stopped, recent errors)
5. Open TODOs and rollback notes
6. Tool outputs can be deleted — keep pass/fail status only
