"""Generate and send daily group chat summary to each Feishu group.

Reads today's daily_buffer, groups messages by chat_id,
generates a separate summary per group, and sends each to its own group.
Designed to run via launchd before daily_evolution archives the buffer.
"""

import json
import logging
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import settings
from src.feishu_sender import FeishuSender
from src.quota_tracker import QuotaTracker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

BUFFER_DIR = Path("/Users/tuanyou/Happycode2026/data/daily_buffer")
MIN_MESSAGES = 3  # Skip summary if fewer than this many group messages


def load_group_messages_by_chat(target_date: date = None) -> dict[str, list[dict]]:
    """Load today's group messages, grouped by chat_id."""
    d = target_date or date.today()
    buffer_file = BUFFER_DIR / f"{d.isoformat()}.jsonl"
    if not buffer_file.exists():
        return {}

    groups: dict[str, list[dict]] = defaultdict(list)
    for line in buffer_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
            if entry.get("chat_type") == "group":
                chat_id = entry.get("chat_id", "")
                # Backwards compat: old entries without chat_id go to default
                if not chat_id:
                    chat_id = "unknown"
                groups[chat_id].append(entry)
        except json.JSONDecodeError:
            continue
    return dict(groups)


def format_conversations(messages: list[dict]) -> str:
    """Format messages into readable conversation text."""
    lines = []
    for msg in messages:
        name = msg.get("user_name", "未知")
        user_msg = msg.get("user_msg", "")
        bot_reply = msg.get("bot_reply", "")
        lines.append(f"[{name}]: {user_msg}")
        if bot_reply:
            lines.append(f"[小叼毛]: {bot_reply[:300]}")
        lines.append("")
    return "\n".join(lines)


SUMMARY_PROMPT = """你是一个群聊日报编辑，风格幽默、简洁。
以下是今天群聊的所有对话记录。请生成一份"今日群聊回顾"，要求：

1. 用 3-5 个要点总结今天聊了什么（每个要点一句话）
2. 选出一条"今日最佳发言"（最有趣/最有料的）
3. 给今天的群聊氛围打个分（1-10），配一句点评
4. 语气轻松有趣，符合小叼毛的人设（雅痞、嘴贱、但靠谱）

格式：
📋 今日群聊回顾 ({date})

💬 聊了啥：
• ...
• ...

🏆 今日最佳：
"原文" —— 点评

🌡️ 氛围指数：X/10
点评一句话

---
对话记录：
{conversations}"""


def main():
    today = date.today()
    groups = load_group_messages_by_chat(today)

    if not groups:
        logger.info("No group messages today, skipping summary")
        return

    tracker = QuotaTracker()
    sender = FeishuSender(settings)

    for chat_id, messages in groups.items():
        if len(messages) < MIN_MESSAGES:
            logger.info(
                f"Chat {chat_id}: only {len(messages)} messages, "
                f"skipping (min={MIN_MESSAGES})"
            )
            continue

        if chat_id == "unknown":
            logger.warning("Skipping messages without chat_id (old format)")
            continue

        conversations = format_conversations(messages)
        prompt = SUMMARY_PROMPT.format(
            date=today.isoformat(),
            conversations=conversations,
        )

        summary = tracker.call_claude(prompt, model="sonnet", timeout=60)
        if not summary:
            logger.warning(f"Failed to generate summary for chat {chat_id}")
            continue

        sender.send_text(chat_id, summary)
        logger.info(f"Summary sent to {chat_id} ({len(messages)} messages)")


if __name__ == "__main__":
    main()
