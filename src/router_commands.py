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
            "/bt list — 多维表格模板列表\n"
            "/bt info <模板> — 查看模板详情\n"
            "/bt create <模板> — 一键建表\n"
            "/bt new <模板> — 新建多维表格+表\n"
            "/bt export <token> <id> — 导出数据\n"
            "/memory-review — 记忆文件 Review\n"
            "/ticket — 任务追踪 (create/list/update)\n"
            "/research <任务> — 启动研究任务（竞品分析/市场调研等）\n"
            "/research status — 查看研究任务进度\n"
            "/research stop — 停止当前研究任务\n"
            "/research list — 历史研究任务\n"
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
            "/bt list — 多维表格模板\n"
            "/bt create <模板> — 一键建表\n"
            "/ticket create <标题> — 创建任务\n"
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
        """Resume execution from interrupted long task or last checkpoint."""
        # Priority: check for interrupted long task first
        from src.long_task import LongTaskManager
        from datetime import datetime
        ltm = LongTaskManager()
        lt = ltm._load()
        if lt and lt.status == "interrupted" and lt.sender_id == sender_id:
            lt.status = "active"
            lt.updated_at = datetime.now().isoformat()
            ltm._save(lt)
            self.sender.send_text(
                sender_id,
                f"恢复中断任务（已完成 {lt.steps_completed} 步）...",
            )
            recovery_prompt = ltm.build_recovery_prompt(lt)
            self._add_turn("user", "继续中断任务", chat_id=sender_id)
            self._execute_claude(recovery_prompt, sender_id, is_long_task=True)
            return

        # Fallback: checkpoint-based resume
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

    # ── Bitable Commands ──

    def _handle_bitable_command(self, text: str, sender_id: str):
        """Handle /bt commands for Bitable template operations.

        Usage:
            /bt list              — 列出所有模板
            /bt info <模板名>     — 查看模板详情
            /bt create <模板名> [自定义表名]  — 在默认 app 中一键建表
            /bt new <模板名> [app名]         — 新建 app + 表
            /bt stats <app_token> <table_id> — 表统计
            /bt export <app_token> <table_id> [md|csv] — 导出数据
        """
        parts = text.strip().split(maxsplit=3)
        # parts[0] = "/bt", parts[1] = subcommand, ...

        if len(parts) < 2:
            self._send_long_text(sender_id, self.bitable_factory.list_available_formatted())
            return

        sub = parts[1].lower()

        if sub in ("list", "列表", "ls"):
            self._send_long_text(sender_id, self.bitable_factory.list_available_formatted())
            return

        if sub in ("info", "详情", "describe"):
            if len(parts) < 3:
                self.sender.send_text(sender_id, "用法: /bt info <模板名>")
                return
            desc = self.bitable_factory.describe_template(parts[2])
            if desc:
                self._send_long_text(sender_id, desc)
            else:
                self.sender.send_text(
                    sender_id,
                    f"模板 '{parts[2]}' 不存在。用 /bt list 查看可用模板",
                )
            return

        if sub in ("create", "建表"):
            if len(parts) < 3:
                self.sender.send_text(sender_id, "用法: /bt create <模板名> [自定义表名]")
                return
            template_key = parts[2]
            custom_name = parts[3] if len(parts) > 3 else ""
            # Use default app token from env
            import os
            app_token = os.getenv("BITABLE_DEFAULT_APP_TOKEN", "")
            if not app_token:
                self.sender.send_text(
                    sender_id,
                    "未配置默认多维表格。请先设置 BITABLE_DEFAULT_APP_TOKEN 环境变量，"
                    "或使用 /bt new <模板名> 创建新的多维表格",
                )
                return
            self.sender.send_text(sender_id, f"正在创建表: {template_key}...")
            result = self.bitable_factory.create_from_template(
                app_token, template_key, custom_name,
            )
            if result:
                self.sender.send_markdown(
                    sender_id,
                    f"✅ **表创建成功**\n"
                    f"表名: {result['name']}\n"
                    f"表ID: `{result['table_id']}`\n"
                    f"字段数: {result['fields_created']}\n"
                    f"模板: {result.get('template', template_key)}",
                )
            else:
                self.sender.send_text(sender_id, f"❌ 建表失败，检查模板名是否正确")
            return

        if sub in ("new", "新建"):
            if len(parts) < 3:
                self.sender.send_text(sender_id, "用法: /bt new <模板名> [app名]")
                return
            template_key = parts[2]
            app_name = parts[3] if len(parts) > 3 else ""
            self.sender.send_text(sender_id, f"正在创建新的多维表格: {template_key}...")
            result = self.bitable_factory.create_full_app(
                template_key, app_name,
            )
            if result:
                self.sender.send_markdown(
                    sender_id,
                    f"✅ **多维表格创建成功**\n"
                    f"名称: {result['name']}\n"
                    f"App Token: `{result['app_token']}`\n"
                    f"链接: {result['url']}\n"
                    f"表ID: `{result.get('table_id', 'N/A')}`\n"
                    f"字段数: {result.get('fields_created', 0)}",
                )
            else:
                self.sender.send_text(sender_id, f"❌ 创建失败，检查模板名是否正确")
            return

        if sub in ("stats", "统计"):
            if len(parts) < 4:
                self.sender.send_text(sender_id, "用法: /bt stats <app_token> <table_id>")
                return
            app_token, table_id = parts[2], parts[3]
            stats = self.bitable_manager.get_table_stats(app_token, table_id)
            self.sender.send_markdown(
                sender_id,
                f"📊 **表统计**\n"
                f"记录数: {stats['record_count']}\n"
                f"字段数: {stats['field_count']}\n"
                f"字段: {self.bitable_manager.format_fields(stats['fields'])}",
            )
            return

        if sub in ("export", "导出"):
            if len(parts) < 4:
                self.sender.send_text(sender_id, "用法: /bt export <app_token> <table_id> [md|csv]")
                return
            # Parse: /bt export <app_token> <table_id> [format]
            app_token, table_id = parts[2], parts[3]
            fmt = parts[4] if len(parts) > 4 else "md"
            self.sender.send_text(sender_id, f"正在导出...")
            if fmt == "csv":
                data = self.bitable_manager.export_to_csv(app_token, table_id)
            else:
                data = self.bitable_manager.export_to_markdown(app_token, table_id)
            if data:
                self._send_long_text(sender_id, data)
            else:
                self.sender.send_text(sender_id, "表中无数据")
            return

        # Unknown subcommand → show help
        self._send_long_text(sender_id, self.bitable_factory.list_available_formatted())

    # ── Memory Review ──

    def _show_memory_review(self, sender_id: str, args: str = ""):
        """Show auto-generated memory files for human review.

        Usage:
            /memory-review           — 列出所有记忆文件摘要
            /memory-review <文件名>  — 查看某个文件完整内容
            /memory-review clean     — 清理建议（列出可疑条目）
        """
        if args == "clean":
            self._memory_review_clean(sender_id)
            return

        if args:
            # Show specific file content
            target = MEMORY_DIR / args
            if not target.exists():
                # Try with .md extension
                target = MEMORY_DIR / f"{args}.md"
            if not target.exists():
                self.sender.send_text(sender_id, f"文件不存在: {args}")
                return
            content = target.read_text(encoding="utf-8").strip()
            if not content:
                self.sender.send_text(sender_id, f"{target.name} 为空")
                return
            header = f"📄 **{target.name}** ({len(content)}字)\n{'─' * 30}\n"
            self._send_long_text(sender_id, header + content)
            return

        # List all memory files with summaries
        lines = ["🧠 **记忆文件 Review**\n"]

        # Vault memory files
        if MEMORY_DIR.exists():
            vault_files = sorted(MEMORY_DIR.glob("*.md"))
            if vault_files:
                lines.append("**Vault 记忆** (vault/memory/):")
                for f in vault_files:
                    size_kb = f.stat().st_size / 1024
                    content = f.read_text(encoding="utf-8").strip()
                    # Count sections
                    sections = [l for l in content.split("\n") if l.startswith("## ") or l.startswith("### ")]
                    section_count = len(sections)
                    # Last modified
                    import time
                    mtime = time.strftime("%m-%d %H:%M", time.localtime(f.stat().st_mtime))
                    # Quality indicator
                    quality = "🟢" if size_kb < 5 else "🟡" if size_kb < 10 else "🔴"
                    lines.append(
                        f"  {quality} `{f.name}` — {size_kb:.1f}KB, "
                        f"{section_count}节, 更新 {mtime}"
                    )
                    # Show last section title as preview
                    if sections:
                        lines.append(f"      最近: {sections[-1].strip()}")

        # Auto-generated Claude memory
        auto_mem_dir = Path(os.path.expanduser(
            "~/.claude/projects/-Users-tuanyou-Happycode2026/memory"
        ))
        if auto_mem_dir.exists():
            auto_files = sorted(auto_mem_dir.glob("*.md"))
            if auto_files:
                lines.append("\n**Claude Auto-Memory** (~/.claude/projects/.../memory/):")
                for f in auto_files:
                    size_kb = f.stat().st_size / 1024
                    import time
                    mtime = time.strftime("%m-%d %H:%M", time.localtime(f.stat().st_mtime))
                    lines.append(f"  📝 `{f.name}` — {size_kb:.1f}KB, 更新 {mtime}")

        # Contact memory stats
        contacts_dir = MEMORY_DIR / "contacts"
        if contacts_dir.exists():
            contact_files = list(contacts_dir.glob("*.json"))
            lines.append(f"\n**联系人记忆**: {len(contact_files)} 人")

        # Group memory stats
        groups_dir = MEMORY_DIR / "groups"
        if groups_dir.exists():
            group_files = list(groups_dir.glob("*.json"))
            lines.append(f"**群记忆**: {len(group_files)} 群")

        lines.append("\n用法:")
        lines.append("  `/memory-review <文件名>` — 查看完整内容")
        lines.append("  `/memory-review clean` — 清理建议")

        self._send_long_text(sender_id, "\n".join(lines))

    def _memory_review_clean(self, sender_id: str):
        """Analyze memory files and suggest cleanup."""
        lines = ["🧹 **记忆清理建议**\n"]
        issues_found = 0

        if not MEMORY_DIR.exists():
            self.sender.send_text(sender_id, "记忆目录不存在")
            return

        for f in sorted(MEMORY_DIR.glob("*.md")):
            size_kb = f.stat().st_size / 1024
            content = f.read_text(encoding="utf-8").strip()
            file_issues = []

            # Check size
            if size_kb > 5:
                file_issues.append(f"⚠️ 体积过大 ({size_kb:.1f}KB > 5KB)，建议压缩旧条目")

            # Check for potential low-quality entries
            low_quality_patterns = [
                "如果 A，那么 B",
                "AUTOFIX:",
                "PATTERN:",
                "TODO:",
            ]
            for pattern in low_quality_patterns:
                count = content.count(pattern)
                if count > 3:
                    file_issues.append(
                        f"⚠️ 含 {count} 条「{pattern}」格式条目，考虑精简"
                    )

            # Check for duplicate-like entries (same date, similar content)
            date_sections = [l for l in content.split("\n") if l.startswith("## 2026-")]
            if len(date_sections) > 20:
                file_issues.append(
                    f"⚠️ 含 {len(date_sections)} 个日期节，考虑归档旧条目"
                )

            if file_issues:
                issues_found += len(file_issues)
                lines.append(f"**{f.name}**:")
                for issue in file_issues:
                    lines.append(f"  {issue}")

        if issues_found == 0:
            lines.append("✅ 所有记忆文件状态良好，无需清理")
        else:
            lines.append(f"\n共发现 {issues_found} 个待处理项")
            lines.append("确认后可手动编辑，或让我自动压缩（回复「自动清理」）")

        self._send_long_text(sender_id, "\n".join(lines))

    # ── Research Task ──

    def _handle_research_command(self, text: str, sender_id: str):
        """Handle /research commands for autonomous research tasks.

        Usage:
            /research <任务描述>   — 启动研究任务
            /research status      — 查看当前进度
            /research stop        — 停止当前任务
            /research list        — 历史任务列表
        """
        parts = text.strip().split(None, 1)
        sub = parts[1].strip() if len(parts) > 1 else ""

        if not sub:
            self.sender.send_text(
                sender_id,
                "用法:\n"
                "  /research <任务描述> — 启动研究任务\n"
                "  /research status — 查看进度\n"
                "  /research stop — 停止任务\n"
                "  /research list — 历史列表\n\n"
                "示例:\n"
                "  /research 嘉宝莉艺术漆在小红书的竞品分析，对标三棵树和立邦",
            )
            return

        if sub == "status":
            status = self._get_research_manager().get_status(sender_id)
            self.sender.send_text(sender_id, status)
            return

        if sub == "stop":
            self._get_research_manager().stop(sender_id)
            return

        if sub == "list":
            result = self._get_research_manager().list_tasks(sender_id)
            self.sender.send_text(sender_id, result)
            return

        # Anything else is a task description
        self._get_research_manager().start(sub, sender_id)

    # ── Ticket Management ──

    def _handle_ticket_command(self, text: str, sender_id: str):
        """Handle /ticket commands for task tracking.

        Usage:
            /ticket create <标题>     — 创建新任务
            /ticket list              — 查看任务列表
            /ticket update <ID> <状态> — 更新任务状态
        """
        parts = text.strip().split(maxsplit=3)

        if len(parts) < 2:
            self.sender.send_text(
                sender_id,
                "Ticket 命令:\n"
                "  /ticket create <标题> — 创建任务\n"
                "  /ticket list — 查看任务\n"
                "  /ticket setup — 初始化 Ticket 表\n"
                "  /ticket update <ID> <状态> — 更新状态"
            )
            return

        sub = parts[1].lower()

        if sub in ("setup", "init", "初始化"):
            # Create ticket tracking table in Bitable
            import os
            app_token = os.getenv("BITABLE_DEFAULT_APP_TOKEN", "")
            if not app_token:
                self.sender.send_text(
                    sender_id,
                    "未配置 BITABLE_DEFAULT_APP_TOKEN。"
                    "先用 /bt new ticket 创建，或设置环境变量"
                )
                return
            self.sender.send_text(sender_id, "正在初始化 Ticket 表...")
            result = self.bitable_factory.create_from_template(
                app_token, "ticket", ""
            )
            if result:
                self.sender.send_markdown(
                    sender_id,
                    f"✅ **Ticket 表创建成功**\n"
                    f"表ID: `{result['table_id']}`\n"
                    f"字段数: {result['fields_created']}\n"
                    f"现在可以用 `/ticket create <标题>` 创建任务"
                )
            else:
                self.sender.send_text(sender_id, "❌ 创建失败")
            return

        if sub in ("create", "new", "新建"):
            title = parts[2] if len(parts) > 2 else ""
            if not title:
                self.sender.send_text(sender_id, "用法: /ticket create <任务标题>")
                return
            description = parts[3] if len(parts) > 3 else ""
            self._create_ticket(title, description, sender_id)
            return

        if sub in ("list", "列表", "ls"):
            self._list_tickets(sender_id)
            return

        if sub in ("update", "更新"):
            if len(parts) < 4:
                self.sender.send_text(sender_id, "用法: /ticket update <记录ID> <新状态>")
                return
            record_id, new_status = parts[2], parts[3]
            self._update_ticket(record_id, new_status, sender_id)
            return

        self.sender.send_text(sender_id, "未知子命令。用 /ticket 查看帮助")

    def _create_ticket(self, title: str, description: str, sender_id: str):
        """Create a ticket record in Bitable."""
        import os
        app_token = os.getenv("BITABLE_DEFAULT_APP_TOKEN", "")
        table_id = os.getenv("BITABLE_TICKET_TABLE_ID", "")
        if not app_token or not table_id:
            self.sender.send_text(
                sender_id,
                "Ticket 表未配置。先运行 /ticket setup 初始化，"
                "然后设置 BITABLE_TICKET_TABLE_ID 环境变量"
            )
            return
        from datetime import datetime
        fields = {
            "任务标题": title,
            "状态": "待处理",
            "优先级": "P1",
            "创建时间": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        if description:
            fields["描述"] = description
        try:
            result = self.bitable_manager.create_record(app_token, table_id, fields)
            if result:
                record_id = result.get("record", {}).get("record_id", "?")
                self.sender.send_markdown(
                    sender_id,
                    f"✅ **Ticket 已创建**\n"
                    f"标题: {title}\n"
                    f"ID: `{record_id}`\n"
                    f"状态: 待处理"
                )
            else:
                self.sender.send_text(sender_id, "❌ 创建失败")
        except Exception as e:
            logger.error(f"Ticket creation failed: {e}")
            self.sender.send_text(sender_id, f"创建失败: {e}")

    def _list_tickets(self, sender_id: str):
        """List recent tickets from Bitable."""
        import os
        app_token = os.getenv("BITABLE_DEFAULT_APP_TOKEN", "")
        table_id = os.getenv("BITABLE_TICKET_TABLE_ID", "")
        if not app_token or not table_id:
            self.sender.send_text(sender_id, "Ticket 表未配置。先运行 /ticket setup")
            return
        try:
            records = self.bitable_manager.search_records(
                app_token, table_id, page_size=20
            )
            if not records:
                self.sender.send_text(sender_id, "暂无 Ticket")
                return
            lines = ["📋 **任务列表**\n"]
            status_icons = {
                "待处理": "⬜", "进行中": "🔵", "已完成": "✅",
                "已关闭": "⚫", "阻塞": "🔴",
            }
            for r in records:
                fields = r.get("fields", {})
                title = fields.get("任务标题", "无标题")
                status = fields.get("状态", "未知")
                priority = fields.get("优先级", "")
                icon = status_icons.get(status, "❓")
                rid = r.get("record_id", "")[:8]
                lines.append(f"{icon} [{priority}] {title} (`{rid}`)")
            self._send_long_text(sender_id, "\n".join(lines))
        except Exception as e:
            logger.error(f"Ticket list failed: {e}")
            self.sender.send_text(sender_id, f"查询失败: {e}")

    def _update_ticket(self, record_id: str, new_status: str, sender_id: str):
        """Update a ticket's status."""
        import os
        app_token = os.getenv("BITABLE_DEFAULT_APP_TOKEN", "")
        table_id = os.getenv("BITABLE_TICKET_TABLE_ID", "")
        if not app_token or not table_id:
            self.sender.send_text(sender_id, "Ticket 表未配置")
            return
        try:
            result = self.bitable_manager.update_record(
                app_token, table_id, record_id, {"状态": new_status}
            )
            if result:
                self.sender.send_text(sender_id, f"✅ Ticket {record_id[:8]} 状态更新为: {new_status}")
            else:
                self.sender.send_text(sender_id, "❌ 更新失败")
        except Exception as e:
            logger.error(f"Ticket update failed: {e}")
            self.sender.send_text(sender_id, f"更新失败: {e}")

    # ── Decision Display ──

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

    # ── Evolution Report (基于 git log 的精确进化报告) ──

    def _show_evolution_report(self, sender_id: str, date_str: str = ""):
        """Generate evolution report from git log + evolution logs."""
        from datetime import date, datetime, timedelta

        project_dir = "/Users/tuanyou/Happycode2026"

        # Parse target date
        if date_str:
            try:
                target = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                self.sender.send_text(sender_id, f"日期格式错误，请用 YYYY-MM-DD")
                return
        else:
            target = date.today()

        next_day = target + timedelta(days=1)

        # 1. Git commits for the target date
        try:
            git_result = subprocess.run(
                ["git", "log",
                 f"--since={target.isoformat()} 00:00:00",
                 f"--until={next_day.isoformat()} 00:00:00",
                 "--pretty=format:%h|%s|%ai",
                 "--no-merges"],
                capture_output=True, text=True, timeout=10,
                cwd=project_dir,
            )
            commits = [line.split("|", 2) for line in git_result.stdout.strip().split("\n") if line.strip()]
        except Exception as e:
            logger.error(f"Git log failed: {e}")
            commits = []

        # 2. Uncommitted changes
        try:
            diff_result = subprocess.run(
                ["git", "diff", "--stat", "HEAD"],
                capture_output=True, text=True, timeout=10,
                cwd=project_dir,
            )
            uncommitted = diff_result.stdout.strip()
        except Exception:
            uncommitted = ""

        # 3. Evolution log for the day (if exists)
        evo_log_path = Path(f"{project_dir}/vault/logs/evolution-{target.isoformat()}.md")
        evo_summary = ""
        if evo_log_path.exists():
            try:
                content = evo_log_path.read_text(encoding="utf-8")
                # Extract key findings (skip frontmatter)
                in_body = False
                evo_lines = []
                for line in content.split("\n"):
                    if in_body:
                        evo_lines.append(line)
                    elif line.startswith("---") and evo_lines:
                        in_body = True
                    elif line.startswith("---"):
                        evo_lines.append("")  # mark start of frontmatter
                if evo_lines:
                    evo_summary = "\n".join(evo_lines[:30]).strip()
            except Exception:
                pass

        # 4. Format report
        report_lines = [f"## 进化报告 ({target.isoformat()})"]

        if commits:
            # Categorize commits
            feats = []
            fixes = []
            others = []
            for parts in commits:
                if len(parts) < 2:
                    continue
                hash_id, msg = parts[0], parts[1]
                if msg.startswith("feat"):
                    feats.append(f"- `{hash_id}` {msg}")
                elif msg.startswith("fix"):
                    fixes.append(f"- `{hash_id}` {msg}")
                else:
                    others.append(f"- `{hash_id}` {msg}")

            if feats:
                report_lines.append(f"\n### 新功能 ({len(feats)})")
                report_lines.extend(feats)
            if fixes:
                report_lines.append(f"\n### 修复 ({len(fixes)})")
                report_lines.extend(fixes)
            if others:
                report_lines.append(f"\n### 其他 ({len(others)})")
                report_lines.extend(others)

            # Stats
            try:
                stat_result = subprocess.run(
                    ["git", "diff", "--stat",
                     f"--since={target.isoformat()} 00:00:00",
                     f"HEAD~{len(commits)}", "HEAD"],
                    capture_output=True, text=True, timeout=10,
                    cwd=project_dir,
                )
                # Use shortstat for summary
                shortstat = subprocess.run(
                    ["git", "diff", "--shortstat",
                     f"HEAD~{len(commits)}", "HEAD"],
                    capture_output=True, text=True, timeout=10,
                    cwd=project_dir,
                )
                if shortstat.stdout.strip():
                    report_lines.append(f"\n**代码统计**: {shortstat.stdout.strip()}")
            except Exception:
                pass
        else:
            report_lines.append("\n今天暂无 git 提交。")

        if uncommitted:
            report_lines.append(f"\n### 未提交更改")
            # Only show summary line
            stat_lines = uncommitted.strip().split("\n")
            if stat_lines:
                report_lines.append(stat_lines[-1])  # summary line

        if evo_summary:
            report_lines.append(f"\n### 自动进化摘要")
            report_lines.append(evo_summary[:500])

        report = "\n".join(report_lines)
        self._send_long_text(sender_id, report)
