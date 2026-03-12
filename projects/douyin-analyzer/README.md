# 抖音爆款视频拆解 → 飞书多维表格

> 状态：**已封存 → 迁移至 `projects/viral-video-analyzer/`**
> 创建：2026-03-10
> 封存：2026-03-11（升级为全链路视频拆解项目）

## 目标

用户发指令（关键词/链接），bot 自动：
1. 抓取抖音视频数据（标题、播放量、点赞、评论、标签）
2. AI 拆解爆款逻辑（选题、钩子、节奏、文案结构）
3. 写入飞书多维表格（结构化存储）
4. 通知用户

## 数据采集方案对比

| 方案 | Star | 优势 | 劣势 | 链接 |
|------|------|------|------|------|
| **MediaCrawler** | 30K+ | 免费开源，抖音/小红书/B站通吃，Playwright 模拟 | 需登录态(扫码)，维护成本高 | https://github.com/NanmiCoder/MediaCrawler |
| **Douyin_TikTok_Download_API** | — | 无水印下载，自带 API，有 PyPI 包 | 仅解析单条链接，不做热门榜 | https://github.com/Evil0ctal/Douyin_TikTok_Download_API |
| **douyin-tiktok-scraper (PyPI)** | — | `pip install douyin-tiktok-scraper`，最轻量 | 功能有限 | https://pypi.org/project/douyin-tiktok-scraper/ |
| **天聚数行 API** | — | 现成 REST API，50条热搜榜，3分钟更新 | 付费 | https://www.tianapi.com/apiview/155 |
| **蝉妈妈/飞瓜/新抖** | — | 数据最全最专业 | 贵(几千/月)，无公开 API | — |

**已选方案**: MediaCrawler（免费，用子进程调用松耦合）

## 技术架构

```
/douyin 美妆 → douyin_scraper.py (MediaCrawler 封装)
  → 抓取 Top N 视频
  → video_analyzer.py (sonnet 拆解)
  → feishu_bitable.py (写入多维表格)
  → 回复用户「已拆解 N 条，查看多维表格」
```

## 文件规划

| 文件 | 说明 |
|------|------|
| `src/douyin_scraper.py` | MediaCrawler 轻量封装，关键词搜索 + 数据提取 |
| `src/feishu_bitable.py` | 飞书多维表格 CRUD（创建表、写入记录） |
| `src/video_analyzer.py` | sonnet 拆解爆款视频 |
| `src/router_douyin.py` | Mixin: `/douyin` 命令处理 |
| `src/message_router.py` | 添加 DouyinMixin + 路由（改动） |

## 飞书多维表格 API

- SDK: `lark-oapi` (已安装)
- 写入: `BatchCreateAppTableRecordRequest`
- 前提: bot App 需添加为文档协作者（可编辑权限）
- 文档: https://open.feishu.cn/document/server-docs/docs/bitable-v1/app-table-record/create

### 多维表格字段设计（草案）

| 字段名 | 类型 | 说明 |
|--------|------|------|
| 视频标题 | 文本 | |
| 链接 | URL | |
| 作者 | 文本 | |
| 播放量 | 数字 | |
| 点赞数 | 数字 | |
| 评论数 | 数字 | |
| 发布时间 | 日期 | |
| 标签 | 文本 | 逗号分隔 |
| 选题类型 | 单选 | 痛点/热点/反转/干货 |
| 开头钩子 | 文本 | AI 拆解 |
| 叙事结构 | 文本 | AI 拆解 |
| 可复用元素 | 文本 | AI 拆解 |
| 抓取日期 | 日期 | |
| 搜索关键词 | 文本 | |

## 前置条件

- [ ] 抖音账号扫码登录 MediaCrawler（获取 cookie）
- [ ] 创建飞书多维表格模板
- [ ] bot App 添加为多维表格协作者
- [ ] `pip install MediaCrawler` 或 clone 到本地

## 预估工时

~9h 总计：
- 数据采集封装: 3h
- 飞书多维表格 CRUD: 3h
- AI 拆解 prompt: 1h
- 命令集成: 2h

## 参考资料

- MediaCrawler 文档: https://nanmicoder.github.io/MediaCrawler/
- MediaCrawler Pro: https://github.com/MediaCrawlerPro
- douyin-downloader: https://github.com/jiji262/douyin-downloader
- 飞书 Bitable API: https://open.feishu.cn/document/server-docs/docs/bitable-v1/app-table-record/create
- 抖音数据分析工具对比: https://www.jiushuyun.com/blog/ds/28031.html
