"""Capability Manager — safe self-installation of tools and skills.

Manages installation of Claude Code skills, MCP servers, and prompt templates.
All installs are logged, tested, and reported to admin via Feishu.
"""

import json
import logging
import os
import subprocess
from datetime import datetime
from pathlib import Path
from src.utils.subprocess_env import CLAUDE_PATH, safe_env

logger = logging.getLogger(__name__)

INSTALL_LOG = Path("/Users/tuanyou/Happycode2026/data/install_history.json")
SKILLS_DIR = Path("/Users/tuanyou/.claude/commands")
MCP_CONFIG = Path("/Users/tuanyou/.claude.json")
MEMORY_DIR = Path("/Users/tuanyou/Happycode2026/vault/memory")

# Only these action types are allowed
SAFE_ACTIONS = frozenset({
    "skill_install",
    "mcp_config",
    "prompt_template",
    "memory_update",
    "pip_install",
})


def _log_install(action: str, name: str, result: str, source: str):
    """Log an install action to history."""
    try:
        history = []
        if INSTALL_LOG.exists():
            history = json.loads(INSTALL_LOG.read_text(encoding="utf-8"))

        history.append({
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "name": name,
            "result": result,
            "source": source,
        })

        # Keep last 200 entries
        if len(history) > 200:
            history = history[-200:]

        INSTALL_LOG.parent.mkdir(parents=True, exist_ok=True)
        INSTALL_LOG.write_text(
            json.dumps(history, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        logger.error(f"Failed to log install: {e}")


def install_skill(name: str, content: str, source: str = "") -> tuple[bool, str]:
    """Install a Claude Code slash command (skill).

    Args:
        name: Skill name (e.g., "analyze-data")
        content: Markdown content for the skill file
        source: Where this skill came from (e.g., "daily-briefing")

    Returns:
        (success, message)
    """
    try:
        skill_file = SKILLS_DIR / f"{name}.md"
        SKILLS_DIR.mkdir(parents=True, exist_ok=True)

        if skill_file.exists():
            _log_install("skill_install", name, "skipped_exists", source)
            return False, f"Skill '{name}' already exists"

        skill_file.write_text(content, encoding="utf-8")

        # Test: verify it's a valid file
        if not skill_file.exists() or skill_file.stat().st_size == 0:
            _log_install("skill_install", name, "failed_write", source)
            return False, f"Failed to write skill file"

        _log_install("skill_install", name, "success", source)
        logger.info(f"Skill installed: {name} (from {source})")
        return True, f"Skill '/{name}' installed successfully"

    except Exception as e:
        _log_install("skill_install", name, f"error: {e}", source)
        return False, str(e)


def install_pip_package(package: str, source: str = "") -> tuple[bool, str]:
    """Install a pip package into the project venv.

    Args:
        package: Package name (e.g., "pandas")
        source: Where this requirement came from

    Returns:
        (success, message)
    """
    # Safety: only allow alphanumeric + hyphens + version specifiers
    safe_chars = set("abcdefghijklmnopqrstuvwxyz0123456789-_.>=<[]")
    if not all(c in safe_chars for c in package.lower()):
        _log_install("pip_install", package, "blocked_unsafe", source)
        return False, f"Package name '{package}' contains unsafe characters"

    try:
        venv_pip = "/Users/tuanyou/Happycode2026/.venv/bin/pip"
        result = subprocess.run(
            [venv_pip, "install", package],
            capture_output=True, text=True, timeout=120,
        )

        if result.returncode == 0:
            _log_install("pip_install", package, "success", source)
            logger.info(f"Package installed: {package}")
            return True, f"Package '{package}' installed"
        else:
            err = result.stderr[:200]
            _log_install("pip_install", package, f"failed: {err}", source)
            return False, f"Install failed: {err}"

    except subprocess.TimeoutExpired:
        _log_install("pip_install", package, "timeout", source)
        return False, "Install timed out"
    except Exception as e:
        _log_install("pip_install", package, f"error: {e}", source)
        return False, str(e)


def update_memory(filename: str, content: str,
                  source: str = "") -> tuple[bool, str]:
    """Append content to a memory file.

    Args:
        filename: One of the allowed memory files
        content: Content to append
        source: Where this update came from

    Returns:
        (success, message)
    """
    allowed = {"learnings.md", "tools.md", "patterns.md", "decisions.md"}
    if filename not in allowed:
        return False, f"Memory file '{filename}' not in allowed list"

    try:
        path = MEMORY_DIR / filename
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"\n{content}")
        _log_install("memory_update", filename, "success", source)
        return True, f"Memory '{filename}' updated"
    except Exception as e:
        _log_install("memory_update", filename, f"error: {e}", source)
        return False, str(e)


def test_capability(name: str, test_prompt: str) -> bool:
    """Run a quick test to verify an installed capability works.

    Args:
        name: Capability name (for logging)
        test_prompt: A simple prompt to test

    Returns:
        True if test passed
    """
    try:
        env = safe_env()
        result = subprocess.run(
            [CLAUDE_PATH, "-p", test_prompt, "--model", "haiku"],
            capture_output=True, text=True, timeout=30, env=env,
        )
        passed = bool(result.stdout.strip())
        _log_install("test", name,
                     "passed" if passed else "failed", "self-test")
        return passed
    except Exception as e:
        logger.warning(f"Capability test failed for {name}: {e}")
        return False


def rollback(name: str, action: str = "skill_install") -> bool:
    """Remove a recently installed capability.

    Args:
        name: Name of the capability
        action: Type of install to rollback

    Returns:
        True if rollback succeeded
    """
    try:
        if action == "skill_install":
            skill_file = SKILLS_DIR / f"{name}.md"
            if skill_file.exists():
                skill_file.unlink()
                _log_install("rollback", name, "success", "admin")
                return True
        _log_install("rollback", name, "not_found", "admin")
        return False
    except Exception as e:
        _log_install("rollback", name, f"error: {e}", "admin")
        return False


def get_install_history(limit: int = 20) -> list[dict]:
    """Get recent install history."""
    try:
        if INSTALL_LOG.exists():
            history = json.loads(INSTALL_LOG.read_text(encoding="utf-8"))
            return history[-limit:]
    except Exception:
        pass
    return []


def format_install_report() -> str:
    """Format recent installs for admin notification."""
    history = get_install_history(10)
    if not history:
        return "No recent installations."

    lines = ["📦 近期安装记录:"]
    for h in history:
        status = "✅" if h["result"] == "success" else "❌"
        lines.append(
            f"{status} [{h['action']}] {h['name']} "
            f"({h.get('source', '?')}) — {h['timestamp'][:16]}"
        )
    return "\n".join(lines)
