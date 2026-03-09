# HappyCode 知识管理系统 - 项目日志

## 项目概述

**名称**: HappyCode Knowledge System
**目标**: 通过飞书机器人收集各平台有价值内容，AI自动分析打标签，保存到本地Obsidian知识库
**启动日期**: 2026-03-04

---

## 2026-03-04 - 项目初始化

### 完成内容

#### 1. 环境搭建
- 安装 Python 3.11.15 (via Homebrew)
- 创建虚拟环境 `.venv`
- 安装核心依赖: lark-oapi, anthropic, chromadb, requests, beautifulsoup4, readability-lxml, pydantic-settings 等
- 初始化 Git 仓库

#### 2. 项目架构 (31个文件)

```
Happycode2026/
├── config/settings.py          # 配置管理 (pydantic-settings, 读取.env)
├── config/prompts.py           # Claude API 提示词模板
├── src/main.py                 # 服务入口
├── src/feishu_listener.py      # 飞书 WebSocket 长连接监听
├── src/message_router.py       # URL识别 → 解析 → AI分析 → 保存
├── src/parsers/                # 6个平台内容解析器
│   ├── generic_web.py          #   通用网页 (readability-lxml)
│   ├── wechat_article.py       #   微信公众号
│   ├── twitter.py              #   X/Twitter (oembed API)
│   ├── xiaohongshu.py          #   小红书 (meta标签提取)
│   ├── douyin.py               #   抖音 (meta标签提取)
│   └── feishu_doc.py           #   飞书文档
├── src/ai/analyzer.py          # Claude API 智能分析 (标签/摘要/分类/关联)
├── src/ai/embeddings.py        # 向量嵌入 (bge-m3, 待安装)
├── src/storage/
│   ├── obsidian_writer.py      # 生成 Obsidian .md (YAML frontmatter + 正文)
│   ├── vector_store.py         # ChromaDB 向量存储 (相似内容搜索)
│   └── content_index.py        # SQLite 元数据索引 (去重)
├── vault/                      # Obsidian 知识库
│   ├── articles/               #   公众号、网页文章
│   ├── social/                 #   小红书、抖音、Twitter
│   └── docs/                   #   飞书文档
└── scripts/install_service.sh  # macOS launchd 后台服务安装脚本
```

#### 3. 技术决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 消息接收 | 飞书 WebSocket 长连接 | 无需公网IP/ngrok，SDK自动重连 |
| 内容提取 | readability-lxml + BeautifulSoup | 通用且成熟 |
| AI分析 | Claude API (Sonnet) | 中英文理解能力强，性价比高 |
| 向量搜索 | ChromaDB + bge-m3 | 本地运行，多语言，免费 |
| 元数据存储 | SQLite | 轻量，用于URL去重和检索 |
| 后台服务 | macOS launchd | 原生方案，崩溃自动重启 |

#### 4. 飞书应用配置
- 应用名称: BOT_知识库0302
- App ID: cli_a92e7aa038f89bcd
- 已创建飞书自建应用，添加机器人能力
- 事件订阅模式: 长连接 (WebSocket)
- 需订阅事件: `im.message.receive_v1`

### 待完成

- [ ] 配置 Anthropic API Key
- [ ] 首次端到端测试 (飞书发消息 → Obsidian .md)
- [ ] 安装 sentence-transformers (向量嵌入，约2GB)
- [ ] 配置 launchd 后台服务
- [ ] 飞书机器人回复确认消息功能

### 已知限制 (v1)

1. **小红书/抖音**: 反爬严格，仅能提取 meta 标签信息，完整内容可能需手动查看
2. **飞书文档**: 私有文档暂用通用解析，后续可用 lark-oapi docx API 认证访问
3. **向量嵌入**: sentence-transformers 未安装，关联推荐功能暂不可用
4. **视频内容**: 抖音等视频平台仅提取标题/描述，不含视频转录

---

## 工作流程

```
用户在飞书转发链接给 BOT_知识库0302
        ↓
飞书云 → WebSocket → Mac Studio (feishu_listener.py)
        ↓
message_router.py: 提取URL → 识别平台 → 检查去重
        ↓
parsers/*: 抓取网页 → 提取标题/正文/作者/图片
        ↓
ai/analyzer.py: Claude API → 标签/摘要/分类/要点
        ↓
storage/obsidian_writer.py: 生成 .md → 写入 vault/
storage/vector_store.py: 向量索引 (用于关联推荐)
storage/content_index.py: SQLite记录 (用于去重)
```
