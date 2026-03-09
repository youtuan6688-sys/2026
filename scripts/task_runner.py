"""Python wrapper for task runner with auto-resume on timeout.

Uses claude_runner.run_with_resume for robust execution that automatically
saves checkpoints and retries when Claude times out.
"""

import logging
import sys
from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path("/Users/tuanyou/Happycode2026")
sys.path.insert(0, str(PROJECT_DIR))

from src.task_queue import TaskQueue
from scripts.claude_runner import run_with_resume

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")


def run_task(task_id: str, title: str, prompt: str, timeout: int = 120) -> tuple[bool, str]:
    """Execute a single task with auto-resume on timeout."""
    full_prompt = (
        f"You are working in ~/Happycode2026 project. Python venv at .venv/bin/python.\n\n"
        f"TASK: {title}\n\n{prompt}\n\n"
        f"IMPORTANT: Be concise. Complete the task and output only the result summary."
    )

    return run_with_resume(
        full_prompt,
        task_id=task_id,
        timeout=timeout,
        max_retries=2,
        cwd=str(PROJECT_DIR),
    )


def run_queue(max_tasks: int = 5, max_minutes: int = 60):
    """Process tasks from the queue."""
    q = TaskQueue()
    q.clear_stale_running()

    start = datetime.now()
    tasks_run = 0

    while tasks_run < max_tasks:
        elapsed = (datetime.now() - start).total_seconds() / 60
        if elapsed >= max_minutes:
            logger.info(f"Time limit reached ({elapsed:.0f} min)")
            break

        task = q.next()
        if not task:
            logger.info("No pending tasks")
            break

        q.mark_running(task.task_id)
        logger.info(f"Running: {task.task_id} - {task.title}")

        success, output = run_task(
            task.task_id, task.title, task.prompt, task.timeout_seconds
        )

        if success:
            q.mark_completed(task.task_id, output)
            logger.info(f"Completed: {task.task_id}")
        else:
            q.mark_failed(task.task_id, output)
            logger.warning(f"Failed: {task.task_id} - {output[:100]}")

        tasks_run += 1

    logger.info(f"Finished: {tasks_run} tasks processed")
    logger.info(q.format_status())


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-tasks", type=int, default=5)
    parser.add_argument("--max-minutes", type=int, default=60)
    args = parser.parse_args()
    run_queue(max_tasks=args.max_tasks, max_minutes=args.max_minutes)
