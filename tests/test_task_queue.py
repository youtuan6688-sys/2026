"""Tests for Task Queue system."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch

from src.task_queue import Task, TaskQueue


@pytest.fixture
def tmp_queue(tmp_path):
    queue_file = tmp_path / "queue.json"
    history_file = tmp_path / "history.json"
    return TaskQueue(queue_file=queue_file, history_file=history_file)


@pytest.fixture
def sample_task():
    return Task(
        task_id="test-001",
        title="Test Task",
        prompt="Do something",
        priority=5,
        category="test",
        timeout_seconds=60,
    )


class TestTask:
    def test_create_task(self, sample_task):
        assert sample_task.task_id == "test-001"
        assert sample_task.status == "pending"
        assert sample_task.retry_count == 0

    def test_to_dict_roundtrip(self, sample_task):
        d = sample_task.to_dict()
        restored = Task.from_dict(d)
        assert restored.task_id == sample_task.task_id
        assert restored.title == sample_task.title
        assert restored.priority == sample_task.priority

    def test_from_dict_defaults(self):
        t = Task.from_dict({"task_id": "min", "title": "Minimal"})
        assert t.priority == 5
        assert t.status == "pending"
        assert t.max_retries == 2


class TestTaskQueue:
    def test_add_task(self, tmp_queue, sample_task):
        tmp_queue.add(sample_task)
        assert tmp_queue.get_pending_count() == 1

    def test_add_duplicate_skipped(self, tmp_queue, sample_task):
        tmp_queue.add(sample_task)
        tmp_queue.add(sample_task)
        assert tmp_queue.get_pending_count() == 1

    def test_next_returns_highest_priority(self, tmp_queue):
        tmp_queue.add(Task(task_id="low", title="Low", prompt="x", priority=8))
        tmp_queue.add(Task(task_id="high", title="High", prompt="x", priority=2))
        tmp_queue.add(Task(task_id="mid", title="Mid", prompt="x", priority=5))
        nxt = tmp_queue.next()
        assert nxt.task_id == "high"

    def test_next_respects_dependencies(self, tmp_queue):
        tmp_queue.add(Task(
            task_id="dep",
            title="Dependent",
            prompt="x",
            priority=1,
            depends_on=["prereq"],
        ))
        tmp_queue.add(Task(task_id="free", title="Free", prompt="x", priority=5))
        nxt = tmp_queue.next()
        assert nxt.task_id == "free"

    def test_next_unblocks_after_dependency_completed(self, tmp_queue):
        tmp_queue.add(Task(task_id="prereq", title="Prereq", prompt="x", priority=1))
        tmp_queue.add(Task(
            task_id="dep",
            title="Dependent",
            prompt="x",
            priority=1,
            depends_on=["prereq"],
        ))
        # Complete prereq
        tmp_queue.mark_running("prereq")
        tmp_queue.mark_completed("prereq", "done")
        nxt = tmp_queue.next()
        assert nxt.task_id == "dep"

    def test_next_returns_none_when_empty(self, tmp_queue):
        assert tmp_queue.next() is None

    def test_mark_running(self, tmp_queue, sample_task):
        tmp_queue.add(sample_task)
        tmp_queue.mark_running("test-001")
        assert tmp_queue.get_running_count() == 1
        assert tmp_queue.get_pending_count() == 0

    def test_mark_completed_moves_to_history(self, tmp_queue, sample_task):
        tmp_queue.add(sample_task)
        tmp_queue.mark_running("test-001")
        tmp_queue.mark_completed("test-001", "success")
        assert tmp_queue.get_pending_count() == 0
        assert tmp_queue.get_running_count() == 0
        stats = tmp_queue.get_stats()
        assert stats["completed"] == 1

    def test_mark_failed_retries(self, tmp_queue):
        task = Task(task_id="retry-me", title="Retry", prompt="x", max_retries=2)
        tmp_queue.add(task)
        tmp_queue.mark_running("retry-me")
        tmp_queue.mark_failed("retry-me", "timeout")
        # Should be back to pending for retry
        assert tmp_queue.get_pending_count() == 1

    def test_mark_failed_permanent_after_max_retries(self, tmp_queue):
        task = Task(task_id="fail-me", title="Fail", prompt="x", max_retries=1)
        tmp_queue.add(task)
        # First failure -> retry
        tmp_queue.mark_running("fail-me")
        tmp_queue.mark_failed("fail-me", "error1")
        assert tmp_queue.get_pending_count() == 1
        # Second failure -> permanent
        tmp_queue.mark_running("fail-me")
        tmp_queue.mark_failed("fail-me", "error2")
        assert tmp_queue.get_pending_count() == 0
        stats = tmp_queue.get_stats()
        assert stats["failed"] == 1

    def test_get_stats(self, tmp_queue, sample_task):
        tmp_queue.add(sample_task)
        stats = tmp_queue.get_stats()
        assert stats["pending"] == 1
        assert stats["running"] == 0

    def test_format_status(self, tmp_queue, sample_task):
        tmp_queue.add(sample_task)
        status = tmp_queue.format_status()
        assert "1 pending" in status
        assert "Test Task" in status

    def test_clear_stale_running(self, tmp_queue, sample_task):
        tmp_queue.add(sample_task)
        tmp_queue.mark_running("test-001")
        # Manually set started_at to 1 hour ago
        for t in tmp_queue._tasks:
            if t["task_id"] == "test-001":
                from datetime import datetime, timedelta
                old = (datetime.now() - timedelta(hours=1)).isoformat()
                t["started_at"] = old
        tmp_queue._save_queue()

        tmp_queue.clear_stale_running(max_age_minutes=30)
        assert tmp_queue.get_running_count() == 0
        assert tmp_queue.get_pending_count() == 1

    def test_persistence(self, tmp_path):
        queue_file = tmp_path / "q.json"
        history_file = tmp_path / "h.json"

        q1 = TaskQueue(queue_file=queue_file, history_file=history_file)
        q1.add(Task(task_id="persist", title="Persist", prompt="x"))

        q2 = TaskQueue(queue_file=queue_file, history_file=history_file)
        assert q2.get_pending_count() == 1
        nxt = q2.next()
        assert nxt.task_id == "persist"

    def test_get_all(self, tmp_queue, sample_task):
        tmp_queue.add(sample_task)
        all_tasks = tmp_queue.get_all()
        assert len(all_tasks) == 1
        assert all_tasks[0].task_id == "test-001"
