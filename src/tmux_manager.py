"""Manage persistent Claude Code sessions via tmux.

Each session runs in its own tmux window, allowing the bot to:
- Start long-running Claude sessions (e.g., /loop for periodic tasks)
- Send commands to existing sessions
- Read output from sessions
- Monitor session health and auto-restart dead ones
"""

import logging
import subprocess
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

CLAUDE_BIN = "/Users/tuanyou/.local/bin/claude"
TMUX_SESSION_PREFIX = "hc-"  # happycode prefix


@dataclass(frozen=True)
class SessionInfo:
    name: str
    alive: bool
    created: str


def _run(cmd: list[str], timeout: int = 10) -> tuple[int, str]:
    """Run a shell command and return (exit_code, stdout)."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
        )
        return result.returncode, result.stdout.strip()
    except subprocess.TimeoutExpired:
        return -1, "timeout"
    except Exception as e:
        return -1, str(e)


def list_sessions() -> list[SessionInfo]:
    """List all happycode tmux sessions."""
    code, out = _run(["tmux", "list-sessions", "-F", "#{session_name} #{session_created_string}"])
    if code != 0:
        return []

    sessions = []
    for line in out.split("\n"):
        if not line.strip():
            continue
        parts = line.split(" ", 1)
        name = parts[0]
        created = parts[1] if len(parts) > 1 else ""
        if name.startswith(TMUX_SESSION_PREFIX):
            # Check if session has active processes
            alive = is_alive(name)
            sessions.append(SessionInfo(name=name, alive=alive, created=created))
    return sessions


def is_alive(session_name: str) -> bool:
    """Check if a tmux session exists and has running processes."""
    code, _ = _run(["tmux", "has-session", "-t", session_name])
    return code == 0


def start_session(
    name: str,
    initial_command: str = "",
    working_dir: str = "/Users/tuanyou/Happycode2026",
) -> bool:
    """Start a new tmux session with an optional initial Claude command.

    Args:
        name: Session name (will be prefixed with TMUX_SESSION_PREFIX)
        initial_command: Command to run in the session (e.g., "claude" to start interactive)
        working_dir: Working directory for the session
    """
    session_name = f"{TMUX_SESSION_PREFIX}{name}"

    if is_alive(session_name):
        logger.warning(f"Session {session_name} already exists")
        return False

    cmd = [
        "tmux", "new-session", "-d",
        "-s", session_name,
        "-c", working_dir,
    ]

    code, out = _run(cmd)
    if code != 0:
        logger.error(f"Failed to create tmux session {session_name}: {out}")
        return False

    logger.info(f"Created tmux session: {session_name}")

    if initial_command:
        time.sleep(0.5)
        send_keys(name, initial_command)

    return True


def start_loop_session(
    name: str = "loop",
    interval: str = "60m",
    prompt_file: str = "",
    model: str = "sonnet",
    working_dir: str = "/Users/tuanyou/Happycode2026",
) -> bool:
    """Start a Claude session with /loop for periodic tasks.

    Args:
        name: Session name
        interval: Loop interval (e.g., "10m", "60m")
        prompt_file: Path to a prompt file for the loop task
        model: Claude model to use (haiku/sonnet/opus)
        working_dir: Working directory
    """
    session_name = f"{TMUX_SESSION_PREFIX}{name}"

    if is_alive(session_name):
        logger.warning(f"Loop session {session_name} already exists")
        return False

    # Start tmux session
    if not start_session(name, working_dir=working_dir):
        return False

    # Launch Claude interactively with specified model
    env_setup = "unset CLAUDECODE 2>/dev/null; "
    model_flag = f" --model {model}" if model else ""
    send_keys(name, f"{env_setup}{CLAUDE_BIN} --permission-mode auto{model_flag}")

    # Wait for Claude to start
    time.sleep(5)

    # Send /loop command
    loop_cmd = f"/loop {interval}"
    if prompt_file:
        loop_cmd += f" $(cat {prompt_file})"

    send_keys(name, loop_cmd)
    logger.info(f"Started loop session {session_name} with interval {interval}")
    return True


def send_keys(name: str, keys: str) -> bool:
    """Send keystrokes to a tmux session."""
    session_name = name if name.startswith(TMUX_SESSION_PREFIX) else f"{TMUX_SESSION_PREFIX}{name}"

    if not is_alive(session_name):
        logger.error(f"Session {session_name} not found")
        return False

    code, out = _run(["tmux", "send-keys", "-t", session_name, keys, "Enter"])
    if code != 0:
        logger.error(f"Failed to send keys to {session_name}: {out}")
        return False
    return True


def capture_output(name: str, lines: int = 50) -> str:
    """Capture recent output from a tmux session."""
    session_name = name if name.startswith(TMUX_SESSION_PREFIX) else f"{TMUX_SESSION_PREFIX}{name}"

    if not is_alive(session_name):
        return f"Session {session_name} not found"

    code, out = _run([
        "tmux", "capture-pane", "-t", session_name,
        "-p",  # print to stdout
        "-S", f"-{lines}",  # start N lines back
    ])

    if code != 0:
        return f"Failed to capture output: {out}"
    return out.strip()


def stop_session(name: str) -> bool:
    """Stop and destroy a tmux session."""
    session_name = name if name.startswith(TMUX_SESSION_PREFIX) else f"{TMUX_SESSION_PREFIX}{name}"

    if not is_alive(session_name):
        logger.info(f"Session {session_name} already stopped")
        return True

    # Send Ctrl-C first to gracefully stop any running process
    _run(["tmux", "send-keys", "-t", session_name, "C-c", ""])
    time.sleep(1)

    # Then kill the session
    code, out = _run(["tmux", "kill-session", "-t", session_name])
    if code != 0:
        logger.error(f"Failed to kill session {session_name}: {out}")
        return False

    logger.info(f"Stopped session: {session_name}")
    return True


def health_check() -> dict:
    """Check health of all managed sessions, return status dict."""
    sessions = list_sessions()
    return {
        "total": len(sessions),
        "alive": sum(1 for s in sessions if s.alive),
        "dead": sum(1 for s in sessions if not s.alive),
        "sessions": [
            {"name": s.name, "alive": s.alive, "created": s.created}
            for s in sessions
        ],
    }


def ensure_session(name: str, restart_cmd: str = "", **kwargs) -> bool:
    """Ensure a session is running; restart if dead."""
    session_name = f"{TMUX_SESSION_PREFIX}{name}"

    if is_alive(session_name):
        return True

    logger.warning(f"Session {session_name} is dead, restarting...")
    stop_session(name)  # cleanup any remnants

    if restart_cmd:
        return start_session(name, initial_command=restart_cmd, **kwargs)
    return start_session(name, **kwargs)


def format_status() -> str:
    """Format session status for display (e.g., in Feishu message)."""
    status = health_check()
    if status["total"] == 0:
        return "没有运行中的 tmux 会话"

    lines = [f"共 {status['total']} 个会话 ({status['alive']} 活跃, {status['dead']} 已停止)"]
    for s in status["sessions"]:
        icon = "🟢" if s["alive"] else "🔴"
        lines.append(f"  {icon} {s['name']} (创建: {s['created']})")
    return "\n".join(lines)
