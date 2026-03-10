# Happycode2026 — AI 自主进化飞书 Bot 完整架构文档

> 版本: 2026-03-10 | 状态: 生产运行中
> 本文档供 AI 系统阅读理解，支持自动部署和能力复制。

---

## 一、项目概览

Happycode2026 是一个运行在 Mac Studio 上的飞书 AI Bot，具备：
- 飞书即时通讯（WebSocket 长连接，非 webhook）
- 知识库管理（Obsidian Vault + 向量搜索）
- 文件分析（Excel/CSV/PDF/图片）
- 自主进化（每日批量学习 + 行为模式检测）
- 定时任务（每日简报、每日进化、晨间跟进）

核心理念：从"你说我做"的被动 bot，进化为"主动发现→主动执行→主动学习"的自主 AI 助手。

---

## 二、技术栈

| 层 | 技术 | 版本/说明 |
|----|------|-----------|
| 运行环境 | macOS (Mac Studio) | Darwin 23.6.0 |
| 语言 | Python 3.11 | venv at .venv/ |
| 进程管理 | PM2 | 守护 main.py，自动重启 |
| 飞书 SDK | lark-oapi | WebSocket 长连接 |
| AI 主力 | Claude CLI | Max $100 订阅，subprocess 调用 |
| AI 备用 | DeepSeek API | httpx，限流时自动降级 |
| 图片理解 | Gemini Vision API | 图片分析 |
| 向量搜索 | ChromaDB | 本地嵌入式 |
| 结构化索引 | SQLite | 内容元数据 |
| 知识存储 | Obsidian Vault | Markdown 文件 |
| 数据处理 | pandas, matplotlib | Excel 分析 + 图表 |
| 文件解析 | pdfplumber, openpyxl | PDF + Excel |
| 配置管理 | python-dotenv | .env 文件 |
| 定时任务 | macOS cron | 5 个定时任务 |
| 并发控制 | threading + Semaphore | 私聊优先，群聊限流 |

---

## 三、目录结构

```
~/Happycode2026/
├── src/                          # 核心代码
│   ├── main.py                   # 入口：初始化组件 → 启动监听
│   ├── feishu_listener.py        # WebSocket 消息监听 + 去重
│   ├── feishu_sender.py          # 发送消息/文件到飞书
│   ├── feishu_docs.py            # 飞书云文档 CRUD
│   ├── message_router.py         # 消息路由主类 (Mixin 架构)
│   ├── router_context.py         # Mixin: 历史、记忆、上下文
│   ├── router_commands.py        # Mixin: /help /status 等命令
│   ├── router_sessions.py        # Mixin: 后台任务、定时任务审批
│   ├── router_docs.py            # Mixin: 飞书文档操作
│   ├── router_files.py           # Mixin: 文件分析、拆分、自动模式
│   ├── router_claude.py          # Mixin: Claude 执行 + URL 处理
│   ├── quota_tracker.py          # 额度追踪 + DeepSeek 降级
│   ├── concurrency.py            # 并发控制 (MessageGate)
│   ├── contact_memory.py         # 每用户 JSON 记忆
│   ├── daily_evolution.py        # 每日 Opus 批量进化
│   ├── file_handler.py           # 文件解析 + 拆分
│   ├── pending_tasks.py          # 待办任务存储 (M1)
│   ├── pattern_detector.py       # 行为模式检测 (M2)
│   ├── capability_manager.py     # 能力自装管理 (M3)
│   ├── workflow_engine.py        # 工作流引擎 (M4)
│   ├── stock_query.py            # 股票查询
│   ├── chart_generator.py        # 图表生成
│   ├── task_scheduler.py         # 定时任务调度
│   ├── checkpoint.py             # 检查点管理
│   ├── ai/
│   │   ├── analyzer.py           # AI 分析器
│   │   └── embeddings.py         # 嵌入模型
│   ├── storage/
│   │   ├── vector_store.py       # ChromaDB 封装
│   │   ├── content_index.py      # SQLite 索引
│   │   └── obsidian_writer.py    # Vault 写入器
│   └── utils/
│       ├── url_utils.py          # URL 提取
│       └── error_tracker.py      # 错误追踪
├── config/
│   ├── settings.py               # 配置加载 (from .env)
│   └── workflows.yaml            # 工作流定义 (M4)
├── scripts/
│   ├── run_morning_followup.py   # 晨间跟进 cron (M1)
│   ├── claude_runner.py          # Claude 执行器 (带重试)
│   ├── health_check.py           # 健康检查
│   ├── task_runner.py            # 自动修复
│   ├── stock_monitor.py          # 股票监控
│   └── reindex_vault.py          # 向量库重建
├── daily-briefing/
│   ├── run_briefing.sh           # 每日简报脚本
│   └── prompts/briefing.md       # 简报 prompt 模板
├── vault/                        # Obsidian 知识库
│   ├── articles/                 # 文章
│   ├── social/                   # 社交内容
│   └── memory/                   # 长期记忆
│       ├── profile.md            # 用户身份
│       ├── tools.md              # 工具清单
│       ├── decisions.md          # 决策记录
│       ├── learnings.md          # 经验积累
│       ├── patterns.md           # 行为模式
│       ├── daily_summary.md      # 每日摘要
│       ├── pending-tasks.json    # 待办任务 (M1)
│       ├── pending-actions.md    # 能力缺口 (M3)
│       ├── contacts/             # 每用户 JSON
│       └── briefing-digest.md    # 简报要点
├── team/roles/group_persona/
│   └── memory.md                 # 小叼毛群聊人设
├── data/                         # 运行时数据
│   ├── daily_buffer/             # 当日对话缓存
│   ├── seen_messages.json        # 消息去重缓存
│   ├── quota_state.json          # 额度状态
│   ├── chat_history.json         # 对话历史
│   ├── todos.json                # 待办清单
│   ├── phase_log.json            # 阶段日志
│   ├── evolution_metrics.json    # 进化指标
│   ├── file_requests.json        # 文件请求日志
│   └── install_history.json      # 安装历史 (M3)
└── .env                          # 环境变量 (密钥)
```

---

## 四、核心流程

### 4.1 消息处理流程

```
飞书云端
  │ WebSocket 长连接 (lark.ws.Client)
  ▼
feishu_listener.py
  │ 1. 接收消息事件 (P2ImMessageReceiveV1)
  │ 2. 去重: message_id in seen_messages? → skip
  │ 3. 群聊: 无 @mention → skip
  │ 4. 解析: text/post/file/image → 统一文本
  │ 5. 开线程: threading.Thread(target=_dispatch)
  ▼
message_router.py (MessageRouter)
  │ 6. 文件消息 → FilesMixin._handle_file_message()
  │ 7. 引用消息 → 检查是否引用文件
  │ 8. 更新联系人 contacts.touch(user_id)
  │ 9. 检测任务完成 "搞定了" → pending_tasks.mark_done()
  │ 10. 检测模式关闭 "关闭自动分析" → disable_pattern()
  ▼
  群聊路由:
  │ /help → 群聊帮助
  │ /search → 知识库搜索
  │ /doc → 飞书文档
  │ URL → 保存到知识库
  │ 其他 → 小叼毛人设 + Claude sonnet 回复
  ▼
  私聊路由:
  │ /命令 → 对应处理器
  │ 意图分类(正则) → remember/todo/loop/session/document/query
  │ query → Claude Code 执行 (带 RAG + 记忆 + 历史)
  ▼
feishu_sender.py → 回复用户
```

### 4.2 Claude 调用流程

```
router_claude.py._execute_claude()
  │ 1. 构建 full_prompt = 用户指令 + 历史记录 + RAG 上下文
  │ 2. 构建 system_prompt = 长期记忆 + 待办任务
  │ 3. 调用 claude_runner.run_with_resume()
  │    └→ subprocess: claude -p "prompt" --model sonnet
  │       --append-system-prompt "system_prompt"
  │ 4. 超时/限流 → QuotaTracker 自动降级到 DeepSeek
  │ 5. 输出 → send_text() 回复用户
  │ 6. 缓存对话 → data/daily_buffer/ (供每日进化用)
```

### 4.3 文件处理流程

```
收到文件消息 [file_msg:file:xxx.xlsx:file_key:msg_id]
  │ 1. 解析 marker → msg_type, file_name, file_key
  │ 2. 去重: (file_key, prompt_hash) 5分钟 TTL
  │ 3. 检查模式: should_auto_act(user_id, "excel_upload") → 自动分析?
  │ 4. 下载: 飞书 IM API → /tmp/file_xxx
  │ 5. 检测文件操作意图:
  │    ├── 拆分请求 → split_by_column() → 逐文件上传+发送
  │    └── 分析请求 → parse_file() → sonnet 分析 → 图表
  │ 6. system prompt 注入反造假铁律
  │ 7. 清理临时文件
```

### 4.4 每日进化流程 (cron 07:00 PST)

```
daily_evolution.py.run_daily_evolution()
  │ 加载 data/daily_buffer/{date}*.jsonl
  ▼
  1. 人设进化 (Opus)
  │  分析群聊互动 → 更新 team/roles/group_persona/memory.md
  │  压缩旧条目(sonnet)，保留最近 7 天
  │
  2. 联系人进化 (Opus)
  │  分析每用户对话 → 更新 vault/memory/contacts/{id}.json
  │  提取: nickname, traits, preferences, topics
  │
  3. 知识提取 (Opus)
  │  分析私聊 → 提取决策和知识
  │  写入: decisions.md, learnings.md, profile.md, patterns.md
  │
  4. 待办提取 (Sonnet) ← M1
  │  分析对话 → 提取未完成任务 → pending-tasks.json
  │
  5. 模式检测 (无AI) ← M2
  │  规则检测重复行为 → 更新 contact patterns
  │
  6. 能力缺口 (无AI) ← M3
  │  扫描 "不支持/做不到" → pending-actions.md
  │
  7. 指标追踪 → evolution_metrics.json
  8. 日报生成 → daily_summary.md
  9. Vault 归档 → vault/logs/evolution-{date}.md
  10. 通知 admin → 飞书消息
  11. 归档 buffer (全部成功时)
```

---

## 五、四大自主进化机制

### M1: 任务续接

| 组件 | 文件 | 说明 |
|------|------|------|
| 数据层 | src/pending_tasks.py | JSON CRUD, 到期查询, 去重 |
| 提取 | src/daily_evolution.py | sonnet 从对话提取待办 |
| 提醒 | scripts/run_morning_followup.py | 7:30am cron, haiku 生成自然语言 |
| 完成 | src/message_router.py | 检测"搞定了/不用了" |
| 注入 | src/router_context.py | system prompt 含用户待办 |

流转: 对话 → 每日进化提取 → pending-tasks.json → 晨间提醒 → 用户回复"搞定了" → 标记完成

### M2: 模式学习

| 组件 | 文件 | 说明 |
|------|------|------|
| 检测器 | src/pattern_detector.py | 规则检测, 3次阈值激活 |
| 存储 | src/contact_memory.py | patterns 字段 in contact JSON |
| 批量检测 | src/daily_evolution.py | 每日分析 buffer |
| 自动执行 | src/router_files.py | Excel 无指令→自动分析 |
| 关闭 | src/message_router.py | "关闭自动分析" |

模式类型:
- excel_auto_analyze: 发Excel → 自动分析
- file_split_preference: 总按某列拆分
- topic_interest: 反复问同一话题

### M3: 能力自装

| 组件 | 文件 | 说明 |
|------|------|------|
| 管理器 | src/capability_manager.py | 安装/测试/回滚/日志 |
| 缺口检测 | src/daily_evolution.py | 扫描"不支持" |
| 安装日志 | data/install_history.json | 所有安装记录 |

安全动作: skill_install, pip_install, memory_update, mcp_config
每次安装: 写入 → 测试 → 记录 → 通知 admin → 失败可回滚

### M4: 工作流串联

| 组件 | 文件 | 说明 |
|------|------|------|
| 定义 | config/workflows.yaml | YAML 工作流描述 |
| 引擎 | src/workflow_engine.py | 匹配 + 执行 + 错误处理 |
| 集成 | src/router_files.py | 文件上传时匹配 |

预设工作流:
- excel_full_analysis: 下载→解析→AI分析→图表→发送
- excel_split_and_send: 下载→检测列→拆分→发送→摘要
- url_save_to_kb: 抓取→分析→存Vault→向量索引→确认
- weekly_report: 收集数据→AI生成→发送

---

## 六、额度管理 (QuotaTracker)

```
Claude Max $100 订阅:
  Opus:   独立池, 15-35h/周, 仅每日进化 (~3次/天)
  Sonnet: 独立池, 140-280h/周, 主力
  Haiku:  意图分类, 轻量任务

自学习机制:
  1. 记录每个模型每日调用次数
  2. 首次被限流时学习该模型阈值
  3. 之后在 80% 阈值时主动切 DeepSeek
  4. 冷却: 15分钟(临时限流) / 2小时(确认限流)

DeepSeek 降级:
  - httpx 直接调 DeepSeek API
  - 对用户透明，回复照常
  - Opus 不降级（进化任务太重要）
```

---

## 七、并发模型

```
MessageGate (src/concurrency.py):
  私聊: Semaphore(1) — admin 专用通道
  群聊: Semaphore(2) — 最多 2 个 claude 并行
  队列: max 10 — 超出丢弃，防积压
  文件锁: 全局 Lock — 防并发写坏 JSON

消息线程模型:
  WebSocket 回调 → 开 daemon Thread → 处理消息
  (不阻塞 WebSocket 心跳，防止重连风暴)
```

---

## 八、知识库架构

```
数据流: URL/文章 → AI 分析 → 三层存储

1. Obsidian Vault (vault/)
   - articles/: 文章 Markdown + YAML frontmatter
   - social/: 社交内容
   - memory/: 长期记忆文件

2. ChromaDB (向量库)
   - 本地嵌入模型 (sentence-transformers)
   - 语义相似度搜索 (top_k=3, distance<0.7)
   - 自动索引新文章

3. SQLite (结构化索引)
   - 标题、URL、日期、分类
   - 去重检查
   - 统计查询

RAG 流程:
  用户提问 → vector_store.query_similar(text, top_k=3)
  → 相关文章摘要注入 prompt → Claude 回答
```

---

## 九、定时任务

| 时间 (PST) | 北京时间 | 任务 | 脚本 | 模型 |
|------------|----------|------|------|------|
| 15:00 | 07:00+1 | 每日简报 | daily-briefing/run_briefing.sh | sonnet |
| 07:00 | 23:00 | 每日进化 | scripts/run_daily_evolution.sh | opus |
| 07:30 | 23:30 | 晨间跟进 | scripts/run_morning_followup.py | haiku |
| 23:00 | 15:00+1 | 夜间审查 | cron | — |
| 每2小时 | — | 自动修复 | scripts/task_runner.sh | — |

---

## 十、环境变量 (.env)

```
# 飞书
FEISHU_APP_ID=cli_a92e7aa038f89bcd
FEISHU_APP_SECRET=<secret>
FEISHU_ENCRYPT_KEY=<key>
FEISHU_VERIFICATION_TOKEN=<token>

# AI
DEEPSEEK_API_KEY=<key>
GEMINI_API_KEY=<key>

# 路径
VAULT_PATH=~/Happycode2026/vault
CHROMADB_PATH=~/Happycode2026/data/chromadb
SQLITE_PATH=~/Happycode2026/data/content_index.db

# 其他
LOG_LEVEL=INFO
```

---

## 十一、部署步骤 (从零开始)

### 前置条件
- macOS 或 Linux 主机
- Python 3.11+
- Claude CLI 已安装 (claude.ai/code)
- Claude Max 订阅 ($100)
- 飞书开放平台 App（已配好事件订阅）

### 步骤

```bash
# 1. 克隆项目
git clone <repo> ~/Happycode2026
cd ~/Happycode2026

# 2. 创建虚拟环境
python3.11 -m venv .venv
source .venv/bin/activate

# 3. 安装依赖
pip install lark-oapi httpx chromadb pandas openpyxl pdfplumber \
    matplotlib pyyaml sentence-transformers

# 4. 配置环境变量
cp .env.example .env
# 编辑 .env 填入飞书 App 凭证、DeepSeek API Key 等

# 5. 初始化目录
mkdir -p data vault/articles vault/social vault/memory/contacts \
    team/roles/group_persona daily-briefing/reports

# 6. 启动服务
pm2 start .venv/bin/python --name happycode -- src/main.py
pm2 save

# 7. 配置 cron
crontab -e
# 添加:
# 0 15 * * * cd ~/Happycode2026 && bash daily-briefing/run_briefing.sh
# 0 7 * * * cd ~/Happycode2026 && .venv/bin/python -m src.daily_evolution
# 30 7 * * * cd ~/Happycode2026 && .venv/bin/python scripts/run_morning_followup.py
# 0 */2 * * * cd ~/Happycode2026 && bash scripts/task_runner.sh

# 8. 验证
pm2 logs happycode  # 查看日志
# 在飞书私聊 bot，发 /help
```

---

## 十二、飞书 App 配置

### 权限 (Scopes)
- im:message — 接收/发送消息
- im:message:send_as_bot — Bot 身份发消息
- im:file — 上传/下载文件
- im:chat:member — 读取群成员
- contact:user.base:readonly — 读取用户信息
- docx:document — 创建/读写文档
- drive:drive — 访问云文档

### 事件订阅
- im.message.receive_v1 — 接收消息
- im.chat.member.user.added_v1 — 新成员入群

### 连接方式
- WebSocket 长连接（非 HTTP webhook）
- 不需要公网 IP 或域名
- SDK 自动重连

---

## 十三、关键设计决策

1. **Claude CLI 而非 API**: 利用 Max 订阅的固定月费，不按 token 计费
2. **WebSocket 而非 Webhook**: 无需公网 IP，适合家庭/办公室部署
3. **Mixin 架构**: MessageRouter 拆成 6 个 Mixin，每个 <400 行
4. **每日批量进化**: Opus 集中调用 3 次/天，而非每条消息都调
5. **DeepSeek 降级**: 限流时无缝切换，用户无感
6. **模式学习 3 次阈值**: 防止误触发，用户可随时关闭
7. **工作流 YAML 定义**: 非代码用户也能添加新工作流
8. **文件反造假铁律**: system prompt 强制禁止 AI 编造文件操作
