"""
Checkpoint system for Claude Code task continuation.

Tracks high-level task progress with step-by-step state,
enabling seamless resume after timeout or context exhaustion.
Integrates with TaskQueue for granular execution control.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

CHECKPOINT_DIR = Path("/Users/tuanyou/Happycode2026/vault/checkpoints")
CURRENT_TASK_FILE = CHECKPOINT_DIR / "current_task.json"
TASK_HISTORY_FILE = CHECKPOINT_DIR / "task_history.json"
MAX_HISTORY = 50


class CheckpointStep:
    """Immutable step within a checkpoint."""

    def __init__(
        self,
        name: str,
        status: str = "pending",
        progress: str = "",
        queue_task_ids: Optional[list[str]] = None,
    ):
        self.name = name
        self.status = status  # pending, in_progress, done, failed
        self.progress = progress
        self.queue_task_ids = queue_task_ids or []

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "status": self.status,
            "progress": self.progress,
            "queue_task_ids": self.queue_task_ids,
        }

    @staticmethod
    def from_dict(data: dict) -> "CheckpointStep":
        return CheckpointStep(
            name=data["name"],
            status=data.get("status", "pending"),
            progress=data.get("progress", ""),
            queue_task_ids=data.get("queue_task_ids", []),
        )


class Checkpoint:
    """Persistent checkpoint for a high-level task."""

    def __init__(
        self,
        task_id: str,
        description: str,
        steps: Optional[list[CheckpointStep]] = None,
        context_notes: str = "",
        created_at: Optional[str] = None,
        last_updated: Optional[str] = None,
    ):
        self.task_id = task_id
        self.description = description
        self.steps = steps or []
        self.context_notes = context_notes
        self.created_at = created_at or datetime.now().isoformat()
        self.last_updated = last_updated or datetime.now().isoformat()

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "description": self.description,
            "steps": [s.to_dict() for s in self.steps],
            "context_notes": self.context_notes,
            "created_at": self.created_at,
            "last_updated": self.last_updated,
        }

    @staticmethod
    def from_dict(data: dict) -> "Checkpoint":
        return Checkpoint(
            task_id=data["task_id"],
            description=data.get("description", ""),
            steps=[CheckpointStep.from_dict(s) for s in data.get("steps", [])],
            context_notes=data.get("context_notes", ""),
            created_at=data.get("created_at"),
            last_updated=data.get("last_updated"),
        )

    def current_step(self) -> Optional[CheckpointStep]:
        """Get the first non-done step."""
        for step in self.steps:
            if step.status in ("pending", "in_progress"):
                return step
        return None

    def progress_summary(self) -> str:
        """Human-readable progress summary."""
        done = sum(1 for s in self.steps if s.status == "done")
        total = len(self.steps)
        current = self.current_step()
        current_text = f" | Current: {current.name}" if current else " | All done"
        return f"[{done}/{total}]{current_text}"

    def is_complete(self) -> bool:
        return all(s.status == "done" for s in self.steps)


class CheckpointManager:
    """Manages checkpoint persistence and lifecycle."""

    def __init__(
        self,
        checkpoint_dir: Path = CHECKPOINT_DIR,
        current_file: Path = CURRENT_TASK_FILE,
        history_file: Path = TASK_HISTORY_FILE,
    ):
        self._checkpoint_dir = checkpoint_dir
        self._current_file = current_file
        self._history_file = history_file
        self._checkpoint_dir.mkdir(parents=True, exist_ok=True)

    def save(self, checkpoint: Checkpoint) -> None:
        """Save current checkpoint to disk."""
        checkpoint.last_updated = datetime.now().isoformat()
        self._current_file.write_text(
            json.dumps(checkpoint.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info(f"Checkpoint saved: {checkpoint.task_id} {checkpoint.progress_summary()}")

    def load(self) -> Optional[Checkpoint]:
        """Load current checkpoint from disk."""
        try:
            if self._current_file.exists():
                data = json.loads(self._current_file.read_text(encoding="utf-8"))
                return Checkpoint.from_dict(data)
        except Exception as e:
            logger.warning(f"Failed to load checkpoint: {e}")
        return None

    def complete(self, checkpoint: Checkpoint) -> None:
        """Move completed checkpoint to history."""
        history = self._load_history()
        history.append(checkpoint.to_dict())
        if len(history) > MAX_HISTORY:
            history = history[-MAX_HISTORY:]
        self._history_file.write_text(
            json.dumps(history, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        # Remove current task file
        if self._current_file.exists():
            self._current_file.unlink()
        logger.info(f"Checkpoint completed: {checkpoint.task_id}")

    def clear(self) -> None:
        """Clear current checkpoint without saving to history."""
        if self._current_file.exists():
            self._current_file.unlink()

    def update_step(
        self,
        checkpoint: Checkpoint,
        step_name: str,
        status: str,
        progress: str = "",
    ) -> Checkpoint:
        """Update a step's status and save. Returns new Checkpoint (immutable pattern)."""
        new_steps = []
        for step in checkpoint.steps:
            if step.name == step_name:
                new_steps.append(CheckpointStep(
                    name=step.name,
                    status=status,
                    progress=progress or step.progress,
                    queue_task_ids=step.queue_task_ids,
                ))
            else:
                new_steps.append(step)

        new_checkpoint = Checkpoint(
            task_id=checkpoint.task_id,
            description=checkpoint.description,
            steps=new_steps,
            context_notes=checkpoint.context_notes,
            created_at=checkpoint.created_at,
        )
        self.save(new_checkpoint)

        if new_checkpoint.is_complete():
            self.complete(new_checkpoint)

        return new_checkpoint

    def _load_history(self) -> list[dict]:
        try:
            if self._history_file.exists():
                return json.loads(self._history_file.read_text(encoding="utf-8"))
        except Exception:
            pass
        return []

    def get_resume_prompt(self) -> Optional[str]:
        """Generate a prompt for Claude to resume from checkpoint.

        This is the key integration point: when the bot receives "继续",
        it calls this to build a context-rich prompt for the next `claude -p` call.
        """
        checkpoint = self.load()
        if not checkpoint:
            return None

        current = checkpoint.current_step()
        if not current:
            return None

        # Build resume context
        done_steps = [s for s in checkpoint.steps if s.status == "done"]
        pending_steps = [s for s in checkpoint.steps if s.status in ("pending", "in_progress")]

        lines = [
            f"# Resume Task: {checkpoint.description}",
            f"Task ID: {checkpoint.task_id}",
            f"Progress: {checkpoint.progress_summary()}",
            "",
        ]

        if checkpoint.context_notes:
            lines.extend([
                "## Context",
                checkpoint.context_notes,
                "",
            ])

        if done_steps:
            lines.append("## Completed Steps")
            for s in done_steps:
                lines.append(f"- [x] {s.name}: {s.progress}")
            lines.append("")

        lines.append("## Current Step")
        lines.append(f"**{current.name}**")
        if current.progress:
            lines.append(f"Progress so far: {current.progress}")
        lines.append("")

        if len(pending_steps) > 1:
            lines.append("## Remaining Steps")
            for s in pending_steps[1:]:
                lines.append(f"- [ ] {s.name}")
            lines.append("")

        lines.extend([
            "## Instructions",
            f"Continue from step '{current.name}'. When you complete a step, "
            "update the checkpoint file at:",
            str(self._current_file),
            "",
            "Update format: change the step's status to 'done' and add progress notes.",
            "Then proceed to the next pending step.",
        ])

        return "\n".join(lines)

    def format_status(self) -> str:
        """Human-readable status for /status command."""
        checkpoint = self.load()
        if not checkpoint:
            return "No active checkpoint"

        lines = [
            f"Checkpoint: {checkpoint.description}",
            f"Progress: {checkpoint.progress_summary()}",
        ]
        for step in checkpoint.steps:
            icon = {"done": "OK", "in_progress": ">>", "pending": "..", "failed": "XX"}.get(step.status, "??")
            lines.append(f"  [{icon}] {step.name}")
            if step.progress:
                lines.append(f"       {step.progress[:80]}")
        return "\n".join(lines)
