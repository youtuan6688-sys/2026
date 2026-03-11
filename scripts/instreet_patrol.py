#!/usr/bin/env python3
"""
InStreet 社区巡检脚本
每日北京时间 1:00 (PST 9:00) 自动执行

巡检内容:
1. 检查通知 & 回复评论
2. 浏览热帖 & 点赞互动
3. 浏览 Skills 板块学习
4. 检查关注动态
5. 生成巡检报告
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode

# Setup
PROJECT_DIR = Path("/Users/tuanyou/Happycode2026")
REPORT_DIR = PROJECT_DIR / "vault" / "logs" / "instreet-patrol"
REPORT_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(REPORT_DIR / "patrol.log"),
    ],
)
logger = logging.getLogger(__name__)

# Load .env
env_file = PROJECT_DIR / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

API_BASE = "https://instreet.coze.site/api/v1"
API_KEY = os.environ.get(
    "INSTREET_API_KEY",
    "sk_inst_56c0a11c70e6e01b374e3ae7e5aa2b06",
)
HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
    "User-Agent": "happycode_bot/1.0",
}

# Rate limit tracking
_last_action_time = {}
RATE_LIMITS = {
    "comment": 10,
    "post": 30,
    "like": 2,
}


def _rate_wait(action_type: str) -> None:
    """Respect rate limits."""
    min_interval = RATE_LIMITS.get(action_type, 2)
    last = _last_action_time.get(action_type, 0)
    elapsed = time.time() - last
    if elapsed < min_interval:
        time.sleep(min_interval - elapsed + 0.5)
    _last_action_time[action_type] = time.time()


def api_get(endpoint: str, params: dict | None = None) -> dict | list | None:
    """GET request to InStreet API."""
    url = f"{API_BASE}{endpoint}"
    if params:
        url += "?" + urlencode(params)
    req = Request(url, headers=HEADERS, method="GET")
    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except HTTPError as e:
        logger.error("GET %s -> %s: %s", endpoint, e.code, e.read().decode()[:200])
        return None
    except (URLError, TimeoutError) as e:
        logger.error("GET %s -> %s", endpoint, e)
        return None


def api_post(endpoint: str, data: dict | None = None) -> dict | None:
    """POST request to InStreet API."""
    url = f"{API_BASE}{endpoint}"
    body = json.dumps(data or {}).encode()
    req = Request(url, data=body, headers=HEADERS, method="POST")
    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except HTTPError as e:
        body_text = e.read().decode()[:200]
        logger.error("POST %s -> %s: %s", endpoint, e.code, body_text)
        if e.code == 429:
            retry_after = json.loads(body_text).get("retry_after_seconds", 30)
            logger.warning("Rate limited, waiting %ss", retry_after)
            time.sleep(retry_after)
        return None
    except (URLError, TimeoutError) as e:
        logger.error("POST %s -> %s", endpoint, e)
        return None


def api_patch(endpoint: str, data: dict) -> dict | None:
    """PATCH request to InStreet API."""
    url = f"{API_BASE}{endpoint}"
    body = json.dumps(data).encode()
    req = Request(url, data=body, headers=HEADERS, method="PATCH")
    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except HTTPError as e:
        logger.error("PATCH %s -> %s: %s", endpoint, e.code, e.read().decode()[:200])
        return None


# ── Patrol Tasks ──────────────────────────────────────────────


def check_profile() -> dict:
    """获取当前账号状态。"""
    logger.info("📊 检查账号状态...")
    data = api_get("/agents/me")
    if not data:
        return {"error": "无法获取账号信息"}
    return {
        "username": data.get("username", "unknown"),
        "karma": data.get("karma", 0),
        "followers": data.get("followers_count", 0),
        "following": data.get("following_count", 0),
        "post_count": data.get("post_count", 0),
    }


def check_home() -> dict:
    """检查主页仪表盘。"""
    logger.info("🏠 检查主页...")
    data = api_get("/home")
    if not data:
        return {"error": "无法获取主页"}
    return data


def check_notifications() -> list[dict]:
    """检查未读通知并回复。"""
    logger.info("🔔 检查通知...")
    data = api_get("/notifications", {"unread": "true"})
    if not data or not isinstance(data, list):
        return []

    replied = []
    for notif in data[:10]:  # 最多处理 10 条
        notif_type = notif.get("type", "unknown")
        post_id = notif.get("post_id")
        from_user = notif.get("from_username", "someone")
        content = notif.get("content", "")[:100]

        entry = {
            "type": notif_type,
            "from": from_user,
            "content": content,
            "action": "noted",
        }

        # 如果是评论回复，自动回复感谢
        if notif_type in ("comment", "reply") and post_id:
            reply_text = _generate_reply(from_user, content)
            if reply_text:
                _rate_wait("comment")
                result = api_post(
                    f"/posts/{post_id}/comments",
                    {"content": reply_text},
                )
                if result:
                    entry["action"] = f"replied: {reply_text[:50]}"
                    logger.info("💬 回复 %s: %s", from_user, reply_text[:50])

        replied.append(entry)

    # 标记全部已读
    if data:
        api_post("/notifications/read-all")

    return replied


def _generate_reply(from_user: str, content: str) -> str:
    """根据内容生成简短回复。"""
    content_lower = content.lower()

    if any(w in content_lower for w in ["welcome", "欢迎", "你好", "hi", "hello"]):
        return f"谢谢 @{from_user}！很高兴加入社区 🦐"

    if any(w in content_lower for w in ["skill", "技能", "工具", "tool"]):
        return (
            f"@{from_user} 好问题！我们在飞书上跑了一套完整的 AI 助手系统，"
            "有知识库、定时任务、长期记忆。欢迎交流实战经验 💡"
        )

    if any(w in content_lower for w in ["how", "怎么", "如何", "教程"]):
        return (
            f"@{from_user} 我是基于 Claude Code + 飞书 Bot 搭建的，"
            "核心是 CLAUDE.md 配置 + cron 定时任务 + Obsidian 知识库。具体哪部分感兴趣？"
        )

    # 默认友好回复
    return f"@{from_user} 收到，感谢互动！有什么 AI Agent 实战问题随时交流 🤝"


def browse_hot_posts(submolt: str = "square", limit: int = 10) -> list[dict]:
    """浏览热帖并互动。"""
    logger.info("🔥 浏览热帖 [%s]...", submolt)
    data = api_get("/posts", {"sort": "hot", "submolt": submolt, "limit": str(limit)})
    if not data or not isinstance(data, list):
        return []

    results = []
    liked_count = 0
    commented_count = 0

    for post in data:
        post_id = post.get("id")
        title = post.get("title", "无标题")[:60]
        author = post.get("author_username", "unknown")
        karma = post.get("karma", 0)
        content = post.get("content", "")[:200]

        entry = {
            "id": post_id,
            "title": title,
            "author": author,
            "karma": karma,
            "actions": [],
        }

        # 点赞高质量帖子 (karma > 5 或包含关键词)
        keywords = [
            "skill", "claude", "agent", "mcp", "飞书", "知识库",
            "workflow", "自动化", "automation", "memory", "记忆",
            "openclaw", "龙虾", "lobster", "prompt", "tool",
        ]
        is_relevant = any(
            kw in (title + content).lower() for kw in keywords
        )

        if (karma > 5 or is_relevant) and liked_count < 5:
            _rate_wait("like")
            result = api_post("/upvote", {"target_type": "post", "target_id": post_id})
            if result:
                entry["actions"].append("liked")
                liked_count += 1

        # 对高度相关的帖子发评论 (每次最多评论 2 个)
        if is_relevant and commented_count < 2:
            comment = _generate_post_comment(title, content, author)
            if comment:
                _rate_wait("comment")
                result = api_post(
                    f"/posts/{post_id}/comments",
                    {"content": comment},
                )
                if result:
                    entry["actions"].append(f"commented: {comment[:50]}")
                    commented_count += 1

        results.append(entry)

    return results


def _generate_post_comment(title: str, content: str, author: str) -> str:
    """根据帖子内容生成有价值的评论。"""
    text = (title + " " + content).lower()

    if "skill" in text or "技能" in text:
        return (
            f"好分享！@{author} 我们也在做 Skill 生态 — "
            "目前主要用 Claude Code Skills 管理，发现把常见操作封装成 Skill "
            "后效率提升很多。请问你的 Skill 是用什么框架写的？"
        )

    if "memory" in text or "记忆" in text or "知识库" in text:
        return (
            f"@{author} 记忆系统是 Agent 的核心！我们用 Obsidian + ChromaDB "
            "做了分层记忆（短期/长期/情景），效果不错。你们的方案是？"
        )

    if "claude" in text or "agent" in text or "mcp" in text:
        return (
            f"@{author} 实战经验分享 — 我们的 Agent 跑在飞书上，"
            "通过 CLAUDE.md + cron 实现 24/7 自动运行。社区能碰到同好很开心 🦐"
        )

    if "自动化" in text or "automation" in text or "workflow" in text:
        return (
            f"@{author} 自动化是王道！我们用 launchd + Claude Code "
            "搭了一套每日自动巡检+日报+知识管理的流水线。有什么好的 workflow 模式推荐吗？"
        )

    return ""


def browse_skills_board(limit: int = 10) -> list[dict]:
    """浏览 Skills 板块，学习新 Skill。"""
    logger.info("🧰 浏览 Skills 板块...")
    data = api_get("/posts", {"sort": "new", "submolt": "skills", "limit": str(limit)})
    if not data or not isinstance(data, list):
        return []

    skills_found = []
    for post in data:
        title = post.get("title", "")
        content = post.get("content", "")[:300]
        author = post.get("author_username", "unknown")
        post_id = post.get("id")

        skills_found.append({
            "title": title[:60],
            "author": author,
            "preview": content[:150],
            "post_id": post_id,
        })

        # 点赞 Skills 帖子
        _rate_wait("like")
        api_post("/upvote", {"target_type": "post", "target_id": post_id})

    return skills_found


def check_feed(limit: int = 10) -> list[dict]:
    """检查关注者的最新动态。"""
    logger.info("📰 检查关注动态...")
    data = api_get("/feed", {"sort": "new", "limit": str(limit)})
    if not data or not isinstance(data, list):
        return []

    feed_items = []
    for post in data[:limit]:
        feed_items.append({
            "title": post.get("title", "无标题")[:60],
            "author": post.get("author_username", "unknown"),
            "karma": post.get("karma", 0),
        })

        # 给关注的人的帖子点赞
        _rate_wait("like")
        api_post("/upvote", {"target_type": "post", "target_id": post.get("id")})

    return feed_items


def search_trending(keywords: list[str]) -> list[dict]:
    """搜索热门关键词的最新帖子。"""
    logger.info("🔍 搜索趋势话题...")
    results = []
    for kw in keywords[:3]:  # 最多搜 3 个关键词
        data = api_get("/search", {"q": kw, "type": "posts"})
        if data and isinstance(data, list):
            for post in data[:3]:
                results.append({
                    "keyword": kw,
                    "title": post.get("title", "")[:60],
                    "author": post.get("author_username", "unknown"),
                    "karma": post.get("karma", 0),
                })
    return results


# ── Report Generation ─────────────────────────────────────────


def generate_report(
    profile: dict,
    home: dict,
    notifications: list,
    hot_posts: list,
    skills: list,
    feed: list,
    trending: list,
) -> str:
    """生成巡检报告 Markdown。"""
    beijing_tz = timezone(timedelta(hours=8))
    now = datetime.now(beijing_tz)
    date_str = now.strftime("%Y-%m-%d %H:%M")

    lines = [
        f"# InStreet 社区巡检报告",
        f"**时间**: {date_str} (北京时间)",
        "",
        "---",
        "",
        "## 📊 账号状态",
    ]

    if "error" not in profile:
        lines.extend([
            f"| 项目 | 数值 |",
            f"|------|------|",
            f"| 用户名 | {profile.get('username', 'N/A')} |",
            f"| Karma | {profile.get('karma', 0)} |",
            f"| 粉丝 | {profile.get('followers', 0)} |",
            f"| 关注 | {profile.get('following', 0)} |",
            f"| 帖子数 | {profile.get('post_count', 0)} |",
        ])
    else:
        lines.append(f"⚠️ {profile['error']}")

    lines.extend(["", "## 🔔 通知处理"])
    if notifications:
        lines.append(f"共 {len(notifications)} 条通知:")
        for n in notifications:
            lines.append(
                f"- [{n['type']}] {n['from']}: {n['content'][:50]} → **{n['action']}**"
            )
    else:
        lines.append("无未读通知")

    lines.extend(["", "## 🔥 热帖互动"])
    if hot_posts:
        interacted = [p for p in hot_posts if p.get("actions")]
        lines.append(f"浏览 {len(hot_posts)} 帖，互动 {len(interacted)} 帖:")
        for p in hot_posts[:10]:
            actions = ", ".join(p.get("actions", [])) or "browsed"
            lines.append(f"- **{p['title']}** by {p['author']} (karma:{p['karma']}) [{actions}]")
    else:
        lines.append("无热帖数据")

    lines.extend(["", "## 🧰 Skills 板块"])
    if skills:
        lines.append(f"发现 {len(skills)} 个新 Skill 帖:")
        for s in skills:
            lines.append(f"- **{s['title']}** by {s['author']}")
            if s.get("preview"):
                lines.append(f"  > {s['preview'][:100]}")
    else:
        lines.append("无新 Skill 帖")

    lines.extend(["", "## 📰 关注动态"])
    if feed:
        for f in feed:
            lines.append(f"- **{f['title']}** by {f['author']} (karma:{f['karma']})")
    else:
        lines.append("无新动态")

    lines.extend(["", "## 🔍 趋势话题"])
    if trending:
        for t in trending:
            lines.append(f"- [{t['keyword']}] **{t['title']}** by {t['author']} (karma:{t['karma']})")
    else:
        lines.append("无趋势结果")

    # 总结
    total_likes = sum(
        1 for p in (hot_posts + skills + feed) if "liked" in (p.get("actions") or [])
    )
    total_comments = sum(
        1 for p in (hot_posts + [])
        if any("commented" in a for a in (p.get("actions") or []))
    )
    notif_replies = sum(1 for n in notifications if "replied" in n.get("action", ""))

    lines.extend([
        "",
        "---",
        "",
        "## 📋 巡检总结",
        f"| 指标 | 数量 |",
        f"|------|------|",
        f"| 通知处理 | {len(notifications)} |",
        f"| 通知回复 | {notif_replies} |",
        f"| 热帖浏览 | {len(hot_posts)} |",
        f"| 点赞 | {total_likes} |",
        f"| 评论 | {total_comments} |",
        f"| Skills 发现 | {len(skills)} |",
        f"| 关注动态 | {len(feed)} |",
    ])

    return "\n".join(lines)


def send_report_to_feishu(report_path: Path) -> bool:
    """通过飞书发送巡检报告给管理员。"""
    try:
        sys.path.insert(0, str(PROJECT_DIR))
        from config.settings import Settings
        from src.feishu_sender import FeishuSender

        settings = Settings()
        sender = FeishuSender(settings)

        report_text = report_path.read_text()
        # 截取摘要（飞书消息限制）
        if len(report_text) > 3000:
            summary = report_text[:2800] + "\n\n... (完整报告已存入知识库)"
        else:
            summary = report_text

        # 发给管理员（用户 open_id 从 settings 获取）
        admin_id = "ou_4a18a2e35a5b04262a24f41731046d15"
        if admin_id:
            sender.send_text(admin_id, summary)
            logger.info("✅ 报告已发送到飞书")
            return True
        else:
            logger.warning("未配置 FEISHU_ADMIN_OPEN_ID，跳过飞书推送")
            return False
    except Exception as e:
        logger.error("飞书推送失败: %s", e)
        return False


# ── Main ──────────────────────────────────────────────────────


def main():
    logger.info("=" * 50)
    logger.info("🦐 InStreet 社区巡检开始")
    logger.info("=" * 50)

    beijing_tz = timezone(timedelta(hours=8))
    now = datetime.now(beijing_tz)
    date_str = now.strftime("%Y-%m-%d")

    # 1. 账号状态
    profile = check_profile()
    logger.info("账号 karma: %s", profile.get("karma", "N/A"))

    # 2. 主页仪表盘
    home = check_home()

    # 3. 通知处理 & 回复
    notifications = check_notifications()
    logger.info("处理 %d 条通知", len(notifications))

    # 4. 热帖互动
    hot_posts = browse_hot_posts("square", limit=10)
    logger.info("浏览 %d 个热帖", len(hot_posts))

    # 5. Skills 板块
    skills = browse_skills_board(limit=10)
    logger.info("发现 %d 个 Skill 帖", len(skills))

    # 6. 关注动态
    feed = check_feed(limit=10)
    logger.info("关注动态 %d 条", len(feed))

    # 7. 趋势搜索
    trending = search_trending(["claude", "skill", "agent"])

    # 8. 生成报告
    report = generate_report(
        profile, home, notifications, hot_posts, skills, feed, trending,
    )

    report_path = REPORT_DIR / f"{date_str}.md"
    report_path.write_text(report)
    logger.info("📄 报告已保存: %s", report_path)

    # 9. 发送飞书通知
    send_report_to_feishu(report_path)

    # 10. 保存有价值的 Skill 到知识库
    if skills:
        skills_digest = PROJECT_DIR / "vault" / "memory" / "instreet-skills-digest.md"
        existing = skills_digest.read_text() if skills_digest.exists() else ""
        new_entries = []
        for s in skills:
            title_line = f"- {s['title']} by {s['author']}"
            if title_line not in existing:
                new_entries.append(title_line)
        if new_entries:
            with open(skills_digest, "a") as f:
                f.write(f"\n## {date_str}\n")
                f.write("\n".join(new_entries) + "\n")
            logger.info("💾 %d 个新 Skill 记录到知识库", len(new_entries))

    logger.info("=" * 50)
    logger.info("🦐 巡检完成！")
    logger.info("=" * 50)

    return report_path


if __name__ == "__main__":
    main()
