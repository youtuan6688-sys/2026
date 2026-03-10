"""Scheduled task manager for the Feishu bot.

Tasks are stored in data/scheduled_tasks.json.
A launchd plist runs the executor every 5 minutes to check and fire due tasks.

Approval flow:
  1. Group member requests a scheduled task → bot @mentions admin for approval
  2. Admin replies 同意/批准 → task is created and starts running
  3. Pending requests stored separately from active tasks
"""

import json
import logging
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config.settings import settings
from src.feishu_sender import FeishuSender
from src.utils.subprocess_env import CLAUDE_PATH, safe_env

logger = logging.getLogger(__name__)

PROJECT_DIR = Path("/Users/tuanyou/Happycode2026")
TASKS_FILE = PROJECT_DIR / "data" / "scheduled_tasks.json"
PENDING_FILE = PROJECT_DIR / "data" / "pending_task_requests.json"

ADMIN_OPEN_ID = "ou_4a18a2e35a5b04262a24f41731046d15"
GROUP_CHAT_ID = "oc_4f17f731a0a3bf9489c095c26be6dedc"

CN_TZ = timezone(timedelta(hours=8))


# ── Storage ──────────────────────────────────────────────────────────────────

def _load_json(path: Path) -> list[dict]:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _save_json(path: Path, data: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_tasks() -> list[dict]:
    return _load_json(TASKS_FILE)


def save_tasks(tasks: list[dict]):
    _save_json(TASKS_FILE, tasks)


def load_pending() -> list[dict]:
    return _load_json(PENDING_FILE)


def save_pending(pending: list[dict]):
    _save_json(PENDING_FILE, pending)


# ── Task CRUD ────────────────────────────────────────────────────────────────

def create_task(
    description: str,
    prompt: str,
    interval_min: int = 0,
    next_run: str = "",
    target: str = GROUP_CHAT_ID,
    created_by: str = ADMIN_OPEN_ID,
    one_shot: bool = False,
    script: str = "",
) -> dict:
    """Create a new scheduled task (already approved).

    Args:
        description: Human-readable task name
        prompt: Claude prompt to execute, OR empty if script is used
        interval_min: Minutes between runs (0 for one-shot)
        next_run: ISO datetime for first run (default: now)
        target: Chat ID to send results to
        created_by: open_id of requester
        one_shot: If True, delete after first execution
        script: Python script path to run instead of Claude prompt
    """
    now = datetime.now(CN_TZ)
    task = {
        "id": uuid.uuid4().hex[:8],
        "description": description,
        "prompt": prompt,
        "script": script,
        "interval_min": interval_min,
        "next_run": next_run or now.isoformat(),
        "target": target,
        "created_by": created_by,
        "one_shot": one_shot,
        "enabled": True,
        "created_at": now.isoformat(),
        "last_run": None,
        "run_count": 0,
    }
    tasks = load_tasks()
    tasks.append(task)
    save_tasks(tasks)
    logger.info(f"Task created: {task['id']} — {description}")
    return task


def delete_task(task_id: str) -> bool:
    tasks = load_tasks()
    original_len = len(tasks)
    tasks = [t for t in tasks if t["id"] != task_id]
    if len(tasks) < original_len:
        save_tasks(tasks)
        logger.info(f"Task deleted: {task_id}")
        return True
    return False


def list_tasks() -> list[dict]:
    return [t for t in load_tasks() if t.get("enabled", True)]


def format_tasks() -> str:
    """Format task list for display."""
    tasks = list_tasks()
    if not tasks:
        return "当前没有定时任务"
    lines = ["📋 定时任务列表："]
    for t in tasks:
        interval = f"每{t['interval_min']}分钟" if t["interval_min"] else "一次性"
        next_dt = _parse_dt(t["next_run"])
        next_str = next_dt.strftime("%m/%d %H:%M") if next_dt else "?"
        runs = t.get("run_count", 0)
        lines.append(
            f"• [{t['id']}] {t['description']}\n"
            f"  {interval} | 下次: {next_str} | 已执行: {runs}次"
        )
    return "\n".join(lines)


# ── Pending Requests (approval flow) ─────────────────────────────────────────

def create_pending_request(
    description: str,
    prompt: str,
    interval_min: int,
    requested_by: str,
    requester_name: str = "",
    script: str = "",
    one_shot: bool = False,
    next_run: str = "",
) -> dict:
    """Create a pending task request that needs admin approval."""
    req = {
        "id": uuid.uuid4().hex[:8],
        "description": description,
        "prompt": prompt,
        "script": script,
        "interval_min": interval_min,
        "one_shot": one_shot,
        "next_run": next_run,
        "requested_by": requested_by,
        "requester_name": requester_name,
        "requested_at": datetime.now(CN_TZ).isoformat(),
    }
    pending = load_pending()
    pending.append(req)
    save_pending(pending)
    logger.info(f"Pending request created: {req['id']} — {description}")
    return req


def approve_pending(request_id: str) -> dict | None:
    """Approve a pending request and create the actual task."""
    pending = load_pending()
    found = None
    remaining = []
    for p in pending:
        if p["id"] == request_id:
            found = p
        else:
            remaining.append(p)
    if not found:
        return None
    save_pending(remaining)
    task = create_task(
        description=found["description"],
        prompt=found["prompt"],
        interval_min=found["interval_min"],
        next_run=found.get("next_run", ""),
        target=GROUP_CHAT_ID,
        created_by=found["requested_by"],
        one_shot=found.get("one_shot", False),
        script=found.get("script", ""),
    )
    return task


def reject_pending(request_id: str) -> bool:
    pending = load_pending()
    original_len = len(pending)
    pending = [p for p in pending if p["id"] != request_id]
    if len(pending) < original_len:
        save_pending(pending)
        return True
    return False


def get_latest_pending() -> dict | None:
    """Get the most recent pending request (for approval matching)."""
    pending = load_pending()
    return pending[-1] if pending else None


def find_pending(request_id: str) -> dict | None:
    for p in load_pending():
        if p["id"] == request_id:
            return p
    return None


# ── Executor ─────────────────────────────────────────────────────────────────

def _parse_dt(s: str) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=CN_TZ)
        return dt
    except Exception:
        return None


def execute_due_tasks():
    """Check all tasks and execute those that are due. Called by launchd."""
    tasks = load_tasks()
    now = datetime.now(CN_TZ)
    changed = False
    sender = FeishuSender(settings)

    for task in tasks:
        if not task.get("enabled", True):
            continue
        next_run = _parse_dt(task["next_run"])
        if not next_run or next_run > now:
            continue

        # Task is due
        logger.info(f"Executing task {task['id']}: {task['description']}")
        try:
            result = _execute_task(task)
            if result:
                header = f"⏰ 定时任务: {task['description']}\n\n"
                msg = header + result
                # Truncate if too long
                if len(msg) > 3000:
                    msg = msg[:2950] + "\n\n...（内容过长已截断）"
                sender.send_text(task["target"], msg)
            task["last_run"] = now.isoformat()
            task["run_count"] = task.get("run_count", 0) + 1
            changed = True

            if task["one_shot"]:
                task["enabled"] = False
                logger.info(f"One-shot task {task['id']} completed, disabled")
            elif task["interval_min"] > 0:
                task["next_run"] = (now + timedelta(minutes=task["interval_min"])).isoformat()
        except Exception as e:
            logger.error(f"Task {task['id']} failed: {e}", exc_info=True)
            task["last_run"] = now.isoformat()
            # Retry next interval, don't disable
            if task["interval_min"] > 0:
                task["next_run"] = (now + timedelta(minutes=task["interval_min"])).isoformat()
            changed = True

    if changed:
        save_tasks(tasks)


def _execute_task(task: dict) -> str:
    """Execute a single task and return the output text."""
    # Script-based task (scripts handle their own notifications)
    if task.get("script"):
        _run_script(task["script"])
        return ""

    # Claude prompt-based task
    if task.get("prompt"):
        return _run_claude_prompt(task["prompt"])

    return ""


def _run_script(script_path: str) -> str:
    """Run a Python script and capture its output."""
    try:
        result = subprocess.run(
            ["/Users/tuanyou/Happycode2026/.venv/bin/python", script_path],
            capture_output=True, text=True, timeout=120,
            cwd=str(PROJECT_DIR),
        )
        output = result.stdout.strip()
        if result.returncode != 0 and result.stderr:
            logger.warning(f"Script {script_path} stderr: {result.stderr[:500]}")
        return output
    except subprocess.TimeoutExpired:
        logger.error(f"Script {script_path} timed out")
        return "脚本执行超时"
    except Exception as e:
        logger.error(f"Script {script_path} failed: {e}")
        return f"脚本执行失败: {e}"


def _run_claude_prompt(prompt: str) -> str:
    """Run a Claude prompt and return the output."""
    try:
        env = {k: v for k, v in __import__("os").environ.items() if k != "CLAUDECODE"}
        result = subprocess.run(
            [CLAUDE_PATH, "-p", prompt, "--model", "sonnet"],
            capture_output=True, text=True, timeout=120, env=env,
        )
        output = result.stdout.strip()
        if not output:
            return "（无输出）"
        return output
    except subprocess.TimeoutExpired:
        return "Claude 执行超时"
    except Exception as e:
        logger.error(f"Claude prompt failed: {e}")
        return f"执行失败: {e}"


# ── CLI Entry Point ──────────────────────────────────────────────────────────

def main():
    """Entry point for launchd executor."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger.info("Task scheduler executor running...")
    execute_due_tasks()
    logger.info("Task scheduler executor done.")


if __name__ == "__main__":
    main()
