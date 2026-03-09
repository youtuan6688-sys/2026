import json
import logging
import os
import re
import subprocess
import threading
from collections import deque
from datetime import date, datetime
from pathlib import Path

from src.utils.url_utils import extract_urls, detect_platform
from src.utils.error_tracker import ErrorTracker
from src.task_queue import TaskQueue
from src.checkpoint import CheckpointManager
from src.parsers import get_parser
from src.ai.analyzer import AIAnalyzer
from src.storage.obsidian_writer import ObsidianWriter
from src.storage.content_index import ContentIndex
from src.storage.vector_store import VectorStore
from src.feishu_sender import FeishuSender
from config.settings import settings
from src.feishu_docs import FeishuDocManager
from src.contact_memory import ContactMemory
from src.concurrency import MessageGate
from src.quota_tracker import QuotaTracker
from src import tmux_manager

logger = logging.getLogger(__name__)

HISTORY_FILE = Path("/Users/tuanyou/Happycode2026/data/chat_history.json")
TODO_FILE = Path("/Users/tuanyou/Happycode2026/data/todos.json")
PHASE_LOG_FILE = Path("/Users/tuanyou/Happycode2026/data/phase_log.json")
CLAUDE_PATH = "/Users/tuanyou/.local/bin/claude"
MEMORY_DIR = Path("/Users/tuanyou/Happycode2026/vault/memory")
GROUP_PERSONA_FILE = Path("/Users/tuanyou/Happycode2026/team/roles/group_persona/memory.md")
BUFFER_DIR = Path("/Users/tuanyou/Happycode2026/data/daily_buffer")

# Admin-only commands (private chat only)
_ADMIN_COMMANDS = frozenset((
    "/health", "/errors", "/tasks", "/checkpoint", "/cp",
    "/continue", "/resume", "/loop", "/session", "/phase",
    "/summary", "/decisions",
))


class MessageRouter:
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
        self.contacts = ContactMemory(settings)
        self.gate = MessageGate(max_group_workers=2)
        self.quota = QuotaTracker()
        BUFFER_DIR.mkdir(parents=True, exist_ok=True)
        # Per-chat history: {chat_id: deque([{role, text, time, user}], maxlen=15)}
        self._histories: dict[str, deque] = {}
        self._load_histories()
        self._phase_log = self._load_phase_log()
        self._interaction_count = 0

    # ── History Management (per-chat) ──

    def _load_histories(self):
        """Load per-chat histories from disk."""
        try:
            if HISTORY_FILE.exists():
                data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    # New format: {chat_id: [turns]}
                    for cid, turns in data.items():
                        self._histories[cid] = deque(turns[-15:], maxlen=15)
                elif isinstance(data, list):
                    # Old format: migrate to "default" key
                    self._histories["default"] = deque(data[-15:], maxlen=15)
        except Exception:
            pass

    def _save_histories(self):
        """Persist per-chat histories to disk."""
        try:
            HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
            serialized = {
                cid: list(turns) for cid, turns in self._histories.items()
            }
            HISTORY_FILE.write_text(
                json.dumps(serialized, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning(f"Failed to save history: {e}")

    def _get_history(self, chat_id: str) -> deque:
        """Get or create history for a specific chat."""
        if chat_id not in self._histories:
            self._histories[chat_id] = deque(maxlen=15)
        return self._histories[chat_id]

    # ── Phase Log Management ──

    def _load_phase_log(self) -> dict:
        try:
            if PHASE_LOG_FILE.exists():
                return json.loads(PHASE_LOG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {"current_phase": None, "phases": [], "decisions": []}

    def _save_phase_log(self):
        try:
            PHASE_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            PHASE_LOG_FILE.write_text(
                json.dumps(self._phase_log, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning(f"Failed to save phase log: {e}")

    def _track_decision(self, decision: str, context: str = ""):
        """Record a key decision with timestamp."""
        entry = {
            "decision": decision,
            "context": context[:200],
            "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        self._phase_log.setdefault("decisions", []).append(entry)
        self._save_phase_log()

        # Also persist to decisions.md
        today = date.today().isoformat()
        memory_file = MEMORY_DIR / "decisions.md"
        with open(memory_file, "a", encoding="utf-8") as f:
            f.write(f"\n### {entry['time']}\n- {decision}\n")
        logger.info(f"Decision tracked: {decision[:80]}")

    def _start_phase(self, phase_name: str, sender_id: str):
        """Start tracking a new phase."""
        # Auto-summarize previous phase if exists
        if self._phase_log.get("current_phase"):
            self._end_phase(sender_id, auto=True)

        self._phase_log["current_phase"] = {
            "name": phase_name,
            "started": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "interactions": 0,
            "key_actions": [],
        }
        self._interaction_count = 0
        self._save_phase_log()
        logger.info(f"Phase started: {phase_name}")

    def _end_phase(self, sender_id: str, auto: bool = False):
        """End current phase and generate summary."""
        phase = self._phase_log.get("current_phase")
        if not phase:
            if not auto:
                self.sender.send_text(sender_id, "当前没有进行中的阶段")
            return

        phase["ended"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        self._phase_log.setdefault("phases", []).append(phase)

        # Generate and save summary
        summary = self._generate_phase_summary(phase)
        self._phase_log["current_phase"] = None
        self._save_phase_log()

        # Persist to decisions.md
        memory_file = MEMORY_DIR / "decisions.md"
        with open(memory_file, "a", encoding="utf-8") as f:
            f.write(f"\n### 阶段总结: {phase['name']} ({phase['started']} ~ {phase['ended']})\n")
            f.write(f"{summary}\n")

        if not auto:
            self.sender.send_text(sender_id, f"阶段「{phase['name']}」已总结存档:\n\n{summary}")
        logger.info(f"Phase ended: {phase['name']}")

    def _generate_phase_summary(self, phase: dict) -> str:
        """Use Claude to generate a concise phase summary."""
        actions = phase.get("key_actions", [])
        decisions = [
            d for d in self._phase_log.get("decisions", [])
            if d.get("time", "") >= phase.get("started", "")
        ]

        prompt = (
            "你是一个项目记忆管理器。根据以下信息，生成一个简洁的阶段总结（3-5行），"
            "重点记录：完成了什么、做了什么决策、遗留什么问题。\n\n"
            f"阶段名称: {phase['name']}\n"
            f"开始时间: {phase['started']}\n"
            f"交互次数: {phase.get('interactions', 0)}\n"
            f"关键操作: {json.dumps(actions[-10:], ensure_ascii=False)}\n"
            f"决策记录: {json.dumps(decisions[-5:], ensure_ascii=False)}\n\n"
            "只输出总结，不要额外解释。"
        )
        try:
            env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
            result = subprocess.run(
                [CLAUDE_PATH, "-p", prompt],
                capture_output=True, text=True, timeout=60, env=env,
            )
            return result.stdout.strip() if result.stdout.strip() else "（自动总结生成失败）"
        except Exception as e:
            logger.warning(f"Phase summary generation failed: {e}")
            actions_text = "\n".join(f"- {a}" for a in actions[-5:])
            return f"完成操作:\n{actions_text}" if actions_text else "（无记录）"

    def _track_action(self, action: str):
        """Track a key action in the current phase."""
        phase = self._phase_log.get("current_phase")
        if phase:
            phase.setdefault("key_actions", []).append(action)
            phase["interactions"] = phase.get("interactions", 0) + 1
            self._save_phase_log()

    def _add_turn(self, role: str, text: str, chat_id: str = "default",
                  user_name: str = ""):
        history = self._get_history(chat_id)
        entry = {
            "role": role,
            "text": text[:500],
            "time": datetime.now().strftime("%H:%M"),
        }
        if user_name and role == "user":
            entry["user"] = user_name
        history.append(entry)
        self._save_histories()

    def _format_history(self, chat_id: str = "default") -> str:
        history = self._get_history(chat_id)
        if not history:
            return ""
        lines = []
        for turn in history:
            if turn["role"] == "user":
                name = turn.get("user", "用户")
                prefix = name
            else:
                prefix = "助手"
            lines.append(f"[{turn.get('time','')}] {prefix}: {turn['text']}")
        return "最近对话记录:\n" + "\n".join(lines)

    # ── Smart Intent Classification ──

    def _classify_intent(self, text: str) -> str:
        """Classify user intent using haiku (auto-degrades to DeepSeek)."""
        prompt = (
            "分类以下消息的意图，只输出一个词：\n"
            "- remember: 用户想让你记住偏好、规则、习惯\n"
            "- todo: 用户在管理任务（添加、查看、完成待办）\n"
            "- query: 用户在问问题、闲聊、讨论\n"
            "- execute: 用户想让你执行某个操作（写代码、搜索、分析等）\n"
            "- loop: 用户想启动、停止或管理定时循环任务（如定时检查、定时汇报）\n"
            "- session: 用户想查看、管理运行中的会话（查看状态、停止会话、查看输出）\n"
            "- document: 用户想操作飞书在线文档（创建、读取、写入、分享文档）\n\n"
            f"消息: {text[:200]}\n意图:"
        )
        try:
            output = self.quota.call_claude(prompt, "haiku", timeout=30)
            intent = output.lower().split()[0] if output else "query"
            if intent in ("remember", "todo", "query", "execute", "loop", "session", "document"):
                return intent
        except Exception as e:
            logger.warning(f"Intent classification failed: {e}")
            self.error_tracker.track("intent_classify_error", str(e), "classify_intent", "low", text[:100])
        return "query"

    # ── RAG: Knowledge Base Query ──

    def _query_knowledge_base(self, text: str) -> str:
        """Query vector store for relevant articles to inject as context."""
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

    # ── Todo Management ──

    def _load_todos(self) -> list[dict]:
        try:
            if TODO_FILE.exists():
                return json.loads(TODO_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
        return []

    def _save_todos(self, todos: list[dict]):
        TODO_FILE.parent.mkdir(parents=True, exist_ok=True)
        TODO_FILE.write_text(
            json.dumps(todos, ensure_ascii=False, indent=2), encoding="utf-8",
        )

    def _handle_todo(self, text: str, sender_id: str):
        """Handle todo commands: /todo, /todo add ..., /todo done N, /todo del N."""
        stripped = text.strip()
        todos = self._load_todos()

        if stripped == "/todo" or stripped == "/todo list":
            if not todos:
                self.sender.send_text(sender_id, "待办清单为空")
                return
            lines = []
            for i, t in enumerate(todos, 1):
                check = "[x]" if t.get("done") else "[ ]"
                due = f" (截止: {t['due']})" if t.get("due") else ""
                lines.append(f"{check} {i}. {t['text']}{due}")
            self.sender.send_text(sender_id, "待办清单：\n" + "\n".join(lines))
            return

        if stripped.startswith("/todo add "):
            task_text = stripped[10:].strip()
            todos.append({"text": task_text, "done": False, "created": date.today().isoformat()})
            self._save_todos(todos)
            self.sender.send_text(sender_id, f"已添加待办: {task_text}")
            return

        if stripped.startswith("/todo done "):
            try:
                idx = int(stripped[11:].strip()) - 1
                todos[idx]["done"] = True
                self._save_todos(todos)
                self.sender.send_text(sender_id, f"已完成: {todos[idx]['text']}")
            except (ValueError, IndexError):
                self.sender.send_text(sender_id, "无效序号")
            return

        if stripped.startswith("/todo del "):
            try:
                idx = int(stripped[10:].strip()) - 1
                removed = todos.pop(idx)
                self._save_todos(todos)
                self.sender.send_text(sender_id, f"已删除: {removed['text']}")
            except (ValueError, IndexError):
                self.sender.send_text(sender_id, "无效序号")
            return

        # Natural language todo — let Claude parse it
        self._add_turn("user", stripped, chat_id=sender_id)
        self._execute_claude(stripped, sender_id)

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

        # Resolve the actual user's open_id
        user_id = sender_open_id or sender_id
        is_group = chat_type == "group"

        # Update contact memory (track last_seen, message_count)
        self.contacts.touch(user_id)

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
            # Group only supports: /help, /search, /doc, /kb, /status, and free chat
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

            # Group: URL → save to knowledge base (same as private)
            urls = extract_urls(text)
            if urls:
                saved_titles = []
                for url in urls:
                    try:
                        title = self._process_url(url, sender_id)
                        if title:
                            saved_titles.append(title)
                    except Exception as e:
                        logger.error(f"Failed to process URL {url}: {e}", exc_info=True)
                        self.sender.send_error(sender_id, url, str(e)[:200])
                return

            # Group: all other messages → 小叼毛 persona chat
            user_name = self.contacts.get_name(user_id) if user_id else ""
            self._add_turn("user", stripped, chat_id=sender_id, user_name=user_name)
            self._execute_claude_group(stripped, sender_id, user_id=user_id)
            return

        # ══════════════════════════════════════
        # ── Private chat: full admin mode ──
        # ══════════════════════════════════════

        # Explicit commands always take priority
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
                self._add_turn("user", f"[发送了链接] {summary}", chat_id=sender_id)
                self._add_turn("assistant", f"已保存到知识库: {summary}", chat_id=sender_id)
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
            # Try to split at a newline boundary
            split_pos = text.rfind("\n", 0, max_len)
            if split_pos < max_len // 2:
                # No good newline break, split at max_len
                split_pos = max_len
            chunks.append(text[:split_pos])
            text = text[split_pos:].lstrip("\n")
        return chunks

    def _send_long_text(self, sender_id: str, text: str,
                        at_user_id: str = "", at_user_name: str = ""):
        """Send text, splitting into multiple messages if needed.

        If at_user_id is provided and sender_id is a group chat (oc_),
        the first chunk will @mention the user.
        """
        chunks = self._split_text(text)
        for i, chunk in enumerate(chunks):
            if len(chunks) > 1:
                chunk = f"[{i + 1}/{len(chunks)}]\n{chunk}"
            # @mention the user in the first chunk of group replies
            if i == 0 and at_user_id and sender_id.startswith("oc_"):
                self.sender.send_text_at(
                    sender_id, chunk, at_user_id, at_user_name,
                )
            else:
                self.sender.send_text(sender_id, chunk)

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

    # ── Tmux Session Management ──

    def _handle_loop(self, text: str, sender_id: str):
        """Handle /loop commands: start or stop a loop session."""
        parts = text.strip().split(None, 2)
        # /loop stop
        if len(parts) >= 2 and parts[1] == "stop":
            name = parts[2] if len(parts) > 2 else "loop"
            if tmux_manager.stop_session(name):
                self.sender.send_text(sender_id, f"已停止循环会话: {name}")
            else:
                self.sender.send_text(sender_id, f"停止会话失败: {name}")
            return

        # /loop <interval> [prompt]  — e.g., /loop 60m 检查系统状态
        if len(parts) < 2:
            self.sender.send_text(
                sender_id,
                "用法:\n/loop <间隔> [提示] — 启动定时任务 (如: /loop 60m 检查状态)\n/loop stop [名称] — 停止",
            )
            return

        interval = parts[1]
        name = f"loop-{interval}"

        if tmux_manager.start_loop_session(name=name, interval=interval):
            msg = f"已启动循环会话 {name}，间隔 {interval}"
            # If there's a custom prompt, send it after loop starts
            if len(parts) > 2:
                import time
                time.sleep(3)
                tmux_manager.send_keys(name, parts[2])
                msg += f"\n任务: {parts[2]}"
            self.sender.send_text(sender_id, msg)
        else:
            self.sender.send_text(sender_id, f"启动失败，可能已有同名会话: {name}")

    def _handle_session(self, text: str, sender_id: str):
        """Handle /session commands: list, stop, output."""
        parts = text.strip().split(None, 2)
        subcmd = parts[1] if len(parts) > 1 else "list"

        if subcmd == "list":
            status = tmux_manager.format_status()
            self.sender.send_text(sender_id, status)
            return

        if subcmd == "stop" and len(parts) > 2:
            name = parts[2]
            if tmux_manager.stop_session(name):
                self.sender.send_text(sender_id, f"已停止: {name}")
            else:
                self.sender.send_text(sender_id, f"停止失败: {name}")
            return

        if subcmd == "output" and len(parts) > 2:
            name = parts[2]
            output = tmux_manager.capture_output(name, lines=30)
            self._send_long_text(sender_id, f"会话 {name} 最近输出:\n\n{output}")
            return

        self.sender.send_text(
            sender_id,
            "用法:\n/session list — 查看会话\n/session stop <名称> — 停止\n/session output <名称> — 查看输出",
        )

    def _handle_loop_natural(self, text: str, sender_id: str):
        """Handle natural language loop requests via Claude."""
        # Let Claude parse the natural language and decide the action
        sessions = tmux_manager.list_sessions()
        session_info = ", ".join(s.name for s in sessions) if sessions else "无"

        prompt = (
            "用户想管理定时循环任务。根据消息判断操作，只输出一行 JSON：\n"
            '- 启动: {"action":"start","interval":"60m","task":"任务描述"}\n'
            '- 停止: {"action":"stop","name":"会话名"}\n'
            '- 查看: {"action":"list"}\n\n'
            f"当前运行的会话: {session_info}\n"
            f"消息: {text}"
        )
        try:
            raw = self.quota.call_claude(prompt, "haiku", timeout=30)
            parsed = json.loads(raw.strip("`").strip())
            action = parsed.get("action", "list")

            if action == "start":
                interval = parsed.get("interval", "60m")
                task = parsed.get("task", "")
                name = f"loop-{interval}"
                if tmux_manager.start_loop_session(name=name, interval=interval):
                    msg = f"已启动循环任务，间隔 {interval}"
                    if task:
                        import time
                        time.sleep(3)
                        tmux_manager.send_keys(name, task)
                        msg += f"\n任务: {task}"
                    self.sender.send_text(sender_id, msg)
                else:
                    self.sender.send_text(sender_id, f"启动失败，可能已有同名会话: {name}")
            elif action == "stop":
                name = parsed.get("name", "loop-60m")
                if tmux_manager.stop_session(name):
                    self.sender.send_text(sender_id, f"已停止: {name}")
                else:
                    self.sender.send_text(sender_id, f"停止失败: {name}")
            else:
                status = tmux_manager.format_status()
                self.sender.send_text(sender_id, status)
        except Exception as e:
            logger.warning(f"Natural loop handling failed: {e}")
            self.sender.send_text(sender_id, f"没理解你的意思，试试: /loop 60m 任务描述")

    def _handle_session_natural(self, text: str, sender_id: str):
        """Handle natural language session management via Claude."""
        sessions = tmux_manager.list_sessions()
        session_info = ", ".join(f"{s.name}({'活跃' if s.alive else '停止'})" for s in sessions) if sessions else "无"

        prompt = (
            "用户想管理运行中的会话。根据消息判断操作，只输出一行 JSON：\n"
            '- 查看: {"action":"list"}\n'
            '- 停止: {"action":"stop","name":"会话名"}\n'
            '- 查看输出: {"action":"output","name":"会话名"}\n\n'
            f"当前会话: {session_info}\n"
            f"消息: {text}"
        )
        try:
            raw = self.quota.call_claude(prompt, "haiku", timeout=30)
            parsed = json.loads(raw.strip("`").strip())
            action = parsed.get("action", "list")

            if action == "stop":
                name = parsed.get("name", "")
                if name and tmux_manager.stop_session(name):
                    self.sender.send_text(sender_id, f"已停止: {name}")
                else:
                    self.sender.send_text(sender_id, f"停止失败: {name}")
            elif action == "output":
                name = parsed.get("name", "")
                if name:
                    output = tmux_manager.capture_output(name, lines=30)
                    self._send_long_text(sender_id, f"会话 {name} 最近输出:\n\n{output}")
                else:
                    self.sender.send_text(sender_id, "请指定会话名称")
            else:
                status = tmux_manager.format_status()
                self.sender.send_text(sender_id, status)
        except Exception as e:
            logger.warning(f"Natural session handling failed: {e}")
            status = tmux_manager.format_status()
            self.sender.send_text(sender_id, status)

    # ── Feishu Document Management ──

    def _handle_doc(self, text: str, sender_id: str):
        """Handle /doc commands: read, create, write, share."""
        parts = text.strip().split(None, 2)
        subcmd = parts[1] if len(parts) > 1 else "help"

        if subcmd == "read" and len(parts) > 2:
            url_or_id = parts[2].strip()
            result = self.doc_manager.read_document(url_or_id)
            if result:
                content = result["content"][:3000] if result["content"] else "(空文档)"
                self._send_long_text(
                    sender_id,
                    f"文档: {result['title']}\nID: {result['doc_id']}\n\n{content}",
                )
            else:
                self.sender.send_text(sender_id, "读取文档失败，请检查链接或权限")
            return

        if subcmd == "create" and len(parts) > 2:
            title = parts[2].strip()
            result = self.doc_manager.create_document(title)
            if result:
                self.sender.send_text(
                    sender_id,
                    f"文档已创建:\n标题: {title}\nID: {result['doc_id']}\n链接: {result['url']}",
                )
            else:
                self.sender.send_text(sender_id, "创建文档失败")
            return

        if subcmd == "write" and len(parts) > 2:
            # /doc write <doc_id_or_url> <content>
            rest = parts[2].strip()
            write_parts = rest.split(None, 1)
            if len(write_parts) < 2:
                self.sender.send_text(sender_id, "用法: /doc write <文档ID或链接> <内容>")
                return
            doc_ref, content = write_parts
            if self.doc_manager.write_content(doc_ref, content):
                self.sender.send_text(sender_id, f"已写入文档 {doc_ref}")
            else:
                self.sender.send_text(sender_id, "写入失败，请检查权限")
            return

        if subcmd == "share" and len(parts) > 2:
            # /doc share <doc_id_or_url> <member_id>
            rest = parts[2].strip()
            share_parts = rest.split(None, 1)
            if len(share_parts) < 2:
                self.sender.send_text(sender_id, "用法: /doc share <文档ID或链接> <用户ID或邮箱>")
                return
            doc_ref, member = share_parts
            # Auto-detect member type
            member_type = "email" if "@" in member else "openid"
            if self.doc_manager.share_document(doc_ref, member, member_type=member_type):
                self.sender.send_text(sender_id, f"已分享文档给 {member}")
            else:
                self.sender.send_text(sender_id, "分享失败，请检查权限")
            return

        # Help
        self.sender.send_text(
            sender_id,
            "飞书文档命令:\n"
            "/doc read <链接或ID> — 读取文档内容\n"
            "/doc create <标题> — 创建新文档\n"
            "/doc write <ID或链接> <内容> — 写入内容到文档\n"
            "/doc share <ID或链接> <邮箱或open_id> — 分享文档",
        )

    def _handle_doc_natural(self, text: str, sender_id: str):
        """Handle natural language document requests via haiku."""
        prompt = (
            "用户想操作飞书在线文档。根据消息判断操作，只输出一行 JSON：\n"
            '- 读取: {"action":"read","target":"文档链接或ID"}\n'
            '- 创建: {"action":"create","title":"文档标题","content":"可选内容"}\n'
            '- 写入: {"action":"write","target":"文档链接或ID","content":"要写的内容"}\n'
            '- 创建并写入: {"action":"create_write","title":"标题","content":"内容"}\n'
            '- 分享: {"action":"share","target":"文档链接或ID","member":"邮箱或open_id"}\n\n'
            f"消息: {text}"
        )
        try:
            raw = self.quota.call_claude(prompt, "haiku", timeout=30)
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            parsed = json.loads(raw)
            action = parsed.get("action", "")

            if action == "read":
                target = parsed.get("target", "")
                if not target:
                    self.sender.send_text(sender_id, "请提供文档链接或ID")
                    return
                doc = self.doc_manager.read_document(target)
                if doc:
                    content = doc["content"][:3000] if doc["content"] else "(空文档)"
                    self._send_long_text(
                        sender_id,
                        f"文档: {doc['title']}\n\n{content}",
                    )
                else:
                    self.sender.send_text(sender_id, "读取文档失败")

            elif action == "create":
                title = parsed.get("title", "未命名文档")
                content = parsed.get("content", "")
                if content:
                    doc = self.doc_manager.create_and_write(title, content)
                else:
                    doc = self.doc_manager.create_document(title)
                if doc:
                    self.sender.send_text(
                        sender_id,
                        f"文档已创建:\n标题: {title}\n链接: {doc['url']}",
                    )
                else:
                    self.sender.send_text(sender_id, "创建文档失败")

            elif action == "create_write":
                title = parsed.get("title", "未命名文档")
                content = parsed.get("content", "")
                doc = self.doc_manager.create_and_write(title, content)
                if doc:
                    self.sender.send_text(
                        sender_id,
                        f"文档已创建并写入:\n标题: {title}\n链接: {doc['url']}",
                    )
                else:
                    self.sender.send_text(sender_id, "创建文档失败")

            elif action == "write":
                target = parsed.get("target", "")
                content = parsed.get("content", "")
                if not target or not content:
                    self.sender.send_text(sender_id, "请提供文档ID和要写入的内容")
                    return
                if self.doc_manager.write_content(target, content):
                    self.sender.send_text(sender_id, f"已写入文档")
                else:
                    self.sender.send_text(sender_id, "写入失败")

            elif action == "share":
                target = parsed.get("target", "")
                member = parsed.get("member", "")
                if not target or not member:
                    self.sender.send_text(sender_id, "请提供文档ID和要分享的用户")
                    return
                member_type = "email" if "@" in member else "openid"
                if self.doc_manager.share_document(target, member, member_type=member_type):
                    self.sender.send_text(sender_id, f"已分享文档给 {member}")
                else:
                    self.sender.send_text(sender_id, "分享失败")
            else:
                self.sender.send_text(sender_id, "没理解你的文档操作，试试: /doc help")

        except Exception as e:
            logger.warning(f"Natural doc handling failed: {e}")
            self.sender.send_text(sender_id, f"文档操作解析失败，试试命令: /doc help")

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
        # Knowledge base stats
        article_count = 0
        vault_dir = Path("/Users/tuanyou/Happycode2026/vault")
        for subdir in ["articles", "social", "docs"]:
            d = vault_dir / subdir
            if d.exists():
                article_count += len([f for f in d.iterdir() if f.suffix == ".md"])

        # Pending todos
        todos = self._load_todos()
        pending = sum(1 for t in todos if not t.get("done"))
        done = sum(1 for t in todos if t.get("done"))

        # Phase info
        phase = self._phase_log.get("current_phase")
        phase_text = f"当前阶段: {phase['name']}" if phase else "无进行中的阶段"

        # Decision count
        decision_count = len(self._phase_log.get("decisions", []))

        # Memory files
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

        # Index stats
        try:
            index_count = self.index.count() if hasattr(self.index, "count") else "N/A"
        except Exception:
            index_count = "N/A"

        # Vector store stats
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

            # Next pending tasks
            pending = [t for t in q.get_all() if t.status == "pending"]
            pending.sort(key=lambda t: t.priority)
            if pending:
                lines.append("\nNext tasks:")
                for t in pending[:5]:
                    lines.append(f"  [{t.priority}] {t.title}")

            # Recent history
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
        """Resume execution from the last checkpoint.

        Tries to re-read the full original prompt from the saved prompt file.
        Falls back to checkpoint-based resume if the prompt file is missing.
        """
        checkpoint = self.checkpoint_manager.load()
        if not checkpoint:
            self.sender.send_text(sender_id, "没有可续接的任务检查点")
            return

        # Try to load the full original prompt from disk
        from scripts.claude_runner import _load_prompt
        original_prompt = _load_prompt(checkpoint.task_id)

        if not original_prompt:
            # Fallback to checkpoint-based resume
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
            env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
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

        # Recent unresolved
        recent = self.error_tracker.get_recent(5, unresolved_only=True)
        if recent:
            lines.append("\nRecent unresolved:")
            for e in recent:
                ts = e.get("timestamp", "")[:16]
                lines.append(f"  [{e.get('severity', '').upper()}] {ts} {e.get('error_type')} - {e.get('message', '')[:80]}")

        # Recurring patterns
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

    # ── Memory ──

    def _save_memory(self, content: str, sender_id: str):
        today = date.today().isoformat()
        memory_file = MEMORY_DIR / "decisions.md"
        with open(memory_file, "a", encoding="utf-8") as f:
            f.write(f"\n## {today}\n- {content}\n")
        logger.info(f"Memory saved: {content[:80]}")
        self.sender.send_text(sender_id, f"已记住: {content}")

    def _load_memory_context(self) -> str:
        """Load condensed memory context. Only include essential info to save prompt space."""
        memory_parts = []
        for name in ["profile.md", "tools.md", "decisions.md", "patterns.md"]:
            path = MEMORY_DIR / name
            if path.exists():
                content = path.read_text(encoding="utf-8").strip()
                if content:
                    # Truncate each file to ~800 chars to prevent prompt bloat
                    if len(content) > 800:
                        content = content[:800] + "\n...(truncated)"
                    memory_parts.append(f"- Memory: {name}: {content}")
        if not memory_parts:
            return ""
        return "长期记忆摘要：\n" + "\n".join(memory_parts)

    # ── Context Builder ──

    def _build_full_prompt(self, prompt: str, chat_id: str = "default") -> str:
        """Build context-enriched prompt. User instruction goes FIRST to prevent being buried.

        Static memory context is NOT included here — it goes to --append-system-prompt
        via _build_system_prompt() to reduce prompt bloat.
        """
        parts = []

        # 1. USER INSTRUCTION FIRST — most important, must not be buried
        parts.append(f"# 用户指令（最高优先级）\n{prompt}")

        # 2. Recent conversation history (compact)
        history = self._format_history(chat_id=chat_id)
        if history:
            parts.append(history)

        # 3. RAG context (only if relevant)
        kb_context = self._query_knowledge_base(prompt)
        if kb_context:
            parts.append(kb_context)

        return "\n\n---\n\n".join(parts)

    def _build_system_prompt(self) -> str:
        """Build static system prompt for --append-system-prompt.

        This is sent once per session and persists across --resume retries,
        so it doesn't need to be repeated in every prompt.
        """
        return self._load_memory_context()

    # ── Group Chat: 小叼毛 Persona ──

    def _load_group_persona(self) -> str:
        """Load the 小叼毛 persona prompt."""
        if GROUP_PERSONA_FILE.exists():
            return GROUP_PERSONA_FILE.read_text(encoding="utf-8")
        return "你是小叼毛，一个嘴贱但靠谱的 AI 助手。雅痞风格，喜欢开玩笑但干活从不含糊。"

    def _show_group_help(self, sender_id: str):
        self.sender.send_text(
            sender_id,
            "yo，小叼毛在此 🫡 能帮你干这些活儿：\n\n"
            "直接 @我 说话 — 聊天、问问题、写文案、翻译、头脑风暴\n"
            "/search <关键词> — 搜知识库\n"
            "/doc read <链接> — 读飞书文档\n"
            "/doc create <标题> — 创建飞书文档\n"
            "/kb — 知识库统计\n"
            "发链接 — 自动解析保存\n\n"
            "其他骚操作？私聊老板去，我在群里权限有限 😏",
        )

    def _execute_claude_group(self, prompt: str, sender_id: str,
                              user_id: str = ""):
        """Execute Claude with 小叼毛 persona for group chat."""

        def _run():
            try:
                persona = self._load_group_persona()

                # Build group prompt: persona + history + user context + message + knowledge
                parts = [
                    f"# 你的人设\n{persona}",
                ]

                # Inject recent conversation history for context continuity
                history_text = self._format_history(chat_id=sender_id)
                if history_text:
                    parts.append(f"\n# {history_text}")

                # Inject user context so 小叼毛 knows who's talking
                if user_id:
                    user_ctx = self.contacts.format_context(user_id)
                    parts.append(f"\n# 对话用户信息\n{user_ctx}")

                parts.append(f"\n# 用户消息\n{prompt}")

                kb_context = self._query_knowledge_base(prompt)
                if kb_context:
                    parts.append(f"\n{kb_context}")

                full_prompt = "\n\n".join(parts)

                output = self.quota.call_claude(
                    full_prompt, "sonnet", timeout=120,
                    extra_args=["--permission-mode", "auto", "--verbose"],
                )

                if not output:
                    output = "啊这...我刚走神了，再说一遍？"

                # Reply with @mention so the asker gets notified
                user_name = self.contacts.get_name(user_id) if user_id else ""
                self._send_long_text(
                    sender_id, output,
                    at_user_id=user_id, at_user_name=user_name,
                )
                self._add_turn("assistant", output[:500], chat_id=sender_id)

                # Buffer for daily evolution (no real-time opus calls)
                self._buffer_conversation(
                    user_id=user_id, user_name=user_name,
                    user_msg=prompt, bot_reply=output,
                    chat_type="group",
                )

            except subprocess.TimeoutExpired:
                self.sender.send_text(sender_id, "想太久了脑子转不过来，换个简单点的问法？")
            except Exception as e:
                logger.error(f"Group chat execution failed: {e}", exc_info=True)
                self.sender.send_text(sender_id, "出了点小状况，等会儿再试试")

        # Group chat: bounded concurrency, queued when pool is full
        if not self.gate.run_group(_run, sender_id):
            self.sender.send_text(sender_id, "消息太多啦，排队中...等前面的处理完再来 🫠")

    def _buffer_conversation(self, user_id: str, user_name: str,
                             user_msg: str, bot_reply: str,
                             chat_type: str = "p2p"):
        """Buffer conversation for daily opus evolution (no real-time AI calls)."""
        entry = {
            "ts": datetime.now().isoformat(),
            "user_id": user_id,
            "user_name": user_name,
            "user_msg": user_msg[:500],
            "bot_reply": bot_reply[:1000],
            "chat_type": chat_type,
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
        """Execute Claude via claude -p with RAG context and auto-resume.

        Private chat uses dedicated gate slot (never queued behind group tasks).
        """
        self.sender.send_text(sender_id, f"思考中... \n> {prompt[:100]}")

        def _run():
            try:
                from scripts.claude_runner import run_with_resume

                full_prompt = self._build_full_prompt(prompt, chat_id=sender_id)
                system_prompt = self._build_system_prompt()
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

                # Buffer for daily evolution (no real-time opus calls)
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

        # Private chat: dedicated slot, always runs immediately
        self.gate.run_private(_run)

    def _execute_claude_fallback(self, prompt: str, sender_id: str):
        """Fallback to per-message claude -p when brain is unavailable."""
        try:
            from scripts.claude_runner import run_with_resume

            full_prompt = self._build_full_prompt(prompt)
            system_prompt = self._build_system_prompt()
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

        # Feishu online docs: use FeishuDocManager instead of generic parser
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

        # Wrap as ParsedContent to reuse existing analysis pipeline
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

    # ── Proactive Features (called by cron) ──

    def get_pending_reminders(self) -> list[str]:
        """Get overdue or due-today todos for proactive notification."""
        todos = self._load_todos()
        today = date.today().isoformat()
        reminders = []
        for t in todos:
            if t.get("done"):
                continue
            due = t.get("due", "")
            if due and due <= today:
                reminders.append(f"到期: {t['text']} (截止: {due})")
            elif not due:
                created = t.get("created", "")
                if created and created < today:
                    reminders.append(f"待办: {t['text']}")
        return reminders
