"""
Seed the task queue with evolution tasks.
Each task is a small, focused unit that runs in its own claude -p session.
"""

import sys
sys.path.insert(0, "/Users/tuanyou/Happycode2026")

from src.task_queue import Task, TaskQueue


def seed_tasks():
    q = TaskQueue()

    tasks = [
        Task(
            task_id="evo-001-proactive-reminder",
            title="Add proactive reminder cron job",
            prompt="""Create a script at ~/Happycode2026/scripts/proactive_reminder.sh that:
1. Checks vault/tasks/queue.json for pending tasks
2. Checks vault/logs/error_log.json for unresolved errors
3. If there are pending tasks or errors, sends a summary to Feishu via the bot
4. If no issues, does nothing (silent success)

Use the existing feishu_sender.py to send messages.
Make the script executable. Test it works by running it once.""",
            priority=3,
            category="evolution",
            timeout_seconds=180,
        ),
        Task(
            task_id="evo-002-task-feishu-cmd",
            title="Add /tasks command to Feishu bot",
            prompt="""Add a /tasks command to the Feishu bot message router (src/message_router.py).

The command should:
1. Show task queue status (pending/running/completed/failed counts)
2. Show next 3 pending tasks
3. Show last 3 completed tasks from history

Import TaskQueue from src.task_queue and use its format_status() method.
Add the command to the help text too.
Write tests for the new command in tests/.""",
            priority=4,
            category="evolution",
            timeout_seconds=180,
            depends_on=["evo-001-proactive-reminder"],
        ),
        Task(
            task_id="evo-003-health-check",
            title="Create system health check script",
            prompt="""Create ~/Happycode2026/scripts/health_check.py that checks:
1. Feishu bot process is running (check launchd service)
2. Cron jobs are registered (crontab -l)
3. Error log has no critical unresolved errors
4. Vault directory is accessible
5. Claude binary exists and is executable
6. Python venv is working

Output a JSON report with status for each check.
Return exit code 0 if all healthy, 1 if any critical issue.""",
            priority=3,
            category="evolution",
            timeout_seconds=120,
        ),
        Task(
            task_id="evo-004-auto-task-gen",
            title="Create auto task generator from error patterns",
            prompt="""Create ~/Happycode2026/scripts/generate_fix_tasks.py that:
1. Reads vault/logs/error_log.json
2. Finds recurring unresolved error patterns (3+ occurrences)
3. For each pattern, generates a Task with a prompt to fix the root cause
4. Adds generated tasks to the queue via TaskQueue.add()

This creates a self-healing loop: errors → fix tasks → task runner → fixes applied.
Include tests.""",
            priority=5,
            category="evolution",
            timeout_seconds=180,
            depends_on=["evo-003-health-check"],
        ),
        Task(
            task_id="evo-005-queue-cron",
            title="Set up task runner cron job",
            prompt="""Add a cron job that runs the task runner every 30 minutes:
*/30 * * * * /Users/tuanyou/Happycode2026/scripts/task_runner.sh --max-tasks 3 --max-minutes 20

Steps:
1. Read current crontab
2. Add the new entry if not already present
3. Verify with crontab -l
4. Make task_runner.sh executable

Also add a 5pm PST proactive reminder cron:
0 17 * * * /Users/tuanyou/Happycode2026/scripts/proactive_reminder.sh""",
            priority=2,
            category="infrastructure",
            timeout_seconds=60,
        ),
    ]

    added = 0
    for task in tasks:
        result = q.add(task)
        if result.status == "pending":
            added += 1
            print(f"Added: {task.task_id} - {task.title}")
        else:
            print(f"Skipped (exists): {task.task_id}")

    print(f"\n{added} tasks added. Queue status:")
    print(q.format_status())


if __name__ == "__main__":
    seed_tasks()
