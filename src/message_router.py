"""MessageRouter — main message routing class.

Split into mixins for maintainability:
- router_context.py  — History, Phase, Todo, Memory, Context builder
- router_commands.py — Help, Status, Health, Errors, KB, Contacts, Decisions
- router_sessions.py — Tmux/Loop/Session, Scheduled task approval
- router_docs.py     — Feishu document handling
- router_files.py    — File analysis, quoted messages, stock queries
- router_claude.py   — Claude execution (group + private), URL processing
"""

import json
import logging
import re
from collections import deque
from pathlib import Path

from src.utils.url_utils import extract_urls
from src.utils.error_tracker import ErrorTracker
from src.checkpoint import CheckpointManager
from src.ai.analyzer import AIAnalyzer
from src.storage.obsidian_writer import ObsidianWriter
from src.storage.content_index import ContentIndex
from src.storage.vector_store import VectorStore
from src.feishu_sender import FeishuSender
from config.settings import settings
from src.feishu_docs import FeishuDocManager
from src.feishu_bitable import FeishuBitableManager
from src.feishu_sheets import FeishuSheetsManager
from src.contact_memory import ContactMemory
from src.concurrency import MessageGate
from src.quota_tracker import QuotaTracker
from src import task_scheduler

from src.router_context import ContextMixin
from src.router_commands import CommandsMixin
from src.router_sessions import SessionsMixin
from src.router_docs import DocsMixin
from src.router_files import FilesMixin
from src.router_claude import ClaudeMixin, BUFFER_DIR
from src.workflow_engine import WorkflowEngine

logger = logging.getLogger(__name__)

# Admin-only commands (private chat only)
_ADMIN_COMMANDS = frozenset((
    "/health", "/errors", "/tasks", "/checkpoint", "/cp",
    "/continue", "/resume", "/loop", "/session", "/phase",
    "/summary", "/decisions",
))


class MessageRouter(ContextMixin, CommandsMixin, SessionsMixin,
                    DocsMixin, FilesMixin, ClaudeMixin):
    def __init__(self, ai_analyzer: AIAnalyzer, writer: ObsidianWriter,
                 index: ContentIndex, sender: FeishuSender,
                 vector_store: VectorStore,
                 error_tracker: ErrorTracker | None = None,
                 checkpoint_manager: CheckpointManager | None = None):
        self.ai_analyzer = ai_analyzer
        self.writer = writer
        self.index = index
        self.sender = sender
        self.vector_store = vector_store
        self.error_tracker = error_tracker or ErrorTracker()
        self.checkpoint_manager = checkpoint_manager or CheckpointManager()
        self.doc_manager = FeishuDocManager(settings)
        self.bitable_manager = FeishuBitableManager(settings)
        self.sheets_manager = FeishuSheetsManager(settings)
        self.contacts = ContactMemory(settings)
        self.gate = MessageGate(max_group_workers=2)
        self.quota = QuotaTracker()
        self.workflow_engine = WorkflowEngine()
        BUFFER_DIR.mkdir(parents=True, exist_ok=True)
        # Per-chat history: {chat_id: deque([{role, text, time, user}], maxlen=15)}
        self._histories: dict[str, deque] = {}
        self._load_histories()
        self._phase_log = self._load_phase_log()
        self._interaction_count = 0

    # ── Intent Classification (rule-based, no subprocess) ──

    _REMEMBER_PATTERNS = re.compile(
        r"(记住.{0,4}(?:这|我|以后|偏好|习惯|规则)|"
        r"记一下|别忘了?|帮我记|"
        r"(?:偏好|习惯|规则).*(?:设|改|调)|设置.*(?:为|成))"
    )
    # If message looks like a task with instructions, don't classify as remember
    # Note: "帮我记" is excluded — it's a remember intent, not a task
    _TASK_SIGNAL_PATTERNS = re.compile(
        r"(希望你|帮我[^记]|请你|你来|你去|你帮|做一下|做完|执行|分析|学习.*了解|结合)"
    )
    _TODO_PATTERNS = re.compile(
        r"(提醒我.{2,}|加个.{2,}|添加.*任务|完成.*任务)"
    )
    # Questions about todos should NOT create new todos
    _TODO_QUERY_PATTERNS = re.compile(
        r"(还有.{0,4}(待办|任务|代办)|待办.*吗|任务.*呢|有.*任务吗|清单.*呢)"
    )
    _LOOP_PATTERNS = re.compile(
        r"(定时|循环|每隔|loop|cron|定期|巡检|监控.*(?:启动|停止|状态))"
    )
    _SCHEDULE_PATTERNS = re.compile(
        r"(每\s*\d+\s*分钟|每\s*\d+\s*小时|每天|每日|每周|定时.*(?:查|看|监控|提醒|发|推)"
        r"|帮我.*(?:盯|监控|提醒|定时)|(?:分钟|小时).*(?:一次|提醒|推送|查看))"
    )
    _APPROVAL_PATTERNS = re.compile(
        r"^(同意|批准|approve|ok|可以|行|准了|通过|yes)\s*$", re.IGNORECASE
    )
    _REJECT_PATTERNS = re.compile(
        r"^(拒绝|不行|reject|no|否|算了|不用)\s*$", re.IGNORECASE
    )
    _SESSION_PATTERNS = re.compile(
        r"(会话|session|运行中|停止.*会话|查看.*输出|后台.*任务)"
    )
    _DOCUMENT_PATTERNS = re.compile(
        r"(创建文档|写入文档|读取文档|分享文档|打开文档|编辑文档|操作文档|"
        r"文档操作|列.*云文档|"
        r"创建.*多维表格|操作.*多维表格|多维表格.{0,6}(记录|数据|查看|读取)|bitable|"
        r"创建.*电子表格|操作.*电子表格|电子表格.{0,6}(数据|查看|读取)|spreadsheet|"
        r"/doc\b|/sheets?\b|"
        r"feishu\.cn/(?:docx|docs|wiki|sheets|base)/[A-Za-z0-9])"
    )
    _TASK_DONE_PATTERNS = re.compile(
        r"^(搞定了|完成了|做完了|弄好了|ok了|已完成|done|不用了|算了|取消吧)\s*$",
        re.IGNORECASE,
    )
    _DISABLE_PATTERN_RE = re.compile(
        r"(不要自动|关闭自动|别自动|停止自动)(分析|拆分|处理|执行|回复)",
    )

    def _classify_intent(self, text: str) -> str:
        """Classify user intent using keyword rules (no subprocess call)."""
        t = text[:200].lower()
        # Remember only if no task signals — long messages with instructions
        # like "学习了解，结合你做的..." should go to Claude, not memory
        if self._REMEMBER_PATTERNS.search(t):
            if not self._TASK_SIGNAL_PATTERNS.search(t):
                return "remember"
        # Questions about todos → query (not create)
        if self._TODO_QUERY_PATTERNS.search(t):
            return "query"
        if self._TODO_PATTERNS.search(t):
            return "todo"
        if self._LOOP_PATTERNS.search(t):
            return "loop"
        if self._SESSION_PATTERNS.search(t):
            return "session"
        if self._DOCUMENT_PATTERNS.search(t):
            return "document"
        return "query"

    # ── RAG: Knowledge Base Query ──

    _SKIP_RAG_PATTERNS = re.compile(
        r"^(你好|hi|hello|ok|好的|嗯嗯?|哈哈+|谢谢|感谢|666+|牛|👍|😂|😄|🤣|"
        r"行|收到|了解|明白|是的|对的|可以|没问题|好嘞|好哒|"
        r"好的[，,]?谢谢[！!]?|谢谢[啦了哈]?[！!]?|辛苦了?|"
        r"哈哈哈+|笑死|太强了|厉害|6+|赞|对|嘿|哦|噢|啊|呵呵"
        r")[！!。.～~]?$",
        re.IGNORECASE,
    )

    def _query_knowledge_base(self, text: str, chat_type: str = "p2p") -> str:
        """Query vector store for relevant articles to inject as context."""
        min_len = 10 if chat_type == "group" else 6
        if len(text) < min_len or self._SKIP_RAG_PATTERNS.match(text.strip()):
            return ""
        try:
            results = self.vector_store.query_similar(text, top_k=3)
            if not results:
                return ""
            context_parts = []
            for r in results:
                if r.get("distance", 1) < 0.7:
                    title = r.get("title", "")
                    summary = r.get("summary", "")
                    if title or summary:
                        context_parts.append(f"- {title}: {summary}")
            if not context_parts:
                return ""
            return "相关知识库内容：\n" + "\n".join(context_parts)
        except Exception as e:
            logger.warning(f"Knowledge base query failed: {e}")
            self.error_tracker.track("kb_query_error", str(e), "query_knowledge_base", "medium", text[:100])
            return ""

    # ── Main Message Router ──

    def handle_message(self, sender_id: str, text: str, raw_message=None,
                       chat_type: str = "p2p", sender_open_id: str = ""):
        """Route messages with smart intent detection.

        Args:
            sender_id: reply target (open_id for p2p, chat_id for group)
            text: message text
            raw_message: raw Feishu message object
            chat_type: "p2p" or "group"
            sender_open_id: actual sender's open_id (same as sender_id for p2p)
        """
        stripped = text.strip()
        if not stripped:
            return

        # ── File message handling ──
        if stripped.startswith("[file_msg:"):
            self._handle_file_message(sender_id, stripped, chat_type, sender_open_id)
            return

        # ── Quoted/reply message: check if it references a file or text ──
        parent_id = getattr(raw_message, "parent_id", None) if raw_message else None
        if parent_id:
            if self._handle_quoted_file(sender_id, stripped, parent_id, chat_type, sender_open_id):
                return
            # Not a file quote — try to extract quoted text for context
            quoted_text = self._extract_quoted_text(parent_id)
            if quoted_text:
                enriched = f"[引用消息] {quoted_text}\n\n用户回复: {stripped}"
                logger.info(f"Quoted text prepended: {quoted_text[:80]}")
                # Quoted messages with URLs or complex context → full Claude execution
                # Skip simple intent classification which misroutes these
                user_id = sender_open_id or sender_id
                self.contacts.touch(user_id)
                self._add_turn("user", enriched[:500], chat_id=sender_id)
                if chat_type == "group":
                    self._execute_claude_group(enriched, sender_id, user_id=user_id)
                else:
                    self._execute_claude(enriched, sender_id)
                return

        # Resolve the actual user's open_id
        user_id = sender_open_id or sender_id
        is_group = chat_type == "group"

        # Update contact memory (track last_seen, message_count)
        self.contacts.touch(user_id)

        # ── Pending task completion detection ──
        if self._TASK_DONE_PATTERNS.match(stripped):
            if self._try_complete_pending_task(user_id, stripped, sender_id):
                return

        # ── Pattern disable detection ──
        disable_match = self._DISABLE_PATTERN_RE.search(stripped)
        if disable_match:
            action_map = {
                "分析": "excel_auto_analyze",
                "拆分": "file_split_preference",
            }
            action = action_map.get(disable_match.group(2), disable_match.group(2))
            self.contacts.disable_pattern(user_id, action=action)
            self.sender.send_text(sender_id, f"好的，已关闭自动{disable_match.group(2)} ✅")
            return

        # ── Group chat: block admin commands ──
        if is_group:
            cmd_word = stripped.split()[0] if stripped.startswith("/") else ""
            if cmd_word and any(stripped.startswith(ac) for ac in _ADMIN_COMMANDS):
                self.sender.send_text(
                    sender_id,
                    "这活儿得找我老板私聊，我在群里只管嘴炮和干活 😏",
                )
                return

        # ── Group chat: simplified routing ──
        if is_group:
            if stripped == "/help":
                self._show_group_help(sender_id)
                return
            if stripped.startswith("/search "):
                self._search_knowledge_base(stripped[8:].strip(), sender_id)
                return
            if stripped.startswith("/doc"):
                self._handle_doc(stripped, sender_id)
                return
            if stripped == "/kb":
                self._show_kb_stats(sender_id)
                return
            if stripped == "/status":
                self.sender.send_text(
                    sender_id,
                    "小叼毛在线，随时待命。有啥活儿尽管吩咐 🫡",
                )
                return
            if stripped.startswith("/stock"):
                self._handle_stock_query(stripped, sender_id)
                return

            # Group: URL → save to knowledge base
            urls = extract_urls(text)
            if urls:
                for url in urls:
                    try:
                        self._process_url(url, sender_id)
                    except Exception as e:
                        logger.error(f"Failed to process URL {url}: {e}", exc_info=True)
                        self.sender.send_error(sender_id, url, str(e)[:200])
                return

            # Group: admin approval/rejection for pending tasks
            if user_id == task_scheduler.ADMIN_OPEN_ID:
                if self._APPROVAL_PATTERNS.match(stripped):
                    self._handle_task_approval(sender_id)
                    return
                if self._REJECT_PATTERNS.match(stripped):
                    self._handle_task_rejection(sender_id)
                    return
                if stripped == "/tasks":
                    self.sender.send_text(sender_id, task_scheduler.format_tasks())
                    return

            # Group: detect schedule requests → ask admin for approval
            if self._SCHEDULE_PATTERNS.search(stripped):
                self._handle_schedule_request(stripped, sender_id, user_id)
                return

            # Group: reject unknown slash commands
            if stripped.startswith("/") and not stripped.startswith("//"):
                self.sender.send_text(
                    sender_id,
                    f"群里不支持 {stripped.split()[0]} 命令，发 /help 看看我能干啥 😏",
                )
                return

            # Group: all other messages → 小叼毛 persona chat
            user_name = self.contacts.get_name(user_id) if user_id else ""
            self._add_turn("user", stripped, chat_id=sender_id, user_name=user_name)
            self._execute_claude_group(stripped, sender_id, user_id=user_id)
            return

        # ══════════════════════════════════════
        # ── Private chat: full admin mode ──
        # ══════════════════════════════════════

        if stripped.startswith("/stock"):
            self._handle_stock_query(stripped, sender_id)
            return
        if stripped.startswith("/remember ") or stripped.startswith("/r "):
            self._save_memory(stripped.split(" ", 1)[1].strip(), sender_id)
            return
        if stripped.startswith("/todo"):
            self._handle_todo(stripped, sender_id)
            return
        if stripped == "/summary" or stripped == "/phase end":
            self._end_phase(sender_id)
            return
        if stripped.startswith("/phase "):
            phase_name = stripped[7:].strip()
            self._start_phase(phase_name, sender_id)
            self.sender.send_text(sender_id, f"开始新阶段: {phase_name}")
            return
        if stripped == "/decisions":
            self._show_recent_decisions(sender_id)
            return
        if stripped == "/help":
            self._show_help(sender_id)
            return
        if stripped == "/status":
            self._show_status(sender_id)
            return
        if stripped.startswith("/search "):
            self._search_knowledge_base(stripped[8:].strip(), sender_id)
            return
        if stripped == "/kb":
            self._show_kb_stats(sender_id)
            return
        if stripped == "/errors":
            self._show_errors(sender_id)
            return
        if stripped == "/health":
            self._show_health(sender_id)
            return
        if stripped == "/tasks":
            self._show_tasks(sender_id)
            return
        if stripped == "/checkpoint" or stripped == "/cp":
            self._show_checkpoint(sender_id)
            return
        if stripped in ("/continue", "/resume", "继续", "继续执行"):
            self._resume_from_checkpoint(sender_id)
            return
        if stripped == "/contacts":
            self._show_contacts(sender_id)
            return
        if stripped.startswith("/loop"):
            self._handle_loop(stripped, sender_id)
            return
        if stripped.startswith("/session"):
            self._handle_session(stripped, sender_id)
            return
        if stripped.startswith("/doc"):
            self._handle_doc(stripped, sender_id)
            return

        # URL mode: if message contains URLs, save them
        urls = extract_urls(text)
        if urls:
            # Check if there's extra text beyond the URLs (instructions)
            text_without_urls = stripped
            for url in urls:
                text_without_urls = text_without_urls.replace(url, "").strip()
            has_instructions = len(text_without_urls) > 5

            saved_titles = []
            for url in urls:
                try:
                    title = self._process_url(url, sender_id)
                    if title:
                        saved_titles.append(title)
                except Exception as e:
                    logger.error(f"Failed to process URL {url}: {e}", exc_info=True)
                    self.error_tracker.track("url_parse_error", str(e), "url_processing", "medium", url)
                    self.sender.send_error(sender_id, url, str(e)[:200])
            if saved_titles:
                summary = "、".join(saved_titles[:3])
                url_list = " ".join(urls[:3])
                self._add_turn("user", f"[发送了链接] {url_list} → {summary}", chat_id=sender_id)
                self._add_turn("assistant", f"已保存到知识库: {summary}", chat_id=sender_id)

            # If message has instructions beyond URLs, send everything to Claude
            if has_instructions:
                logger.info(f"URL + instructions detected, forwarding to Claude: {text_without_urls[:80]}")
                self._execute_claude(stripped, sender_id)
                return
            return

        # Smart intent classification
        intent = self._classify_intent(stripped)
        logger.info(f"Intent: {intent} | Message: {stripped[:80]}")

        if intent == "remember":
            self._save_memory(stripped, sender_id)
            return
        if intent == "todo":
            self._handle_todo(f"/todo add {stripped}", sender_id)
            return
        if intent == "loop":
            self._handle_loop_natural(stripped, sender_id)
            return
        if intent == "session":
            self._handle_session_natural(stripped, sender_id)
            return
        if intent == "document":
            self._handle_doc_natural(stripped, sender_id)
            return

        # Default: Claude Code with RAG + memory + history
        self._add_turn("user", stripped, chat_id=sender_id)
        self._execute_claude(stripped, sender_id)

    # ── Pending Task Completion ──

    def _try_complete_pending_task(self, user_id: str, text: str,
                                    sender_id: str) -> bool:
        """Check if user is confirming a pending task completion.

        Returns True if a task was matched and handled.
        """
        from src import pending_tasks

        user_tasks = pending_tasks.get_user_pending(user_id)
        if not user_tasks:
            return False

        # Determine action: done or dismissed
        dismiss_words = {"不用了", "算了", "取消吧"}
        is_dismiss = text.strip() in dismiss_words

        # If user has exactly one pending task, auto-match it
        if len(user_tasks) == 1:
            task = user_tasks[0]
            if is_dismiss:
                pending_tasks.mark_dismissed(task["task_id"])
                self.sender.send_text(sender_id, f"好的，已取消跟进：{task['description']}")
            else:
                pending_tasks.mark_done(task["task_id"])
                self.sender.send_text(sender_id, f"👍 已标记完成：{task['description']}")
            return True

        # Multiple tasks: mark the most recent one (last reminded or last created)
        # Sort by reminded_at desc, then created_at desc
        sorted_tasks = sorted(
            user_tasks,
            key=lambda t: t.get("reminded_at") or t.get("created_at", ""),
            reverse=True,
        )
        task = sorted_tasks[0]
        if is_dismiss:
            pending_tasks.mark_dismissed(task["task_id"])
            self.sender.send_text(sender_id, f"好的，已取消跟进：{task['description']}")
        else:
            pending_tasks.mark_done(task["task_id"])
            remaining = len(user_tasks) - 1
            extra = f"\n（还有 {remaining} 条待跟进）" if remaining > 0 else ""
            self.sender.send_text(sender_id, f"👍 已标记完成：{task['description']}{extra}")
        return True
