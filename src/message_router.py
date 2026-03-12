"""MessageRouter — main message routing class.

Split into mixins for maintainability:
- router_intent.py   — Intent classification, regex patterns, RAG query
- router_context.py   — History, Phase, Todo, Memory, Context builder
- router_commands.py  — Help, Status, Health, Errors, KB, Contacts, Decisions
- router_sessions.py  — Tmux/Loop/Session, Scheduled task approval
- router_docs.py      — Feishu document handling
- router_files.py     — File analysis, quoted messages, stock queries
- router_claude.py    — Claude execution (group + private), URL processing
"""

import logging
from collections import deque
from pathlib import Path

from src.utils.url_utils import extract_urls, detect_music_platform
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

from src.router_intent import IntentMixin
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


class MessageRouter(IntentMixin, ContextMixin, CommandsMixin, SessionsMixin,
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
        self._music_handler = None
        self._image_handler = None
        self._video_handler = None
        self._workspace_handler = None

    # ── Feature Handlers (lazy init) ──

    def _get_music_handler(self):
        if self._music_handler is None:
            from src.music.handler import MusicHandler
            self._music_handler = MusicHandler(self.sender)
        return self._music_handler

    def _get_image_handler(self):
        if self._image_handler is None:
            from src.image.handler import ImageHandler
            self._image_handler = ImageHandler(self.sender)
        return self._image_handler

    def _get_video_handler(self):
        if self._video_handler is None:
            from src.video.handler import VideoHandler
            self._video_handler = VideoHandler(self.sender)
        return self._video_handler

    def _get_workspace_handler(self):
        if self._workspace_handler is None:
            from src.workspace_handler import WorkspaceHandler
            self._workspace_handler = WorkspaceHandler(
                self.sender, self.contacts, self.gate,
            )
        return self._workspace_handler

    # Video analysis groups — auto-analyze video URLs dropped in these groups
    _VIDEO_GROUP_IDS = frozenset((
        "oc_d42807f92f606dc0b448f16c6c42fece",  # 爆款视频拆解实验室 (旧)
        "oc_494f1c2a811f65378639269461ba312f",  # 爆款视频拆解 (新·陈维玺)
    ))

    def _is_video_group(self, chat_id: str) -> bool:
        return chat_id in self._VIDEO_GROUP_IDS

    # ══════════════════════════════════════
    # ── Main Entry Point ──
    # ══════════════════════════════════════

    def handle_message(self, sender_id: str, text: str, raw_message=None,
                       chat_type: str = "p2p", sender_open_id: str = ""):
        """Route messages with smart intent detection."""
        stripped = text.strip()

        # Quoted/reply message — check BEFORE empty-text guard so that
        # "@bot" replies to a previous message still get context-aware handling
        parent_id = getattr(raw_message, "parent_id", None) if raw_message else None
        if parent_id:
            root_id = getattr(raw_message, "root_id", None)
            # For empty text replies, set a default prompt so Claude knows to continue
            reply_text = stripped or "继续"
            if self._handle_quoted_message(sender_id, reply_text, parent_id, chat_type, sender_open_id, root_id=root_id):
                return

        if not stripped:
            # Group @mention with no text and no reply context → friendly nudge
            if chat_type == "group":
                self.sender.send_text(
                    sender_id,
                    "叫我干嘛？直接说事儿，或者发 /help 看看我能干啥 😏",
                )
            return

        # File message handling
        if stripped.startswith("[file_msg:"):
            self._handle_file_message(sender_id, stripped, chat_type, sender_open_id)
            return

        # Resolve actual user
        user_id = sender_open_id or sender_id
        is_group = chat_type == "group"
        self.contacts.touch(user_id)

        # Pending task completion detection
        if self._TASK_DONE_PATTERNS.match(stripped):
            if self._try_complete_pending_task(user_id, stripped, sender_id):
                return

        # Pattern disable detection
        disable_match = self._DISABLE_PATTERN_RE.search(stripped)
        if disable_match:
            action_map = {"分析": "excel_auto_analyze", "拆分": "file_split_preference"}
            action = action_map.get(disable_match.group(2), disable_match.group(2))
            self.contacts.disable_pattern(user_id, action=action)
            self.sender.send_text(sender_id, f"好的，已关闭自动{disable_match.group(2)} ✅")
            return

        # Dispatch to group or private handler
        if is_group:
            self._route_group(stripped, text, sender_id, user_id)
        else:
            self._route_private(stripped, text, sender_id)

    # ══════════════════════════════════════
    # ── Quoted Message Handler ──
    # ══════════════════════════════════════

    def _handle_quoted_message(self, sender_id: str, stripped: str,
                               parent_id: str, chat_type: str,
                               sender_open_id: str, *,
                               root_id: str | None = None) -> bool:
        """Handle quoted/reply messages. Returns True if handled.

        When root_id differs from parent_id, fetches the thread root
        to provide richer conversation context.
        """
        if self._handle_quoted_file(sender_id, stripped, parent_id, chat_type, sender_open_id):
            return True

        # Not a file quote — try to extract quoted text for context
        quoted_text = self._extract_quoted_text(parent_id)
        if not quoted_text:
            return False

        logger.info(f"Quoted text prepended: {quoted_text[:80]}")

        # Thread context: if root differs from parent, fetch root for full picture
        thread_context = ""
        if root_id and root_id != parent_id:
            root_text = self._extract_quoted_text(root_id)
            if root_text:
                # Sanitize: strip bracket-prefixed injections from user content
                root_text_safe = root_text.lstrip().removeprefix("[").removeprefix("]")
                thread_context = f"[话题起始消息] {root_text_safe[:300]}\n\n"
                logger.info(f"Thread root added: {root_text_safe[:60]}")

        # Check if quoted text contains URLs — fetch content first
        quoted_urls = extract_urls(quoted_text)
        fetched_context = ""
        if quoted_urls:
            for qurl in quoted_urls[:1]:
                try:
                    article = self._fetch_url_as_context(qurl)
                    if article:
                        fetched_context = article
                except Exception as e:
                    logger.warning(f"Failed to fetch quoted URL {qurl}: {e}")

        if fetched_context:
            enriched = (
                f"{thread_context}"
                f"[引用消息] {quoted_text}\n\n"
                f"[引用消息中的文章内容]\n{fetched_context}\n\n"
                f"用户问题: {stripped}"
            )
        else:
            history_context = self._search_conversation_history(quoted_text[:200])
            if history_context:
                enriched = (
                    f"{thread_context}"
                    f"[引用消息] {quoted_text}\n\n"
                    f"{history_context}\n\n"
                    f"用户回复: {stripped}"
                )
            else:
                enriched = f"{thread_context}[引用消息] {quoted_text}\n\n用户回复: {stripped}"

        user_id = sender_open_id or sender_id
        self.contacts.touch(user_id)
        self._add_turn("user", enriched[:500], chat_id=sender_id)
        if chat_type == "group":
            self._execute_claude_group(enriched, sender_id, user_id=user_id)
        else:
            self._execute_claude(enriched, sender_id)
        return True

    # ══════════════════════════════════════
    # ── Group Chat Router ──
    # ══════════════════════════════════════

    def _route_group(self, stripped: str, text: str, sender_id: str,
                     user_id: str) -> None:
        """Route group chat messages."""
        # Block admin commands in groups
        cmd_word = stripped.split()[0] if stripped.startswith("/") else ""
        if cmd_word and any(stripped.startswith(ac) for ac in _ADMIN_COMMANDS):
            self.sender.send_text(
                sender_id,
                "这活儿得找我老板私聊，我在群里只管嘴炮和干活 😏",
            )
            return

        # Explicit commands
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
                sender_id, "小叼毛在线，随时待命。有啥活儿尽管吩咐 🫡",
            )
            return
        if stripped.startswith("/stock"):
            self._handle_stock_query(stripped, sender_id)
            return
        if stripped.startswith("/image"):
            self._get_image_handler().handle_command(stripped, sender_id)
            return
        if stripped.startswith("/video"):
            self._get_video_handler().handle_command(stripped, sender_id)
            return
        if stripped.startswith("/work"):
            if self._is_video_group(sender_id):
                task_text = stripped[5:].strip() if len(stripped) > 5 else ""
                self._get_workspace_handler().handle_work(
                    task_text, sender_id, user_id,
                )
            else:
                self.sender.send_text(
                    sender_id, "/work 命令仅限视频拆解群使用 🔒"
                )
            return

        # URLs → music detection + video auto-analyze + knowledge base save
        urls = extract_urls(text)
        if urls:
            from src.video.handler import is_video_url
            remaining_urls = []
            for url in urls:
                music_platform = detect_music_platform(url)
                if music_platform:
                    self._get_music_handler().handle_music_url(url, music_platform, sender_id)
                elif is_video_url(url) and self._is_video_group(sender_id):
                    self._get_video_handler().auto_analyze(url, sender_id)
                else:
                    remaining_urls.append(url)
            for url in remaining_urls:
                try:
                    self._process_url(url, sender_id)
                except Exception as e:
                    logger.error(f"Failed to process URL {url}: {e}", exc_info=True)
                    self.sender.send_error(sender_id, url, str(e)[:200])
            return

        # Admin approval/rejection for pending tasks
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

        # Schedule requests → ask admin for approval
        if self._SCHEDULE_PATTERNS.search(stripped):
            self._handle_schedule_request(stripped, sender_id, user_id)
            return

        # Reject unknown slash commands
        if stripped.startswith("/") and not stripped.startswith("//"):
            self.sender.send_text(
                sender_id,
                f"群里不支持 {stripped.split()[0]} 命令，发 /help 看看我能干啥 😏",
            )
            return

        # Default: 小叼毛 persona chat
        user_name = self.contacts.get_name(user_id) if user_id else ""
        self._add_turn("user", stripped, chat_id=sender_id, user_name=user_name)
        self._execute_claude_group(stripped, sender_id, user_id=user_id)

    # ══════════════════════════════════════
    # ── Private Chat Router ──
    # ══════════════════════════════════════

    def _route_private(self, stripped: str, text: str, sender_id: str) -> None:
        """Route private chat messages (full admin mode)."""
        from src.long_task import LongTaskManager

        ltm = LongTaskManager()

        # Pause any active long task when user sends a new message
        # (unless it's a continuation shortcut)
        if stripped not in ("继续", "继续执行"):
            active = ltm.get_active(sender_id)
            if active:
                ltm.pause(reason="user_new_message")
                logger.info(f"Long task {active.task_id} paused by new user message")

        # Non-slash resume shortcuts
        if stripped in ("继续", "继续执行"):
            self._resume_from_checkpoint(sender_id)
            return

        # Slash commands
        if stripped.startswith("/"):
            if self._dispatch_private_command(stripped, sender_id):
                return

        # URL mode
        urls = extract_urls(text)
        if urls:
            if self._handle_urls_private(stripped, urls, sender_id):
                return

        # Detect multi-step task signal
        is_long_task = ltm.is_multi_step_request(stripped)
        if is_long_task:
            logger.info(f"Multi-step task detected: {stripped[:80]}")

        # All non-command, non-URL messages → Claude Code with RAG + memory + history
        self._add_turn("user", stripped, chat_id=sender_id)
        self._execute_claude(stripped, sender_id, is_long_task=is_long_task)

    def _dispatch_private_command(self, stripped: str, sender_id: str) -> bool:
        """Dispatch explicit slash commands. Returns True if handled."""
        _CMD_MAP = {
            "/help": lambda: self._show_help(sender_id),
            "/status": lambda: self._show_status(sender_id),
            "/kb": lambda: self._show_kb_stats(sender_id),
            "/errors": lambda: self._show_errors(sender_id),
            "/health": lambda: self._show_health(sender_id),
            "/contacts": lambda: self._show_contacts(sender_id),
            "/decisions": lambda: self._show_recent_decisions(sender_id),
        }

        # Exact match commands
        if stripped in _CMD_MAP:
            _CMD_MAP[stripped]()
            return True
        if stripped in ("/checkpoint", "/cp"):
            self._show_checkpoint(sender_id)
            return True
        if stripped in ("/continue", "/resume"):
            self._resume_from_checkpoint(sender_id)
            return True
        if stripped == "/summary" or stripped == "/phase end":
            self._end_phase(sender_id)
            return True
        if stripped == "/tasks":
            self._show_tasks(sender_id)
            return True

        # Prefix match commands
        if stripped.startswith("/stock"):
            self._handle_stock_query(stripped, sender_id)
            return True
        if stripped.startswith("/remember ") or stripped.startswith("/r "):
            self._save_memory(stripped.split(" ", 1)[1].strip(), sender_id)
            return True
        if stripped.startswith("/todo"):
            self._handle_todo(stripped, sender_id)
            return True
        if stripped.startswith("/phase "):
            phase_name = stripped[7:].strip()
            self._start_phase(phase_name, sender_id)
            self.sender.send_text(sender_id, f"开始新阶段: {phase_name}")
            return True
        if stripped.startswith("/search "):
            self._search_knowledge_base(stripped[8:].strip(), sender_id)
            return True
        if stripped.startswith("/loop"):
            self._handle_loop(stripped, sender_id)
            return True
        if stripped.startswith("/session"):
            self._handle_session(stripped, sender_id)
            return True
        if stripped.startswith("/doc"):
            self._handle_doc(stripped, sender_id)
            return True
        if stripped.startswith("/music"):
            self._get_music_handler().handle_command(stripped, sender_id)
            return True
        if stripped.startswith("/image"):
            self._get_image_handler().handle_command(stripped, sender_id)
            return True
        if stripped.startswith("/video"):
            self._get_video_handler().handle_command(stripped, sender_id)
            return True

        return False

    # ══════════════════════════════════════
    # ── Private URL Handler ──
    # ══════════════════════════════════════

    def _handle_urls_private(self, stripped: str, urls: list[str],
                             sender_id: str) -> bool:
        """Handle URLs in private chat. Returns True if fully handled."""
        # Separate music vs non-music URLs
        music_urls = []
        non_music_urls = []
        for url in urls:
            music_platform = detect_music_platform(url)
            if music_platform:
                music_urls.append((url, music_platform))
            else:
                non_music_urls.append(url)

        # Process music URLs
        for url, platform in music_urls:
            self._get_music_handler().handle_music_url(url, platform, sender_id)

        # If only music URLs, we're done
        if not non_music_urls:
            return True

        # Check for extra text beyond URLs (instructions)
        text_without_urls = stripped
        for url in urls:
            text_without_urls = text_without_urls.replace(url, "").strip()
        has_instructions = len(text_without_urls) > 5

        # Save non-music URLs to knowledge base
        saved_titles = []
        for url in non_music_urls:
            try:
                title = self._process_url(url, sender_id)
                if title:
                    saved_titles.append(title)
            except Exception as e:
                logger.error(f"Failed to process URL {url}: {e}", exc_info=True)
                self.error_tracker.track(
                    "url_parse_error", str(e), "url_processing", "medium", url,
                )
                self.sender.send_error(sender_id, url, str(e)[:200])

        if saved_titles:
            summary = "、".join(saved_titles[:3])
            url_list = " ".join(non_music_urls[:3])
            self._add_turn("user", f"[发送了链接] {url_list} → {summary}", chat_id=sender_id)
            self._add_turn("assistant", f"已保存到知识库: {summary}", chat_id=sender_id)

        # If message has instructions beyond URLs, send to Claude
        if has_instructions:
            logger.info(f"URL + instructions detected: {text_without_urls[:80]}")
            self._execute_claude(stripped, sender_id)
        return True

    # ══════════════════════════════════════
    # ── Pending Task Completion ──
    # ══════════════════════════════════════

    def _try_complete_pending_task(self, user_id: str, text: str,
                                    sender_id: str) -> bool:
        """Check if user is confirming a pending task completion."""
        from src import pending_tasks

        user_tasks = pending_tasks.get_user_pending(user_id)
        if not user_tasks:
            return False

        dismiss_words = {"不用了", "算了", "取消吧"}
        is_dismiss = text.strip() in dismiss_words

        if len(user_tasks) == 1:
            task = user_tasks[0]
            if is_dismiss:
                pending_tasks.mark_dismissed(task["task_id"])
                self.sender.send_text(sender_id, f"好的，已取消跟进：{task['description']}")
            else:
                pending_tasks.mark_done(task["task_id"])
                self.sender.send_text(sender_id, f"👍 已标记完成：{task['description']}")
            return True

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
