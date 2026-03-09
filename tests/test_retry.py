import pytest
from unittest.mock import MagicMock, patch

from src.utils.retry import retry


class TestRetryDecorator:
    def test_success_on_first_try(self):
        @retry(max_attempts=3, delay=0.01)
        def always_works():
            return "ok"

        assert always_works() == "ok"

    def test_success_after_retries(self):
        call_count = 0

        @retry(max_attempts=3, delay=0.01)
        def fails_then_works():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("not yet")
            return "ok"

        assert fails_then_works() == "ok"
        assert call_count == 3

    def test_raises_after_max_attempts(self):
        @retry(max_attempts=2, delay=0.01)
        def always_fails():
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError, match="boom"):
            always_fails()

    def test_preserves_function_name(self):
        @retry(max_attempts=2)
        def my_function():
            pass

        assert my_function.__name__ == "my_function"

    def test_passes_args_and_kwargs(self):
        @retry(max_attempts=1, delay=0.01)
        def add(a, b, extra=0):
            return a + b + extra

        assert add(1, 2, extra=3) == 6

    @patch("src.utils.retry.time.sleep")
    def test_exponential_backoff(self, mock_sleep):
        call_count = 0

        @retry(max_attempts=3, delay=1.0, backoff=2.0)
        def fails_twice():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("fail")
            return "ok"

        fails_twice()
        assert mock_sleep.call_count == 2
        mock_sleep.assert_any_call(1.0)   # delay * backoff^0
        mock_sleep.assert_any_call(2.0)   # delay * backoff^1
