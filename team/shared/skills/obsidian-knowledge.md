# 共享技能: Obsidian 知识库操作

## 目录结构
```
vault/
  articles/     # 网页文章（URL 解析后保存）
  social/       # 社交媒体内容
  memory/       # 长期记忆
    profile.md      # 用户身份
    tools.md        # 工具清单
    decisions.md    # 决策记录
    learnings.md    # 经验教训
    patterns.md     # 决策 DNA
    briefing-digest.md  # 简报摘要
```

## 写入规范

### 文章保存格式
```markdown
---
title: 文章标题
url: https://original-url.com
date: 2026-03-05
source: twitter/weixin/web
tags: [tag1, tag2]
---

# 文章标题

## 摘要
3-5 句话总结

## 关键要点
- 要点 1
- 要点 2

## 原文内容
（可选，完整内容）
```

### 记忆写入规则
- 追加到已有文件，不要覆盖
- 加时间戳标记
- 超过 5KB 时压缩旧条目
- 用 `## ` 二级标题分隔条目

### MCP 搜索
```
# 语义搜索（知识库）
happycode-knowledge.semantic_search("query")

# 全文搜索
happycode-knowledge.search_vault("keyword")

# 知识图谱
memory.search_nodes("entity name")
```
