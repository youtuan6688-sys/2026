"""Long task auto-continuation for private chat.

When a user sends a multi-step task (e.g., "一步步完成"), the bot should
automatically continue executing steps until the task is done, rather than
stopping after a single Claude invocation.

Flow:
  1. User message detected as multi-step → LongTaskManager.start()
  2. _execute_claude() completes one step → check should_continue()
  3. If Claude's output has continuation signals → auto-trigger next step
  4. Repeat until: task complete / max steps / user sends new message / error
"""

import json
import logging
import re
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

LONG_TASK_FILE = Path("/Users/tuanyou/Happycode2026/data/long_task.json")
MAX_AUTO_STEPS = 10
STEP_COOLDOWN_S = 5  # seconds between auto-steps

# Module-level lock: shared across all LongTaskManager instances
_GLOBAL_LOCK = threading.Lock()

# Per-sender continuation guard: prevents duplicate step scheduling
_step_in_flight: set[str] = set()
_step_in_flight_lock = threading.Lock()

# Signals that user wants multi-step execution
_MULTI_STEP_PATTERNS = re.compile(
    r"(一步步|逐步|step.by.step|按步骤|分步|依次|开始.*任务|开始你的|"
    r"继续.*完成|一个个|全部完成|都做完|挨个)"
)

# Signals that Claude has more work to do
_CONTINUE_SIGNALS = re.compile(
    r"(下一步[：:是]|接下来[我将要]|待完成|TODO|Phase \d|Step \d|"
    r"然后[我将]|还需要|接着[我将要]|下面[我将要开]|"
    r"下一个任务|继续[实现完成]|下一阶段|还有\d+[个项步])"
)

# Signals that Claude thinks it's done
_DONE_SIGNALS = re.compile(
    r"(全部完成|所有.*完成|任务.*完成|已全部|大功告成|全部搞定|"
    r"所有步骤.*完成|以上就是全部|至此.*完成|到这里.*结束)"
)


@dataclass
class LongTask:
    task_id: str
    original_prompt: str
    sender_id: str
    session_id: str = ""
    status: str = "active"  # active, completed, paused, failed, interrupted
    steps_completed: int = 0
    max_steps: int = MAX_AUTO_STEPS
    last_output: str = ""
    step_results: list[str] = field(default_factory=list)  # per-step summary (max 200 chars each)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())


class LongTaskManager:
    """Manage long-running auto-continuation tasks."""

    def __init__(self):
        pass  # All state is module-level (lock, file)

    def is_multi_step_request(self, text: str) -> bool:
        """Check if user message signals a multi-step task."""
        return bool(_MULTI_STEP_PATTERNS.search(text[:200]))

    def start(self, prompt: str, sender_id: str, session_id: str = "") -> LongTask:
        """Create and persist a new long task."""
        task = LongTask(
            task_id=f"long-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
            original_prompt=prompt[:2000],
            sender_id=sender_id,
            session_id=session_id,
        )
        self._save(task)
        logger.info(f"Long task started: {task.task_id} | {prompt[:80]}")
        return task

    def get_active(self, sender_id: str) -> LongTask | None:
        """Get the active long task for a sender, if any."""
        task = self._load()
        if task and task.status == "active" and task.sender_id == sender_id:
            return task
        return None

    def should_continue(self, output: str) -> bool:
        """Check if Claude's output indicates more work to do."""
        if not output:
            return False
        # Check last 500 chars for signals
        tail = output[-500:]
        if _DONE_SIGNALS.search(tail):
            return False
        return bool(_CONTINUE_SIGNALS.search(tail))

    def record_step(self, output: str) -> LongTask | None:
        """Record a completed step. Returns updated task or None if done/exhausted."""
        task = self._load()
        if not task or task.status != "active":
            return None

        task.steps_completed += 1
        task.last_output = output[-500:]
        task.step_results.append(output[:200].strip())
        task.updated_at = datetime.now().isoformat()

        if task.steps_completed >= task.max_steps:
            task.status = "completed"
            logger.info(f"Long task {task.task_id} hit max steps ({task.max_steps})")

        self._save(task)
        return task

    def complete(self, reason: str = "done") -> None:
        """Mark active task as completed."""
        task = self._load()
        if task and task.status == "active":
            task.status = "completed"
            task.updated_at = datetime.now().isoformat()
            self._save(task)
            logger.info(f"Long task {task.task_id} completed: {reason}")

    def pause(self, reason: str = "user_message") -> None:
        """Pause active task (e.g., user sent a new message)."""
        task = self._load()
        if task and task.status == "active":
            task.status = "paused"
            task.updated_at = datetime.now().isoformat()
            self._save(task)
            logger.info(f"Long task {task.task_id} paused: {reason}")

    def build_continue_prompt(self, task: LongTask) -> str:
        """Build the auto-continuation prompt for the next step."""
        parts = [
            f"继续执行任务。上一步已完成（第 {task.steps_completed} 步）。",
            f"原始任务: {task.original_prompt[:500]}",
        ]
        if task.step_results:
            steps_text = "\n".join(
                f"  步骤{i+1}: {r}" for i, r in enumerate(task.step_results[-3:])
            )
            parts.append(f"已完成步骤:\n{steps_text}")
        parts.append(f"上一步输出摘要:\n{task.last_output[:300]}")
        parts.append("请继续下一步。如果全部完成，请明确说明「全部完成」。")
        return "\n\n".join(parts)

    def build_recovery_prompt(self, task: LongTask) -> str:
        """Build prompt for resuming an interrupted task."""
        parts = [
            f"任务被中断，请从第 {task.steps_completed + 1} 步继续。",
            f"原始任务: {task.original_prompt[:500]}",
        ]
        if task.step_results:
            steps_text = "\n".join(
                f"  步骤{i+1}: {r}" for i, r in enumerate(task.step_results)
            )
            parts.append(f"已完成步骤:\n{steps_text}")
        parts.append("请继续下一步。如果全部完成，请明确说明「全部完成」。")
        return "\n\n".join(parts)

    def fail(self, reason: str = "failed") -> None:
        """Mark active task as failed (not completed)."""
        task = self._load()
        if task and task.status == "active":
            task.status = "failed"
            task.updated_at = datetime.now().isoformat()
            self._save(task)
            logger.info(f"Long task {task.task_id} failed: {reason}")

    def recover_orphaned(self) -> LongTask | None:
        """Detect orphaned active task after bot restart.

        Changes status to 'interrupted' and returns the task for user notification.
        Returns None if no orphaned task found.
        """
        task = self._load()
        if task and task.status == "active":
            task.status = "interrupted"
            task.updated_at = datetime.now().isoformat()
            self._save(task)
            logger.info(f"Recovered orphaned task: {task.task_id} ({task.steps_completed} steps done)")
            return task
        return None

    @staticmethod
    def claim_step(sender_id: str) -> bool:
        """Try to claim the continuation slot for a sender. Returns False if already in flight."""
        with _step_in_flight_lock:
            if sender_id in _step_in_flight:
                return False
            _step_in_flight.add(sender_id)
            return True

    @staticmethod
    def release_step(sender_id: str) -> None:
        """Release the continuation slot for a sender."""
        with _step_in_flight_lock:
            _step_in_flight.discard(sender_id)

    def _save(self, task: LongTask) -> None:
        with _GLOBAL_LOCK:
            try:
                LONG_TASK_FILE.parent.mkdir(parents=True, exist_ok=True)
                LONG_TASK_FILE.write_text(
                    json.dumps(asdict(task), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except Exception as e:
                logger.error(f"Failed to save long task: {e}")

    def _load(self) -> LongTask | None:
        with _GLOBAL_LOCK:
            try:
                if not LONG_TASK_FILE.exists():
                    return None
                data = json.loads(LONG_TASK_FILE.read_text(encoding="utf-8"))
                return LongTask(**data)
            except Exception as e:
                logger.warning(f"Failed to load long task: {e}")
                return None
