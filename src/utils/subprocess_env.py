"""Shared subprocess environment for Claude CLI calls."""

import os

CLAUDE_PATH = "/Users/tuanyou/.local/bin/claude"


def safe_env() -> dict:
    """Build a safe environment for subprocess calls to Claude CLI.

    Filters out CLAUDECODE to prevent nesting errors,
    ensures PATH includes Claude binary location.
    """
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    env["PATH"] = f"/Users/tuanyou/.local/bin:{env.get('PATH', '')}"
    return env
