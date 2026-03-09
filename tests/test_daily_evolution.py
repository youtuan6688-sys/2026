"""Tests for daily_evolution module — P0-P3 fixes."""

import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.daily_evolution import (
    OpusCallError,
    _call_opus,
    archive_buffer,
    evolve_persona,
    extract_knowledge,
    load_buffer,
    run_daily_evolution,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def buffer_dir(tmp_path):
    """Temporary buffer directory."""
    d = tmp_path / "daily_buffer"
    d.mkdir()
    return d


@pytest.fixture
def sample_entries():
    """Sample conversation entries."""
    return [
        {
            "ts": "2026-03-08T20:43:18",
            "user_id": "ou_abc",
            "user_name": "Alice",
            "user_msg": "你好",
            "bot_reply": "你好啊",
            "chat_type": "group",
        },
        {
            "ts": "2026-03-08T20:50:00",
            "user_id": "ou_abc",
            "user_name": "Alice",
            "user_msg": "帮我查个东西",
            "bot_reply": "好的",
            "chat_type": "p2p",
        },
        {
            "ts": "2026-03-08T21:00:00",
            "user_id": "ou_def",
            "user_name": "Bob",
            "user_msg": "测试消息",
            "bot_reply": "收到",
            "chat_type": "p2p",
        },
    ]


@pytest.fixture
def buffer_file(buffer_dir, sample_entries):
    """Write sample entries to a buffer file."""
    today = date.today().isoformat()
    path = buffer_dir / f"{today}.jsonl"
    lines = [json.dumps(e, ensure_ascii=False) for e in sample_entries]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# P0: _call_opus error detection
# ---------------------------------------------------------------------------

class TestCallOpus:
    """Tests for _call_opus error detection."""

    @patch("src.daily_evolution.subprocess.run")
    def test_normal_output(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="- 群友喜欢聊技术\n- 氛围友好",
        )
        result = _call_opus("test prompt")
        assert "群友" in result

    @patch("src.daily_evolution.subprocess.run")
    def test_nonzero_returncode_raises(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="some error",
        )
        with pytest.raises(OpusCallError, match="exited with code 1"):
            _call_opus("test")

    @patch("src.daily_evolution.subprocess.run")
    def test_empty_output_raises(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="   ",
        )
        with pytest.raises(OpusCallError, match="empty output"):
            _call_opus("test")

    @patch("src.daily_evolution.subprocess.run")
    def test_rate_limit_detected(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="You've hit your limit · resets 8pm (America/Los_Angeles)",
        )
        with pytest.raises(OpusCallError, match="error-like output"):
            _call_opus("test")

    @patch("src.daily_evolution.subprocess.run")
    def test_long_output_with_error_word_not_rejected(self, mock_run):
        """Long legitimate output containing 'error:' should NOT be rejected."""
        long_text = "Here is an analysis about error: handling patterns. " * 10
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=long_text,
        )
        result = _call_opus("test")
        assert "error" in result  # Should pass through since len > 200


# ---------------------------------------------------------------------------
# P1: load_buffer
# ---------------------------------------------------------------------------

class TestLoadBuffer:

    def test_load_existing_buffer(self, buffer_file, buffer_dir, sample_entries):
        with patch("src.daily_evolution.BUFFER_DIR", buffer_dir):
            entries = load_buffer(date.today())
        assert len(entries) == len(sample_entries)
        assert entries[0]["user_name"] == "Alice"

    def test_load_missing_buffer(self, buffer_dir):
        with patch("src.daily_evolution.BUFFER_DIR", buffer_dir):
            entries = load_buffer(date(2020, 1, 1))
        assert entries == []

    def test_load_buffer_skips_bad_lines(self, buffer_dir):
        today = date.today().isoformat()
        path = buffer_dir / f"{today}.jsonl"
        path.write_text('{"ok":true}\nnot json\n{"also":"ok"}', encoding="utf-8")
        with patch("src.daily_evolution.BUFFER_DIR", buffer_dir):
            entries = load_buffer(date.today())
        assert len(entries) == 2


# ---------------------------------------------------------------------------
# P2: archive_buffer (not delete)
# ---------------------------------------------------------------------------

class TestArchiveBuffer:

    def test_archive_moves_file(self, buffer_file, buffer_dir):
        with patch("src.daily_evolution.BUFFER_DIR", buffer_dir):
            archive_buffer(date.today())

        # Original should be gone
        assert not buffer_file.exists()
        # Archive should exist
        archive_dir = buffer_dir / "archive"
        assert archive_dir.exists()
        archived = archive_dir / buffer_file.name
        assert archived.exists()

    def test_archive_nonexistent_noop(self, buffer_dir):
        """Archiving a missing date should not raise."""
        with patch("src.daily_evolution.BUFFER_DIR", buffer_dir):
            archive_buffer(date(2020, 1, 1))  # no error


# ---------------------------------------------------------------------------
# P3: extract_knowledge — current_file init
# ---------------------------------------------------------------------------

class TestExtractKnowledge:

    @patch("src.daily_evolution._call_opus")
    def test_content_before_file_is_ignored(self, mock_opus):
        """CONTENT: line before any FILE: should not crash (P3 fix)."""
        mock_opus.return_value = (
            "CONTENT: orphan content\n"
            "FILE: learnings.md\n"
            "CONTENT: real learning\n"
        )
        entries = [
            {"user_msg": "test", "bot_reply": "ok", "chat_type": "p2p"},
            {"user_msg": "test2", "bot_reply": "ok2", "chat_type": "p2p"},
        ]
        with patch("src.daily_evolution._append_to_memory") as mock_append:
            result = extract_knowledge(entries)

        # Should only append the valid one (after FILE: line)
        assert mock_append.call_count == 1
        args = mock_append.call_args[0]
        assert args[0] == "learnings.md"
        assert "real learning" in args[1]

    @patch("src.daily_evolution._call_opus")
    def test_skip_output(self, mock_opus):
        mock_opus.return_value = "SKIP"
        entries = [{"user_msg": "x", "chat_type": "p2p"}] * 2
        result = extract_knowledge(entries)
        assert "No notable" in result

    @patch("src.daily_evolution._call_opus")
    def test_no_private_entries(self, mock_opus):
        entries = [{"user_msg": "x", "chat_type": "group"}]
        result = extract_knowledge(entries)
        assert "No private" in result
        mock_opus.assert_not_called()


# ---------------------------------------------------------------------------
# P0+P2: run_daily_evolution — failure keeps buffer
# ---------------------------------------------------------------------------

class TestRunDailyEvolution:

    @patch("src.daily_evolution.archive_buffer")
    @patch("src.daily_evolution.extract_knowledge", return_value="ok")
    @patch("src.daily_evolution.evolve_contacts", return_value={})
    @patch("src.daily_evolution.evolve_persona", return_value="ok")
    @patch("src.daily_evolution.load_buffer")
    def test_all_succeed_archives_buffer(
        self, mock_load, mock_persona, mock_contacts, mock_knowledge, mock_archive
    ):
        mock_load.return_value = [{"msg": "test"}]
        run_daily_evolution()
        mock_archive.assert_called_once()

    @patch("src.daily_evolution.archive_buffer")
    @patch("src.daily_evolution.extract_knowledge", return_value="ok")
    @patch("src.daily_evolution.evolve_contacts", return_value={})
    @patch("src.daily_evolution.evolve_persona", side_effect=OpusCallError("rate limited"))
    @patch("src.daily_evolution.load_buffer")
    def test_partial_failure_keeps_buffer(
        self, mock_load, mock_persona, mock_contacts, mock_knowledge, mock_archive
    ):
        mock_load.return_value = [{"msg": "test"}]
        run_daily_evolution()
        mock_archive.assert_not_called()

    @patch("src.daily_evolution.archive_buffer")
    @patch("src.daily_evolution.load_buffer")
    def test_empty_buffer_skips(self, mock_load, mock_archive):
        mock_load.return_value = []
        run_daily_evolution()
        mock_archive.assert_not_called()
