"""Tests for auto task generator from error patterns."""

import json
import pytest
from pathlib import Path

from scripts.generate_fix_tasks import (
    load_errors,
    find_recurring_patterns,
    generate_task,
)
from src.task_queue import TaskQueue


@pytest.fixture
def error_log(tmp_path):
    log_file = tmp_path / "error_log.json"
    errors = [
        {"error_type": "timeout", "message": f"timeout #{i}", "source": "execute_claude",
         "severity": "high", "resolved": False, "timestamp": f"2026-03-05T10:0{i}:00"}
        for i in range(5)
    ] + [
        {"error_type": "kb_query_error", "message": f"query fail #{i}", "source": "query_knowledge_base",
         "severity": "medium", "resolved": False, "timestamp": f"2026-03-05T11:0{i}:00"}
        for i in range(3)
    ] + [
        {"error_type": "rare_error", "message": "one-off", "source": "somewhere",
         "severity": "low", "resolved": False, "timestamp": "2026-03-05T12:00:00"}
    ] + [
        {"error_type": "resolved_error", "message": "already fixed", "source": "old",
         "severity": "high", "resolved": True, "timestamp": "2026-03-04T10:00:00"}
    ]
    log_file.write_text(json.dumps(errors, ensure_ascii=False), encoding="utf-8")
    return log_file


class TestFindRecurringPatterns:
    def test_finds_patterns_above_threshold(self, error_log):
        import scripts.generate_fix_tasks as mod
        orig = mod.ERROR_LOG
        mod.ERROR_LOG = error_log
        try:
            errors = load_errors()
            patterns = find_recurring_patterns(errors)
            types = [p["error_type"] for p in patterns]
            assert "timeout" in types
            assert "kb_query_error" in types
            assert "rare_error" not in types
            assert "resolved_error" not in types
        finally:
            mod.ERROR_LOG = orig

    def test_sorts_by_severity_then_count(self, error_log):
        import scripts.generate_fix_tasks as mod
        orig = mod.ERROR_LOG
        mod.ERROR_LOG = error_log
        try:
            errors = load_errors()
            patterns = find_recurring_patterns(errors)
            # "timeout" is high severity, should come first
            assert patterns[0]["error_type"] == "timeout"
        finally:
            mod.ERROR_LOG = orig

    def test_empty_log(self, tmp_path):
        import scripts.generate_fix_tasks as mod
        orig = mod.ERROR_LOG
        mod.ERROR_LOG = tmp_path / "nonexistent.json"
        try:
            errors = load_errors()
            assert errors == []
            patterns = find_recurring_patterns(errors)
            assert patterns == []
        finally:
            mod.ERROR_LOG = orig


class TestGenerateTask:
    def test_creates_valid_task(self):
        pattern = {
            "error_type": "timeout",
            "count": 5,
            "sources": ["execute_claude"],
            "messages": ["timeout #1", "timeout #2"],
            "max_severity": "high",
        }
        task = generate_task(pattern)
        assert task.task_id.startswith("autofix-timeout")
        assert task.category == "autofix"
        assert task.priority == 2  # high severity
        assert "timeout" in task.prompt
        assert task.max_retries == 1

    def test_priority_mapping(self):
        for severity, expected_priority in [("critical", 1), ("high", 2), ("medium", 4), ("low", 6)]:
            pattern = {
                "error_type": "test",
                "count": 3,
                "sources": ["test"],
                "messages": ["msg"],
                "max_severity": severity,
            }
            task = generate_task(pattern)
            assert task.priority == expected_priority


class TestIntegration:
    def test_full_pipeline(self, error_log, tmp_path):
        import scripts.generate_fix_tasks as mod
        from src.task_queue import TaskQueue

        orig_log = mod.ERROR_LOG
        mod.ERROR_LOG = error_log
        try:
            errors = load_errors()
            patterns = find_recurring_patterns(errors)

            q = TaskQueue(
                queue_file=tmp_path / "queue.json",
                history_file=tmp_path / "history.json",
            )

            for pattern in patterns:
                task = generate_task(pattern)
                q.add(task)

            assert q.get_pending_count() == 2  # timeout + kb_query_error
            stats = q.get_stats()
            assert stats["pending"] == 2
        finally:
            mod.ERROR_LOG = orig_log
