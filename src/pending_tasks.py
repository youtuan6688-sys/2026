"""Pending task storage and management.

Tracks tasks extracted from conversations that need follow-up.
Storage: vault/memory/pending-tasks.json
"""

import json
import logging
import uuid
from datetime import date, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

TASKS_FILE = Path("/Users/tuanyou/Happycode2026/vault/memory/pending-tasks.json")


def _generate_id() -> str:
    return uuid.uuid4().hex[:8]


def load_tasks() -> list[dict]:
    """Load all pending tasks from disk."""
    try:
        if TASKS_FILE.exists():
            return json.loads(TASKS_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error(f"Failed to load pending tasks: {e}")
    return []


def save_tasks(tasks: list[dict]):
    """Persist tasks to disk."""
    try:
        TASKS_FILE.parent.mkdir(parents=True, exist_ok=True)
        TASKS_FILE.write_text(
            json.dumps(tasks, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        logger.error(f"Failed to save pending tasks: {e}")


def add_task(user_id: str, user_name: str, description: str,
             source_date: str, chat_id: str, chat_type: str,
             due_date: str | None = None) -> dict:
    """Add a new pending task.

    Args:
        user_id: User's open_id
        user_name: Display name
        description: What needs to be done
        source_date: Date the task was mentioned (YYYY-MM-DD)
        chat_id: Chat where task was mentioned
        chat_type: "group" or "p2p"
        due_date: Optional due date (YYYY-MM-DD)

    Returns:
        The created task dict.
    """
    tasks = load_tasks()

    # Dedup: skip if same user + very similar description exists
    for t in tasks:
        if (t["user_id"] == user_id
                and t["status"] == "pending"
                and t["description"] == description):
            logger.info(f"Duplicate task skipped: {description[:50]}")
            return t

    task = {
        "task_id": _generate_id(),
        "user_id": user_id,
        "user_name": user_name,
        "description": description,
        "source_date": source_date,
        "due_date": due_date,
        "chat_id": chat_id,
        "chat_type": chat_type,
        "status": "pending",  # pending | reminded | done | dismissed
        "reminded_at": None,
        "created_at": datetime.now().isoformat(),
    }

    tasks.append(task)
    save_tasks(tasks)
    logger.info(f"Task added: [{task['task_id']}] {description[:60]}")
    return task


def get_due_tasks(target_date: date | None = None) -> list[dict]:
    """Get tasks that are due for follow-up on target_date.

    Returns tasks that are:
    - status == "pending" (not yet reminded)
    - source_date < target_date (from a previous day)
    - OR due_date <= target_date
    """
    target = target_date or date.today()
    target_str = target.isoformat()
    tasks = load_tasks()

    due = []
    for t in tasks:
        if t["status"] != "pending":
            continue
        # Task from a previous day, not yet reminded
        if t["source_date"] < target_str:
            due.append(t)
        # Or has explicit due date that's today or past
        elif t.get("due_date") and t["due_date"] <= target_str:
            due.append(t)

    return due


def get_user_pending(user_id: str) -> list[dict]:
    """Get all pending/reminded tasks for a specific user."""
    tasks = load_tasks()
    return [t for t in tasks if t["user_id"] == user_id
            and t["status"] in ("pending", "reminded")]


def mark_done(task_id: str) -> bool:
    """Mark a task as done. Returns True if found."""
    tasks = load_tasks()
    for t in tasks:
        if t["task_id"] == task_id:
            t["status"] = "done"
            t["completed_at"] = datetime.now().isoformat()
            save_tasks(tasks)
            logger.info(f"Task done: [{task_id}] {t['description'][:60]}")
            return True
    return False


def mark_reminded(task_id: str) -> bool:
    """Mark a task as reminded. Returns True if found."""
    tasks = load_tasks()
    for t in tasks:
        if t["task_id"] == task_id:
            t["status"] = "reminded"
            t["reminded_at"] = datetime.now().isoformat()
            save_tasks(tasks)
            return True
    return False


def mark_dismissed(task_id: str) -> bool:
    """Mark a task as dismissed. Returns True if found."""
    tasks = load_tasks()
    for t in tasks:
        if t["task_id"] == task_id:
            t["status"] = "dismissed"
            save_tasks(tasks)
            logger.info(f"Task dismissed: [{task_id}]")
            return True
    return False


def cleanup_old(days: int = 30):
    """Remove done/dismissed tasks older than N days."""
    tasks = load_tasks()
    cutoff = date.today().isoformat()
    # Simple: just keep tasks from the last 30 days or active ones
    kept = []
    for t in tasks:
        if t["status"] in ("pending", "reminded"):
            kept.append(t)
        elif t["source_date"] >= cutoff:
            kept.append(t)
        # else: old completed/dismissed, drop
    if len(kept) != len(tasks):
        save_tasks(kept)
        logger.info(f"Cleaned up {len(tasks) - len(kept)} old tasks")
