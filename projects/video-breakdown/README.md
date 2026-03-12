# 爆款视频拆解

全链路爆款视频拆解系统：采集 → AI 视频理解 → 结构化拆解 → 知识积累

## 当前能力（已上线）

| 功能 | 触发方式 | 说明 |
|------|----------|------|
| 视频拆解 | 发视频链接 / `/video <URL>` | 抖音/B站/小红书/YouTube |
| 视频搜索 | `/video search <关键词>` | Brave Search + yt-dlp |
| 工作区 | `/work <任务>` | 沙箱内写代码/跑脚本/分析数据 |
| 每日爬取 | 定时 cron (10:00 PST) | 自动爬各平台热门 + 分析 |
| 自动拆解 | 群内发视频链接 | 视频群内自动触发 |

## 技术栈

- **视频理解**: Gemini 2.5 Flash (原生视频分析：画面+音频)
- **视频下载**: yt-dlp (全平台)
- **视频搜索**: Brave Web Search API (抖音/小红书) + yt-dlp search (B站/YouTube)
- **Bot**: 飞书 WebSocket bot
- **工作区**: Claude CLI 沙箱执行

## 目录结构

```
projects/video-breakdown/
├── README.md              ← 本文件
├── prompts/
│   ├── video_breakdown.md ← 视频拆解 prompt
│   └── trend_analysis.md  ← 趋势分析 prompt
├── reports/               ← 周报/月报
├── learnings/             ← 爆款模式积累
└── workspaces/            ← 用户独立工作区
    └── 陈维玺/            ← 陈维玺的沙箱工作区
```

## 数据存储

- `data/video_breakdowns/*.jsonl` — 每日拆解结果 (JSONL)
- `data/video_trending/*.json` — 平台热门 URL 缓存
- `data/video_raw/` — 临时视频文件 (分析后自动清理)

## 核心代码

- `src/video/analyzer.py` — Gemini 视频分析
- `src/video/crawler.py` — 视频搜索 (Brave + yt-dlp)
- `src/video/downloader.py` — 视频下载
- `src/video/handler.py` — 飞书命令处理
- `src/workspace_handler.py` — 工作区沙箱执行

## 飞书群

- 爆款视频拆解实验室 (旧): `oc_d42807f92f606dc0b448f16c6c42fece`
- 爆款视频拆解 (新·陈维玺): `oc_494f1c2a811f65378639269461ba312f`

## 拆解维度

钩子(hook) → 结构(structure) → 视觉(visual) → 音频(audio) → 文案(copywriting) → 可复用元素 → 综合评分
