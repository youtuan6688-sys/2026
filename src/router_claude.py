"""Mixin: Claude execution (group + private) and URL processing for MessageRouter."""

import json
import logging
import re
import subprocess
from datetime import date, datetime
from pathlib import Path

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
                system_prompt = (
                    "⛔ 铁律（违反任何一条=严重失职，优先级最高）：\n"
                    "1. 严禁编造数据！你回复中的任何数字、百分比、排名、趋势，"
                    "必须100%来自用户在对话中明确提供的原始数据。"
                    "如果没有数据，就说「需要你提供XX数据才能分析」。"
                    "绝对不能猜、不能推算、不能编示例数据、不能写占位符。"
                    "违规示例（禁止）：'渗透率<8%'、'客单价¥68'、'占比65%' ← 这些如果不是来自用户文件就是编造。\n"
                    "2. 严禁空头承诺！不能说「已安排」「正在监控」「帮你拉数据」。"
                    "你只能处理对话中已有的信息。\n"
                    "3. 推测性结论必须标注「⚠️ 推测」。\n\n"
                    f"{persona}"
                )

                # 用户消息 + 上下文 → user prompt
                parts = []

                history_text = self._format_history(chat_id=sender_id)
                if history_text:
                    parts.append(history_text)

                if user_id:
                    user_ctx = self.contacts.format_context(user_id)
                    parts.append(f"对话用户信息:\n{user_ctx}")

                parts.append(f"用户消息:\n{prompt}")

                kb_context = self._query_knowledge_base(prompt)
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

                user_name = self.contacts.get_name(user_id) if user_id else ""
                self._send_long_text(
                    sender_id, output,
                    at_user_id=user_id, at_user_name=user_name,
                )
                self._add_turn("assistant", output[:500], chat_id=sender_id)

                self._buffer_conversation(
                    user_id=user_id, user_name=user_name,
                    user_msg=prompt, bot_reply=output,
                    chat_type="group", chat_id=sender_id,
                )

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

    def _execute_claude(self, prompt: str, sender_id: str):
        """Execute Claude via claude -p with RAG context and auto-resume."""
        self.sender.send_text(sender_id, f"思考中... \n> {prompt[:100]}")

        def _run():
            try:
                from scripts.claude_runner import run_with_resume

                full_prompt = self._build_full_prompt(prompt, chat_id=sender_id)
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
                self._add_turn("assistant", output[:500], chat_id=sender_id)

                user_id = sender_id if not sender_id.startswith("oc_") else ""
                user_name = self.contacts.get_name(user_id) if user_id else ""
                self._buffer_conversation(
                    user_id=user_id, user_name=user_name,
                    user_msg=prompt, bot_reply=output,
                    chat_type="p2p",
                )

            except Exception as e:
                logger.error(f"Claude execution failed: {e}", exc_info=True)
                self.error_tracker.track(
                    "claude_error", str(e), "execute_claude", "high", prompt[:200],
                )
                self.sender.send_text(sender_id, f"执行失败: {e}")

        self.gate.run_private(_run)

    def _execute_claude_fallback(self, prompt: str, sender_id: str):
        """Fallback to per-message claude -p when brain is unavailable."""
        try:
            from scripts.claude_runner import run_with_resume

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
            self._add_turn("assistant", output[:500], chat_id=sender_id)
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
            self.sender.send_error(sender_id, url, "无法读取飞书文档（请检查 bot 是否有文档权限）")
            return None

        title = doc["title"] or "未命名飞书文档"
        content = doc["content"]
        logger.info(f"Read Feishu doc: {title} ({len(content)} chars)")

        parsed = ParsedContent(
            url=url,
            platform="feishu",
            title=title,
            content=content,
            metadata={"doc_id": doc["doc_id"], "source": "feishu_doc"},
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
