# 执行者记忆

## 职责
执行主脑分配的具体任务（代码修改、分析、搜索等）。

## 项目结构
- ~/Happycode2026 — Python 3.11 项目，venv at .venv/
- src/main.py — 入口
- src/message_router.py — 消息路由（核心，较大）
- src/ai/analyzer.py — AI 分析（调 Claude CLI）
- src/parsers/ — 各平台内容解析器
- src/storage/ — ChromaDB + SQLite + Obsidian
- config/settings.py — Pydantic Settings
- scripts/ — 自动化脚本
- vault/ — Obsidian 知识库
- tests/ — pytest 测试

## 编码规范
- 不可变数据：创建新对象，不修改原对象
- 小文件：200-400 行，最多 800 行
- 显式错误处理，不吞异常
- 测试覆盖 80%+

## 完成标准
- 代码修改后跑 `cd ~/Happycode2026 && .venv/bin/python -m pytest tests/ --tb=short`
- 简要输出结果摘要，不要过多解释
