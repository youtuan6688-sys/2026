"""Workflow Engine — multi-step automated action chains.

Matches incoming messages/files against workflow definitions and executes
step-by-step, passing context between steps.
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

WORKFLOWS_FILE = Path("/Users/tuanyou/Happycode2026/config/workflows.yaml")


@dataclass
class WorkflowResult:
    """Result of a workflow execution."""
    workflow_name: str
    completed_steps: list[str] = field(default_factory=list)
    failed_step: str | None = None
    partial: bool = False
    error: str = ""


class WorkflowEngine:
    """Load workflows from YAML and execute matched ones."""

    def __init__(self):
        self.workflows = self._load_workflows()

    def _load_workflows(self) -> list[dict]:
        """Load workflow definitions from YAML."""
        try:
            if WORKFLOWS_FILE.exists():
                data = yaml.safe_load(
                    WORKFLOWS_FILE.read_text(encoding="utf-8")
                )
                return data.get("workflows", [])
        except Exception as e:
            logger.error(f"Failed to load workflows: {e}")
        return []

    def reload(self):
        """Reload workflows from disk."""
        self.workflows = self._load_workflows()

    def match_file(self, file_name: str, user_prompt: str = "") -> dict | None:
        """Match a file upload against workflow triggers.

        Args:
            file_name: Name of the uploaded file
            user_prompt: Optional user text accompanying the file

        Returns:
            Matched workflow dict, or None
        """
        ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
        prompt_lower = user_prompt.lower()

        for wf in self.workflows:
            trigger = wf.get("trigger", {})
            if trigger.get("type") != "file_upload":
                continue

            # Check file type
            file_types = trigger.get("file_types", [])
            if file_types and ext not in file_types:
                continue

            # Check keywords (must match at least one)
            keywords = trigger.get("keywords", [])
            if keywords:
                matched = any(
                    re.search(kw, prompt_lower) for kw in keywords
                )
                if not matched:
                    continue

            # Check no_keywords (must NOT match any)
            no_keywords = trigger.get("no_keywords", [])
            if no_keywords:
                blocked = any(
                    re.search(kw, prompt_lower) for kw in no_keywords
                )
                if blocked:
                    continue

            return wf

        return None

    def match_text(self, text: str) -> dict | None:
        """Match a text message against workflow triggers.

        Args:
            text: Message text

        Returns:
            Matched workflow dict, or None
        """
        text_lower = text.lower()

        for wf in self.workflows:
            trigger = wf.get("trigger", {})
            if trigger.get("type") != "text":
                continue

            # Check keywords
            keywords = trigger.get("keywords", [])
            if keywords:
                matched = any(
                    re.search(kw, text_lower) for kw in keywords
                )
                if matched:
                    return wf

            # Check patterns (regex)
            patterns = trigger.get("patterns", [])
            if patterns:
                matched = any(
                    re.search(p, text) for p in patterns
                )
                if matched:
                    return wf

        return None

    def execute(self, workflow: dict, context: dict,
                step_executor) -> WorkflowResult:
        """Execute a workflow step by step.

        Args:
            workflow: Workflow definition dict
            context: Shared context dict (mutable, passed between steps)
            step_executor: Callable(action: str, context: dict) -> (bool, dict)
                          Returns (success, updated_context_fields)

        Returns:
            WorkflowResult with execution details
        """
        name = workflow.get("name", "unknown")
        steps = workflow.get("steps", [])
        result = WorkflowResult(workflow_name=name)

        logger.info(f"Workflow started: {name} ({len(steps)} steps)")

        for step in steps:
            action = step.get("action", "")
            optional = step.get("optional", False)

            try:
                success, updates = step_executor(action, context)

                if success:
                    result.completed_steps.append(action)
                    if updates:
                        context.update(updates)
                else:
                    if optional:
                        logger.info(
                            f"Workflow {name}: optional step '{action}' "
                            f"failed, skipping"
                        )
                        result.completed_steps.append(f"{action} (skipped)")
                    else:
                        result.failed_step = action
                        result.partial = bool(result.completed_steps)
                        result.error = f"Step '{action}' failed"
                        logger.warning(
                            f"Workflow {name}: step '{action}' failed, "
                            f"stopping"
                        )
                        break

            except Exception as e:
                if optional:
                    result.completed_steps.append(f"{action} (error)")
                    logger.info(
                        f"Workflow {name}: optional step '{action}' "
                        f"errored: {e}"
                    )
                else:
                    result.failed_step = action
                    result.partial = bool(result.completed_steps)
                    result.error = str(e)[:200]
                    logger.error(
                        f"Workflow {name}: step '{action}' errored: {e}",
                        exc_info=True,
                    )
                    break

        if not result.failed_step:
            logger.info(
                f"Workflow {name}: completed all {len(result.completed_steps)} steps"
            )

        return result

    def format_result(self, result: WorkflowResult) -> str:
        """Format a workflow result for user display."""
        if not result.failed_step:
            return ""  # All good, no extra message needed

        completed = ", ".join(result.completed_steps) or "none"
        msg = (
            f"⚠️ 工作流「{result.workflow_name}」部分完成\n"
            f"✅ 已完成: {completed}\n"
            f"❌ 失败: {result.failed_step}"
        )
        if result.error:
            msg += f"\n原因: {result.error[:100]}"
        return msg

    def list_workflows(self) -> str:
        """List available workflows for display."""
        if not self.workflows:
            return "No workflows configured."

        lines = ["📋 可用工作流:"]
        for wf in self.workflows:
            trigger = wf.get("trigger", {})
            steps = wf.get("steps", [])
            desc = wf.get("description", wf["name"])
            lines.append(
                f"- **{wf['name']}**: {desc} "
                f"({len(steps)} steps, trigger: {trigger.get('type', '?')})"
            )
        return "\n".join(lines)
