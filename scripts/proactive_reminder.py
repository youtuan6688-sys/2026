"""Proactive reminder: checks pending tasks and unresolved errors, notifies via Feishu."""

import json
import sys
from pathlib import Path

# Add project root to path
PROJECT_DIR = Path("/Users/tuanyou/Happycode2026")
sys.path.insert(0, str(PROJECT_DIR))

from src.task_queue import TaskQueue
from src.utils.error_tracker import ErrorTracker
from src.feishu_sender import FeishuSender


QUEUE_FILE = PROJECT_DIR / "vault/tasks/queue.json"
HISTORY_FILE = PROJECT_DIR / "vault/tasks/history.json"
ERROR_LOG = PROJECT_DIR / "vault/logs/error_log.json"


def build_reminder() -> str | None:
    """Build reminder message. Returns None if nothing to report."""
    parts = []

    # Check task queue
    try:
        q = TaskQueue(queue_file=QUEUE_FILE, history_file=HISTORY_FILE)
        stats = q.get_stats()
        pending = stats.get("pending", 0)
        failed = stats.get("failed", 0)
        if pending > 0 or failed > 0:
            lines = [f"Task Queue: {pending} pending, {failed} failed"]
            pending_tasks = [t for t in q.get_all() if t.status == "pending"]
            pending_tasks.sort(key=lambda t: t.priority)
            for t in pending_tasks[:3]:
                lines.append(f"  [{t.priority}] {t.title}")
            parts.append("\n".join(lines))
    except Exception as e:
        parts.append(f"Task queue check failed: {e}")

    # Check unresolved errors
    try:
        tracker = ErrorTracker(log_file=ERROR_LOG)
        error_stats = tracker.get_stats()
        unresolved = error_stats.get("unresolved", 0)
        if unresolved > 0:
            lines = [f"Unresolved errors: {unresolved}"]
            recent = tracker.get_recent(3, unresolved_only=True)
            for e in recent:
                lines.append(f"  [{e.get('severity', '?').upper()}] {e.get('error_type', '?')}: {e.get('message', '')[:60]}")
            parts.append("\n".join(lines))
    except Exception as e:
        parts.append(f"Error log check failed: {e}")

    if not parts:
        return None

    return "Proactive Reminder\n\n" + "\n\n".join(parts)


def main():
    reminder = build_reminder()
    if not reminder:
        print("Nothing to report.")
        return

    print(reminder)

    # Send to Feishu
    try:
        sender = FeishuSender()
        # Use the bot owner's open_id from env or config
        import os
        owner_id = os.environ.get("FEISHU_OWNER_OPEN_ID", "")
        if owner_id:
            sender.send_text(owner_id, reminder)
            print(f"Sent reminder to {owner_id}")
        else:
            print("FEISHU_OWNER_OPEN_ID not set, skipping Feishu notification")
    except Exception as e:
        print(f"Failed to send Feishu notification: {e}")


if __name__ == "__main__":
    main()
