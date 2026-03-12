# 小红书自动化全景图

## 一、三条技术路线

| 路线 | 原理 | 安全性 | 适合场景 |
|------|------|--------|----------|
| **① ADB 真机自动化** | 通过 USB 控制手机，模拟真人点击/滑动 | ⭐⭐⭐⭐⭐ 最安全 | 养号、刷内容、点赞、评论 |
| **② MCP + 浏览器自动化** | AI 通过 MCP 协议驱动浏览器操作小红书网页版 | ⭐⭐⭐ 中等 | 搜索、发布笔记、数据采集 |
| **③ API 逆向** | 破解 x-s/x-t 签名直接调用接口 | ⭐ 高风险 | 大规模数据采集（不推荐长期用） |

**推荐策略**: ① + ② 结合 — ADB 真机做日常互动养号，MCP 做内容发布和数据分析。

---

## 二、我们的硬件优势

- OPPO PDYM20 真机 + USB 连接 = 真实设备指纹，绕过所有网页层反爬
- 手机已装 UIAutomator = 可直接用 uiautomator2 (Python) 控制
- Mac Studio 24/7 在线 = 可跑定时自动化任务

---

## 三、可玩的自动化场景

### A. 养号自动化 (ADB)
- 每天定时浏览 15-30 分钟（随机滑动、停留、点赞）
- 自动关注对标账号
- 自动点赞/收藏（模拟真人节奏，随机延时）

### B. 内容发布自动化 (MCP)
- AI 生成图文笔记（Claude/DeepSeek 写文案 + AI 生图）
- 通过 MCP 自动发布到小红书
- 定时发布，分散节奏

### C. 数据采集与监控 (MCP)
- 搜索热门话题/关键词
- 监控竞品笔记数据
- 采集爆文模板分析

### D. 互动自动化 (ADB)
- 自动回复评论
- 自动私信（谨慎）
- 批量点赞同领域内容

---

## 四、关键工具

### GitHub 项目

| 项目 | Stars | 用途 | 链接 |
|------|-------|------|------|
| **MediaCrawler** | 27k+ | 多平台数据采集 | github.com/NanmiCoder/MediaCrawler |
| **xiaohongshu-mcp** | 11k+ | MCP 发布/搜索/登录 | github.com/xpzouying/xiaohongshu-mcp |
| **xhs-auto** | - | ADB 真机养号/互动 | github.com/lonerge/xhs-auto |
| **xhs_ai_publisher** | - | AI 生成 + 自动发布 | github.com/BetaStreetOmnis/xhs_ai_publisher |
| **XiaoFeiShu RPA** | - | 多账号矩阵 RPA | github.com/Jici-Zeroten/XiaoFeiShu |
| **uiautomator2** | - | Python 控制 Android | github.com/openatx/uiautomator2 |

### MCP 服务器 (可接入 Claude)

| 项目 | 功能 |
|------|------|
| **xpzouying/xiaohongshu-mcp** | 登录、搜索、发布图文/视频、评论、推荐 |
| **iFurySt/RedNote-MCP** | 搜索笔记、查看详情、自动 Cookie |
| **luyike221/xiaohongshu-mcp-python** | Python 版，支持图文/视频发布 |
| **ToDieOrNot/xiaohongshu-mcp-nodejs** | 企业级，多账号矩阵 + 反风控 |

---

## 五、小红书反检测机制

| 检测层 | 手段 | 我们的应对 |
|--------|------|-----------|
| 设备指纹 | Canvas/WebGL/硬件指纹 | ✅ 真机操作，天然绕过 |
| API 签名 | x-s/x-t 动态加密 | ✅ 不走 API，走真机 UI |
| Cookie | 短时效 (~10min) | ⚠️ MCP 需自动刷新 |
| IP 检测 | 频率阈值 | ✅ 家庭网络，单设备 |
| 行为分析 | 模式识别 | ⚠️ 需随机延时+曲线滑动 |
| 账号关联 | 设备/IP/GPS 关联 | ✅ 单账号单设备 |

---

## 六、安全运营红线

### 绝对不能做
- ❌ 发微信号/二维码/外链（2025.3.12 新规严打）
- ❌ 买粉/买赞/刷量
- ❌ 短时间批量操作（固定间隔=机器人特征）
- ❌ 频繁修改资料

### 安全频率
- 发布: ≤3 篇/天，间隔 ≥2 小时
- 点赞: 3-5 次/天
- 评论: 1-2 条/天（有质量）
- 收藏: 2-3 次/天
- 每篇停留 >10 秒，滑到底再互动

### 养号周期
- 新号前 5 天：只浏览+少量互动，不发布
- Day 5-14：开始发布，每周 2 篇
- Week 3-4：测试内容方向，每天 2-3 篇
- Week 4+：稳定期，每周 5 篇

---

## 七、官方 API（有限）

- 开放平台: open.xiaohongshu.com（主要面向电商商家）
- 能力: 订单管理、商品管理、笔记数据查询
- **不提供**: 通用内容搜索、笔记发布 API
- 结论: 内容自动化只能走浏览器/真机路线
