"""Scheduled task manager for the Feishu bot.

Tasks are stored in data/scheduled_tasks.json.
A launchd plist runs the executor every 5 minutes to check and fire due tasks.

Schedule types:
  - interval: run every N minutes (legacy, backward compatible)
  - cron: standard cron expression (e.g. "0 10 * * 1" = every Monday 10:00)
  - once: run once at a specific time, then disable

CLI usage (for bot self-scheduling via Bash):
  python -m src.task_scheduler create --desc "..." --cron "0 10 * * 1" --prompt "..."
  python -m src.task_scheduler create --desc "..." --interval 30 --script "/path/to.py"
  python -m src.task_scheduler create --desc "..." --once "2026-03-15 14:00" --prompt "..."
  python -m src.task_scheduler list
  python -m src.task_scheduler delete <task_id>
  python -m src.task_scheduler enable <task_id>
  python -m src.task_scheduler disable <task_id>
  python -m src.task_scheduler run   (execute due tasks — called by launchd)

Approval flow (group chat):
  1. Group member requests a scheduled task -> bot @mentions admin for approval
  2. Admin replies 同意/批准 -> task is created and starts running
  3. Pending requests stored separately from active tasks
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from croniter import croniter

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
        except Exception as exc:
            logger.error(f"Failed to parse {path}: {exc}")
            # Backup corrupt file instead of silently losing data
            backup = path.with_suffix(".json.bak")
            path.rename(backup)
            logger.error(f"Corrupt file backed up to {backup}")
    return []


def _save_json(path: Path, data: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


_TASK_DEFAULTS = {
    "schedule_type": "interval",
    "cron_expr": "",
    "timeout": 120,
    "one_shot": False,
}


def _migrate_task(task: dict) -> dict:
    """Ensure task has all required fields (backward compat)."""
    return {**_TASK_DEFAULTS, **task}


def load_tasks() -> list[dict]:
    return [_migrate_task(t) for t in _load_json(TASKS_FILE)]


def save_tasks(tasks: list[dict]):
    _save_json(TASKS_FILE, tasks)


def load_pending() -> list[dict]:
    return _load_json(PENDING_FILE)


def save_pending(pending: list[dict]):
    _save_json(PENDING_FILE, pending)


# ── Schedule helpers ─────────────────────────────────────────────────────────

def _compute_next_run(task: dict, after: datetime | None = None) -> str:
    """Compute the next run time for a task.

    Supports three schedule types:
      - "cron": uses croniter to compute next fire time
      - "interval": adds interval_min to `after`
      - "once": returns the fixed next_run (no recompute)

    Legacy tasks without schedule_type default to "interval".
    """
    now = after or datetime.now(CN_TZ)
    schedule_type = task.get("schedule_type", "interval")

    if schedule_type == "cron":
        cron_expr = task.get("cron_expr", "")
        if not cron_expr:
            return now.isoformat()
        # croniter needs a naive or tz-aware base; use CN_TZ
        base = now.astimezone(CN_TZ)
        cron = croniter(cron_expr, base)
        next_dt = cron.get_next(datetime)
        if next_dt.tzinfo is None:
            next_dt = next_dt.replace(tzinfo=CN_TZ)
        else:
            next_dt = next_dt.astimezone(CN_TZ)
        return next_dt.isoformat()

    if schedule_type == "interval":
        interval = task.get("interval_min", 0)
        if interval > 0:
            return (now + timedelta(minutes=interval)).isoformat()
        return now.isoformat()

    # "once" — no recompute, keep existing next_run
    return task.get("next_run", now.isoformat())


def _validate_cron(expr: str) -> bool:
    """Check if a standard 5-field cron expression is valid."""
    if len(expr.strip().split()) != 5:
        return False
    try:
        croniter(expr)
        return True
    except (ValueError, KeyError):
        return False


# ── Task CRUD ────────────────────────────────────────────────────────────────

def create_task(
    description: str,
    prompt: str = "",
    interval_min: int = 0,
    cron_expr: str = "",
    next_run: str = "",
    target: str = GROUP_CHAT_ID,
    created_by: str = ADMIN_OPEN_ID,
    one_shot: bool = False,
    script: str = "",
    timeout: int = 120,
) -> dict:
    """Create a new scheduled task (already approved).

    Args:
        description: Human-readable task name
        prompt: Claude prompt to execute, OR empty if script is used
        interval_min: Minutes between runs (0 if using cron/once)
        cron_expr: Cron expression (e.g. "0 10 * * 1")
        next_run: ISO datetime for first run (auto-computed if empty)
        target: Chat ID to send results to
        created_by: open_id of requester
        one_shot: If True, disable after first execution
        script: Python script path to run instead of Claude prompt
        timeout: Execution timeout in seconds (default 120)
    """
    now = datetime.now(CN_TZ)

    # Determine schedule type
    if cron_expr:
        schedule_type = "cron"
        if not _validate_cron(cron_expr):
            raise ValueError(f"Invalid cron expression: {cron_expr}")
    elif one_shot:
        schedule_type = "once"
    else:
        schedule_type = "interval"

    task = {
        "id": uuid.uuid4().hex[:8],
        "description": description,
        "prompt": prompt,
        "script": script,
        "schedule_type": schedule_type,
        "interval_min": interval_min,
        "cron_expr": cron_expr,
        "next_run": "",
        "target": target,
        "created_by": created_by,
        "one_shot": one_shot,
        "enabled": True,
        "created_at": now.isoformat(),
        "last_run": None,
        "run_count": 0,
        "timeout": timeout,
    }

    # Compute first next_run
    if next_run:
        task["next_run"] = next_run
    else:
        task["next_run"] = _compute_next_run(task, after=now)

    tasks = load_tasks()
    tasks.append(task)
    save_tasks(tasks)
    logger.info(f"Task created: {task['id']} — {description} [{schedule_type}]")
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


def enable_task(task_id: str) -> bool:
    tasks = load_tasks()
    for t in tasks:
        if t["id"] == task_id:
            t["enabled"] = True
            # Recompute next_run from now
            t["next_run"] = _compute_next_run(t)
            save_tasks(tasks)
            logger.info(f"Task enabled: {task_id}")
            return True
    return False


def disable_task(task_id: str) -> bool:
    tasks = load_tasks()
    for t in tasks:
        if t["id"] == task_id:
            t["enabled"] = False
            save_tasks(tasks)
            logger.info(f"Task disabled: {task_id}")
            return True
    return False


def list_tasks() -> list[dict]:
    return [t for t in load_tasks() if t.get("enabled", True)]


def _format_schedule(task: dict) -> str:
    """Human-readable schedule description."""
    schedule_type = task.get("schedule_type", "interval")
    if schedule_type == "cron":
        return f"cron: {task.get('cron_expr', '?')}"
    if schedule_type == "once":
        return "一次性"
    interval = task.get("interval_min", 0)
    if interval >= 1440:
        return f"每{interval // 1440}天"
    if interval >= 60:
        return f"每{interval // 60}小时"
    return f"每{interval}分钟" if interval else "一次性"


def format_tasks() -> str:
    """Format task list for display."""
    tasks = list_tasks()
    if not tasks:
        return "当前没有定时任务"
    lines = ["定时任务列表："]
    for t in tasks:
        schedule = _format_schedule(t)
        next_dt = _parse_dt(t["next_run"])
        next_str = next_dt.strftime("%m/%d %H:%M") if next_dt else "?"
        runs = t.get("run_count", 0)
        lines.append(
            f"  [{t['id']}] {t['description']}\n"
            f"  {schedule} | 下次: {next_str} | 已执行: {runs}次"
        )
    return "\n".join(lines)


def format_tasks_all() -> str:
    """Format ALL tasks (including disabled) for display."""
    tasks = load_tasks()
    if not tasks:
        return "没有任何任务"
    lines = ["所有任务："]
    for t in tasks:
        status = "ON" if t.get("enabled", True) else "OFF"
        schedule = _format_schedule(t)
        next_dt = _parse_dt(t["next_run"])
        next_str = next_dt.strftime("%m/%d %H:%M") if next_dt else "?"
        runs = t.get("run_count", 0)
        lines.append(
            f"  [{t['id']}] [{status}] {t['description']}\n"
            f"  {schedule} | 下次: {next_str} | 已执行: {runs}次"
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
    cron_expr: str = "",
) -> dict:
    """Create a pending task request that needs admin approval."""
    req = {
        "id": uuid.uuid4().hex[:8],
        "description": description,
        "prompt": prompt,
        "script": script,
        "interval_min": interval_min,
        "cron_expr": cron_expr,
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
        cron_expr=found.get("cron_expr", ""),
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
    except Exception as exc:
        logger.warning(f"Could not parse datetime {s!r}: {exc}")
        return None


def execute_due_tasks():
    """Check all tasks and execute those that are due. Called by launchd."""
    tasks = load_tasks()
    now = datetime.now(CN_TZ)
    changed = False

    # Lazy-init sender only when needed
    sender = None

    for task in tasks:
        if not task.get("enabled", True):
            continue
        next_run = _parse_dt(task["next_run"])
        if not next_run or next_run > now:
            continue

        # Task is due
        logger.info(f"Executing task {task['id']}: {task['description']}")
        try:
            task_timeout = task.get("timeout", 120)
            result = _execute_task(task, timeout=task_timeout)
            if result:
                if sender is None:
                    from config.settings import settings
                    from src.feishu_sender import FeishuSender
                    sender = FeishuSender(settings)
                header = f"⏰ 定时任务: {task['description']}\n\n"
                msg = header + result
                if len(msg) > 3000:
                    msg = msg[:2950] + "\n\n...（内容过长已截断）"
                sender.send_text(task["target"], msg)
            task["last_run"] = now.isoformat()
            task["run_count"] = task.get("run_count", 0) + 1
            changed = True

            if task["one_shot"]:
                task["enabled"] = False
                logger.info(f"One-shot task {task['id']} completed, disabled")
            else:
                task["next_run"] = _compute_next_run(task, after=now)
        except Exception as e:
            logger.error(f"Task {task['id']} failed: {e}", exc_info=True)
            task["last_run"] = now.isoformat()
            # Once tasks should not retry on failure
            if task.get("schedule_type", "interval") == "once":
                task["enabled"] = False
                logger.info(f"Once task {task['id']} failed, disabled")
            else:
                task["next_run"] = _compute_next_run(task, after=now)
            changed = True

    if changed:
        save_tasks(tasks)


def _execute_task(task: dict, timeout: int = 120) -> str:
    """Execute a single task and return the output text."""
    if task.get("script"):
        return _run_script(task["script"], timeout=timeout)

    if task.get("prompt"):
        return _run_claude_prompt(task["prompt"], timeout=timeout)

    return ""


def _run_script(script_path: str, timeout: int = 120) -> str:
    """Run a Python script and capture its output."""
    resolved = Path(script_path).resolve()
    if not str(resolved).startswith(str(PROJECT_DIR)):
        logger.error(f"Script path outside project dir: {script_path}")
        return f"安全限制: 脚本路径必须在项目目录内"
    try:
        result = subprocess.run(
            ["/Users/tuanyou/Happycode2026/.venv/bin/python", script_path],
            capture_output=True, text=True, timeout=timeout,
            cwd=str(PROJECT_DIR),
        )
        output = result.stdout.strip()
        if result.returncode != 0 and result.stderr:
            logger.warning(f"Script {script_path} stderr: {result.stderr[:500]}")
        return output
    except subprocess.TimeoutExpired:
        logger.error(f"Script {script_path} timed out ({timeout}s)")
        return f"脚本执行超时 ({timeout}s)"
    except Exception as e:
        logger.error(f"Script {script_path} failed: {e}")
        return f"脚本执行失败: {e}"


def _run_claude_prompt(prompt: str, timeout: int = 120) -> str:
    """Run a Claude prompt and return the output."""
    try:
        from src.utils.subprocess_env import CLAUDE_PATH
        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
        result = subprocess.run(
            [CLAUDE_PATH, "-p", prompt, "--model", "sonnet"],
            capture_output=True, text=True, timeout=timeout, env=env,
        )
        output = result.stdout.strip()
        if not output:
            return "（无输出）"
        return output
    except subprocess.TimeoutExpired:
        return f"Claude 执行超时 ({timeout}s)"
    except Exception as e:
        logger.error(f"Claude prompt failed: {e}")
        return f"执行失败: {e}"


# ── CLI ──────────────────────────────────────────────────────────────────────

def _cli_create(args: argparse.Namespace) -> None:
    """Handle 'create' subcommand."""
    if not args.prompt and not args.script:
        print("ERROR: --prompt or --script is required", file=sys.stderr)
        sys.exit(1)

    schedule_opts = [args.cron, args.interval, args.once]
    if not any(schedule_opts):
        print("ERROR: one of --cron, --interval, or --once is required", file=sys.stderr)
        sys.exit(1)
    if sum(bool(x) for x in schedule_opts) > 1:
        print("ERROR: --cron, --interval, and --once are mutually exclusive", file=sys.stderr)
        sys.exit(1)

    cron_expr = args.cron or ""
    if cron_expr and not _validate_cron(cron_expr):
        print(f"ERROR: invalid cron expression: {cron_expr}", file=sys.stderr)
        sys.exit(1)

    one_shot = bool(args.once)
    next_run = ""
    if args.once:
        # Parse "2026-03-15 14:00" or ISO format
        try:
            dt = datetime.fromisoformat(args.once)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=CN_TZ)
            next_run = dt.isoformat()
        except ValueError:
            print(f"ERROR: invalid datetime: {args.once}", file=sys.stderr)
            sys.exit(1)

    # Read prompt from stdin if --prompt is "-"
    prompt = args.prompt or ""
    if prompt == "-":
        prompt = sys.stdin.read().strip()

    task = create_task(
        description=args.desc,
        prompt=prompt,
        interval_min=args.interval or 0,
        cron_expr=cron_expr,
        next_run=next_run,
        target=args.target,
        created_by=ADMIN_OPEN_ID,
        one_shot=one_shot,
        script=args.script or "",
        timeout=args.timeout,
    )
    print(json.dumps(task, ensure_ascii=False, indent=2))


def _cli_list(args: argparse.Namespace) -> None:
    """Handle 'list' subcommand."""
    if args.all:
        print(format_tasks_all())
    else:
        print(format_tasks())


def _cli_delete(args: argparse.Namespace) -> None:
    """Handle 'delete' subcommand."""
    if delete_task(args.task_id):
        print(f"Deleted: {args.task_id}")
    else:
        print(f"Not found: {args.task_id}", file=sys.stderr)
        sys.exit(1)


def _cli_enable(args: argparse.Namespace) -> None:
    if enable_task(args.task_id):
        print(f"Enabled: {args.task_id}")
    else:
        print(f"Not found: {args.task_id}", file=sys.stderr)
        sys.exit(1)


def _cli_disable(args: argparse.Namespace) -> None:
    if disable_task(args.task_id):
        print(f"Disabled: {args.task_id}")
    else:
        print(f"Not found: {args.task_id}", file=sys.stderr)
        sys.exit(1)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scheduled task manager",
        prog="python -m src.task_scheduler",
    )
    sub = parser.add_subparsers(dest="command")

    # create
    p_create = sub.add_parser("create", help="Create a new scheduled task")
    p_create.add_argument("--desc", required=True, help="Task description")
    p_create.add_argument("--prompt", default="", help="Claude prompt (use '-' for stdin)")
    p_create.add_argument("--script", default="", help="Python script path")
    p_create.add_argument("--cron", default="", help="Cron expression (e.g. '0 10 * * 1')")
    p_create.add_argument("--interval", type=int, default=0, help="Interval in minutes")
    p_create.add_argument("--once", default="", help="One-shot datetime (e.g. '2026-03-15 14:00')")
    p_create.add_argument("--target", default=ADMIN_OPEN_ID, help="Target chat/user ID")
    p_create.add_argument("--timeout", type=int, default=120, help="Execution timeout seconds")

    # list
    p_list = sub.add_parser("list", help="List scheduled tasks")
    p_list.add_argument("--all", action="store_true", help="Include disabled tasks")

    # delete
    p_del = sub.add_parser("delete", help="Delete a task")
    p_del.add_argument("task_id", help="Task ID to delete")

    # enable / disable
    p_en = sub.add_parser("enable", help="Enable a task")
    p_en.add_argument("task_id", help="Task ID")
    p_dis = sub.add_parser("disable", help="Disable a task")
    p_dis.add_argument("task_id", help="Task ID")

    # run (executor)
    sub.add_parser("run", help="Execute due tasks (called by launchd)")

    return parser


def main():
    """CLI entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    parser = _build_parser()
    args = parser.parse_args()

    if not args.command:
        # Default: run executor (backward compatible with launchd)
        logger.info("Task scheduler executor running...")
        execute_due_tasks()
        logger.info("Task scheduler executor done.")
        return

    handlers = {
        "create": _cli_create,
        "list": _cli_list,
        "delete": _cli_delete,
        "enable": _cli_enable,
        "disable": _cli_disable,
        "run": lambda _: execute_due_tasks(),
    }
    handler = handlers.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
