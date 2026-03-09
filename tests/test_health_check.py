import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Import the module under test
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.health_check import (
    check_disk_space,
    check_error_rate,
    run_all_checks,
    auto_heal,
    save_health_log,
    format_report,
)


class TestCheckDiskSpace:
    def test_returns_healthy_with_enough_space(self):
        result = check_disk_space()
        assert result["name"] == "disk_space"
        assert "free_gb" in result
        assert "pct_used" in result
        assert isinstance(result["healthy"], bool)


class TestCheckErrorRate:
    def test_no_error_log(self, tmp_path):
        with patch("scripts.health_check.ERROR_LOG", tmp_path / "missing.json"):
            result = check_error_rate()
            assert result["healthy"] is True

    def test_empty_error_log(self, tmp_path):
        log_file = tmp_path / "error_log.json"
        log_file.write_text("[]")
        with patch("scripts.health_check.ERROR_LOG", log_file):
            result = check_error_rate()
            assert result["healthy"] is True
            assert result["recent_count"] == 0


class TestRunAllChecks:
    @patch("scripts.health_check.check_feishu_bot")
    @patch("scripts.health_check.check_launchd_service")
    @patch("scripts.health_check.check_cron_jobs")
    @patch("scripts.health_check.check_disk_space")
    @patch("scripts.health_check.check_error_rate")
    @patch("scripts.health_check.check_vector_store")
    @patch("scripts.health_check.check_claude_binary")
    def test_all_healthy(self, mock_claude, mock_vector, mock_error, mock_disk,
                         mock_cron, mock_launchd, mock_feishu):
        for m in [mock_claude, mock_vector, mock_error, mock_disk, mock_cron, mock_launchd, mock_feishu]:
            m.return_value = {"name": "test", "healthy": True, "message": "ok"}
        report = run_all_checks()
        assert report["all_healthy"] is True
        assert len(report["checks"]) == 7

    @patch("scripts.health_check.check_feishu_bot")
    @patch("scripts.health_check.check_launchd_service")
    @patch("scripts.health_check.check_cron_jobs")
    @patch("scripts.health_check.check_disk_space")
    @patch("scripts.health_check.check_error_rate")
    @patch("scripts.health_check.check_vector_store")
    @patch("scripts.health_check.check_claude_binary")
    def test_one_unhealthy(self, mock_claude, mock_vector, mock_error, mock_disk,
                           mock_cron, mock_launchd, mock_feishu):
        for m in [mock_claude, mock_vector, mock_error, mock_disk, mock_cron, mock_launchd]:
            m.return_value = {"name": "test", "healthy": True, "message": "ok"}
        mock_feishu.return_value = {"name": "feishu_bot", "healthy": False, "message": "NOT RUNNING"}
        report = run_all_checks()
        assert report["all_healthy"] is False


class TestAutoHeal:
    def test_heal_feishu_bot(self):
        report = {
            "checks": [
                {"name": "feishu_bot", "healthy": False, "message": "NOT RUNNING"},
                {"name": "disk_space", "healthy": True, "message": "ok"},
            ]
        }
        with patch("scripts.health_check.restart_feishu_bot", return_value="Restart triggered"):
            actions = auto_heal(report)
            assert len(actions) == 1
            assert "feishu_bot" in actions[0]

    def test_heal_vector_store(self):
        report = {
            "checks": [
                {"name": "vector_store", "healthy": False, "message": "Empty"},
            ]
        }
        with patch("scripts.health_check.reindex_vault", return_value="Reindexed 50 docs"):
            actions = auto_heal(report)
            assert len(actions) == 1
            assert "vector_store" in actions[0]

    def test_no_actions_when_healthy(self):
        report = {
            "checks": [
                {"name": "feishu_bot", "healthy": True, "message": "ok"},
            ]
        }
        actions = auto_heal(report)
        assert len(actions) == 0


class TestSaveHealthLog:
    def test_creates_log_file(self, tmp_path):
        log_file = tmp_path / "health_log.json"
        with patch("scripts.health_check.HEALTH_LOG", log_file):
            report = {"timestamp": "2026-03-05T10:00:00", "all_healthy": True, "checks": []}
            save_health_log(report, [])
            data = json.loads(log_file.read_text())
            assert len(data) == 1
            assert data[0]["all_healthy"] is True

    def test_appends_to_existing(self, tmp_path):
        log_file = tmp_path / "health_log.json"
        log_file.write_text(json.dumps([{"old": True}]))
        with patch("scripts.health_check.HEALTH_LOG", log_file):
            save_health_log({"new": True}, [])
            data = json.loads(log_file.read_text())
            assert len(data) == 2

    def test_trims_to_100(self, tmp_path):
        log_file = tmp_path / "health_log.json"
        log_file.write_text(json.dumps([{"i": i} for i in range(105)]))
        with patch("scripts.health_check.HEALTH_LOG", log_file):
            save_health_log({"new": True}, [])
            data = json.loads(log_file.read_text())
            assert len(data) == 100


class TestFormatReport:
    def test_healthy_report(self):
        report = {
            "timestamp": "2026-03-05T10:00:00",
            "all_healthy": True,
            "checks": [
                {"name": "feishu_bot", "healthy": True, "message": "Running (PID 123)"},
            ],
        }
        text = format_report(report, [])
        assert "ALL HEALTHY" in text
        assert "feishu_bot" in text

    def test_unhealthy_with_actions(self):
        report = {
            "timestamp": "2026-03-05T10:00:00",
            "all_healthy": False,
            "checks": [
                {"name": "feishu_bot", "healthy": False, "message": "NOT RUNNING"},
            ],
        }
        text = format_report(report, ["feishu_bot: Restart triggered"])
        assert "ISSUES DETECTED" in text
        assert "Auto-heal" in text
