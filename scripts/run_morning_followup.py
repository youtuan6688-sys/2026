"""Morning follow-up: remind users about pending tasks from previous days.

Cron: 7:30am Beijing time (after daily briefing at 7:00am).
"""

import json
import logging
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

# Add project root to path
PROJECT_DIR = Path("/Users/tuanyou/Happycode2026")
sys.path.insert(0, str(PROJECT_DIR))

from config.settings import settings
from src.feishu_sender import FeishuSender
from src import pending_tasks

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)

CLAUDE_PATH = "/Users/tuanyou/.local/bin/claude"
ADMIN_ID = "ou_4a18a2e35a5b04262a24f41731046d15"


def _call_haiku(prompt: str) -> str:
    """Call Claude haiku for lightweight text generation."""
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    env["PATH"] = f"/Users/tuanyou/.local/bin:{env.get('PATH', '')}"
    try:
        result = subprocess.run(
            [CLAUDE_PATH, "-p", prompt, "--model", "haiku"],
            capture_output=True, text=True, timeout=30, env=env,
        )
        return result.stdout.strip()
    except Exception as e:
        logger.error(f"Haiku call failed: {e}")
        return ""


def send_reminders():
    """Send follow-up reminders for due tasks."""
    today = date.today()
    due = pending_tasks.get_due_tasks(today)

    if not due:
        logger.info("No pending tasks due today")
        return

    sender = FeishuSender(settings)

    # Group tasks by user for p2p, by chat_id for group
    p2p_tasks: dict[str, list[dict]] = {}
    group_tasks: dict[str, list[dict]] = {}

    for task in due:
        if task["chat_type"] == "group":
            group_tasks.setdefault(task["chat_id"], []).append(task)
        else:
            p2p_tasks.setdefault(task["user_id"], []).append(task)

    # Send private reminders
    for user_id, tasks in p2p_tasks.items():
        user_name = tasks[0].get("user_name", "")
        task_list = "\n".join(
            f"- {t['description']} (来自 {t['source_date']})"
            for t in tasks
        )

        prompt = (
            f"你是一个贴心的 AI 助手。用简短自然的语气提醒用户有未完成的事项。\n"
            f"用户名: {user_name}\n"
            f"待办事项:\n{task_list}\n\n"
            f"要求: 1-2句话，口语化，不要太正式。如果只有一条就直接说。"
            f"不要说「根据记录」这种话。"
        )
        reminder = _call_haiku(prompt)
        if not reminder:
            # Fallback: plain text
            reminder = f"昨天提到的事还需要跟进吗？\n{task_list}"

        sender.send_text(user_id, f"☀️ {reminder}")
        logger.info(f"Sent p2p reminder to {user_id}: {len(tasks)} tasks")

        # Mark as reminded
        for t in tasks:
            pending_tasks.mark_reminded(t["task_id"])

    # Send group reminders (consolidated per group)
    for chat_id, tasks in group_tasks.items():
        lines = []
        for t in tasks:
            name = t.get("user_name", "某位同学")
            lines.append(f"- {name}: {t['description']}")

        task_list = "\n".join(lines)
        prompt = (
            f"你是群聊 AI 助手「小叼毛」。用你的风格提醒群里有未完成的事。\n"
            f"待办事项:\n{task_list}\n\n"
            f"要求: 简短，嘴贱但不失礼。一段话搞定。"
        )
        reminder = _call_haiku(prompt)
        if not reminder:
            reminder = f"昨天还有几件事没搞完呢：\n{task_list}"

        sender.send_text(chat_id, f"☀️ 早间跟进\n\n{reminder}")
        logger.info(f"Sent group reminder to {chat_id}: {len(tasks)} tasks")

        for t in tasks:
            pending_tasks.mark_reminded(t["task_id"])

    # Cleanup old tasks
    pending_tasks.cleanup_old(days=30)

    # Notify admin with summary
    total = len(due)
    sender.send_text(
        ADMIN_ID,
        f"📋 晨间跟进完成：{total} 条待办已提醒 "
        f"(私聊 {len(p2p_tasks)} 人, 群聊 {len(group_tasks)} 个群)",
    )


if __name__ == "__main__":
    send_reminders()
