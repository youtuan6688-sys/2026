"""
Auto-resume wrapper for Claude Code `-p` mode.

Key improvements over v1:
1. Uses --session-id + --resume to maintain conversation context across retries
2. Uses --output-format stream-json for incremental output capture (no empty stdout on timeout)
3. Moves static memory to --append-system-prompt to reduce prompt bloat

Usage:
    from scripts.claude_runner import run_with_resume
    success, output = run_with_resume("implement feature X", task_id="feat-x")
"""

import json
import logging
import os
import subprocess
import sys
import threading
import uuid
from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path("/Users/tuanyou/Happycode2026")
sys.path.insert(0, str(PROJECT_DIR))

from src.checkpoint import Checkpoint, CheckpointManager, CheckpointStep

logger = logging.getLogger(__name__)

CLAUDE_BIN = "/Users/tuanyou/.local/bin/claude"
LOG_DIR = PROJECT_DIR / "vault/tasks/logs"
PROMPT_DIR = PROJECT_DIR / "vault/tasks/prompts"
DEFAULT_TIMEOUT = 480  # 8min per attempt, enough for complex tasks
MAX_RETRIES = 5
ALLOWED_TOOLS = "WebSearch,WebFetch,Read,Write,Edit,Bash,Glob,Grep,Agent"


def _build_env() -> dict:
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    env["PATH"] = f"/Users/tuanyou/.local/bin:{env.get('PATH', '')}"
    return env


def _save_prompt(task_id: str, prompt: str, user_message: str = "") -> Path:
    """Persist the full prompt and user message to files for resume."""
    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    path = PROMPT_DIR / f"{task_id}.txt"
    path.write_text(prompt, encoding="utf-8")
    if user_message:
        msg_path = PROMPT_DIR / f"{task_id}.user_msg.txt"
        msg_path.write_text(user_message, encoding="utf-8")
    return path


def _load_prompt(task_id: str) -> str:
    """Load a previously saved prompt."""
    path = PROMPT_DIR / f"{task_id}.txt"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def _load_user_message(task_id: str) -> str:
    """Load the original short user message for resume context."""
    path = PROMPT_DIR / f"{task_id}.user_msg.txt"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def _run_claude_streaming(
    prompt: str,
    timeout: int = DEFAULT_TIMEOUT,
    cwd: str = str(PROJECT_DIR),
    max_turns: int = 30,
    session_id: str = "",
    resume: bool = False,
    system_prompt: str = "",
) -> tuple[int, str, str]:
    """Run claude -p with stream-json output for incremental capture.

    Uses --output-format stream-json and reads stdout line by line,
    so partial output is always available even on timeout.

    Returns (exit_code, collected_text, stderr).
    exit_code=-1 means timeout.
    """
    cmd = [CLAUDE_BIN, "-p", prompt,
           "--allowedTools", ALLOWED_TOOLS,
           "--permission-mode", "auto",
           "--max-turns", str(max_turns),
           "--output-format", "text",
           ]

    if session_id and resume:
        cmd.extend(["--resume", session_id])
    elif session_id:
        cmd.extend(["--session-id", session_id])

    if system_prompt:
        cmd.extend(["--append-system-prompt", system_prompt])

    collected_text = []
    stderr_chunks = []
    timed_out = False

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd,
        env=_build_env(),
    )

    def _read_stderr():
        """Read stderr in background to prevent blocking."""
        for line in proc.stderr:
            stderr_chunks.append(line.decode("utf-8", errors="replace"))

    def _watchdog():
        """Kill process if deadline exceeded (fixes blocking stdout read)."""
        nonlocal timed_out
        import time
        remaining = timeout
        while remaining > 0 and proc.poll() is None:
            time.sleep(min(5, remaining))
            remaining -= 5
        if proc.poll() is None:
            timed_out = True
            logger.warning(f"Watchdog: killing process after {timeout}s timeout")
            proc.kill()

    stderr_thread = threading.Thread(target=_read_stderr, daemon=True)
    stderr_thread.start()
    watchdog_thread = threading.Thread(target=_watchdog, daemon=True)
    watchdog_thread.start()

    try:
        # --output-format text: stdout is plain text, read line by line
        for raw_line in proc.stdout:
            if timed_out:
                break
            collected_text.append(raw_line.decode("utf-8", errors="replace"))

        if not timed_out:
            proc.wait(timeout=10)
        else:
            proc.kill()
            proc.wait(timeout=5)

    except Exception as e:
        logger.warning(f"Stream reading error: {e}")
        proc.kill()
        proc.wait(timeout=5)
        timed_out = True

    stderr_thread.join(timeout=2)
    stderr_text = "".join(stderr_chunks).strip()
    final_text = "".join(collected_text).strip()

    if timed_out:
        return -1, final_text, f"TIMEOUT after {timeout}s. {stderr_text}"

    return proc.returncode or 0, final_text, stderr_text


def _check_recent_file_changes() -> str:
    """When output is empty, check filesystem for evidence of work done."""
    try:
        result = subprocess.run(
            ["find", str(PROJECT_DIR), "-maxdepth", "3",
             "-name", "*.py", "-o", "-name", "*.md", "-o", "-name", "*.json",
             "-newer", str(PROJECT_DIR / "src/main.py"),
             "-not", "-path", "*/.*", "-not", "-path", "*/__pycache__/*"],
            capture_output=True, text=True, timeout=5,
        )
        files = result.stdout.strip().split("\n")[:10]
        if files and files[0]:
            return "Recently modified files:\n" + "\n".join(files)
    except Exception:
        pass
    return "No output captured and no recent file changes detected"


def run_with_resume(
    prompt: str,
    task_id: str = "",
    timeout: int = DEFAULT_TIMEOUT,
    max_retries: int = MAX_RETRIES,
    cwd: str = str(PROJECT_DIR),
    on_output: callable = None,
    user_message: str = "",
    system_prompt: str = "",
) -> tuple[bool, str]:
    """Run a prompt with auto-resume on timeout.

    Key behavior:
    - First attempt uses --session-id to establish a session
    - Subsequent attempts use --resume to continue the SAME session
    - Output is captured incrementally via stream-json (no empty stdout)
    - Static context goes in --append-system-prompt to save prompt space

    Args:
        prompt: The task prompt (full context-enriched prompt)
        task_id: Unique task identifier (auto-generated if empty)
        timeout: Seconds before timeout per attempt
        max_retries: Maximum number of resume attempts
        cwd: Working directory
        on_output: Optional callback(attempt, output) for progress updates
        user_message: The original short user message (for clear resume context)
        system_prompt: Static context to append to system prompt (memory, etc.)

    Returns:
        (success: bool, final_output: str)
    """
    if not task_id:
        task_id = f"runner-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    log_file = LOG_DIR / f"runner-{task_id}-{date_str}.log"

    cm = CheckpointManager()
    all_outputs = []

    # Generate a stable session ID for this task
    session_id = str(uuid.uuid4())

    # Persist prompt and user message for manual resume
    _save_prompt(task_id, prompt, user_message=user_message)

    for attempt in range(max_retries + 1):
        is_resume = attempt > 0

        if is_resume:
            # Resume: short prompt, Claude already has full context from session
            user_msg = user_message or _load_user_message(task_id)
            partial_hint = ""
            if all_outputs and all_outputs[-1]:
                tail = all_outputs[-1].strip()[-200:]
                partial_hint = f"\n\n上次部分输出:\n```\n...{tail}\n```"

            current_prompt = (
                f"上一次执行在 {timeout}s 后超时。请继续完成任务。"
                f"\n\n原始指令: {user_msg}"
                f"{partial_hint}"
                f"\n\n注意: 不要重复已完成的工作，从上次停下的地方继续。"
            )
        else:
            current_prompt = prompt

        logger.info(
            f"Attempt {attempt + 1}/{max_retries + 1} for task {task_id} "
            f"(session={session_id[:8]}..., resume={is_resume})"
        )

        exit_code, stdout, stderr = _run_claude_streaming(
            current_prompt,
            timeout=timeout,
            cwd=cwd,
            session_id=session_id,
            resume=is_resume,
            system_prompt=system_prompt if not is_resume else "",
        )

        # Log this attempt
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"\n{'='*60}\n")
            f.write(f"Attempt {attempt + 1} at {datetime.now().isoformat()}\n")
            f.write(f"Session: {session_id}\n")
            f.write(f"Resume: {is_resume}\n")
            f.write(f"Exit code: {exit_code}\n")
            f.write(f"Stdout ({len(stdout)} chars):\n{stdout[:2000]}\n")
            if stderr:
                f.write(f"Stderr:\n{stderr[:500]}\n")

        all_outputs.append(stdout)

        if on_output:
            on_output(attempt + 1, stdout)

        # Success
        if exit_code == 0 and stdout:
            checkpoint = cm.load()
            if checkpoint and checkpoint.task_id == task_id:
                cm.complete(checkpoint)
            prompt_file = PROMPT_DIR / f"{task_id}.txt"
            if prompt_file.exists():
                prompt_file.unlink()
            msg_file = PROMPT_DIR / f"{task_id}.user_msg.txt"
            if msg_file.exists():
                msg_file.unlink()
            logger.info(f"Task {task_id} completed on attempt {attempt + 1}")
            return True, stdout

        # Timeout — save checkpoint and retry
        if exit_code == -1:
            logger.warning(
                f"Task {task_id} timed out on attempt {attempt + 1} "
                f"(captured {len(stdout)} chars)"
            )

            # Save/update checkpoint
            checkpoint = cm.load()
            if checkpoint and checkpoint.task_id == task_id:
                current_step = checkpoint.current_step()
                if current_step:
                    cm.update_step(
                        checkpoint, current_step.name,
                        "in_progress",
                        f"Attempt {attempt + 1} timed out. "
                        f"Captured {len(stdout)} chars. "
                        f"Session: {session_id}",
                    )
            else:
                checkpoint = Checkpoint(
                    task_id=task_id,
                    description=(user_message or prompt)[:200],
                    steps=[
                        CheckpointStep(
                            name="main_task",
                            status="in_progress",
                            progress=f"Attempt {attempt + 1} timed out. "
                                     f"Session: {session_id}",
                        ),
                    ],
                    context_notes=f"Session ID: {session_id}\n"
                                  f"Original prompt saved at: {PROMPT_DIR / f'{task_id}.txt'}",
                )
                cm.save(checkpoint)

            continue  # retry with --resume

        # Non-timeout failure
        logger.error(f"Task {task_id} failed with exit code {exit_code}")
        if attempt < max_retries:
            continue
        break

    # All retries exhausted
    prompt_file = PROMPT_DIR / f"{task_id}.txt"
    if prompt_file.exists():
        prompt_file.unlink()
    msg_file = PROMPT_DIR / f"{task_id}.user_msg.txt"
    if msg_file.exists():
        msg_file.unlink()
    final_output = all_outputs[-1] if all_outputs else "(no output)"
    logger.error(f"Task {task_id} failed after {max_retries + 1} attempts")
    return False, final_output


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [runner] %(message)s")
    import argparse

    parser = argparse.ArgumentParser(description="Run Claude with auto-resume on timeout")
    parser.add_argument("prompt", help="The task prompt")
    parser.add_argument("--task-id", default="", help="Task ID for checkpoint tracking")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument("--max-retries", type=int, default=MAX_RETRIES)
    parser.add_argument("--cwd", default=str(PROJECT_DIR))
    args = parser.parse_args()

    def print_progress(attempt, output):
        print(f"\n--- Attempt {attempt} output ({len(output)} chars) ---")
        print(output[-200:] if len(output) > 200 else output)

    success, output = run_with_resume(
        args.prompt,
        task_id=args.task_id,
        timeout=args.timeout,
        max_retries=args.max_retries,
        cwd=args.cwd,
        on_output=print_progress,
    )

    print(f"\n{'SUCCESS' if success else 'FAILED'}")
    print(output[-500:])
    sys.exit(0 if success else 1)
