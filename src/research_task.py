"""Research Task Manager — autonomous research via Claude Code.

Handles complex, multi-step research tasks (competitive analysis, market research,
e-commerce review analysis, etc.) by launching Claude CLI in a dedicated workspace
with full tool access (search, browse, Python, file analysis).

Flow:
  1. User sends /research <task> via Feishu
  2. Bot creates workspace directory + task.md + progress.json
  3. Bot launches Claude CLI as background process (max-turns, permission=auto)
  4. Monitor thread checks progress.json every 3 min, reports to Feishu
  5. On completion: sends report + stats
"""

import json
import logging
import os
import signal
import subprocess
import tempfile
import threading
from dataclasses import dataclass, field, asdict, replace
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_DIR = Path("/Users/tuanyou/Happycode2026")
RESEARCH_DIR = PROJECT_DIR / "data" / "research"
CLAUDE_BIN = "/Users/tuanyou/.local/bin/claude"
MONITOR_INTERVAL = 180  # 3 minutes
DEFAULT_MAX_TURNS = 40
MAX_ALLOWED_TURNS = 100
ALLOWED_TOOLS = "WebSearch,WebFetch,Read,Write,Edit,Bash,Glob,Grep"


@dataclass(frozen=True)
class ResearchTask:
    """Persistent research task state (immutable)."""

    task_id: str
    title: str
    description: str
    status: str = "pending"  # pending, running, completed, failed, cancelled
    workspace: str = ""
    pid: int = 0
    sender_id: str = ""
    max_turns: int = DEFAULT_MAX_TURNS
    started_at: str = ""
    completed_at: str = ""
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())


class ResearchTaskManager:
    """Manage research task lifecycle: create, run, monitor, report."""

    def __init__(self, sender, quota):
        self.sender = sender
        self.quota = quota
        self._lock = threading.Lock()
        self._monitor_threads: dict[str, threading.Event] = {}

    # ── Public API ──

    def start(self, description: str, sender_id: str,
              max_turns: int = DEFAULT_MAX_TURNS) -> ResearchTask | None:
        """Create and launch a research task. Returns task or None on failure."""
        max_turns = min(max(1, max_turns), MAX_ALLOWED_TURNS)

        # Guard: only 1 concurrent task
        active = self._get_active_task()
        if active:
            self.sender.send_text(
                sender_id,
                f"已有研究任务在运行中:\n"
                f"  {active.title}\n"
                f"  状态: {active.status}\n\n"
                f"请等待完成或用 /research stop 终止",
            )
            return None

        # Create task
        now = datetime.now()
        task_id = f"research-{now.strftime('%Y%m%d-%H%M%S')}"
        title = description[:60].replace("\n", " ")
        workspace = RESEARCH_DIR / task_id

        task = ResearchTask(
            task_id=task_id,
            title=title,
            description=description,
            status="running",
            workspace=str(workspace),
            sender_id=sender_id,
            max_turns=max_turns,
            started_at=now.isoformat(),
        )

        # Create workspace
        self._create_workspace(task)

        # Save state
        self._save_task(task)

        # Notify user
        self.sender.send_text(
            sender_id,
            f"📋 研究任务已创建\n"
            f"任务: {title}\n"
            f"最大 turns: {max_turns}\n"
            f"开始执行...",
        )

        # Launch Claude CLI in background
        self._launch_claude(task)

        return task

    def get_status(self, sender_id: str) -> str:
        """Return human-readable status of active or most recent task."""
        task = self._get_active_task()
        if not task:
            recent = self._get_recent_tasks(limit=1)
            if recent:
                t = recent[0]
                return (
                    f"无活跃任务\n\n"
                    f"最近完成: {t.title}\n"
                    f"状态: {t.status}\n"
                    f"完成时间: {t.completed_at or '?'}"
                )
            return "无研究任务记录"

        progress = self._read_progress(task)
        lines = [
            f"📊 研究任务进行中",
            f"任务: {task.title}",
            f"PID: {task.pid}",
            f"启动: {task.started_at[:16]}",
        ]
        if progress:
            phase = progress.get("current_phase", "?")
            done = progress.get("phases_completed", [])
            remaining = progress.get("phases_remaining", [])
            summary = progress.get("summary", "")
            total = len(done) + len(remaining) + 1
            lines.append(f"阶段: {phase} ({len(done)}/{total})")
            if summary:
                lines.append(f"进展: {summary}")
        else:
            lines.append("(等待首次进度更新)")

        return "\n".join(lines)

    def stop(self, sender_id: str) -> bool:
        """Stop the active research task. Returns True if stopped."""
        task = self._get_active_task()
        if not task:
            self.sender.send_text(sender_id, "没有正在运行的研究任务")
            return False

        # Kill process
        if task.pid:
            try:
                os.kill(task.pid, signal.SIGTERM)
                logger.info(f"Killed research task process {task.pid}")
            except ProcessLookupError:
                pass

        # Stop monitor
        with self._lock:
            stop_event = self._monitor_threads.get(task.task_id)
        if stop_event:
            stop_event.set()

        # Update state (immutable)
        updated = replace(
            task, status="cancelled",
            completed_at=datetime.now().isoformat(),
        )
        self._save_task(updated)

        self.sender.send_text(
            sender_id,
            f"⏹ 研究任务已停止: {task.title}\n"
            f"工作目录保留: {task.workspace}",
        )
        return True

    def list_tasks(self, sender_id: str) -> str:
        """List recent research tasks."""
        tasks = self._get_recent_tasks(limit=10)
        if not tasks:
            return "无研究任务记录"

        lines = ["📋 研究任务列表\n"]
        for t in tasks:
            icon = {
                "running": "▶️", "completed": "✅",
                "failed": "❌", "cancelled": "⏹",
            }.get(t.status, "?")
            date_str = t.started_at[:10] if t.started_at else "?"
            lines.append(f"{icon} [{date_str}] {t.title}")

        return "\n".join(lines)

    # ── Workspace Setup ──

    def _create_workspace(self, task: ResearchTask) -> None:
        """Create task directory structure and task.md."""
        ws = Path(task.workspace)
        ws.mkdir(parents=True, exist_ok=True)
        (ws / "data").mkdir(exist_ok=True)
        (ws / "code").mkdir(exist_ok=True)
        (ws / "output").mkdir(exist_ok=True)

        # Initial progress.json
        progress = {
            "current_phase": "规划",
            "phases_completed": [],
            "phases_remaining": ["数据收集", "数据分析", "报告撰写"],
            "summary": "任务启动中",
            "turns_used": 0,
        }
        self._atomic_write(ws / "progress.json", progress)

        # task.md
        task_md = self._build_task_md(task)
        (ws / "task.md").write_text(task_md, encoding="utf-8")

        # Empty log
        (ws / "log.md").write_text(
            f"# 研究日志 — {task.title}\n\n"
            f"> 创建于 {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n---\n\n",
            encoding="utf-8",
        )

        logger.info(f"Created research workspace: {ws}")

    def _build_task_md(self, task: ResearchTask) -> str:
        """Build the task description file for Claude."""
        ws = task.workspace
        return (
            f"# 研究任务\n\n"
            f"## 任务描述\n{task.description}\n\n"
            f"## 工作目录\n"
            f"当前目录就是你的工作区：{ws}\n"
            f"- data/ — 存放爬取的原始数据、下载的文件\n"
            f"- code/ — 存放你写的 Python 脚本\n"
            f"- output/ — 存放最终报告和交付物\n"
            f"- log.md — 记录你的执行过程（每个阶段追加记录）\n\n"
            f"## 进度追踪（重要！）\n"
            f"每完成一个阶段，必须更新 progress.json：\n"
            f'```json\n'
            f'{{\n'
            f'  "current_phase": "当前阶段名",\n'
            f'  "phases_completed": ["已完成的阶段"],\n'
            f'  "phases_remaining": ["待完成的阶段"],\n'
            f'  "summary": "一句话描述当前进展",\n'
            f'  "turns_used": 12\n'
            f'}}\n'
            f'```\n\n'
            f"## 可用工具\n"
            f"1. **网络搜索**: WebSearch 工具（Brave Search）\n"
            f"2. **网页抓取**: WebFetch 抓取网页全文\n"
            f"3. **浏览器操作**: 用 Bash 调用 camoufox（反检测浏览器），适合需要登录或反爬的网站\n"
            f"4. **Python**: 写脚本到 code/ 并用 Bash 执行（.venv 在 {PROJECT_DIR}/.venv/）\n"
            f"5. **文件分析**: Read 工具可读取 PDF、Excel、图片\n"
            f"6. **数据存储**: 中间数据存到 data/，最终结果存到 output/\n\n"
            f"## 工作流程\n"
            f"1. **规划**: 先在 log.md 写下研究计划，更新 progress.json\n"
            f"2. **收集**: 搜索、爬取、下载，数据存 data/\n"
            f"3. **分析**: 整理、对比、提炼洞察\n"
            f"4. **输出**: 在 output/report.md 生成最终报告\n\n"
            f"## 输出要求\n"
            f"- 最终报告必须存为 output/report.md\n"
            f"- 报告包含：摘要、方法论、数据来源、核心发现、建议\n"
            f"- 所有数据来源必须标注\n"
            f"- 每完成一个阶段更新 progress.json\n"
            f"- 执行过程记录到 log.md\n"
        )

    # ── Claude CLI Execution ──

    def _launch_claude(self, task: ResearchTask) -> None:
        """Launch Claude CLI as background process with monitoring."""
        ws = Path(task.workspace)
        task_md = (ws / "task.md").read_text(encoding="utf-8")

        system_prompt = (
            "你是一个自主研究 Agent。你的任务描述在当前目录的 task.md 中。\n"
            "严格遵守 task.md 中的工作流程和输出要求。\n"
            "每完成一个阶段，必须更新 progress.json。\n"
            "最终报告必须存为 output/report.md。\n"
            "不要问确认，直接执行。"
        )

        cmd = [
            CLAUDE_BIN, "-p", task_md,
            "--allowedTools", ALLOWED_TOOLS,
            "--permission-mode", "auto",
            "--max-turns", str(task.max_turns),
            "--output-format", "text",
            "--model", "sonnet",
            "--append-system-prompt", system_prompt,
        ]

        env = self._build_env()

        stdout_file = open(ws / "claude_stdout.txt", "w", encoding="utf-8")
        stderr_file = open(ws / "claude_stderr.txt", "w", encoding="utf-8")
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=stdout_file,
                stderr=stderr_file,
                cwd=str(ws),
                env=env,
            )
        except Exception:
            stdout_file.close()
            stderr_file.close()
            raise

        updated = replace(task, pid=proc.pid)
        self._save_task(updated)
        logger.info(f"Research task launched: {task.task_id} PID={proc.pid}")

        # Start monitor thread
        stop_event = threading.Event()
        with self._lock:
            self._monitor_threads[task.task_id] = stop_event
        monitor = threading.Thread(
            target=self._monitor_loop,
            args=(updated, proc, stop_event, stdout_file, stderr_file),
            daemon=True,
        )
        monitor.start()

    def _monitor_loop(
        self, task: ResearchTask, proc: subprocess.Popen,
        stop_event: threading.Event,
        stdout_file, stderr_file,
    ) -> None:
        """Background thread: monitor progress and report to Feishu."""
        last_progress_mtime = 0.0
        ws = Path(task.workspace)
        progress_file = ws / "progress.json"

        try:
            while not stop_event.wait(MONITOR_INTERVAL):
                if proc.poll() is not None:
                    break

                try:
                    if progress_file.exists():
                        mtime = progress_file.stat().st_mtime
                        if mtime > last_progress_mtime:
                            last_progress_mtime = mtime
                            progress = json.loads(
                                progress_file.read_text(encoding="utf-8")
                            )
                            self._report_progress(task, progress)
                except Exception as e:
                    logger.warning(f"Progress check failed: {e}")

            # Reap the process to avoid zombie
            proc.wait(timeout=30)
        finally:
            stdout_file.close()
            stderr_file.close()

        exit_code = proc.returncode
        report_path = ws / "output" / "report.md"
        has_report = report_path.exists() and report_path.stat().st_size > 100

        if has_report:
            status = "completed"
        elif exit_code == 0:
            status = "completed"
        else:
            status = "failed"

        updated = replace(
            task, status=status,
            completed_at=datetime.now().isoformat(),
        )
        self._save_task(updated)

        with self._lock:
            self._monitor_threads.pop(task.task_id, None)

        self._report_completion(updated)

    def _report_progress(self, task: ResearchTask, progress: dict) -> None:
        """Send progress update to Feishu."""
        phase = progress.get("current_phase", "?")
        done = progress.get("phases_completed", [])
        remaining = progress.get("phases_remaining", [])
        summary = progress.get("summary", "")
        total = len(done) + len(remaining) + 1

        done_text = "\n".join(f"  ✅ {p}" for p in done) if done else ""
        msg = (
            f"📊 研究进度 [{len(done)}/{total}]\n"
            f"{done_text}\n"
            f"  ▶️ {phase}\n"
        )
        if summary:
            msg += f"\n{summary}"

        self.sender.send_text(task.sender_id, msg)

    def _report_completion(self, task: ResearchTask) -> None:
        """Send final report to Feishu."""
        ws = Path(task.workspace)

        if task.status == "completed":
            duration = ""
            try:
                start = datetime.fromisoformat(task.started_at)
                end = datetime.fromisoformat(task.completed_at)
                minutes = int((end - start).total_seconds() / 60)
                duration = f"⏱ 耗时: {minutes} 分钟"
            except Exception:
                pass

            report_path = ws / "output" / "report.md"
            self.sender.send_text(
                task.sender_id,
                f"✅ 研究任务完成！\n"
                f"任务: {task.title}\n"
                f"{duration}\n"
                f"📁 工作目录: {task.workspace}",
            )

            if report_path.exists():
                try:
                    self.sender.send_file(
                        task.sender_id,
                        str(report_path),
                        f"{task.title}-报告.md",
                    )
                except Exception as e:
                    logger.warning(f"Failed to send report file: {e}")
                    content = report_path.read_text(encoding="utf-8")
                    if len(content) > 3500:
                        content = content[:3500] + "\n\n...(报告已截断，完整版在工作目录)"
                    self.sender.send_text(task.sender_id, f"📄 报告内容:\n\n{content}")
        else:
            stderr_path = ws / "claude_stderr.txt"
            error_hint = ""
            if stderr_path.exists():
                stderr = stderr_path.read_text(encoding="utf-8").strip()
                if stderr:
                    error_hint = f"\n错误信息: {stderr[-300:]}"

            self.sender.send_text(
                task.sender_id,
                f"❌ 研究任务失败\n"
                f"任务: {task.title}{error_hint}\n"
                f"📁 工作目录: {task.workspace}",
            )

        try:
            self.quota.record_call("sonnet", task.status == "completed", "")
        except Exception:
            pass

    # ── State Persistence ──

    def _save_task(self, task: ResearchTask) -> None:
        """Atomically save task state to state.json in workspace."""
        updated = replace(task, updated_at=datetime.now().isoformat())
        ws = Path(updated.workspace)
        ws.mkdir(parents=True, exist_ok=True)
        state_file = ws / "state.json"
        self._atomic_write(state_file, asdict(updated))

    @staticmethod
    def _atomic_write(path: Path, data: dict) -> None:
        """Write JSON atomically via temp file + rename."""
        content = json.dumps(data, ensure_ascii=False, indent=2)
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=str(path.parent), suffix=".tmp",
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                f.write(content)
            Path(tmp_path).replace(path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def _get_active_task(self) -> ResearchTask | None:
        """Find the currently running research task."""
        if not RESEARCH_DIR.exists():
            return None
        for task_dir in sorted(RESEARCH_DIR.iterdir(), reverse=True):
            if not task_dir.is_dir():
                continue
            state_file = task_dir / "state.json"
            if state_file.exists():
                try:
                    data = json.loads(state_file.read_text(encoding="utf-8"))
                    task = ResearchTask(**data)
                    if task.status == "running":
                        if task.pid:
                            try:
                                os.kill(task.pid, 0)
                                return task
                            except ProcessLookupError:
                                failed = replace(
                                    task, status="failed",
                                    completed_at=datetime.now().isoformat(),
                                )
                                self._save_task(failed)
                                continue
                        return task
                except Exception as e:
                    logger.warning(f"Failed to load task state: {e}")
        return None

    def _get_recent_tasks(self, limit: int = 10) -> list[ResearchTask]:
        """Load recent tasks, sorted by start time descending."""
        tasks = []
        if not RESEARCH_DIR.exists():
            return tasks
        for task_dir in sorted(RESEARCH_DIR.iterdir(), reverse=True):
            if len(tasks) >= limit:
                break
            if not task_dir.is_dir():
                continue
            state_file = task_dir / "state.json"
            if state_file.exists():
                try:
                    data = json.loads(state_file.read_text(encoding="utf-8"))
                    tasks.append(ResearchTask(**data))
                except Exception:
                    pass
        return tasks

    def _read_progress(self, task: ResearchTask) -> dict | None:
        """Read progress.json from task workspace."""
        progress_file = Path(task.workspace) / "progress.json"
        try:
            if progress_file.exists():
                return json.loads(progress_file.read_text(encoding="utf-8"))
        except Exception:
            pass
        return None

    @staticmethod
    def _build_env() -> dict:
        """Build clean environment for Claude CLI subprocess."""
        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
        env["PATH"] = f"/Users/tuanyou/.local/bin:{env.get('PATH', '')}"
        return env
