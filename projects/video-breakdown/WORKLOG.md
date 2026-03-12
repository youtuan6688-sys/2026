# 工程日志 — 爆款视频拆解

> 每次工作开始前先读这个文件，恢复上下文。最新的在最上面。

---

## 2026-03-11 | 项目重组 + 工作区系统

### 完成
- [x] 从旧 `projects/viral-video-analyzer/` 迁移 prompts 到新目录
- [x] 修复 `src/video/analyzer.py` 的 prompt 路径引用（相对路径替代硬编码）
- [x] 删除旧项目目录 (`viral-video-analyzer/` + `douyin-analyzer/`)
- [x] 新增 `/work` 命令 — 沙箱工作区执行（`src/workspace_handler.py`）
- [x] 新增视频群 `oc_494f1c2a811f65378639269461ba312f`（陈维玺）
- [x] `_VIDEO_GROUP_IDS` 改为 frozenset 支持多群
- [x] 创建陈维玺工作区 `workspaces/陈维玺/`
- [x] Brave Search 集成（抖音/小红书搜索）
- [x] `/video search` 命令上线
- [x] ThreadPoolExecutor 替代裸 Thread
- [x] 两轮 code review 修复所有 CRITICAL/HIGH issues

### 关键决策
- **工作区沙箱**: cwd + system prompt 引导，不做硬限制（宽松模式）
- **群权限**: 视频群所有人都能用 `/work`，按 open_id 自动分配独立工作区
- **搜索策略**: Brave API 搜抖音/小红书，yt-dlp 搜 B站/YouTube

### 上下文指针
- 陈维玺 open_id: `ou_b8d78a70697088e5522d843011ed7dfd`
- 工作区处理: `src/workspace_handler.py`
- 消息路由: `src/message_router.py:266` (`/work` 入口)
