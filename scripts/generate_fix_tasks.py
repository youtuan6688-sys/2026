"""Auto task generator: reads error patterns and creates fix tasks."""

import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path("/Users/tuanyou/Happycode2026")
sys.path.insert(0, str(PROJECT_DIR))

from src.task_queue import Task, TaskQueue

ERROR_LOG = PROJECT_DIR / "vault/logs/error_log.json"
MIN_OCCURRENCES = 3


def load_errors() -> list[dict]:
    """Load unresolved errors from log."""
    if not ERROR_LOG.exists():
        return []
    try:
        entries = json.loads(ERROR_LOG.read_text(encoding="utf-8"))
        return [e for e in entries if not e.get("resolved")]
    except Exception:
        return []


def find_recurring_patterns(errors: list[dict]) -> list[dict]:
    """Find error types that occur 3+ times."""
    type_counts = Counter(e.get("error_type", "unknown") for e in errors)
    patterns = []

    for error_type, count in type_counts.items():
        if count < MIN_OCCURRENCES:
            continue

        # Collect representative errors of this type
        examples = [e for e in errors if e.get("error_type") == error_type]
        sources = list({e.get("source", "unknown") for e in examples})
        messages = list({e.get("message", "")[:100] for e in examples[:5]})
        severities = [e.get("severity", "medium") for e in examples]
        max_severity = "critical" if "critical" in severities else (
            "high" if "high" in severities else "medium"
        )

        patterns.append({
            "error_type": error_type,
            "count": count,
            "sources": sources,
            "messages": messages,
            "max_severity": max_severity,
        })

    # Sort by severity then count
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    patterns.sort(key=lambda p: (severity_order.get(p["max_severity"], 5), -p["count"]))
    return patterns


def generate_task(pattern: dict) -> Task:
    """Generate a fix task from an error pattern."""
    error_type = pattern["error_type"]
    sources = ", ".join(pattern["sources"][:3])
    messages = "\n".join(f"- {m}" for m in pattern["messages"][:3])

    prompt = (
        f"Fix recurring error pattern: {error_type}\n\n"
        f"This error has occurred {pattern['count']} times in: {sources}\n\n"
        f"Example error messages:\n{messages}\n\n"
        f"Steps:\n"
        f"1. Read the source files mentioned above\n"
        f"2. Identify the root cause of the {error_type} errors\n"
        f"3. Implement a fix\n"
        f"4. Add or update tests to prevent regression\n"
        f"5. Run existing tests to verify nothing broke\n\n"
        f"Output: summary of what was fixed and why."
    )

    priority_map = {"critical": 1, "high": 2, "medium": 4, "low": 6}
    priority = priority_map.get(pattern["max_severity"], 5)

    timestamp = datetime.now().strftime("%Y%m%d%H%M")
    task_id = f"autofix-{error_type[:30]}-{timestamp}"

    return Task(
        task_id=task_id,
        title=f"Fix recurring: {error_type} ({pattern['count']}x)",
        prompt=prompt,
        priority=priority,
        category="autofix",
        timeout_seconds=180,
        max_retries=1,
    )


def main():
    errors = load_errors()
    if not errors:
        print("No unresolved errors found.")
        return

    patterns = find_recurring_patterns(errors)
    if not patterns:
        print(f"No recurring patterns found (need {MIN_OCCURRENCES}+ occurrences).")
        return

    q = TaskQueue()
    created = 0

    for pattern in patterns:
        task = generate_task(pattern)
        # Check if a similar autofix task already exists
        existing = [t for t in q.get_all() if t.category == "autofix" and pattern["error_type"] in t.title]
        if existing:
            print(f"Skip: {pattern['error_type']} (existing task)")
            continue

        q.add(task)
        created += 1
        print(f"Created: {task.task_id} (priority={task.priority})")

    print(f"\nGenerated {created} fix tasks from {len(patterns)} patterns")
    print(q.format_status())


if __name__ == "__main__":
    main()
