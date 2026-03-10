"""Mixin: History, Phase, Todo, Memory, Context builder for MessageRouter."""

import json
import logging
import os
import re
import subprocess
from collections import deque
from datetime import date, datetime
from pathlib import Path
from src.utils.subprocess_env import CLAUDE_PATH, safe_env

logger = logging.getLogger(__name__)

HISTORY_FILE = Path("/Users/tuanyou/Happycode2026/data/chat_history.json")
TODO_FILE = Path("/Users/tuanyou/Happycode2026/data/todos.json")
PHASE_LOG_FILE = Path("/Users/tuanyou/Happycode2026/data/phase_log.json")
MEMORY_DIR = Path("/Users/tuanyou/Happycode2026/vault/memory")
GROUP_PERSONA_FILE = Path("/Users/tuanyou/Happycode2026/team/roles/group_persona/memory.md")


class ContextMixin:
    """History, phase tracking, todo, memory, and context building."""

    # ── History Management (per-chat) ──

    def _load_histories(self):
        """Load per-chat histories from disk."""
        try:
            if HISTORY_FILE.exists():
                data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    for cid, turns in data.items():
                        self._histories[cid] = deque(turns[-20:], maxlen=20)
                elif isinstance(data, list):
                    self._histories["default"] = deque(data[-20:], maxlen=20)
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
            self._histories[chat_id] = deque(maxlen=20)
        return self._histories[chat_id]

    def _add_turn(self, role: str, text: str, chat_id: str = "default",
                  user_name: str = ""):
        # Noise filter: skip low-info messages for group chats
        if chat_id.startswith("oc_") and role == "user":
            from src.group_memory import is_noise
            if is_noise(text):
                logger.debug(f"Filtered noise message in {chat_id}: {text[:20]}")
                return

        history = self._get_history(chat_id)
        entry = {
            "role": role,
            "text": text[:500],
            "time": datetime.now().strftime("%H:%M"),
        }
        if user_name and role == "user":
            entry["user"] = user_name
        history.append(entry)

        # Trigger Observer: every 10 meaningful turns, extract observations
        if chat_id.startswith("oc_"):
            self._maybe_observe(chat_id, history)

        self._save_histories()

    def _maybe_observe(self, chat_id: str, history: deque):
        """Trigger Observer agent when enough turns accumulated."""
        try:
            if not hasattr(self, '_group_memory'):
                from src.group_memory import GroupMemory
                self._group_memory = GroupMemory()

            self._group_memory.track_turn(chat_id)

            if self._group_memory.should_observe(chat_id):
                import threading
                turns = list(history)
                # Run Observer in background to not block response
                t = threading.Thread(
                    target=self._group_memory.run_observer,
                    args=(chat_id, turns),
                    daemon=True,
                )
                t.start()
                self._group_memory.reset_pending(chat_id)
                logger.info(f"Observer triggered for {chat_id} ({len(turns)} turns)")
        except Exception as e:
            logger.warning(f"Observer trigger failed: {e}")

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
            lines.append(f"[{turn.get('time', '')}] {prefix}: {turn['text']}")
        return "最近对话记录:\n" + "\n".join(lines)

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

        today = date.today().isoformat()
        memory_file = MEMORY_DIR / "decisions.md"
        with open(memory_file, "a", encoding="utf-8") as f:
            f.write(f"\n### {entry['time']}\n- {decision}\n")
        logger.info(f"Decision tracked: {decision[:80]}")

    def _start_phase(self, phase_name: str, sender_id: str):
        """Start tracking a new phase."""
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

        summary = self._generate_phase_summary(phase)
        self._phase_log["current_phase"] = None
        self._save_phase_log()

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
            env = safe_env()
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

    # ── Memory ──

    def _save_memory(self, content: str, sender_id: str):
        today = date.today().isoformat()
        memory_file = MEMORY_DIR / "decisions.md"
        with open(memory_file, "a", encoding="utf-8") as f:
            f.write(f"\n## {today}\n- {content}\n")
        logger.info(f"Memory saved: {content[:80]}")
        self.sender.send_text(sender_id, f"已记住: {content}")

    def _load_memory_context(self) -> str:
        """Load condensed memory context with smart truncation."""
        memory_parts = []
        for name in ["profile.md", "tools.md", "decisions.md", "patterns.md"]:
            path = MEMORY_DIR / name
            if path.exists():
                content = path.read_text(encoding="utf-8").strip()
                if content:
                    content = self._smart_truncate(content, max_chars=800)
                    memory_parts.append(f"- Memory: {name}: {content}")

        # Load daily summary for cross-day context
        summary_path = MEMORY_DIR / "daily_summary.md"
        if summary_path.exists():
            try:
                summary = summary_path.read_text(encoding="utf-8").strip()
                if summary:
                    memory_parts.append(f"- 近日摘要:\n{summary}")
            except Exception:
                pass

        if not memory_parts:
            return ""
        return "长期记忆摘要：\n" + "\n".join(memory_parts)

    @staticmethod
    def _smart_truncate(content: str, max_chars: int = 800) -> str:
        """Truncate by keeping the last N entries (### or ## headers), not arbitrary chars."""
        if len(content) <= max_chars:
            return content

        # Try to find section boundaries and keep most recent ones
        lines = content.split("\n")
        sections = []
        current = []
        for line in lines:
            if line.startswith("## ") or line.startswith("### "):
                if current:
                    sections.append("\n".join(current))
                current = [line]
            else:
                current.append(line)
        if current:
            sections.append("\n".join(current))

        if len(sections) <= 1:
            # No sections, fall back to tail truncation
            return "..." + content[-max_chars:]

        # Keep last N sections that fit within budget
        result = []
        total = 0
        for section in reversed(sections):
            if total + len(section) > max_chars and result:
                break
            result.insert(0, section)
            total += len(section)

        return "\n".join(result)

    # ── Context Builder ──

    def _build_full_prompt(self, prompt: str, chat_id: str = "default") -> str:
        """Build context-enriched prompt."""
        parts = []
        parts.append(f"# 用户指令（最高优先级）\n{prompt}")

        history = self._format_history(chat_id=chat_id)
        if history:
            parts.append(history)

        kb_context = self._query_knowledge_base(prompt)
        if kb_context:
            parts.append(kb_context)

        return "\n\n---\n\n".join(parts)

    def _build_system_prompt(self, user_id: str = "") -> str:
        """Build static system prompt for --append-system-prompt."""
        parts = [self._load_memory_context()]

        # Inject pending tasks for this user
        if user_id:
            tasks_context = self._get_pending_tasks_context(user_id)
            if tasks_context:
                parts.append(tasks_context)

        return "\n\n".join(p for p in parts if p)

    @staticmethod
    def _get_pending_tasks_context(user_id: str) -> str:
        """Load pending tasks for a user to inject into context."""
        try:
            from src import pending_tasks
            user_tasks = pending_tasks.get_user_pending(user_id)
            if not user_tasks:
                return ""
            lines = ["该用户有以下待跟进事项："]
            for t in user_tasks[:5]:
                due = f" (截止: {t['due_date']})" if t.get("due_date") else ""
                lines.append(f"- {t['description']}{due} (来自 {t['source_date']})")
            lines.append("如果对话涉及这些事项，主动询问进展。")
            return "\n".join(lines)
        except Exception:
            return ""

    # ── Group Chat: 小叼毛 Persona ──

    def _load_group_persona(self) -> str:
        """Load the 小叼毛 persona prompt."""
        if GROUP_PERSONA_FILE.exists():
            return GROUP_PERSONA_FILE.read_text(encoding="utf-8")
        return "你是小叼毛，一个嘴贱但靠谱的 AI 助手。雅痞风格，喜欢开玩笑但干活从不含糊。"

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
