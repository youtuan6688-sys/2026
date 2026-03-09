import time
import logging
from functools import wraps

logger = logging.getLogger(__name__)


def retry(max_attempts: int = 3, delay: float = 1.0, backoff: float = 2.0):
    """Exponential backoff retry decorator."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    if attempt < max_attempts - 1:
                        wait = delay * (backoff ** attempt)
                        logger.warning(f"{func.__name__} failed (attempt {attempt + 1}), retrying in {wait}s: {e}")
                        time.sleep(wait)
            logger.error(f"{func.__name__} failed after {max_attempts} attempts: {last_error}")
            raise last_error
        return wrapper
    return decorator
