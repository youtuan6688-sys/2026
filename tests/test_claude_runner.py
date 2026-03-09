"""Tests for claude_runner auto-resume wrapper (v2: session-based)."""

import json
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock, call

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.claude_runner import (
    _check_recent_file_changes,
    _run_claude_streaming,
    run_with_resume,
)
from src.checkpoint import CheckpointManager


class TestCheckRecentFileChanges:
    @patch("scripts.claude_runner.subprocess.run")
    def test_no_changes(self, mock_run):
        mock_run.return_value = MagicMock(stdout="")
        result = _check_recent_file_changes()
        assert "No" in result

    @patch("scripts.claude_runner.subprocess.run")
    def test_with_changes(self, mock_run):
        mock_run.return_value = MagicMock(stdout="/some/file.py\n/other/file.md\n")
        result = _check_recent_file_changes()
        assert "file.py" in result


class TestRunClaudeStreaming:
    @patch("scripts.claude_runner.subprocess.Popen")
    def test_success_with_result_event(self, mock_popen):
        """stream-json returns a 'result' event at the end."""
        result_event = json.dumps({"type": "result", "result": "task completed"})
        mock_proc = MagicMock()
        mock_proc.stdout = iter([f"{result_event}\n".encode()])
        mock_proc.stderr = iter([])
        mock_proc.wait.return_value = None
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        code, stdout, stderr = _run_claude_streaming("test prompt", timeout=10)
        assert code == 0
        assert "task completed" in stdout

    @patch("scripts.claude_runner.subprocess.Popen")
    def test_success_with_delta_events(self, mock_popen):
        """stream-json returns content_block_delta events."""
        events = [
            json.dumps({"type": "content_block_delta", "delta": {"text": "hello "}}) + "\n",
            json.dumps({"type": "content_block_delta", "delta": {"text": "world"}}) + "\n",
        ]
        mock_proc = MagicMock()
        mock_proc.stdout = iter([e.encode() for e in events])
        mock_proc.stderr = iter([])
        mock_proc.wait.return_value = None
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        code, stdout, stderr = _run_claude_streaming("test", timeout=10)
        assert code == 0
        assert "hello world" in stdout

    @patch("scripts.claude_runner.subprocess.Popen")
    def test_session_id_passed(self, mock_popen):
        """Verify --session-id is passed on first attempt."""
        mock_proc = MagicMock()
        mock_proc.stdout = iter([])
        mock_proc.stderr = iter([])
        mock_proc.wait.return_value = None
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        _run_claude_streaming("test", session_id="abc-123", resume=False)

        cmd = mock_popen.call_args[0][0]
        assert "--session-id" in cmd
        assert "abc-123" in cmd
        assert "--resume" not in cmd

    @patch("scripts.claude_runner.subprocess.Popen")
    def test_resume_flag_passed(self, mock_popen):
        """Verify --resume is passed on subsequent attempts."""
        mock_proc = MagicMock()
        mock_proc.stdout = iter([])
        mock_proc.stderr = iter([])
        mock_proc.wait.return_value = None
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        _run_claude_streaming("continue", session_id="abc-123", resume=True)

        cmd = mock_popen.call_args[0][0]
        assert "--resume" in cmd
        assert "abc-123" in cmd
        assert "--session-id" not in cmd

    @patch("scripts.claude_runner.subprocess.Popen")
    def test_system_prompt_passed(self, mock_popen):
        """Verify --append-system-prompt is passed when provided."""
        mock_proc = MagicMock()
        mock_proc.stdout = iter([])
        mock_proc.stderr = iter([])
        mock_proc.wait.return_value = None
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        _run_claude_streaming("test", system_prompt="memory context here")

        cmd = mock_popen.call_args[0][0]
        assert "--append-system-prompt" in cmd
        assert "memory context here" in cmd


class TestRunWithResume:
    @patch("scripts.claude_runner._run_claude_streaming")
    def test_success_first_attempt(self, mock_run):
        mock_run.return_value = (0, "all done", "")

        with patch("scripts.claude_runner.CheckpointManager") as MockCM:
            mock_cm = MagicMock()
            mock_cm.load.return_value = None
            MockCM.return_value = mock_cm

            success, output = run_with_resume(
                "do something",
                task_id="test-1",
                max_retries=2,
            )

        assert success is True
        assert output == "all done"

    @patch("scripts.claude_runner._run_claude_streaming")
    def test_timeout_then_success(self, mock_run):
        """First attempt times out, second succeeds with --resume."""
        mock_run.side_effect = [
            (-1, "partial work", "TIMEOUT"),  # attempt 1: timeout
            (0, "completed after resume", ""),  # attempt 2: success
        ]

        with patch("scripts.claude_runner.CheckpointManager") as MockCM:
            mock_cm = MagicMock()
            mock_cm.load.return_value = None
            MockCM.return_value = mock_cm

            success, output = run_with_resume(
                "do something",
                task_id="test-2",
                max_retries=3,
            )

        assert success is True
        assert output == "completed after resume"
        assert mock_run.call_count == 2

        # Verify first call uses session_id, second uses resume=True
        first_call = mock_run.call_args_list[0]
        second_call = mock_run.call_args_list[1]
        assert first_call.kwargs.get("resume") is False
        assert second_call.kwargs.get("resume") is True
        # Same session ID for both
        assert first_call.kwargs["session_id"] == second_call.kwargs["session_id"]

    @patch("scripts.claude_runner._run_claude_streaming")
    def test_all_retries_exhausted(self, mock_run):
        """All attempts timeout."""
        mock_run.return_value = (-1, "still timing out", "TIMEOUT")

        with patch("scripts.claude_runner.CheckpointManager") as MockCM:
            mock_cm = MagicMock()
            mock_cm.load.return_value = None
            MockCM.return_value = mock_cm

            success, output = run_with_resume(
                "hard task",
                task_id="test-3",
                max_retries=2,
            )

        assert success is False
        # 1 initial + 2 retries = 3
        assert mock_run.call_count == 3

    @patch("scripts.claude_runner._run_claude_streaming")
    def test_on_output_callback(self, mock_run):
        mock_run.return_value = (0, "done", "")
        attempts = []

        with patch("scripts.claude_runner.CheckpointManager") as MockCM:
            MockCM.return_value = MagicMock(load=MagicMock(return_value=None))

            run_with_resume(
                "task",
                task_id="test-cb",
                on_output=lambda a, o: attempts.append(a),
            )

        assert attempts == [1]

    @patch("scripts.claude_runner._run_claude_streaming")
    def test_checkpoint_saved_on_timeout(self, mock_run):
        """Verify checkpoint is saved when timeout occurs."""
        mock_run.side_effect = [
            (-1, "partial work done", "TIMEOUT"),
            (0, "completed", ""),
        ]

        with patch("scripts.claude_runner.CheckpointManager") as MockCM:
            mock_cm = MagicMock()
            mock_cm.load.return_value = None
            MockCM.return_value = mock_cm

            success, output = run_with_resume(
                "task",
                task_id="test-cp",
                max_retries=2,
            )

        assert success is True
        mock_cm.save.assert_called_once()
        saved_checkpoint = mock_cm.save.call_args[0][0]
        assert saved_checkpoint.task_id == "test-cp"
        assert saved_checkpoint.steps[0].status == "in_progress"
        # Session ID should be recorded in checkpoint
        assert "Session:" in saved_checkpoint.steps[0].progress

    @patch("scripts.claude_runner._run_claude_streaming")
    def test_checkpoint_completed_on_success(self, mock_run):
        """Verify checkpoint is completed when task succeeds."""
        mock_run.return_value = (0, "all done", "")

        mock_checkpoint = MagicMock()
        mock_checkpoint.task_id = "test-complete"

        with patch("scripts.claude_runner.CheckpointManager") as MockCM:
            mock_cm = MagicMock()
            mock_cm.load.return_value = mock_checkpoint
            MockCM.return_value = mock_cm

            success, _ = run_with_resume(
                "task",
                task_id="test-complete",
            )

        assert success is True
        mock_cm.complete.assert_called_once_with(mock_checkpoint)

    @patch("scripts.claude_runner._run_claude_streaming")
    def test_resume_prompt_is_short(self, mock_run):
        """Resume prompt should be concise since session has full context."""
        mock_run.side_effect = [
            (-1, "partial output here", "TIMEOUT"),
            (0, "done", ""),
        ]

        with patch("scripts.claude_runner.CheckpointManager") as MockCM:
            mock_cm = MagicMock()
            mock_cm.load.return_value = None
            MockCM.return_value = mock_cm

            run_with_resume(
                "a very long original prompt " * 50,
                task_id="test-short",
                max_retries=2,
                user_message="简短用户指令",
            )

        # Resume prompt (second call) should be much shorter than original
        second_call_prompt = mock_run.call_args_list[1][0][0]
        assert len(second_call_prompt) < 500
        assert "继续完成" in second_call_prompt or "超时" in second_call_prompt

    @patch("scripts.claude_runner._run_claude_streaming")
    def test_system_prompt_only_on_first_attempt(self, mock_run):
        """System prompt should only be sent on first attempt (session persists it)."""
        mock_run.side_effect = [
            (-1, "partial", "TIMEOUT"),
            (0, "done", ""),
        ]

        with patch("scripts.claude_runner.CheckpointManager") as MockCM:
            mock_cm = MagicMock()
            mock_cm.load.return_value = None
            MockCM.return_value = mock_cm

            run_with_resume(
                "task",
                task_id="test-sys",
                max_retries=2,
                system_prompt="long memory context",
            )

        first_call = mock_run.call_args_list[0]
        second_call = mock_run.call_args_list[1]
        assert first_call.kwargs["system_prompt"] == "long memory context"
        assert second_call.kwargs["system_prompt"] == ""

    @patch("scripts.claude_runner._run_claude_streaming")
    def test_auto_generated_task_id(self, mock_run):
        mock_run.return_value = (0, "done", "")

        with patch("scripts.claude_runner.CheckpointManager") as MockCM:
            MockCM.return_value = MagicMock(load=MagicMock(return_value=None))

            success, _ = run_with_resume("task", task_id="")

        assert success is True
