"""Concurrency control for message processing.

- Private chat (admin): dedicated slot, always executes immediately
- Group chat: shared pool with max concurrency, queued when full
- File write locks to prevent corruption
"""

import logging
import threading
from collections import deque
from typing import Callable

logger = logging.getLogger(__name__)

# Max concurrent claude -p processes for group chat
MAX_GROUP_WORKERS = 2


class MessageGate:
    """Controls concurrent message processing with priority."""

    def __init__(self, max_group_workers: int = MAX_GROUP_WORKERS):
        # Private chat: 2 slots — long task + instant admin message
        self._private_lock = threading.Semaphore(2)

        # Group chat: bounded worker pool
        self._group_semaphore = threading.Semaphore(max_group_workers)
        self._group_queue_size = 0
        self._group_queue_lock = threading.Lock()
        self._max_group_queue = 10  # Drop messages if queue exceeds this

        # File write lock (shared across all threads)
        self._file_lock = threading.Lock()

    @property
    def file_lock(self) -> threading.Lock:
        """Lock for file writes (contacts, persona, memory)."""
        return self._file_lock

    def run_private(self, fn: Callable, *args, **kwargs):
        """Run a private chat task. Always executes, waits if another private task is running."""
        def _wrapper():
            with self._private_lock:
                try:
                    fn(*args, **kwargs)
                except Exception as e:
                    logger.error(f"Private task failed: {e}", exc_info=True)
        threading.Thread(target=_wrapper, daemon=True).start()

    def run_group(self, fn: Callable, sender_id: str, *args, **kwargs) -> bool:
        """Run a group chat task. Returns False if queue is full (message dropped).

        Group tasks are bounded by max_group_workers concurrent processes.
        """
        with self._group_queue_lock:
            if self._group_queue_size >= self._max_group_queue:
                logger.warning(f"Group queue full ({self._group_queue_size}), dropping message")
                return False
            self._group_queue_size += 1

        def _wrapper():
            try:
                with self._group_semaphore:
                    fn(*args, **kwargs)
            except Exception as e:
                logger.error(f"Group task failed: {e}", exc_info=True)
            finally:
                with self._group_queue_lock:
                    self._group_queue_size -= 1

        threading.Thread(target=_wrapper, daemon=True).start()
        return True

    def get_stats(self) -> dict:
        """Get current concurrency stats."""
        return {
            "group_queue": self._group_queue_size,
            "max_group_workers": MAX_GROUP_WORKERS,
        }
