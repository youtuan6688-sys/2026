import json
from pathlib import Path

import pytest

from src.utils.error_tracker import ErrorTracker, ErrorEntry


@pytest.fixture
def tracker(tmp_path):
    log_file = tmp_path / "error_log.json"
    return ErrorTracker(log_file=log_file)


class TestErrorEntry:
    def test_create_entry(self):
        entry = ErrorEntry("test_error", "something failed", "test_module")
        assert entry.error_type == "test_error"
        assert entry.message == "something failed"
        assert entry.source == "test_module"
        assert entry.severity == "medium"
        assert entry.resolved is False

    def test_truncate_long_message(self):
        entry = ErrorEntry("err", "x" * 1000, "src")
        assert len(entry.message) == 500

    def test_truncate_long_context(self):
        entry = ErrorEntry("err", "msg", "src", context="y" * 500)
        assert len(entry.context) == 300

    def test_roundtrip(self):
        entry = ErrorEntry("err", "msg", "src", "high", "ctx")
        d = entry.to_dict()
        restored = ErrorEntry.from_dict(d)
        assert restored.error_type == "err"
        assert restored.severity == "high"
        assert restored.context == "ctx"


class TestErrorTracker:
    def test_track_error(self, tracker):
        entry = tracker.track("timeout", "5min limit", "execute_claude", "high")
        assert entry.error_type == "timeout"
        assert len(tracker._errors) == 1

    def test_persist_to_file(self, tracker):
        tracker.track("err", "msg", "src")
        data = json.loads(tracker._log_file.read_text())
        assert len(data) == 1
        assert data[0]["error_type"] == "err"

    def test_load_existing(self, tmp_path):
        log_file = tmp_path / "error_log.json"
        log_file.write_text(json.dumps([
            {"error_type": "old", "message": "old error", "source": "test",
             "severity": "low", "context": "", "timestamp": "2026-01-01",
             "resolved": False, "resolution": ""}
        ]))
        tracker = ErrorTracker(log_file=log_file)
        assert len(tracker._errors) == 1

    def test_resolve_error(self, tracker):
        tracker.track("err", "msg", "src")
        tracker.resolve(0, "fixed by updating config")
        assert tracker._errors[0]["resolved"] is True
        assert tracker._errors[0]["resolution"] == "fixed by updating config"

    def test_resolve_invalid_index(self, tracker):
        tracker.resolve(99, "nope")  # Should not raise

    def test_get_recent(self, tracker):
        for i in range(15):
            tracker.track(f"err_{i}", f"msg_{i}", "src")
        recent = tracker.get_recent(5)
        assert len(recent) == 5
        assert recent[-1]["error_type"] == "err_14"

    def test_get_recent_unresolved_only(self, tracker):
        tracker.track("err1", "msg1", "src")
        tracker.track("err2", "msg2", "src")
        tracker.resolve(0, "fixed")
        unresolved = tracker.get_recent(10, unresolved_only=True)
        assert len(unresolved) == 1
        assert unresolved[0]["error_type"] == "err2"

    def test_get_stats(self, tracker):
        tracker.track("timeout", "msg", "claude", "high")
        tracker.track("timeout", "msg2", "claude", "high")
        tracker.track("parse_error", "msg3", "url", "medium")
        stats = tracker.get_stats()
        assert stats["total"] == 3
        assert stats["unresolved"] == 3
        assert stats["by_type"]["timeout"] == 2
        assert stats["by_severity"]["high"] == 2

    def test_get_stats_empty(self, tracker):
        stats = tracker.get_stats()
        assert stats["total"] == 0
        assert stats["unresolved"] == 0

    def test_get_recurring_patterns(self, tracker):
        for _ in range(5):
            tracker.track("timeout", "msg", "claude", "high")
        tracker.track("other", "msg", "src")
        patterns = tracker.get_recurring_patterns(min_count=3)
        assert len(patterns) == 1
        assert patterns[0]["error_type"] == "timeout"
        assert patterns[0]["count"] == 5

    def test_no_recurring_patterns(self, tracker):
        tracker.track("err1", "msg", "src")
        tracker.track("err2", "msg", "src")
        patterns = tracker.get_recurring_patterns(min_count=3)
        assert len(patterns) == 0

    def test_format_summary(self, tracker):
        tracker.track("timeout", "Claude timed out", "execute_claude", "high")
        summary = tracker.format_summary()
        assert "timeout" in summary
        assert "HIGH" in summary

    def test_format_summary_empty(self, tracker):
        summary = tracker.format_summary()
        assert "No unresolved" in summary

    def test_max_errors_trimming(self, tmp_path):
        log_file = tmp_path / "error_log.json"
        tracker = ErrorTracker(log_file=log_file)
        for i in range(550):
            tracker.track(f"err_{i}", f"msg_{i}", "src")
        assert len(tracker._errors) == 500

    def test_corrupted_file_graceful(self, tmp_path):
        log_file = tmp_path / "error_log.json"
        log_file.write_text("not valid json{{{")
        tracker = ErrorTracker(log_file=log_file)
        assert len(tracker._errors) == 0

    def test_by_source_stats(self, tracker):
        tracker.track("err", "msg", "module_a")
        tracker.track("err", "msg", "module_a")
        tracker.track("err", "msg", "module_b")
        stats = tracker.get_stats()
        assert stats["by_source"]["module_a"] == 2

    def test_resolve_by_type(self, tracker):
        tracker.track("timeout", "msg1", "claude")
        tracker.track("timeout", "msg2", "claude")
        tracker.track("parse_error", "msg3", "url")
        tracker.resolve_by_type("timeout", "increased timeout setting")
        assert tracker._errors[0]["resolved"] is True
        assert tracker._errors[1]["resolved"] is True
        assert tracker._errors[2]["resolved"] is False

    def test_resolve_by_type_nonexistent(self, tracker):
        tracker.track("err", "msg", "src")
        tracker.resolve_by_type("nonexistent", "fix")
        assert tracker._errors[0]["resolved"] is False

    def test_auto_resolve_duplicates(self, tracker):
        tracker.track("timeout", "msg1", "claude")
        tracker.track("timeout", "msg2", "claude")
        tracker.track("timeout", "msg3", "claude")
        count = tracker.auto_resolve_duplicates()
        assert count == 2
        # Only the last one should remain unresolved
        unresolved = [e for e in tracker._errors if not e["resolved"]]
        assert len(unresolved) == 1
        assert unresolved[0]["message"] == "msg3"

    def test_auto_resolve_duplicates_no_dupes(self, tracker):
        tracker.track("err1", "msg", "src1")
        tracker.track("err2", "msg", "src2")
        count = tracker.auto_resolve_duplicates()
        assert count == 0

    def test_get_fix_suggestions(self, tracker):
        for _ in range(3):
            tracker.track("kb_query_error", "db error", "query_knowledge_base")
        suggestions = tracker.get_fix_suggestions()
        assert len(suggestions) == 1
        assert suggestions[0]["error_type"] == "kb_query_error"
        assert suggestions[0]["auto"] is True

    def test_get_fix_suggestions_unknown_type(self, tracker):
        for _ in range(3):
            tracker.track("new_error_type", "msg", "src")
        suggestions = tracker.get_fix_suggestions()
        assert len(suggestions) == 1
        assert suggestions[0]["auto"] is False

    def test_get_fix_suggestions_empty(self, tracker):
        tracker.track("err", "msg", "src")
        suggestions = tracker.get_fix_suggestions()
        assert len(suggestions) == 0
