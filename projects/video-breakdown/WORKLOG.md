# 工程日志 — 爆款视频拆解

> 每次工作开始前先读这个文件，恢复上下文。最新的在最上面。

---

## 2026-03-11 (晚) | 记忆修复 + 引用增强 + ADB 视频录屏

### 完成
- [x] 陈维玺联系人档案填充（nickname 陈总, traits, notes）
- [x] 新视频群种子记忆（5 条 observations）
- [x] `_KNOWN_CHATS` 加入两个视频群 ID（用户名解析 fallback）
- [x] noise filter 放宽：`len(text) < 3` → `not text`，不再误杀单字中文
- [x] 引用回复增强：提取 `root_id` 获取 thread 起始消息，提供完整对话上下文
- [x] GEMINI_API_KEY fallback 到 pydantic settings（修复 launchd 环境变量缺失）
- [x] 群人设更新：加入视频拆解和工作区能力说明
- [x] `_format_report` bug fix：metrics 值为字符串时格式化崩溃
- [x] **ADB+scrcpy fallback 下载方案**：抖音 yt-dlp 需要 cookies → 自动用手机录屏

### ADB 视频录屏流程（`src/video/downloader.py`）
```
抖音链接 → yt-dlp 尝试下载 → 失败（需 cookies）
  → _adb_record_video() fallback:
    1. curl 解析短链 → 提取 video_id
    2. ADB deeplink: snssdk1128://aweme/detail/{id} 打开手机抖音
    3. sleep 4s 等视频加载
    4. scrcpy --no-playback --no-audio --record=output.mp4 --max-size=720 --time-limit={duration+8}
    5. ffmpeg 裁掉前 3s 打开动画，输出干净视频
    6. → 送 Gemini 做 🎬 视频画面+音频分析
```
- 依赖：ADB 连接的 Android 手机（OPPO PDYM20）+ 已安装抖音 + scrcpy + ffmpeg
- 限制：录屏包含手机 UI（状态栏、抖音按钮），但 Gemini 能忽略
- 韩束视频实测：录屏 55s → 裁剪 13MB → Gemini 分析钩子强度 9/10 ✅

### 关键决策
- **引用回复 root_id**：仅在 `root_id != parent_id` 时才额外请求，零开销无副作用
- **root_text 消毒**：strip 前导 `[` `]` 防 prompt injection
- **ADB fallback 仅限 douyin/xiaohongshu**：其他平台 yt-dlp 工作正常
- **录屏不去音频**：`--no-audio` 因为手机可能静音，Gemini 主要看画面

### 上下文指针
- 引用增强: `src/message_router.py:140-230`（root_id 提取 + _handle_quoted_message）
- ADB 录屏: `src/video/downloader.py:136-231`（_adb_record_video + helpers）
- format bug fix: `src/video/handler.py:225-234`（metrics int() 转换）

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
