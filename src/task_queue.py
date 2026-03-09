"""
Task Queue for autonomous Claude Code evolution.

Breaks large tasks into small, independent units that each run
in a separate `claude -p` session. Solves context exhaustion and
timeout problems by keeping each task focused and short.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

QUEUE_FILE = Path("/Users/tuanyou/Happycode2026/vault/tasks/queue.json")
HISTORY_FILE = Path("/Users/tuanyou/Happycode2026/vault/tasks/history.json")
MAX_HISTORY = 200


class Task:
    """Immutable task definition."""

    def __init__(
        self,
        task_id: str,
        title: str,
        prompt: str,
        priority: int = 5,
        category: str = "evolution",
        timeout_seconds: int = 120,
        depends_on: Optional[list[str]] = None,
        status: str = "pending",
        result: str = "",
        error: str = "",
        created_at: Optional[str] = None,
        started_at: Optional[str] = None,
        completed_at: Optional[str] = None,
        retry_count: int = 0,
        max_retries: int = 2,
    ):
        self.task_id = task_id
        self.title = title
        self.prompt = prompt
        self.priority = priority  # 1=highest, 10=lowest
        self.category = category
        self.timeout_seconds = timeout_seconds
        self.depends_on = depends_on or []
        self.status = status  # pending, running, completed, failed, skipped
        self.result = result
        self.error = error
        self.created_at = created_at or datetime.now().isoformat()
        self.started_at = started_at
        self.completed_at = completed_at
        self.retry_count = retry_count
        self.max_retries = max_retries

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "title": self.title,
            "prompt": self.prompt,
            "priority": self.priority,
            "category": self.category,
            "timeout_seconds": self.timeout_seconds,
            "depends_on": self.depends_on,
            "status": self.status,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
        }

    @staticmethod
    def from_dict(data: dict) -> "Task":
        return Task(
            task_id=data["task_id"],
            title=data.get("title", ""),
            prompt=data.get("prompt", ""),
            priority=data.get("priority", 5),
            category=data.get("category", "evolution"),
            timeout_seconds=data.get("timeout_seconds", 120),
            depends_on=data.get("depends_on", []),
            status=data.get("status", "pending"),
            result=data.get("result", ""),
            error=data.get("error", ""),
            created_at=data.get("created_at"),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            retry_count=data.get("retry_count", 0),
            max_retries=data.get("max_retries", 2),
        )


class TaskQueue:
    """Persistent task queue with priority scheduling and checkpoint integration."""

    def __init__(
        self,
        queue_file: Path = QUEUE_FILE,
        history_file: Path = HISTORY_FILE,
        checkpoint_manager=None,
    ):
        self._queue_file = queue_file
        self._history_file = history_file
        self._checkpoint_manager = checkpoint_manager
        self._tasks: list[dict] = self._load(queue_file)
        self._history: list[dict] = self._load(history_file)

    def _load(self, path: Path) -> list[dict]:
        try:
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
        return []

    def _save_queue(self):
        self._queue_file.parent.mkdir(parents=True, exist_ok=True)
        self._queue_file.write_text(
            json.dumps(self._tasks, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _save_history(self):
        self._history_file.parent.mkdir(parents=True, exist_ok=True)
        if len(self._history) > MAX_HISTORY:
            self._history = self._history[-MAX_HISTORY:]
        self._history_file.write_text(
            json.dumps(self._history, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def add(self, task: Task) -> Task:
        """Add a task to the queue."""
        # Check for duplicate task_id
        for t in self._tasks:
            if t["task_id"] == task.task_id:
                logger.warning(f"Task {task.task_id} already exists, skipping")
                return Task.from_dict(t)
        self._tasks.append(task.to_dict())
        self._save_queue()
        logger.info(f"Task added: {task.task_id} - {task.title}")
        return task

    def next(self) -> Optional[Task]:
        """Get the next runnable task (highest priority, dependencies met)."""
        completed_ids = {
            t["task_id"]
            for t in self._tasks + self._history
            if t.get("status") == "completed"
        }

        candidates = []
        for t in self._tasks:
            if t["status"] != "pending":
                continue
            deps = t.get("depends_on", [])
            if all(d in completed_ids for d in deps):
                candidates.append(t)

        if not candidates:
            return None

        # Sort by priority (lower number = higher priority)
        candidates.sort(key=lambda x: x.get("priority", 5))
        return Task.from_dict(candidates[0])

    def mark_running(self, task_id: str):
        """Mark a task as running."""
        for t in self._tasks:
            if t["task_id"] == task_id:
                t["status"] = "running"
                t["started_at"] = datetime.now().isoformat()
                self._save_queue()
                return

    def mark_completed(self, task_id: str, result: str = ""):
        """Mark a task as completed and move to history. Updates checkpoint if linked."""
        for i, t in enumerate(self._tasks):
            if t["task_id"] == task_id:
                t["status"] = "completed"
                t["completed_at"] = datetime.now().isoformat()
                t["result"] = result[:2000]
                self._history.append(t)
                self._tasks.pop(i)
                self._save_queue()
                self._save_history()
                self._sync_checkpoint(task_id, "done", result[:200])
                return

    def mark_failed(self, task_id: str, error: str = ""):
        """Mark task as failed; retry if under max_retries."""
        for i, t in enumerate(self._tasks):
            if t["task_id"] == task_id:
                t["retry_count"] = t.get("retry_count", 0) + 1
                if t["retry_count"] <= t.get("max_retries", 2):
                    t["status"] = "pending"  # will be retried
                    t["error"] = error[:500]
                    logger.info(
                        f"Task {task_id} failed, will retry "
                        f"({t['retry_count']}/{t['max_retries']})"
                    )
                else:
                    t["status"] = "failed"
                    t["error"] = error[:500]
                    t["completed_at"] = datetime.now().isoformat()
                    self._history.append(t)
                    self._tasks.pop(i)
                    logger.warning(f"Task {task_id} failed permanently: {error[:100]}")
                self._save_queue()
                self._save_history()
                return

    def get_pending_count(self) -> int:
        return sum(1 for t in self._tasks if t.get("status") == "pending")

    def get_running_count(self) -> int:
        return sum(1 for t in self._tasks if t.get("status") == "running")

    def get_all(self) -> list[Task]:
        return [Task.from_dict(t) for t in self._tasks]

    def get_stats(self) -> dict:
        pending = sum(1 for t in self._tasks if t["status"] == "pending")
        running = sum(1 for t in self._tasks if t["status"] == "running")
        completed = sum(1 for t in self._history if t["status"] == "completed")
        failed = sum(1 for t in self._history if t["status"] == "failed")
        return {
            "pending": pending,
            "running": running,
            "completed": completed,
            "failed": failed,
            "total_queued": len(self._tasks),
            "total_history": len(self._history),
        }

    def format_status(self) -> str:
        """Human-readable queue status."""
        stats = self.get_stats()
        lines = [
            f"Task Queue: {stats['pending']} pending, "
            f"{stats['running']} running, "
            f"{stats['completed']} completed, "
            f"{stats['failed']} failed",
        ]
        # Show next 3 pending tasks
        pending = [t for t in self._tasks if t["status"] == "pending"]
        pending.sort(key=lambda x: x.get("priority", 5))
        for t in pending[:3]:
            lines.append(f"  [{t['priority']}] {t['title']}")
        return "\n".join(lines)

    def _sync_checkpoint(self, task_id: str, status: str, progress: str = ""):
        """Sync task completion/failure to the linked checkpoint step."""
        if not self._checkpoint_manager:
            return
        try:
            checkpoint = self._checkpoint_manager.load()
            if not checkpoint:
                return
            for step in checkpoint.steps:
                if task_id in step.queue_task_ids:
                    # Check if ALL queue tasks for this step are done
                    all_done = all(
                        self._is_task_done(tid)
                        for tid in step.queue_task_ids
                        if tid != task_id
                    )
                    step_status = "done" if (status == "done" and all_done) else status
                    self._checkpoint_manager.update_step(
                        checkpoint, step.name, step_status, progress,
                    )
                    break
        except Exception as e:
            logger.warning(f"Checkpoint sync failed: {e}")

    def _is_task_done(self, task_id: str) -> bool:
        """Check if a task is completed (in queue or history)."""
        for t in self._tasks + self._history:
            if t["task_id"] == task_id and t["status"] == "completed":
                return True
        return False

    def clear_stale_running(self, max_age_minutes: int = 30):
        """Reset running tasks that seem stuck (no heartbeat)."""
        now = datetime.now()
        for t in self._tasks:
            if t["status"] != "running":
                continue
            started = t.get("started_at")
            if not started:
                continue
            started_dt = datetime.fromisoformat(started)
            age = (now - started_dt).total_seconds() / 60
            if age > max_age_minutes:
                t["status"] = "pending"
                t["error"] = f"auto-reset: stuck running for {age:.0f}min"
                logger.warning(f"Reset stale task: {t['task_id']}")
        self._save_queue()
