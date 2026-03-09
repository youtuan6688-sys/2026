#!/usr/bin/env python3
"""Service health checker with auto-restart capabilities.
Checks: Feishu bot process, cron jobs, disk space, error rates, vector store.
Can be run standalone or imported as a module.
"""
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_DIR = Path("/Users/tuanyou/Happycode2026")
VAULT_DIR = PROJECT_DIR / "vault"
ERROR_LOG = VAULT_DIR / "logs/error_log.json"
HEALTH_LOG = VAULT_DIR / "logs/health_log.json"
VENV_PYTHON = str(PROJECT_DIR / ".venv/bin/python")


def check_feishu_bot() -> dict:
    """Check if Feishu bot process is running."""
    result = subprocess.run(
        ["pgrep", "-f", "src.main"],
        capture_output=True, text=True,
    )
    running = result.returncode == 0
    pid = result.stdout.strip().split("\n")[0] if running else None
    return {
        "name": "feishu_bot",
        "healthy": running,
        "pid": pid,
        "message": f"Running (PID {pid})" if running else "NOT RUNNING",
    }


def check_launchd_service() -> dict:
    """Check if launchd service is loaded."""
    result = subprocess.run(
        ["launchctl", "list", "com.happycode.feishu-bot"],
        capture_output=True, text=True,
    )
    loaded = result.returncode == 0
    return {
        "name": "launchd_service",
        "healthy": loaded,
        "message": "Loaded" if loaded else "NOT LOADED",
    }


def check_cron_jobs() -> dict:
    """Check if expected cron jobs exist."""
    result = subprocess.run(
        ["crontab", "-l"],
        capture_output=True, text=True,
    )
    cron_text = result.stdout if result.returncode == 0 else ""
    has_briefing = "run_briefing.sh" in cron_text
    has_nightly = "run_nightly_review.sh" in cron_text
    healthy = has_briefing and has_nightly
    missing = []
    if not has_briefing:
        missing.append("daily_briefing")
    if not has_nightly:
        missing.append("nightly_review")
    return {
        "name": "cron_jobs",
        "healthy": healthy,
        "message": "All cron jobs present" if healthy else f"Missing: {', '.join(missing)}",
    }


def check_disk_space() -> dict:
    """Check available disk space."""
    usage = shutil.disk_usage("/")
    free_gb = usage.free / (1024 ** 3)
    pct_used = (usage.used / usage.total) * 100
    healthy = free_gb > 5
    return {
        "name": "disk_space",
        "healthy": healthy,
        "free_gb": round(free_gb, 1),
        "pct_used": round(pct_used, 1),
        "message": f"{round(free_gb, 1)}GB free ({round(pct_used, 1)}% used)",
    }


def check_error_rate() -> dict:
    """Check recent error rate (last 1 hour)."""
    try:
        if not ERROR_LOG.exists():
            return {"name": "error_rate", "healthy": True, "message": "No error log"}
        errors = json.loads(ERROR_LOG.read_text(encoding="utf-8"))
        cutoff = (datetime.now() - timedelta(hours=1)).isoformat()
        recent = [e for e in errors if e.get("timestamp", "") > cutoff and not e.get("resolved")]
        high_severity = [e for e in recent if e.get("severity") in ("high", "critical")]
        healthy = len(high_severity) < 5
        return {
            "name": "error_rate",
            "healthy": healthy,
            "recent_count": len(recent),
            "high_severity_count": len(high_severity),
            "message": f"{len(recent)} errors/hr ({len(high_severity)} high/critical)",
        }
    except Exception as e:
        return {"name": "error_rate", "healthy": True, "message": f"Check failed: {e}"}


def check_vector_store() -> dict:
    """Check if vector store DB exists and is accessible."""
    db_path = PROJECT_DIR / "data/vector_store.db"
    if not db_path.exists():
        return {"name": "vector_store", "healthy": False, "message": "DB file missing"}
    size_mb = db_path.stat().st_size / (1024 * 1024)
    healthy = size_mb > 0.01
    return {
        "name": "vector_store",
        "healthy": healthy,
        "size_mb": round(size_mb, 2),
        "message": f"OK ({round(size_mb, 2)}MB)" if healthy else "Empty or corrupt",
    }


def check_claude_binary() -> dict:
    """Check if Claude Code binary is accessible."""
    claude_path = Path(os.path.expanduser("~/.local/bin/claude"))
    exists = claude_path.exists()
    if exists:
        result = subprocess.run(
            [str(claude_path), "--version"],
            capture_output=True, text=True, timeout=10,
            env={k: v for k, v in os.environ.items() if k != "CLAUDECODE"},
        )
        version = result.stdout.strip()[:50] if result.returncode == 0 else "unknown"
        return {"name": "claude_binary", "healthy": True, "message": f"OK ({version})"}
    return {"name": "claude_binary", "healthy": False, "message": "Binary not found"}


def restart_feishu_bot() -> str:
    """Attempt to restart Feishu bot via launchd."""
    try:
        subprocess.run(
            ["launchctl", "kickstart", "-k", "gui/501/com.happycode.feishu-bot"],
            capture_output=True, text=True, timeout=30,
        )
        return "Restart triggered via launchctl kickstart"
    except Exception as e:
        return f"Restart failed: {e}"


def reindex_vault() -> str:
    """Re-index the vector store."""
    try:
        result = subprocess.run(
            [VENV_PYTHON, str(PROJECT_DIR / "scripts/reindex_vault.py")],
            capture_output=True, text=True, timeout=120,
            cwd=str(PROJECT_DIR),
        )
        return result.stdout.strip()[:200] if result.returncode == 0 else f"Failed: {result.stderr[:200]}"
    except Exception as e:
        return f"Reindex failed: {e}"


def run_all_checks() -> dict:
    """Run all health checks and return results."""
    checks = [
        check_feishu_bot(),
        check_launchd_service(),
        check_cron_jobs(),
        check_disk_space(),
        check_error_rate(),
        check_vector_store(),
        check_claude_binary(),
    ]
    all_healthy = all(c["healthy"] for c in checks)
    report = {
        "timestamp": datetime.now().isoformat(),
        "all_healthy": all_healthy,
        "checks": checks,
    }
    return report


def auto_heal(report: dict) -> list[str]:
    """Attempt to auto-fix unhealthy services."""
    actions = []
    for check in report["checks"]:
        if check["healthy"]:
            continue
        name = check["name"]
        if name == "feishu_bot":
            result = restart_feishu_bot()
            actions.append(f"feishu_bot: {result}")
        elif name == "vector_store":
            result = reindex_vault()
            actions.append(f"vector_store: {result}")
        elif name == "launchd_service":
            # Try to reload the service
            plist = Path.home() / "Library/LaunchAgents/com.happycode.feishu-bot.plist"
            if plist.exists():
                subprocess.run(["launchctl", "load", str(plist)], capture_output=True)
                actions.append("launchd_service: Attempted to reload plist")
            else:
                actions.append("launchd_service: Plist not found, cannot auto-fix")
        elif name == "cron_jobs":
            actions.append(f"cron_jobs: {check['message']} — requires manual setup")
    return actions


def save_health_log(report: dict, actions: list[str]):
    """Append health check result to log."""
    HEALTH_LOG.parent.mkdir(parents=True, exist_ok=True)
    log_entry = {**report, "auto_heal_actions": actions}
    try:
        existing = json.loads(HEALTH_LOG.read_text(encoding="utf-8")) if HEALTH_LOG.exists() else []
    except Exception:
        existing = []
    existing.append(log_entry)
    # Keep last 100 entries
    if len(existing) > 100:
        existing = existing[-100:]
    HEALTH_LOG.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")


def format_report(report: dict, actions: list[str]) -> str:
    """Format health report for Feishu notification."""
    status = "ALL HEALTHY" if report["all_healthy"] else "ISSUES DETECTED"
    lines = [f"Health Check [{status}] {report['timestamp'][:16]}"]
    for c in report["checks"]:
        icon = "OK" if c["healthy"] else "WARN"
        lines.append(f"  [{icon}] {c['name']}: {c['message']}")
    if actions:
        lines.append("\nAuto-heal actions:")
        for a in actions:
            lines.append(f"  - {a}")
    return "\n".join(lines)


if __name__ == "__main__":
    report = run_all_checks()
    actions = []
    if not report["all_healthy"]:
        actions = auto_heal(report)
    save_health_log(report, actions)
    print(format_report(report, actions))
    sys.exit(0 if report["all_healthy"] else 1)
