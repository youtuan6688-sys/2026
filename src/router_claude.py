"""Mixin: Claude execution (group + private) and URL processing for MessageRouter."""

import json
import logging
import re
import subprocess
import threading
import time
from datetime import date, datetime
from pathlib import Path

from scripts.claude_runner import run_with_resume
from src.long_task import LongTaskManager, STEP_COOLDOWN_S
from src.utils.url_utils import extract_urls, detect_platform
from src.parsers import get_parser

logger = logging.getLogger(__name__)

BUFFER_DIR = Path("/Users/tuanyou/Happycode2026/data/daily_buffer")


class ClaudeMixin:
    """Claude execution for group/private chat, URL processing, conversation buffering."""

    def _execute_claude_group(self, prompt: str, sender_id: str,
                              user_id: str = ""):
        """Execute Claude with 小叼毛 persona for group chat."""

        def _run():
            try:
                persona = self._load_group_persona()

                # 铁律 + 人设 → system prompt（高权重）
                is_video_group = self._is_video_group(sender_id)
                task_detect_rule = ""
                if is_video_group:
                    task_detect_rule = (
                        "\n4. 任务检测：如果用户的消息是一个需要写代码、跑脚本、"
                        "操作文件、分析数据、生成报告等实际执行类任务，"
                        "在你的回复最末尾独占一行写 [TASK]。"
                        "纯聊天、提问、讨论则不加。\n"
                    )
                system_prompt = (
                    "⛔ 铁律（违反任何一条=严重失职，优先级最高）：\n"
                    "1. 严禁编造数据！你回复中的任何数字、百分比、排名、趋势，"
                    "必须100%来自用户在对话中明确提供的原始数据。"
                    "如果没有数据，就说「需要你提供XX数据才能分析」。"
                    "绝对不能猜、不能推算、不能编示例数据、不能写占位符。"
                    "违规示例（禁止）：'渗透率<8%'、'客单价¥68'、'占比65%' ← 这些如果不是来自用户文件就是编造。\n"
                    "2. 严禁空头承诺！不能说「已安排」「正在监控」「帮你拉数据」。"
                    "你只能处理对话中已有的信息。\n"
                    "3. 推测性结论必须标注「⚠️ 推测」。\n"
                    f"{task_detect_rule}\n"
                    f"{persona}"
                )

                # 用户消息 + 上下文 → user prompt
                parts = []

                # Group long-term memory (summaries, topics, key info)
                try:
                    if not hasattr(self, '_group_memory'):
                        from src.group_memory import GroupMemory
                        self._group_memory = GroupMemory()
                    group_ctx = self._group_memory.format_context(sender_id)
                    if group_ctx:
                        parts.append(group_ctx)
                    self._group_memory.increment_stats(sender_id)
                except Exception as e:
                    logger.warning(f"Group memory load failed: {e}")

                history_text = self._format_history(chat_id=sender_id)
                if history_text:
                    parts.append(history_text)

                if user_id:
                    user_ctx = self.contacts.format_context(user_id)
                    parts.append(f"对话用户信息:\n{user_ctx}")

                parts.append(f"用户消息:\n{prompt}")

                kb_context = self._query_knowledge_base(prompt, chat_type="group")
                if kb_context:
                    parts.append(kb_context)

                full_prompt = "\n\n".join(parts)

                output = self.quota.call_claude(
                    full_prompt, "sonnet", timeout=120,
                    extra_args=[
                        "--permission-mode", "auto", "--verbose",
                        "--append-system-prompt", system_prompt,
                    ],
                )

                if not output:
                    output = "啊这...我刚走神了，再说一遍？"

                # Detect [TASK] marker → auto-escalate to workspace
                task_escalated = False
                if is_video_group and output.rstrip().endswith("[TASK]"):
                    # Strip the marker from the reply
                    clean_output = output.rstrip().removesuffix("[TASK]").rstrip()
                    if clean_output:
                        output = clean_output
                    task_escalated = True

                user_name = self.contacts.get_name(user_id) if user_id else ""
                self._send_long_text(
                    sender_id, output,
                    at_user_id=user_id, at_user_name=user_name,
                )
                self._add_turn("assistant", output, chat_id=sender_id)

                self._buffer_conversation(
                    user_id=user_id, user_name=user_name,
                    user_msg=prompt, bot_reply=output,
                    chat_type="group", chat_id=sender_id,
                )

                # Auto-escalate: fire workspace execution after chat reply
                if task_escalated and user_id:
                    try:
                        handler = self._get_workspace_handler()
                        handler.handle_work(prompt, sender_id, user_id)
                    except Exception as e:
                        logger.warning("Task escalation failed: %s", e)

            except subprocess.TimeoutExpired:
                self.sender.send_text(sender_id, "想太久了脑子转不过来，换个简单点的问法？")
            except Exception as e:
                logger.error(f"Group chat execution failed: {e}", exc_info=True)
                self.sender.send_text(sender_id, "出了点小状况，等会儿再试试")

        if not self.gate.run_group(_run, sender_id):
            self.sender.send_text(sender_id, "消息太多啦，排队中...等前面的处理完再来 🫠")

    def _buffer_conversation(self, user_id: str, user_name: str,
                             user_msg: str, bot_reply: str,
                             chat_type: str = "p2p",
                             chat_id: str = ""):
        """Buffer conversation for daily opus evolution (no real-time AI calls)."""
        entry = {
            "ts": datetime.now().isoformat(),
            "user_id": user_id,
            "user_name": user_name,
            "user_msg": user_msg[:500],
            "bot_reply": bot_reply[:1000],
            "chat_type": chat_type,
            "chat_id": chat_id,
        }
        buffer_file = BUFFER_DIR / f"{date.today().isoformat()}.jsonl"
        try:
            with self.gate.file_lock:
                with open(buffer_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning(f"Failed to buffer conversation: {e}")

    # ── Claude Code Execution (with RAG + auto-resume) ──

    def _execute_claude(self, prompt: str, sender_id: str,
                        is_long_task: bool = False):
        """Execute Claude via claude -p with RAG context and auto-resume.

        If is_long_task=True, automatically continues until task is done
        or max steps reached.
        """
        self.sender.send_text(sender_id, f"思考中... \n> {prompt[:100]}")

        def _run():
            ltm = LongTaskManager()
            try:

                # Start long task tracking if flagged
                if is_long_task:
                    ltm.start(prompt, sender_id)

                full_prompt = self._build_full_prompt(prompt, chat_id=sender_id)
                system_prompt = self._build_system_prompt(user_id=sender_id)

                # 私聊也注入联系人记忆（与群聊对齐）
                if sender_id and not sender_id.startswith("oc_"):
                    user_ctx = self.contacts.format_context(sender_id)
                    if user_ctx:
                        system_prompt += f"\n\n对话用户信息:\n{user_ctx}"

                task_id = f"chat-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

                success, output = run_with_resume(
                    full_prompt,
                    task_id=task_id,
                    timeout=480,
                    max_retries=2,
                    user_message=prompt,
                    system_prompt=system_prompt,
                )

                if not output:
                    output = "(no output)"
                self._send_long_text(sender_id, output)
                self._add_turn("assistant", output, chat_id=sender_id)

                user_id = sender_id if not sender_id.startswith("oc_") else ""
                user_name = self.contacts.get_name(user_id) if user_id else ""
                self._buffer_conversation(
                    user_id=user_id, user_name=user_name,
                    user_msg=prompt, bot_reply=output,
                    chat_type="p2p",
                )

                # ── Long task: schedule next step outside this lock ──
                active_task = ltm.get_active(sender_id)
                if active_task and success and ltm.claim_step(sender_id):
                    self._schedule_next_step(
                        ltm, active_task, output, sender_id, system_prompt,
                    )
                elif active_task and not success:
                    ltm.complete(reason="execution_failed")

            except Exception as e:
                logger.error(f"Claude execution failed: {e}", exc_info=True)
                self.error_tracker.track(
                    "claude_error", str(e), "execute_claude", "high", prompt[:200],
                )
                self.sender.send_text(sender_id, f"执行失败: {e}")
                # Clean up long task on error
                try:
                    ltm.complete(reason="error")
                except Exception as inner:
                    logger.warning(f"Failed to complete long task on error: {inner}")

        self.gate.run_private(_run)

    def _schedule_next_step(self, ltm, task, last_output: str,
                            sender_id: str, system_prompt: str) -> None:
        """Check if next step needed, then schedule it via run_private().

        Called INSIDE the current private lock. Does pre-checks synchronously,
        then schedules the actual execution as a NEW run_private() call so the
        current lock is released first. Must be the LAST call in the caller.

        Guarantees: release_step() is always called on every exit path.
        """
        try:
            # Record the step just completed
            task = ltm.record_step(last_output)
            if not task or task.status != "active":
                ltm.release_step(sender_id)
                return

            # Check if Claude's output signals task is done
            if not ltm.should_continue(last_output):
                ltm.complete(reason="task_done_signal")
                ltm.release_step(sender_id)
                self.sender.send_text(
                    sender_id,
                    f"长任务完成，共执行 {task.steps_completed} 步 ✅",
                )
                return

            # Check if user sent a new message (task would be paused)
            if not ltm.get_active(sender_id):
                logger.info("Long task no longer active (paused or completed)")
                ltm.release_step(sender_id)
                return

            # Cooldown, then schedule next step as independent run_private()
            # Note: release_step is called inside _run_continuation_step on completion
            def _delayed_step():
                time.sleep(STEP_COOLDOWN_S)
                self._run_continuation_step(ltm, sender_id, system_prompt)

            threading.Thread(target=_delayed_step, daemon=True).start()

        except Exception as e:
            logger.error(f"_schedule_next_step failed: {e}", exc_info=True)
            ltm.release_step(sender_id)

    def _run_continuation_step(self, ltm, sender_id: str,
                               system_prompt: str) -> None:
        """Execute one continuation step via run_private() (acquires its own lock)."""

        def _run():
            try:
                # Re-check task is still active (user may have sent new msg)
                task = ltm.get_active(sender_id)
                if not task:
                    logger.info("Long task no longer active, skipping step")
                    ltm.release_step(sender_id)
                    return

                continue_prompt = ltm.build_continue_prompt(task)
                step_num = task.steps_completed + 1
                self.sender.send_text(
                    sender_id,
                    f"⏩ 自动续接 (步骤 {step_num})...",
                )

                full_prompt = self._build_full_prompt(
                    continue_prompt, chat_id=sender_id,
                )
                task_id = f"long-step-{step_num}-{datetime.now().strftime('%H%M%S')}"

                success, output = run_with_resume(
                    full_prompt,
                    task_id=task_id,
                    timeout=480,
                    max_retries=2,
                    user_message=continue_prompt,
                    system_prompt=system_prompt,
                )

                if not output:
                    output = "(no output)"
                self._send_long_text(sender_id, output)
                self._add_turn("assistant", output, chat_id=sender_id)

                self._buffer_conversation(
                    user_id=sender_id, user_name="",
                    user_msg=f"[auto-continue step {step_num}]",
                    bot_reply=output, chat_type="p2p",
                )

                if not success:
                    ltm.complete(reason="step_failed")
                    ltm.release_step(sender_id)
                    self.sender.send_text(sender_id, "执行出错，长任务暂停")
                    return

                # Schedule next step (recursive chain)
                # _schedule_next_step will call record_step to get fresh task
                self._schedule_next_step(
                    ltm, None, output, sender_id, system_prompt,
                )

            except Exception as e:
                logger.error(f"Continuation step failed: {e}", exc_info=True)
                ltm.complete(reason="error")
                ltm.release_step(sender_id)
                self.sender.send_text(sender_id, f"续接执行失败: {e}")

        self.gate.run_private(_run)

    def _execute_claude_fallback(self, prompt: str, sender_id: str):
        """Fallback to per-message claude -p when brain is unavailable."""
        try:
            full_prompt = self._build_full_prompt(prompt)
            system_prompt = self._build_system_prompt(user_id=sender_id)
            task_id = f"chat-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

            success, output = run_with_resume(
                full_prompt,
                task_id=task_id,
                timeout=480,
                max_retries=2,
                user_message=prompt,
                system_prompt=system_prompt,
            )

            if not output:
                output = "(no output)"
            self._send_long_text(sender_id, output)
            self._add_turn("assistant", output, chat_id=sender_id)
        except Exception as e:
            logger.error(f"Fallback execution also failed: {e}")
            self.sender.send_text(sender_id, f"执行失败: {e}")

    # ── URL Processing ──

    def _process_url(self, url: str, sender_id: str) -> str | None:
        if self.index.exists(url):
            logger.info(f"URL already saved, skipping: {url}")
            self.sender.send_text(sender_id, f"该链接已收录，无需重复保存\n{url}")
            return None

        self.sender.send_text(sender_id, f"收到，正在处理...\n{url}")

        platform = detect_platform(url)

        if platform == "feishu" and self._is_feishu_doc_url(url):
            return self._process_feishu_doc(url, sender_id)

        parser = get_parser(platform)
        logger.info(f"Parsing [{platform}]: {url}")

        parsed = parser.parse(url)
        if not parsed.content and not parsed.title:
            logger.warning(f"No content extracted from {url}")
            self.sender.send_error(sender_id, url, "无法提取内容")
            return None

        logger.info(f"Analyzing: {parsed.title}")
        analyzed = self.ai_analyzer.analyze(parsed)

        filepath = self.writer.save(analyzed)
        logger.info(f"Saved to: {filepath}")

        self.sender.send_card(
            open_id=sender_id,
            title=parsed.title or "未知标题",
            summary=analyzed.summary or "无摘要",
            tags=analyzed.tags,
            category=analyzed.category,
            url=url,
        )
        return parsed.title

    def _fetch_url_as_context(self, url: str) -> str:
        """Fetch URL content for use as Claude context (no save/analyze).

        Returns extracted text (title + content), or empty string on failure.
        Used when user quotes a message containing a URL and asks a question about it.
        """
        platform = detect_platform(url)

        # Feishu docs: use API
        if platform == "feishu" and self._is_feishu_doc_url(url):
            doc = self.doc_manager.read_document(url)
            if doc and doc.get("content"):
                title = doc.get("title", "")
                return f"标题: {title}\n\n{doc['content'][:5000]}"
            return ""

        # Other URLs: use parser
        parser = get_parser(platform)
        try:
            parsed = parser.parse(url)
            if parsed.content or parsed.title:
                title = parsed.title or ""
                content = parsed.content or ""
                return f"标题: {title}\n\n{content[:5000]}"
        except Exception as e:
            logger.warning(f"Failed to parse URL for context: {url}: {e}")
        return ""

    @staticmethod
    def _is_feishu_doc_url(url: str) -> bool:
        """Check if URL is a Feishu online document (docx/wiki/docs)."""
        return bool(re.search(r'feishu\.cn/(?:docx|docs|wiki)/', url)
                    or re.search(r'larksuite\.com/(?:docx|docs|wiki)/', url))

    def _process_feishu_doc(self, url: str, sender_id: str) -> str | None:
        """Read a Feishu doc via API, analyze it, and save to knowledge base."""
        from src.models.content import ParsedContent

        doc = self.doc_manager.read_document(url)
        if not doc or not doc.get("content"):
            logger.warning(f"Failed to read Feishu doc: {url}")
            self.sender.send_text(
                sender_id,
                "无法读取这个飞书文档 😅\n\n"
                "可能原因：文档没有共享给 bot\n\n"
                "解决方法：打开文档 → 右上角「分享」"
                "→ 搜索「BOT_知识库0302」→ 添加为「可阅读」\n\n"
                "或者把文档设为「组织内可阅读」也行",
            )
            # Notify admin about the permission request
            from src.task_scheduler import ADMIN_OPEN_ID
            if sender_id != ADMIN_OPEN_ID:
                user_name = self.contacts.get_name(sender_id) or sender_id[:12]
                self.sender.send_text(
                    ADMIN_OPEN_ID,
                    f"📋 权限请求\n\n"
                    f"用户: {user_name}\n"
                    f"文档: {url}\n\n"
                    f"bot 无权读取，需要文档所有者分享给 BOT_知识库0302。\n"
                    f"如需帮 TA 处理，你可以打开文档添加 bot 权限。",
                )
            return None

        title = doc["title"] or "未命名飞书文档"
        content = doc["content"]
        logger.info(f"Read Feishu doc: {title} ({len(content)} chars)")

        parsed = ParsedContent(
            url=url,
            platform="feishu",
            title=title,
            content=content,
            metadata={
                "doc_id": doc["doc_id"],
                "source": "feishu_doc",
                "has_images": "[IMAGE:" in content,
            },
        )

        analyzed = self.ai_analyzer.analyze(parsed)
        filepath = self.writer.save(analyzed)
        logger.info(f"Feishu doc saved to: {filepath}")

        self.sender.send_card(
            open_id=sender_id,
            title=f"📄 {title}",
            summary=analyzed.summary or "无摘要",
            tags=analyzed.tags,
            category=analyzed.category,
            url=url,
        )
        return title
