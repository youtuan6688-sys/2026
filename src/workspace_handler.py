"""Sandboxed workspace execution for non-admin users in video groups.

Users in video groups can run /work <task> to execute tasks within
their own isolated workspace directory. Each user gets a workspace
at projects/video-breakdown/workspaces/{slug}/.
"""

import logging
import re
import uuid
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_DIR = Path(__file__).parent.parent
WORKSPACES_ROOT = PROJECT_DIR / "projects" / "video-breakdown" / "workspaces"
VIDEO_BREAKDOWNS_DIR = PROJECT_DIR / "data" / "video_breakdowns"

# Claude CLI execution limits for workspace tasks
WORKSPACE_TIMEOUT = 300  # 5 min (shorter than admin's 8 min)
WORKSPACE_MAX_RETRIES = 1
WORKSPACE_ALLOWED_TOOLS = "Read,Write,Edit,Bash,Glob,Grep"


class WorkspaceHandler:
    """Handle /work commands in video groups with sandboxed execution."""

    def __init__(self, sender, contacts, gate):
        self.sender = sender
        self.contacts = contacts
        self.gate = gate

    # Hard limit on task description length
    MAX_TASK_LEN = 2000

    def handle_work(self, task: str, sender_id: str, user_id: str) -> None:
        """Entry point: create/get workspace, execute sandboxed, reply."""
        if not task.strip():
            self.sender.send_text(sender_id, "用法: /work <任务描述>\n例: /work 写个分析最近视频数据的脚本")
            return

        # Enforce length limit
        task = task[:self.MAX_TASK_LEN]

        if not user_id:
            self.sender.send_text(sender_id, "无法识别用户身份，请确保 @bot 发送")
            return

        user_name = self.contacts.get_name(user_id) if self.contacts else "用户"

        def _run():
            try:
                workspace = self._get_or_create_workspace(user_id, user_name)
                self.sender.send_text(
                    sender_id,
                    f"收到，开始执行: {task[:80]}{'...' if len(task) > 80 else ''}\n"
                    f"工作区: workspaces/{workspace.name}/",
                )
                self._execute_sandboxed(task, workspace, sender_id, user_id, user_name)
            except Exception as e:
                logger.error("Workspace execution failed: %s", e, exc_info=True)
                self.sender.send_text(sender_id, "执行出错，请稍后重试或联系管理员")

        if not self.gate.run_group(_run, sender_id):
            self.sender.send_text(sender_id, "前面还有任务在跑，稍等...")

    def _get_or_create_workspace(self, user_id: str, user_name: str) -> Path:
        """Get or create workspace directory for a user."""
        slug = self._user_slug(user_id, user_name)
        workspace = WORKSPACES_ROOT / slug

        # Guard against path traversal
        if not str(workspace.resolve()).startswith(str(WORKSPACES_ROOT.resolve())):
            raise ValueError(f"Invalid workspace slug: {slug!r}")

        if workspace.exists():
            return workspace

        # First time: create directory structure
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "code").mkdir(exist_ok=True)
        (workspace / "output").mkdir(exist_ok=True)
        (workspace / "data").mkdir(exist_ok=True)

        worklog = workspace / "WORKLOG.md"
        worklog.write_text(
            f"# 工作区日志 — {user_name}\n\n"
            f"> 创建于 {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
            f"> 用户 ID: {user_id}\n\n"
            "---\n\n",
            encoding="utf-8",
        )
        logger.info("Created workspace for %s at %s", user_name, workspace)
        return workspace

    def _execute_sandboxed(
        self, task: str, workspace: Path, sender_id: str,
        user_id: str, user_name: str,
    ) -> None:
        """Run Claude CLI with cwd=workspace and sandbox system prompt."""
        from scripts.claude_runner import run_with_resume

        system_prompt = self._build_system_prompt(workspace, user_name)
        task_id = f"work-{workspace.name}-{datetime.now().strftime('%H%M%S')}-{uuid.uuid4().hex[:6]}"

        success, output = run_with_resume(
            prompt=task,
            task_id=task_id,
            timeout=WORKSPACE_TIMEOUT,
            max_retries=WORKSPACE_MAX_RETRIES,
            cwd=str(workspace),
            system_prompt=system_prompt,
        )

        if not output:
            output = "执行完成但没有输出"
        elif not success:
            output = f"⚠️ 任务未完成（超时或中断），已捕获的输出:\n\n{output}"

        # Send result back to group, @mention the user
        self._send_long_text(sender_id, output, user_id, user_name)

        # Auto-append to worklog
        self._append_worklog(workspace, task, output, success)

    def _build_system_prompt(self, workspace: Path, user_name: str) -> str:
        """Build sandbox system prompt guiding Claude to work within workspace."""
        return (
            f"你是一个在沙箱工作区内工作的 AI 助手，正在为 {user_name} 执行任务。\n\n"
            f"## 工作区\n"
            f"当前目录: {workspace}\n"
            f"- code/ — 放代码文件\n"
            f"- output/ — 放输出结果、报告\n"
            f"- data/ — 放工作数据\n"
            f"- WORKLOG.md — 操作日志（系统自动记录）\n\n"
            f"## 可用数据\n"
            f"- 视频拆解数据: {VIDEO_BREAKDOWNS_DIR} (JSONL 格式，每日一个文件)\n"
            f"- 项目 prompts: {WORKSPACES_ROOT.parent / 'prompts'}\n\n"
            f"## 工作原则\n"
            f"1. 优先在工作区目录内操作\n"
            f"2. 代码放 code/，输出放 output/，数据放 data/\n"
            f"3. 可以用 Python、Shell 脚本等工具\n"
            f"4. 可以安装 pip 包（建议用 --target=./data/libs）\n"
            f"5. 可以读取视频拆解数据做分析\n"
            f"6. 直接执行，不要问确认\n"
        )

    def _append_worklog(
        self, workspace: Path, task: str, result: str, success: bool
    ) -> None:
        """Append execution record to workspace WORKLOG.md."""
        worklog = workspace / "WORKLOG.md"
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        status = "完成" if success else "失败"
        # Truncate result for worklog (keep full output in Claude logs)
        result_summary = result[:500] + "..." if len(result) > 500 else result

        entry = (
            f"\n## {now} | {status}\n"
            f"**任务**: {task}\n\n"
            f"**结果**:\n```\n{result_summary}\n```\n\n---\n"
        )

        try:
            with open(worklog, "a", encoding="utf-8") as f:
                f.write(entry)
        except OSError as e:
            logger.warning("Failed to append worklog: %s", e)

    def _send_long_text(
        self, sender_id: str, text: str,
        user_id: str = "", user_name: str = "",
    ) -> None:
        """Send long text, splitting if needed. @mention the user on first chunk."""
        max_len = 3800
        at_prefix = ""
        if user_id and user_name:
            at_prefix = f'<at user_id="{user_id}">{user_name}</at>\n'

        if len(text) <= max_len:
            self.sender.send_text(sender_id, at_prefix + text)
            return
        # Split at paragraph boundaries
        chunks = []
        current = ""
        for line in text.split("\n"):
            if len(current) + len(line) + 1 > max_len:
                chunks.append(current)
                current = line
            else:
                current = f"{current}\n{line}" if current else line
        if current:
            chunks.append(current)
        for i, chunk in enumerate(chunks):
            prefix = at_prefix if i == 0 else ""
            label = f"({i + 1}/{len(chunks)}) " if len(chunks) > 1 else ""
            self.sender.send_text(sender_id, f"{prefix}{label}{chunk}")

    @staticmethod
    def _user_slug(user_id: str, user_name: str) -> str:
        """Convert user_id + name to a filesystem-safe slug.

        Always includes a user_id suffix to avoid collisions between
        users with the same display name.
        """
        short_id = user_id[-6:] if user_id else "xxx"
        if user_name and user_name != "未知用户":
            # Keep Chinese chars, letters, digits, hyphens
            slug = re.sub(r"[^\w\u4e00-\u9fff-]", "", user_name).strip().strip("-")
            # Reject anything that could escape the directory
            if slug and ".." not in slug and not slug.startswith("."):
                return f"{slug[:24]}-{short_id}"
        return f"user-{short_id}"
