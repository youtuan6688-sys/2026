"""每日热点资讯 — 基于前一天群聊话题搜索相关资讯，发到各群。

流水线:
1. 读取昨天群聊 buffer，提取热点话题关键词 (haiku)
2. 用 claude + WebSearch 搜索各话题相关资讯
3. 整理成有信息增量的简报
4. 发到各飞书群
"""

import json
import logging
import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

from config.settings import settings

logger = logging.getLogger(__name__)

BUFFER_DIR = Path("/Users/tuanyou/Happycode2026/data/daily_buffer")
REPORT_DIR = Path("/Users/tuanyou/Happycode2026/data/hot_briefings")
CLAUDE_PATH = "/Users/tuanyou/.local/bin/claude"

GROUP_CHATS = [
    "oc_4f17f731a0a3bf9489c095c26be6dedc",
    "oc_d7120356187aed1e651863428e55ab47",
]


def _load_group_entries(target_date: date) -> list[dict]:
    """Load group chat entries from daily buffer."""
    entries = []

    for f in sorted(BUFFER_DIR.glob(f"{target_date.isoformat()}*.jsonl")):
        try:
            for line in f.read_text(encoding="utf-8").strip().split("\n"):
                if not line.strip():
                    continue
                entry = json.loads(line)
                if entry.get("chat_type") == "group":
                    entries.append(entry)
        except Exception as e:
            logger.warning(f"Failed to read buffer {f}: {e}")

    for f in sorted(BUFFER_DIR.glob(f"{target_date.isoformat()}*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(data, list):
                entries.extend(e for e in data if e.get("chat_type") == "group")
        except Exception:
            pass

    return entries


def _extract_topics(entries: list[dict]) -> list[str]:
    """Extract hot topics/keywords from group chat entries using haiku."""
    if not entries:
        return []

    lines = []
    for e in entries[:80]:
        user = e.get("user_name", "?")[:10]
        msg = e.get("user_msg", "")[:300]
        if msg:
            lines.append(f"{user}: {msg}")

    conv_text = "\n".join(lines)

    prompt = (
        "分析以下群聊记录，提取昨天群里讨论的热点话题和关注领域。\n\n"
        "输出 JSON 数组，每个元素是一个搜索关键词/话题（中文或英文皆可）。\n"
        "要求：\n"
        "- 提取 3-8 个话题\n"
        "- 关键词要适合用于网络搜索\n"
        "- 合并相近话题\n"
        "- 忽略闲聊/打招呼，只保留有实质内容的话题\n"
        "- 只输出 JSON 数组，不要其他内容\n\n"
        f"群聊记录：\n{conv_text}"
    )

    try:
        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
        env["PATH"] = f"/Users/tuanyou/.local/bin:{env.get('PATH', '')}"
        result = subprocess.run(
            [CLAUDE_PATH, "-p", prompt, "--model", "haiku"],
            capture_output=True, text=True, timeout=30, env=env,
        )
        output = result.stdout.strip()

        start = output.find("[")
        end = output.rfind("]") + 1
        if start >= 0 and end > start:
            topics = json.loads(output[start:end])
            logger.info(f"Extracted {len(topics)} topics: {topics}")
            return topics[:8]
    except Exception as e:
        logger.error(f"Topic extraction failed: {e}")

    return []


def _search_and_compile(topics: list[str], target_date: date) -> str:
    """Search for related news/info on each topic, compile into briefing."""
    topics_text = "\n".join(f"- {t}" for t in topics)

    prompt = (
        f"今天是 {date.today().isoformat()}。\n\n"
        f"以下是我们群里昨天（{target_date.isoformat()}）讨论的热点话题：\n"
        f"{topics_text}\n\n"
        "请针对每个话题搜索最新的相关资讯、深度分析、有趣的观点或数据。\n\n"
        "要求：\n"
        "1. 每个话题搜索 2-3 个相关信息源\n"
        "2. 提供**信息增量**——群里没聊到的新角度、新数据、最新进展\n"
        "3. 用中文输出，语气像一个见多识广的朋友在分享\n"
        "4. 每个话题 100-200 字，附来源链接\n"
        "5. 不要重复群里已经说过的内容，要补充新信息\n\n"
        "输出格式（直接输出，不要前言）：\n\n"
        "# ☀️ 早间资讯速递\n\n"
        "基于昨天群里的讨论，我搜了些相关资讯分享给大家：\n\n"
        "## 话题1标题\n内容...\n📎 来源: url\n\n"
        "## 话题2标题\n内容...\n📎 来源: url\n\n"
        "...\n\n"
        "---\n"
        "💡 今日冷知识：（一个有趣的相关知识点）\n\n"
        "如果有什么想深挖的话题，随时 @我～"
    )

    try:
        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
        env["PATH"] = f"/Users/tuanyou/.local/bin:{env.get('PATH', '')}"
        result = subprocess.run(
            [CLAUDE_PATH, "-p", prompt,
             "--allowedTools", "WebSearch,WebFetch"],
            capture_output=True, text=True, timeout=180, env=env,
        )
        output = result.stdout.strip()
        if output and len(output) > 100:
            logger.info(f"Briefing compiled: {len(output)} chars")
            return output
    except Exception as e:
        logger.error(f"Search and compile failed: {e}")

    return ""


def _send_briefing(briefing: str, target_date: date):
    """Send hot briefing to all group chats."""
    from src.feishu_sender import FeishuSender

    sender = FeishuSender(settings)

    # Truncate if too long for Feishu
    if len(briefing) > 3500:
        briefing = briefing[:3500] + "\n\n... 更多内容可以问我～"

    for chat_id in GROUP_CHATS:
        try:
            sender.send_text(chat_id, briefing)
            logger.info(f"Hot briefing sent to {chat_id}")
        except Exception as e:
            logger.error(f"Failed to send to {chat_id}: {e}")


def _save_briefing(briefing: str, topics: list[str], target_date: date):
    """Save briefing for archival."""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_file = REPORT_DIR / f"{target_date.isoformat()}.md"
    content = (
        f"# 热点资讯 [{target_date.isoformat()}]\n\n"
        f"话题: {', '.join(topics)}\n\n"
        f"---\n\n{briefing}\n"
    )
    report_file.write_text(content, encoding="utf-8")
    logger.info(f"Briefing saved to {report_file}")


def generate_hot_briefing(target_date: date | None = None):
    """Main entry: extract topics → search → compile → send."""
    yesterday = target_date or (date.today() - timedelta(days=1))
    logger.info(f"=== Hot Briefing for {yesterday} ===")

    # 1. Load yesterday's group entries
    entries = _load_group_entries(yesterday)
    logger.info(f"Loaded {len(entries)} group entries from {yesterday}")

    if not entries:
        logger.info("No group entries yesterday, skipping hot briefing")
        return

    # 2. Extract topics
    topics = _extract_topics(entries)
    if not topics:
        logger.info("No meaningful topics extracted, skipping")
        return

    # 3. Search and compile briefing
    briefing = _search_and_compile(topics, yesterday)
    if not briefing:
        logger.error("Failed to compile briefing")
        return

    # 4. Save
    _save_briefing(briefing, topics, yesterday)

    # 5. Send to groups
    _send_briefing(briefing, yesterday)

    logger.info("=== Hot Briefing Complete ===")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    target = date.today() - timedelta(days=1)
    if len(sys.argv) > 1:
        if sys.argv[1] == "today":
            target = date.today()
        else:
            target = date.fromisoformat(sys.argv[1])

    generate_hot_briefing(target)
