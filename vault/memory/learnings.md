已写入。压缩后从 74 行降至 45 行，清除了重复的错误分析原始数据和压缩说明文字，同时把 3/12 深度吸收中 3 条可操作洞察合并进了「生态工具洞察」。

## 2026-03-13 - Tw93 Claude Code 工程实践（知识库吸收）
**来源**: vault/articles/tw93-claude-code-architecture-governance-engineering.md
**核心洞察**:
- Claude Code 六层架构: 上下文层→控制层→工具层→Skill层→Subagent层→验证层
- Compact Instructions 写进 CLAUDE.md 控制压缩保留优先级
- HANDOFF.md 跨会话接力比依赖压缩算法更可靠
- Skill 描述应写"何时该用我"而非"我是干什么的"

## 2026-03-13 - MCP 上下文消耗认知纠正（重要）
**之前的错误认知**: "MCP 工具定义是上下文隐形杀手（5个Server ≈ 12.5%上下文）"
**纠正**: Tw93 文章的计算基于没有 ToolSearch 的场景。Claude Code 已内置 ToolSearch 延迟加载机制：
- 当 MCP 工具描述超过 10% 上下文时，自动启用 Tool Search
- MCP 工具被 deferred 为轻量 stub（只有工具名），完整 schema 按需加载
- 实测效果：51K → 8.5K tokens（减少 83%），我们的配置已启用（tengu_mcp_tool_search: true）
- **结论：12 个 MCP Server 不是问题，可以继续扩展到 20+ 也安全**
- 配置方式：环境变量 `ENABLE_TOOL_SEARCH=auto:5`（5% 阈值触发）或 `true`（始终启用）
- **限制**：Haiku 模型不支持 ToolSearch，subagent 用 haiku 时 MCP 工具不会延迟加载
- **Bot 侧注意**：飞书 bot 走 `claude -p` subprocess，不经过 ToolSearch，bot 自身的工具扩展应靠 Python 直接调 API 或 Skill 化，不是加 MCP
- **⛔ 严禁删除 MCP Server**：不要基于"上下文太大"的理由删除任何 MCP Server（filesystem/playwright/fetch 等），ToolSearch 已经自动管理了。之前误删导致功能丢失，已被用户恢复

## 2026-03-13 - 群聊串台教训
PATTERN: 群聊中用户说"接客"被误判为外部商务场景，实际是让 bot 继续处理群内需求
LESSON: 群聊指令需结合上下文理解，不要脱离当前对话链单独解读

## 2026-03-12 - 错误分析
PATTERN: Claude Code 执行超时/崩溃 | 3次 (timeout + crash + retries_exhausted) | execute_claude 函数的超时机制和重试逻辑需要加固
PATTERN: 对象属性访问未做 None 检查 | 2次 (NoneType.get + Block.paragraph) | 数据解析前缺少类型/属性校验

AUTOFIX: kb_query_error — `query_knowledge_base` 中对返回结果加 None 守卫：`result = data.get('key') if data else None`
AUTOFIX: url_parse_error — `url_processing` 中解析 Block 前检查类型：`if hasattr(block, 'paragraph')` 再访问
AUTOFIX: intent_classify_error — `classify_intent` 的异常信息只有 `err`，补全 `except Exception as e: logger.error(f"intent_classify_error: {e}")` 以便定位根因
