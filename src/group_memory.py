"""Observational Memory for group chats.

Architecture (inspired by Mastra's Observational Memory):
- Observer: extracts dated observation notes from conversation batches
- Noise filter: drops low-info messages (emoji-only, <5 chars, "+1" etc.)
- Context = [observations (compressed, long-term)] + [recent raw messages (short-term)]
- 10x token reduction vs full history approach

Each group gets a JSON file in vault/memory/groups/{chat_id}.json.
"""

import json
import logging
import os
import re
import subprocess
import threading
from datetime import date, datetime
from pathlib import Path
from src.utils.subprocess_env import CLAUDE_PATH, safe_env

logger = logging.getLogger(__name__)

GROUPS_DIR = Path("/Users/tuanyou/Happycode2026/vault/memory/groups")

MAX_OBSERVATIONS = 50   # max observation notes per group
MAX_TOPICS = 30

# Noise patterns — messages matching these are filtered out
NOISE_PATTERNS = [
    re.compile(r'^[\U0001F300-\U0001FAFF\U00002702-\U000027B0\U0000FE00-\U0000FE0F\u200d]+$'),  # emoji only
    re.compile(r'^[哈嗯嘻呵啊噢哦嘿]+$'),                     # laughing/filler only
    re.compile(r'^(\+1|ok|OK|好的|收到|是的|对的|6+|666+|厉害|牛|赞|可以)$'),  # short affirmations
    re.compile(r'^\[.+\]$'),                                    # [image] [sticker] etc.
]


def is_noise(text: str) -> bool:
    """Check if a message is low-information noise.

    Filters: empty strings, emoji-only, filler chars (哈嗯嘻…),
    short affirmations (+1/ok/好的/收到…), and [sticker] markers.
    Single-char meaningful messages (好/行) are NOT filtered by length.
    """
    text = text.strip()
    if not text:
        return True
    for pattern in NOISE_PATTERNS:
        if pattern.match(text):
            return True
    return False


class GroupMemory:
    """Observational Memory manager for group chats (thread-safe)."""

    def __init__(self):
        GROUPS_DIR.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, threading.Lock] = {}
        self._locks_lock = threading.Lock()
        # Track unprocessed turns count per chat for Observer trigger
        self._pending_counts: dict[str, int] = {}

    def _get_lock(self, chat_id: str) -> threading.Lock:
        with self._locks_lock:
            if chat_id not in self._locks:
                self._locks[chat_id] = threading.Lock()
            return self._locks[chat_id]

    def _profile_path(self, chat_id: str) -> Path:
        return GROUPS_DIR / f"{chat_id}.json"

    def load(self, chat_id: str) -> dict:
        """Load a group's memory. Creates one if new."""
        path = self._profile_path(chat_id)
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                pass

        profile = {
            "chat_id": chat_id,
            "created": date.today().isoformat(),
            "observations": [],   # dated observation notes (core of observational memory)
            "topics": [],         # recurring topics with frequency
            "stats": {
                "total_messages": 0,
                "total_observations": 0,
                "last_active": None,
            },
        }
        self.save(chat_id, profile)
        return profile

    def save(self, chat_id: str, profile: dict):
        """Save group memory to disk."""
        with self._get_lock(chat_id):
            path = self._profile_path(chat_id)
            path.write_text(
                json.dumps(profile, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def increment_stats(self, chat_id: str):
        """Increment message count and update last_active."""
        profile = self.load(chat_id)
        profile["stats"]["total_messages"] += 1
        profile["stats"]["last_active"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        self.save(chat_id, profile)

    def add_observation(self, chat_id: str, observation: str):
        """Add an observation note from the Observer."""
        profile = self.load(chat_id)
        entry = {
            "note": observation[:500],
            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        profile["observations"].append(entry)
        profile["observations"] = profile["observations"][-MAX_OBSERVATIONS:]
        profile["stats"]["total_observations"] += 1
        self.save(chat_id, profile)

    def update_topics(self, chat_id: str, new_topics: list[str]):
        """Merge new topics into group memory."""
        profile = self.load(chat_id)
        existing = {t["name"] for t in profile["topics"]}
        today = date.today().isoformat()

        for topic in new_topics:
            topic = topic.strip()[:50]
            if not topic:
                continue
            if topic in existing:
                for t in profile["topics"]:
                    if t["name"] == topic:
                        t["last_seen"] = today
                        t["count"] = t.get("count", 1) + 1
                        break
            else:
                profile["topics"].append({
                    "name": topic,
                    "first_seen": today,
                    "last_seen": today,
                    "count": 1,
                })

        profile["topics"] = sorted(
            profile["topics"],
            key=lambda t: t["last_seen"],
            reverse=True,
        )[:MAX_TOPICS]
        self.save(chat_id, profile)

    def format_context(self, chat_id: str) -> str:
        """Format observations as context for prompt injection.

        This is the 'first block' of the context window:
        compressed, dated observation notes from past conversations.
        """
        profile = self.load(chat_id)
        parts = []

        # Observations (last 15 notes, ~2000 tokens)
        observations = profile.get("observations", [])[-15:]
        if observations:
            obs_lines = []
            for o in observations:
                obs_lines.append(f"[{o['date']}] {o['note']}")
            parts.append("观察笔记（历史对话压缩）：\n" + "\n".join(obs_lines))

        # Active topics
        topics = profile.get("topics", [])[:10]
        if topics:
            topic_names = [f"{t['name']}({t['count']}次)" for t in topics]
            parts.append(f"群内常聊话题：{', '.join(topic_names)}")

        if not parts:
            return ""

        return "群聊长期记忆：\n" + "\n\n".join(parts)

    # ── Observer: extract observations from conversation batch ──

    def track_turn(self, chat_id: str):
        """Track that a new turn was added. Triggers Observer at threshold."""
        count = self._pending_counts.get(chat_id, 0) + 1
        self._pending_counts[chat_id] = count

    def should_observe(self, chat_id: str) -> bool:
        """Check if enough turns accumulated to trigger Observer."""
        return self._pending_counts.get(chat_id, 0) >= 10

    def reset_pending(self, chat_id: str):
        """Reset pending count after observation."""
        self._pending_counts[chat_id] = 0

    def run_observer(self, chat_id: str, recent_turns: list[dict]):
        """Observer agent: extract observation notes from recent turns.

        Called when 10+ turns accumulated. Uses haiku for cost efficiency.
        Extracts: key facts, decisions, user preferences, action items, topics.
        """
        if len(recent_turns) < 5:
            return

        # Format turns
        lines = []
        for turn in recent_turns:
            if turn["role"] == "system":
                continue
            name = turn.get("user", "小叼毛") if turn["role"] == "user" else "小叼毛"
            lines.append(f"[{turn.get('time', '')}] {name}: {turn['text']}")

        conv_text = "\n".join(lines)

        # Load existing observations for dedup context
        profile = self.load(chat_id)
        existing_obs = profile.get("observations", [])[-5:]
        existing_text = ""
        if existing_obs:
            existing_text = (
                "\n\n已有的观察笔记（避免重复）：\n" +
                "\n".join(o["note"] for o in existing_obs)
            )

        prompt = (
            "你是一个对话观察员。从以下群聊记录中提取关键观察笔记。\n\n"
            "提取规则：\n"
            "1. 每条笔记一行，简洁扼要（20-80字）\n"
            "2. 只记录有实质内容的信息：事实、决策、用户需求、关键观点、待办事项\n"
            "3. 忽略闲聊、表情、无意义对话\n"
            "4. 不要重复已有的观察笔记\n"
            "5. 输出 3-8 条笔记，每条一行，不要编号\n"
            "6. 如果对话没有实质内容，输出「无新观察」\n\n"
            f"对话记录：\n{conv_text}"
            f"{existing_text}\n\n"
            "观察笔记："
        )

        try:
            env = safe_env()
            result = subprocess.run(
                [CLAUDE_PATH, "-p", prompt, "--model", "haiku"],
                capture_output=True, text=True, timeout=30, env=env,
            )
            output = result.stdout.strip()

            if not output or "无新观察" in output:
                logger.info(f"Observer: no new observations for {chat_id}")
                return

            # Parse observations (one per line)
            new_obs = [
                line.strip().lstrip("- ·•")
                for line in output.split("\n")
                if line.strip() and len(line.strip()) > 5
            ]

            # Extract topics from observations
            topics = []
            for obs in new_obs:
                self.add_observation(chat_id, obs)

            logger.info(f"Observer: added {len(new_obs)} observations for {chat_id}")

        except Exception as e:
            logger.warning(f"Observer failed for {chat_id}: {e}")
