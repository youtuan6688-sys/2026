"""Persistent 'brain' Claude session using stream-json bidirectional I/O.

The brain is a long-lived Claude process that maintains conversation context.
Messages are sent via stdin (stream-json) and responses read from stdout.

This replaces the per-message subprocess.run(claude -p ...) pattern,
saving token costs by reusing context across messages.
"""

import json
import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from queue import Queue, Empty
from src.utils.subprocess_env import CLAUDE_PATH, safe_env

logger = logging.getLogger(__name__)

CLAUDE_BIN = "/Users/tuanyou/.local/bin/claude"
PROJECT_DIR = Path("/Users/tuanyou/Happycode2026")
BRAIN_MEMORY = PROJECT_DIR / "team" / "roles" / "brain" / "memory.md"
VAULT_MEMORY_DIR = PROJECT_DIR / "vault" / "memory"


def _build_system_prompt() -> str:
    """Build system prompt from brain memory + vault memory summaries."""
    parts = []

    # Brain role memory
    if BRAIN_MEMORY.exists():
        parts.append(BRAIN_MEMORY.read_text(encoding="utf-8"))

    # Key vault memory files (concise versions)
    for name in ("profile.md", "tools.md", "decisions.md", "learnings.md"):
        path = VAULT_MEMORY_DIR / name
        if path.exists():
            content = path.read_text(encoding="utf-8")
            # Truncate large files to save tokens
            if len(content) > 2000:
                content = content[:2000] + "\n...(truncated)"
            parts.append(f"--- {name} ---\n{content}")

    return "\n\n".join(parts)


class Brain:
    """A persistent Claude session that acts as the central brain."""

    def __init__(self):
        self._proc: subprocess.Popen | None = None
        self._response_queue: Queue = Queue()
        self._reader_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._started = False

    @property
    def is_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self) -> bool:
        """Start the persistent brain process."""
        with self._lock:
            if self.is_alive:
                logger.info("Brain already running")
                return True

            system_prompt = _build_system_prompt()
            env = safe_env()

            cmd = [
                CLAUDE_BIN,
                "--input-format", "stream-json",
                "--output-format", "stream-json",
                "--permission-mode", "auto",
                "--verbose",
                "--allowedTools", "Read,Write,Edit,Bash,Glob,Grep,WebSearch,WebFetch,Agent",
                "--append-system-prompt", system_prompt,
            ]

            try:
                self._proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=str(PROJECT_DIR),
                    env=env,
                )

                # Start reader threads
                self._reader_thread = threading.Thread(
                    target=self._read_stdout, daemon=True,
                )
                self._reader_thread.start()

                self._stderr_thread = threading.Thread(
                    target=self._read_stderr, daemon=True,
                )
                self._stderr_thread.start()

                self._started = True
                logger.info(f"Brain started (PID {self._proc.pid})")
                return True

            except Exception as e:
                logger.error(f"Failed to start brain: {e}")
                return False

    def stop(self):
        """Stop the brain process."""
        with self._lock:
            if self._proc and self._proc.poll() is None:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
                logger.info("Brain stopped")
            self._proc = None
            self._started = False

    def restart(self) -> bool:
        """Restart the brain (e.g., after context gets too large)."""
        logger.info("Restarting brain...")
        self.stop()
        time.sleep(1)
        return self.start()

    def send_message(self, text: str, timeout: int = 120) -> str:
        """Send a user message and wait for the complete response.

        Args:
            text: User message text
            timeout: Max seconds to wait for response

        Returns:
            The assistant's response text, or error message
        """
        if not self.is_alive:
            if not self.start():
                return "主脑启动失败，请稍后重试"

        # Clear any stale responses
        while not self._response_queue.empty():
            try:
                self._response_queue.get_nowait()
            except Empty:
                break

        # Send user message via stdin (stream-json format)
        message = json.dumps({
            "type": "user",
            "content": text,
        }) + "\n"

        try:
            self._proc.stdin.write(message.encode("utf-8"))
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            logger.error(f"Brain pipe broken: {e}")
            self.restart()
            return "主脑连接中断，已重启，请重新发送"

        # Wait for response
        try:
            response = self._response_queue.get(timeout=timeout)
            return response
        except Empty:
            logger.warning(f"Brain response timeout after {timeout}s")
            return "主脑响应超时，任务可能仍在执行中"

    def _read_stdout(self):
        """Background thread: read stream-json events from stdout."""
        collected_text = []

        for raw_line in self._proc.stdout:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line:
                continue

            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                collected_text.append(line)
                continue

            event_type = event.get("type", "")

            if event_type == "content_block_delta":
                delta = event.get("delta", {})
                text = delta.get("text", "")
                if text:
                    collected_text.append(text)

            elif event_type == "result":
                result_text = event.get("result", "")
                if result_text:
                    self._response_queue.put(result_text)
                    collected_text.clear()
                elif collected_text:
                    self._response_queue.put("".join(collected_text))
                    collected_text.clear()

            elif event_type == "assistant":
                content = event.get("message", {}).get("content", [])
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = block.get("text", "")
                        if text:
                            collected_text.append(text)

            elif event_type == "error":
                error_msg = event.get("error", {}).get("message", "Unknown error")
                logger.error(f"Brain error event: {error_msg}")
                self._response_queue.put(f"主脑错误: {error_msg}")
                collected_text.clear()

        # Process exited
        if collected_text:
            self._response_queue.put("".join(collected_text))
        logger.warning("Brain stdout reader exited (process ended)")

    def _read_stderr(self):
        """Background thread: read stderr for debugging."""
        for raw_line in self._proc.stderr:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if line:
                logger.debug(f"Brain stderr: {line}")
