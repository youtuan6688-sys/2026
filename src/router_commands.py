"""Mixin: Help, Status, Health, Errors, KB, Contacts, Decisions for MessageRouter."""

import logging
import os
import subprocess
from pathlib import Path

from src.task_queue import TaskQueue
from src.utils.subprocess_env import CLAUDE_PATH, safe_env

logger = logging.getLogger(__name__)

MEMORY_DIR = Path("/Users/tuanyou/Happycode2026/vault/memory")


class CommandsMixin:
    """Help, status, health, errors, knowledge base, contacts, decisions."""

    # ── Long Message Splitting ──

    @staticmethod
    def _split_text(text: str, max_len: int = 3800) -> list[str]:
        """Split text into chunks that fit Feishu's message length limit."""
        if len(text) <= max_len:
            return [text]
        chunks = []
        while text:
            if len(text) <= max_len:
                chunks.append(text)
                break
            split_pos = text.rfind("\n", 0, max_len)
            if split_pos < max_len // 2:
                split_pos = max_len
            chunks.append(text[:split_pos])
            text = text[split_pos:].lstrip("\n")
        return chunks

    def _send_long_text(self, sender_id: str, text: str,
                        at_user_id: str = "", at_user_name: str = ""):
        """Send text with markdown rendering, splitting into multiple messages if needed."""
        chunks = self._split_text(text)
        for i, chunk in enumerate(chunks):
            if len(chunks) > 1:
                chunk = f"[{i + 1}/{len(chunks)}]\n{chunk}"
            if i == 0 and at_user_id and sender_id.startswith("oc_"):
                # Prepend @mention using card markdown syntax
                chunk = f'<at id="{at_user_id}"></at> {chunk}'
            self.sender.send_markdown(sender_id, chunk)

    # ── Help & Status ──

    def _show_help(self, sender_id: str):
        help_text = (
            "可用命令:\n"
            "/help — 显示此帮助\n"
            "/status — 系统状态\n"
            "/search <关键词> — 搜索知识库\n"
            "/kb — 知识库统计\n"
            "/todo — 待办管理 (add/done/del)\n"
            "/remember <内容> — 保存到记忆\n"
            "/phase <名称> — 开始新阶段\n"
            "/summary — 结束阶段并总结\n"
            "/decisions — 查看最近决策\n"
            "/errors — 错误日志统计\n"
            "/health — 系统健康检查\n"
            "/tasks — 进化任务队列状态\n"
            "/checkpoint — 当前检查点状态\n"
            "/continue — 从检查点续接执行\n"
            "/contacts — 查看联系人档案\n"
            "/loop <interval> <prompt> — 启动定时循环任务\n"
            "/loop stop — 停止循环任务\n"
            "/session list — 查看运行中的会话\n"
            "/session stop <name> — 停止会话\n"
            "/session output <name> — 查看会话输出\n"
            "/doc read <链接或ID> — 读取飞书文档\n"
            "/doc create <标题> — 创建飞书文档\n"
            "/doc write <ID> <内容> — 写入飞书文档\n"
            "/doc share <ID> <邮箱> — 分享飞书文档\n"
            "\n直接发消息 — AI 对话\n"
            "发送链接 — 自动解析保存到知识库"
        )
        self.sender.send_text(sender_id, help_text)

    def _show_group_help(self, sender_id: str):
        self.sender.send_text(
            sender_id,
            "yo，小叼毛在此 🫡 能帮你干这些活儿：\n\n"
            "直接 @我 说话 — 聊天、问问题、写文案、翻译、头脑风暴\n"
            "/stock <代码/名称> — 查股票行情（A股+港股）\n"
            "/search <关键词> — 搜知识库\n"
            "/doc read <链接> — 读飞书文档\n"
            "/doc create <标题> — 创建飞书文档\n"
            "/kb — 知识库统计\n"
            "/video <URL> — 视频拆解分析\n"
            "/video search <关键词> — 搜索视频\n"
            "/work <任务> — 在你的工作区执行任务（仅视频群）\n"
            "发文件 — Excel/CSV/PDF/图片自动分析\n"
            "发视频链接 — 自动拆解（视频群）\n"
            "发链接 — 自动解析保存\n\n"
            "⚠️ 定时监控类任务需管理员审批\n"
            "其他骚操作？私聊老板去，我在群里权限有限 😏",
        )

    def _show_contacts(self, sender_id: str):
        """Show all known contacts."""
        contacts = self.contacts.list_contacts()
        if not contacts:
            self.sender.send_text(sender_id, "还没有联系人记录")
            return
        lines = [f"联系人档案 ({len(contacts)} 人):"]
        for c in contacts:
            lines.append(
                f"  {c['name'] or '未知'} | "
                f"消息 {c['message_count']} 条 | "
                f"最近 {c['last_seen']}"
            )
        self.sender.send_text(sender_id, "\n".join(lines))

    def _show_status(self, sender_id: str):
        article_count = 0
        vault_dir = Path("/Users/tuanyou/Happycode2026/vault")
        for subdir in ["articles", "social", "docs"]:
            d = vault_dir / subdir
            if d.exists():
                article_count += len([f for f in d.iterdir() if f.suffix == ".md"])

        todos = self._load_todos()
        pending = sum(1 for t in todos if not t.get("done"))
        done = sum(1 for t in todos if t.get("done"))

        phase = self._phase_log.get("current_phase")
        phase_text = f"当前阶段: {phase['name']}" if phase else "无进行中的阶段"

        decision_count = len(self._phase_log.get("decisions", []))

        memory_files = []
        if MEMORY_DIR.exists():
            for f in MEMORY_DIR.iterdir():
                if f.suffix == ".md":
                    size_kb = f.stat().st_size / 1024
                    memory_files.append(f"{f.name} ({size_kb:.1f}KB)")

        status = (
            f"系统状态:\n"
            f"知识库文章: {article_count} 篇\n"
            f"待办: {pending} 待完成, {done} 已完成\n"
            f"决策记录: {decision_count} 条\n"
            f"{phase_text}\n"
            f"记忆文件: {', '.join(memory_files)}"
        )
        self.sender.send_text(sender_id, status)

    def _search_knowledge_base(self, query: str, sender_id: str):
        if not query:
            self.sender.send_text(sender_id, "用法: /search <关键词>")
            return
        try:
            results = self.vector_store.query_similar(query, top_k=5)
            if not results:
                self.sender.send_text(sender_id, f"未找到与「{query}」相关的内容")
                return
            lines = [f"搜索「{query}」结果:"]
            for i, r in enumerate(results, 1):
                title = r.get("title", "无标题")
                dist = r.get("distance", 0)
                summary = r.get("summary", "")[:100]
                lines.append(f"\n{i}. {title} (相关度: {1 - dist:.0%})")
                if summary:
                    lines.append(f"   {summary}")
            self.sender.send_text(sender_id, "\n".join(lines))
        except Exception as e:
            logger.error(f"Knowledge base search failed: {e}", exc_info=True)
            self.sender.send_text(sender_id, f"搜索失败: {e}")

    def _show_kb_stats(self, sender_id: str):
        vault_dir = Path("/Users/tuanyou/Happycode2026/vault")
        stats = {}
        total = 0
        for subdir in ["articles", "social", "docs"]:
            d = vault_dir / subdir
            if d.exists():
                count = len([f for f in d.iterdir() if f.suffix == ".md"])
                stats[subdir] = count
                total += count
            else:
                stats[subdir] = 0

        try:
            index_count = self.index.count() if hasattr(self.index, "count") else "N/A"
        except Exception:
            index_count = "N/A"

        try:
            vector_count = self.vector_store.count() if hasattr(self.vector_store, "count") else "N/A"
        except Exception:
            vector_count = "N/A"

        text = (
            f"知识库统计:\n"
            f"文章 (articles): {stats['articles']} 篇\n"
            f"社交 (social): {stats['social']} 篇\n"
            f"文档 (docs): {stats['docs']} 篇\n"
            f"总计: {total} 篇\n"
            f"索引记录: {index_count}\n"
            f"向量记录: {vector_count}"
        )
        self.sender.send_text(sender_id, text)

    # ── Decision Display ──

    def _show_tasks(self, sender_id: str):
        """Show task queue status."""
        try:
            q = TaskQueue()
            stats = q.get_stats()
            lines = [
                "Evolution Task Queue:",
                f"  Pending: {stats['pending']}  Running: {stats['running']}",
                f"  Completed: {stats['completed']}  Failed: {stats['failed']}",
            ]

            pending = [t for t in q.get_all() if t.status == "pending"]
            pending.sort(key=lambda t: t.priority)
            if pending:
                lines.append("\nNext tasks:")
                for t in pending[:5]:
                    lines.append(f"  [{t.priority}] {t.title}")

            history_file = q._history_file
            if history_file.exists():
                import json as _json
                history = _json.loads(history_file.read_text(encoding="utf-8"))
                recent = history[-3:]
                if recent:
                    lines.append("\nRecent:")
                    for h in reversed(recent):
                        icon = "OK" if h["status"] == "completed" else "FAIL"
                        lines.append(f"  [{icon}] {h.get('title', '?')}")

            self.sender.send_text(sender_id, "\n".join(lines))
        except Exception as e:
            self.sender.send_text(sender_id, f"Task queue error: {e}")

    def _show_checkpoint(self, sender_id: str):
        """Show current checkpoint status."""
        status = self.checkpoint_manager.format_status()
        self.sender.send_text(sender_id, status)

    def _resume_from_checkpoint(self, sender_id: str):
        """Resume execution from the last checkpoint."""
        checkpoint = self.checkpoint_manager.load()
        if not checkpoint:
            self.sender.send_text(sender_id, "没有可续接的任务检查点")
            return

        from scripts.claude_runner import _load_prompt
        original_prompt = _load_prompt(checkpoint.task_id)

        if not original_prompt:
            resume_prompt = self.checkpoint_manager.get_resume_prompt()
            if not resume_prompt:
                self.sender.send_text(sender_id, "没有可续接的任务检查点")
                return
            original_prompt = resume_prompt

        current = checkpoint.current_step() if checkpoint else None
        step_info = f" (step: {current.name})" if current else ""
        self.sender.send_text(
            sender_id,
            f"从检查点续接: {checkpoint.description}{step_info}\n"
            f"进度: {checkpoint.progress_summary()}",
        )

        self._add_turn("user", f"继续 {checkpoint.description}{step_info}", chat_id=sender_id)
        self._execute_claude(original_prompt, sender_id)

    def _show_health(self, sender_id: str):
        """Run health check and show results."""
        try:
            env = safe_env()
            result = subprocess.run(
                ["/Users/tuanyou/Happycode2026/.venv/bin/python",
                 "/Users/tuanyou/Happycode2026/scripts/health_check.py"],
                capture_output=True, text=True, timeout=30,
                cwd="/Users/tuanyou/Happycode2026", env=env,
            )
            output = result.stdout.strip() if result.stdout.strip() else "Health check returned no output"
            self._send_long_text(sender_id, output)
        except Exception as e:
            self.sender.send_text(sender_id, f"Health check failed: {e}")

    def _show_errors(self, sender_id: str):
        stats = self.error_tracker.get_stats()
        if stats["total"] == 0:
            self.sender.send_text(sender_id, "No errors recorded.")
            return

        lines = [
            f"Error Stats: {stats['total']} total, {stats['unresolved']} unresolved",
        ]
        if stats["by_type"]:
            top_types = list(stats["by_type"].items())[:5]
            lines.append("Top types: " + ", ".join(f"{t}({c})" for t, c in top_types))
        if stats["by_severity"]:
            lines.append("Severity: " + ", ".join(f"{k}:{v}" for k, v in stats["by_severity"].items()))

        recent = self.error_tracker.get_recent(5, unresolved_only=True)
        if recent:
            lines.append("\nRecent unresolved:")
            for e in recent:
                ts = e.get("timestamp", "")[:16]
                lines.append(f"  [{e.get('severity', '').upper()}] {ts} {e.get('error_type')} - {e.get('message', '')[:80]}")

        patterns = self.error_tracker.get_recurring_patterns()
        if patterns:
            lines.append("\nRecurring patterns:")
            for p in patterns[:3]:
                lines.append(f"  {p['error_type']}: {p['count']}x in {', '.join(p['sources'][:3])}")

        self._send_long_text(sender_id, "\n".join(lines))

    def _show_recent_decisions(self, sender_id: str):
        decisions = self._phase_log.get("decisions", [])
        if not decisions:
            self.sender.send_text(sender_id, "暂无决策记录")
            return
        recent = decisions[-10:]
        lines = []
        for d in recent:
            ctx = f" ({d['context'][:50]})" if d.get("context") else ""
            lines.append(f"[{d['time']}] {d['decision']}{ctx}")
        self.sender.send_text(sender_id, "最近决策:\n" + "\n".join(lines))
