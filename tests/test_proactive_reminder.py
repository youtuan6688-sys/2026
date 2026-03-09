"""Tests for proactive reminder."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from scripts.proactive_reminder import build_reminder


@pytest.fixture
def queue_with_tasks(tmp_path):
    queue_file = tmp_path / "queue.json"
    queue_file.write_text(json.dumps([
        {"task_id": "t1", "title": "Task 1", "prompt": "x", "priority": 3,
         "status": "pending", "depends_on": [], "timeout_seconds": 60,
         "category": "test", "result": "", "error": "", "created_at": "2026-03-05",
         "started_at": None, "completed_at": None, "retry_count": 0, "max_retries": 2}
    ]), encoding="utf-8")
    history_file = tmp_path / "history.json"
    history_file.write_text("[]", encoding="utf-8")
    return queue_file, history_file


@pytest.fixture
def error_log_with_errors(tmp_path):
    log_file = tmp_path / "error_log.json"
    log_file.write_text(json.dumps([
        {"error_type": "timeout", "message": "test timeout", "source": "test",
         "severity": "high", "resolved": False, "timestamp": "2026-03-05T10:00:00"}
    ]), encoding="utf-8")
    return log_file


class TestBuildReminder:
    def test_returns_none_when_nothing_to_report(self, tmp_path):
        with patch("scripts.proactive_reminder.QUEUE_FILE", tmp_path / "empty_q.json"), \
             patch("scripts.proactive_reminder.HISTORY_FILE", tmp_path / "empty_h.json"), \
             patch("scripts.proactive_reminder.ERROR_LOG", tmp_path / "empty_e.json"):
            # Create empty queue
            (tmp_path / "empty_q.json").write_text("[]", encoding="utf-8")
            (tmp_path / "empty_h.json").write_text("[]", encoding="utf-8")
            (tmp_path / "empty_e.json").write_text("[]", encoding="utf-8")
            result = build_reminder()
            assert result is None

    def test_reports_pending_tasks(self, queue_with_tasks, tmp_path):
        queue_file, history_file = queue_with_tasks
        with patch("scripts.proactive_reminder.QUEUE_FILE", queue_file), \
             patch("scripts.proactive_reminder.HISTORY_FILE", history_file), \
             patch("scripts.proactive_reminder.ERROR_LOG", tmp_path / "no_errors.json"):
            result = build_reminder()
            assert result is not None
            assert "1 pending" in result
            assert "Task 1" in result

    def test_reports_unresolved_errors(self, error_log_with_errors, tmp_path):
        (tmp_path / "q.json").write_text("[]", encoding="utf-8")
        (tmp_path / "h.json").write_text("[]", encoding="utf-8")
        with patch("scripts.proactive_reminder.QUEUE_FILE", tmp_path / "q.json"), \
             patch("scripts.proactive_reminder.HISTORY_FILE", tmp_path / "h.json"), \
             patch("scripts.proactive_reminder.ERROR_LOG", error_log_with_errors):
            result = build_reminder()
            assert result is not None
            assert "Unresolved errors: 1" in result
