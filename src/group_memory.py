"""Observational Memory for group chats.

Architecture (inspired by Mastra's Observational Memory):
- Observer: extracts dated observation notes from conversation batches
- Noise filter: drops low-info messages (emoji-only, <5 chars, "+1" etc.)
- Context = [observations (compressed, long-term)] + [recent raw messages (short-term)]
- 10x token reduction vs full history approach
- Cross-group capability sharing: observations about bot abilities propagate

Each group gets a JSON file in vault/memory/groups/{chat_id}.json.
"""

import json
import logging
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

# Keywords for cross-group capability sharing
_CAPABILITY_KEYWORDS = re.compile(r"能力|功能|可以|支持|上线|新增|升级")


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
                profile = json.loads(path.read_text(encoding="utf-8"))
                # Migrate: add group_profile if missing
                migrated = False
                if "group_profile" not in profile:
                    profile["group_profile"] = ""
                    migrated = True
                # Migrate: add pending_turns if missing
                if "pending_turns" not in profile.get("stats", {}):
                    profile.setdefault("stats", {})["pending_turns"] = 0
                    migrated = True
                if migrated:
                    self.save(chat_id, profile)
                return profile
            except Exception:
                pass

        profile = {
            "chat_id": chat_id,
            "created": date.today().isoformat(),
            "group_profile": "",      # auto-discovered group identity/theme
            "observations": [],       # dated observation notes
            "topics": [],             # recurring topics with frequency
            "stats": {
                "total_messages": 0,
                "total_observations": 0,
                "pending_turns": 0,   # persisted Observer trigger counter
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

    def increment_and_track(self, chat_id: str) -> int:
        """Increment message count + pending turns in one I/O. Returns pending count.

        Combines old increment_stats() + track_turn() to avoid double file I/O.
        """
        profile = self.load(chat_id)
        updated_stats = {
            **profile["stats"],
            "total_messages": profile["stats"].get("total_messages", 0) + 1,
            "pending_turns": profile["stats"].get("pending_turns", 0) + 1,
            "last_active": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        updated = {**profile, "stats": updated_stats}
        self.save(chat_id, updated)
        return updated_stats["pending_turns"]

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

    def update_group_profile(self, chat_id: str, profile_text: str):
        """Update group-specific identity/theme overlay (max 500 chars)."""
        data = self.load(chat_id)
        updated = {**data, "group_profile": profile_text[:500]}
        self.save(chat_id, updated)

    def format_context(self, chat_id: str) -> str:
        """Format observations as context for prompt injection.

        This is the 'first block' of the context window:
        compressed, dated observation notes from past conversations.
        """
        profile = self.load(chat_id)
        parts = []

        # Group identity (auto-discovered)
        group_profile = profile.get("group_profile", "")
        if group_profile:
            parts.append(f"群定位：{group_profile}")

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

    def format_cross_group_context(self, exclude_chat_id: str) -> str:
        """Summarize bot capabilities learned from other groups.

        Scans observations from other groups for capability-related notes.
        Returns formatted context string (max 5 notes).
        """
        capability_notes = []
        for path in GROUPS_DIR.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if data.get("chat_id") == exclude_chat_id:
                    continue
                for obs in data.get("observations", []):
                    note = obs.get("note", "")
                    if _CAPABILITY_KEYWORDS.search(note):
                        capability_notes.append(note)
            except Exception:
                continue

        if not capability_notes:
            return ""

        # Deduplicate and limit
        unique = list(dict.fromkeys(capability_notes))[:5]
        return "其他群已验证的bot能力：\n" + "\n".join(f"- {n}" for n in unique)

    # ── Observer: extract observations from conversation batch ──

    def should_observe(self, chat_id: str) -> bool:
        """Check if enough turns accumulated to trigger Observer.

        Adaptive threshold: new groups (< 5 observations) trigger at 5 turns,
        established groups trigger at 10 turns.
        """
        profile = self.load(chat_id)
        pending = profile["stats"].get("pending_turns", 0)
        total_obs = profile["stats"].get("total_observations", 0)
        threshold = 5 if total_obs < 5 else 10
        return pending >= threshold

    def reset_pending(self, chat_id: str):
        """Reset pending count after observation (persisted to JSON)."""
        profile = self.load(chat_id)
        updated_stats = {**profile["stats"], "pending_turns": 0}
        updated = {**profile, "stats": updated_stats}
        self.save(chat_id, updated)

    def run_observer(self, chat_id: str, recent_turns: list[dict]):
        """Observer agent: extract observation notes + topics from recent turns.

        Called when threshold turns accumulated. Uses haiku for cost efficiency.
        Extracts: key facts, decisions, user preferences, action items, topics,
        and optionally discovers group identity/theme.
        """
        if len(recent_turns) < 3:
            return

        # Format turns
        lines = []
        for turn in recent_turns:
            if turn.get("role") == "system":
                continue
            name = turn.get("user", "小叼毛") if turn.get("role") == "user" else "小叼毛"
            lines.append(f"[{turn.get('time', '')}] {name}: {turn.get('text', '')}")

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

        # Include group profile discovery for new/profileless groups
        has_profile = bool(profile.get("group_profile", ""))
        profile_instruction = ""
        if not has_profile:
            profile_instruction = (
                "8. 如果能判断出这个群的定位/主题（如：视频拆解群、投资讨论群），"
                "在最后一行输出「群定位：xxx」（一句话描述）\n"
            )

        prompt = (
            "你是一个对话观察员。从以下群聊记录中提取关键观察笔记和讨论话题。\n\n"
            "提取规则：\n"
            "1. 每条笔记一行，简洁扼要（20-80字）\n"
            "2. 只记录有实质内容的信息：事实、决策、用户需求、关键观点、待办事项\n"
            "3. 忽略闲聊、表情、无意义对话\n"
            "4. 不要重复已有的观察笔记\n"
            "5. 输出 3-8 条笔记，每条一行，不要编号\n"
            "6. 如果对话没有实质内容，输出「无新观察」\n"
            "7. 在笔记之后，空一行，输出「话题：」后跟逗号分隔的讨论话题（2-5个关键词）\n"
            f"{profile_instruction}\n"
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

            # Parse observations, topics, and group profile from output
            new_obs = []
            topics = []
            group_profile_text = ""

            for line in output.split("\n"):
                stripped = line.strip()
                if not stripped or len(stripped) <= 5:
                    continue

                # Detect group profile line
                if stripped.startswith("群定位：") or stripped.startswith("群定位:"):
                    sep = "：" if "：" in stripped else ":"
                    group_profile_text = stripped.split(sep, 1)[-1].strip()
                    continue

                # Detect topics line
                if stripped.startswith("话题：") or stripped.startswith("话题:"):
                    sep = "：" if "：" in stripped else ":"
                    topic_str = stripped.split(sep, 1)[-1]
                    # Split by Chinese and English commas
                    topics = [
                        t.strip() for t in re.split(r"[，,、]", topic_str)
                        if t.strip()
                    ]
                    continue

                # Regular observation
                new_obs.append(stripped.lstrip("- ·•"))

            # Save observations
            for obs in new_obs:
                self.add_observation(chat_id, obs)

            # Save topics
            if topics:
                self.update_topics(chat_id, topics)

            # Save group profile (only if not already set)
            if group_profile_text and not has_profile:
                self.update_group_profile(chat_id, group_profile_text)
                logger.info(f"Observer: discovered group profile for {chat_id}: {group_profile_text}")

            logger.info(
                f"Observer: added {len(new_obs)} observations, "
                f"{len(topics)} topics for {chat_id}"
            )

        except Exception as e:
            logger.warning(f"Observer failed for {chat_id}: {e}")
