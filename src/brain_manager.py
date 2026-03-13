"""BrainManager — singleton lifecycle manager for the persistent Brain session.

Manages Brain for private chat, with TTL-based restart and fallback to subprocess.
Group chats continue using per-message subprocess (different persona/system prompt).
"""

import logging
import threading
import time

from src.brain import Brain

logger = logging.getLogger(__name__)

# Restart Brain after this many messages (context window hygiene)
MAX_MESSAGES_PER_SESSION = 50
# Restart Brain after this many seconds of idle
IDLE_TIMEOUT_S = 3600  # 60 minutes


class BrainManager:
    """Singleton manager for the persistent Brain session."""

    _instance = None
    _init_lock = threading.Lock()

    def __new__(cls):
        with cls._init_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._brain = Brain()
        self._message_count = 0
        self._last_activity = 0.0
        self._lock = threading.Lock()
        self._initialized = True

    @property
    def is_available(self) -> bool:
        """Check if Brain is usable (alive and not stale)."""
        with self._lock:
            if not self._brain.is_alive:
                return False
            if self._message_count >= MAX_MESSAGES_PER_SESSION:
                logger.info(
                    f"Brain hit message limit ({self._message_count}), "
                    "will restart on next send"
                )
                return False
            if (self._last_activity > 0
                    and time.time() - self._last_activity > IDLE_TIMEOUT_S):
                logger.info("Brain idle timeout, will restart on next send")
                return False
            return True

    def send(self, text: str, timeout: int = 120) -> str | None:
        """Send a message via Brain. Returns response or None on failure.

        Returns None (not error string) so caller can fall back to subprocess.
        """
        with self._lock:
            needs_restart = (
                not self._brain.is_alive
                or self._message_count >= MAX_MESSAGES_PER_SESSION
                or (self._last_activity > 0
                    and time.time() - self._last_activity > IDLE_TIMEOUT_S)
            )
            if needs_restart:
                logger.info("Brain needs restart, restarting...")
                self._brain.restart()
                self._message_count = 0

        try:
            response = self._brain.send_message(text, timeout=timeout)
        except Exception as e:
            logger.error(f"Brain send failed: {e}")
            return None

        # Check for error responses from Brain
        if not response or response.startswith("主脑"):
            logger.warning(f"Brain returned error: {response}")
            return None

        with self._lock:
            self._message_count += 1
            self._last_activity = time.time()

        return response

    def stop(self):
        """Stop the Brain process."""
        with self._lock:
            self._brain.stop()
            self._message_count = 0
            self._last_activity = 0.0

    def get_stats(self) -> dict:
        """Return Brain session stats for monitoring."""
        with self._lock:
            return {
                "alive": self._brain.is_alive,
                "message_count": self._message_count,
                "idle_seconds": (
                    int(time.time() - self._last_activity)
                    if self._last_activity > 0 else 0
                ),
                "max_messages": MAX_MESSAGES_PER_SESSION,
            }
