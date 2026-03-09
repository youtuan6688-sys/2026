"""Tests for Checkpoint system."""

import json
import pytest
from pathlib import Path

from src.checkpoint import Checkpoint, CheckpointStep, CheckpointManager


@pytest.fixture
def tmp_manager(tmp_path):
    return CheckpointManager(
        checkpoint_dir=tmp_path,
        current_file=tmp_path / "current_task.json",
        history_file=tmp_path / "task_history.json",
    )


@pytest.fixture
def sample_checkpoint():
    return Checkpoint(
        task_id="evo-1",
        description="Implement self-repair system",
        steps=[
            CheckpointStep("error_tracker", status="done", progress="Module created"),
            CheckpointStep("nightly_review", status="in_progress", progress="Script drafted"),
            CheckpointStep("health_check", status="pending"),
        ],
        context_notes="Working on evolution roadmap item 1",
    )


class TestCheckpointStep:
    def test_to_dict(self):
        step = CheckpointStep("test_step", "pending", "some progress", ["task-1"])
        d = step.to_dict()
        assert d["name"] == "test_step"
        assert d["status"] == "pending"
        assert d["progress"] == "some progress"
        assert d["queue_task_ids"] == ["task-1"]

    def test_from_dict(self):
        data = {"name": "s1", "status": "done", "progress": "ok", "queue_task_ids": ["t1"]}
        step = CheckpointStep.from_dict(data)
        assert step.name == "s1"
        assert step.status == "done"
        assert step.queue_task_ids == ["t1"]

    def test_from_dict_defaults(self):
        step = CheckpointStep.from_dict({"name": "s2"})
        assert step.status == "pending"
        assert step.progress == ""
        assert step.queue_task_ids == []


class TestCheckpoint:
    def test_current_step_returns_first_non_done(self, sample_checkpoint):
        current = sample_checkpoint.current_step()
        assert current.name == "nightly_review"

    def test_current_step_returns_none_when_all_done(self):
        cp = Checkpoint(
            task_id="x",
            description="x",
            steps=[CheckpointStep("a", "done"), CheckpointStep("b", "done")],
        )
        assert cp.current_step() is None

    def test_is_complete(self):
        cp = Checkpoint(
            task_id="x",
            description="x",
            steps=[CheckpointStep("a", "done"), CheckpointStep("b", "done")],
        )
        assert cp.is_complete() is True

    def test_is_not_complete(self, sample_checkpoint):
        assert sample_checkpoint.is_complete() is False

    def test_progress_summary(self, sample_checkpoint):
        summary = sample_checkpoint.progress_summary()
        assert "[1/3]" in summary
        assert "nightly_review" in summary

    def test_to_dict_round_trip(self, sample_checkpoint):
        d = sample_checkpoint.to_dict()
        restored = Checkpoint.from_dict(d)
        assert restored.task_id == sample_checkpoint.task_id
        assert len(restored.steps) == 3
        assert restored.steps[0].status == "done"


class TestCheckpointManager:
    def test_save_and_load(self, tmp_manager, sample_checkpoint):
        tmp_manager.save(sample_checkpoint)
        loaded = tmp_manager.load()
        assert loaded is not None
        assert loaded.task_id == "evo-1"
        assert len(loaded.steps) == 3

    def test_load_returns_none_when_empty(self, tmp_manager):
        assert tmp_manager.load() is None

    def test_complete_moves_to_history(self, tmp_manager, sample_checkpoint):
        tmp_manager.save(sample_checkpoint)
        tmp_manager.complete(sample_checkpoint)

        assert tmp_manager.load() is None
        history_data = json.loads(tmp_manager._history_file.read_text())
        assert len(history_data) == 1
        assert history_data[0]["task_id"] == "evo-1"

    def test_clear(self, tmp_manager, sample_checkpoint):
        tmp_manager.save(sample_checkpoint)
        tmp_manager.clear()
        assert tmp_manager.load() is None

    def test_update_step(self, tmp_manager, sample_checkpoint):
        tmp_manager.save(sample_checkpoint)
        updated = tmp_manager.update_step(
            sample_checkpoint, "nightly_review", "done", "Script complete",
        )
        assert updated.steps[1].status == "done"
        assert updated.steps[1].progress == "Script complete"

        loaded = tmp_manager.load()
        assert loaded.steps[1].status == "done"

    def test_update_step_auto_completes_when_all_done(self, tmp_manager):
        cp = Checkpoint(
            task_id="auto-complete",
            description="test",
            steps=[
                CheckpointStep("a", "done"),
                CheckpointStep("b", "pending"),
            ],
        )
        tmp_manager.save(cp)
        tmp_manager.update_step(cp, "b", "done", "finished")

        assert tmp_manager.load() is None
        history_data = json.loads(tmp_manager._history_file.read_text())
        assert history_data[0]["task_id"] == "auto-complete"

    def test_get_resume_prompt(self, tmp_manager, sample_checkpoint):
        tmp_manager.save(sample_checkpoint)
        prompt = tmp_manager.get_resume_prompt()
        assert prompt is not None
        assert "Resume Task" in prompt
        assert "nightly_review" in prompt
        assert "error_tracker" in prompt
        assert "health_check" in prompt

    def test_get_resume_prompt_none_when_empty(self, tmp_manager):
        assert tmp_manager.get_resume_prompt() is None

    def test_format_status(self, tmp_manager, sample_checkpoint):
        tmp_manager.save(sample_checkpoint)
        status = tmp_manager.format_status()
        assert "self-repair" in status.lower() or "evo-1" in status.lower() or "Implement" in status

    def test_format_status_no_checkpoint(self, tmp_manager):
        assert "No active" in tmp_manager.format_status()

    def test_history_max_limit(self, tmp_manager):
        for i in range(60):
            cp = Checkpoint(task_id=f"task-{i}", description=f"Task {i}", steps=[])
            tmp_manager.complete(cp)

        history_data = json.loads(tmp_manager._history_file.read_text())
        assert len(history_data) == 50
