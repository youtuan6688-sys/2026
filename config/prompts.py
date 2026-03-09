ANALYSIS_PROMPT = """分析以下内容，返回一个 JSON 对象，包含：

1. "tags": 3-8 个标签，中英文混合，覆盖主题、领域和关键概念
2. "summary": 用内容的原始语言写 2-3 句简洁摘要
3. "category": 从以下选一个 ["tech", "business", "lifestyle", "culture", "science", "design", "finance", "health", "education", "other"]
4. "key_points": 3-5 个要点，每个一句话

内容标题: {title}
来源平台: {platform}
内容正文:
{text}

仅返回合法 JSON，不要 markdown 代码块包裹。"""

RELATION_PROMPT = """以下是一条新保存的内容和几条已有内容的摘要。
判断新内容与哪些已有内容相关，并简要说明关联原因。

新内容:
标题: {new_title}
摘要: {new_summary}
标签: {new_tags}

已有内容:
{existing_summaries}

返回 JSON 数组，每个元素包含:
- "id": 已有内容的 id
- "reason": 关联原因（一句话）

如果没有相关内容，返回空数组 []。仅返回合法 JSON。"""
