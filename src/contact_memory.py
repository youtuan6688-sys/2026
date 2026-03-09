"""Per-user contact memory — remember names, preferences, and conversation history.

Each contact gets a JSON file in vault/memory/contacts/{open_id}.json.
The bot loads this before responding, making conversations personal and alive.
"""

import json
import logging
import threading
from datetime import date, datetime
from pathlib import Path

import lark_oapi as lark
from lark_oapi.api.contact.v3 import GetUserRequest

from config.settings import Settings

logger = logging.getLogger(__name__)

CONTACTS_DIR = Path("/Users/tuanyou/Happycode2026/vault/memory/contacts")


class ContactMemory:
    """Manage per-user memory files (thread-safe)."""

    def __init__(self, settings: Settings):
        CONTACTS_DIR.mkdir(parents=True, exist_ok=True)
        self._client = lark.Client.builder() \
            .app_id(settings.feishu_app_id) \
            .app_secret(settings.feishu_app_secret) \
            .log_level(lark.LogLevel.WARNING) \
            .build()
        # Cache to avoid repeated API calls within a session
        self._name_cache: dict[str, str] = {}
        # Per-user locks to prevent concurrent writes to the same file
        self._locks: dict[str, threading.Lock] = {}
        self._locks_lock = threading.Lock()

    def _get_lock(self, open_id: str) -> threading.Lock:
        with self._locks_lock:
            if open_id not in self._locks:
                self._locks[open_id] = threading.Lock()
            return self._locks[open_id]

    def _profile_path(self, open_id: str) -> Path:
        return CONTACTS_DIR / f"{open_id}.json"

    def load(self, open_id: str) -> dict:
        """Load a contact's profile. Creates one if new."""
        path = self._profile_path(open_id)
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                pass

        # New contact — fetch name from Feishu and create profile
        name = self._fetch_name(open_id)
        profile = {
            "open_id": open_id,
            "name": name,
            "nickname": "",
            "first_seen": date.today().isoformat(),
            "last_seen": date.today().isoformat(),
            "message_count": 0,
            "traits": [],
            "preferences": [],
            "topics": [],
            "notes": [],
        }
        self.save(open_id, profile)
        logger.info(f"New contact created: {name} ({open_id})")
        return profile

    def save(self, open_id: str, profile: dict):
        """Save a contact's profile (thread-safe)."""
        lock = self._get_lock(open_id)
        with lock:
            path = self._profile_path(open_id)
            path.write_text(
                json.dumps(profile, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def touch(self, open_id: str):
        """Update last_seen and message_count."""
        profile = self.load(open_id)
        profile["last_seen"] = date.today().isoformat()
        profile["message_count"] = profile.get("message_count", 0) + 1
        self.save(open_id, profile)

    def get_name(self, open_id: str) -> str:
        """Get display name for a user (cached)."""
        if open_id in self._name_cache:
            return self._name_cache[open_id]
        profile = self.load(open_id)
        name = profile.get("nickname") or profile.get("name") or "未知用户"
        self._name_cache[open_id] = name
        return name

    def add_note(self, open_id: str, note: str):
        """Add a note about this contact."""
        profile = self.load(open_id)
        notes = profile.get("notes", [])
        # Keep last 20 notes
        notes.append({
            "date": date.today().isoformat(),
            "text": note[:200],
        })
        profile["notes"] = notes[-20:]
        self.save(open_id, profile)

    def update_from_conversation(self, open_id: str, extracted: dict):
        """Update profile with extracted info from conversation.

        extracted may contain: nickname, traits, preferences, topics
        """
        profile = self.load(open_id)
        changed = False

        if extracted.get("nickname") and not profile.get("nickname"):
            profile["nickname"] = extracted["nickname"]
            self._name_cache[open_id] = extracted["nickname"]
            changed = True

        for field in ("traits", "preferences", "topics"):
            new_items = extracted.get(field, [])
            if new_items:
                existing = set(profile.get(field, []))
                for item in new_items:
                    if item and item not in existing:
                        profile.setdefault(field, []).append(item)
                        changed = True
                # Keep lists bounded
                profile[field] = profile[field][-15:]

        if changed:
            self.save(open_id, profile)
            logger.info(f"Contact updated: {profile.get('name')} - {extracted}")

    def _log_path(self, open_id: str) -> Path:
        return CONTACTS_DIR / f"{open_id}_log.md"

    def append_log(self, open_id: str, summary: str):
        """Append a daily conversation summary to the user's log."""
        lock = self._get_lock(open_id)
        with lock:
            path = self._log_path(open_id)
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"\n{summary}")

    def get_recent_log(self, open_id: str, max_chars: int = 800) -> str:
        """Get recent conversation history summaries for this user."""
        path = self._log_path(open_id)
        if not path.exists():
            return ""
        try:
            text = path.read_text(encoding="utf-8").strip()
            if not text:
                return ""
            # Return the tail (most recent entries)
            if len(text) > max_chars:
                text = "..." + text[-max_chars:]
            return text
        except Exception:
            return ""

    def format_context(self, open_id: str) -> str:
        """Format contact info + history as context for prompt injection."""
        profile = self.load(open_id)
        name = profile.get("nickname") or profile.get("name") or "未知"
        parts = [f"当前对话用户: {name}"]

        if profile.get("traits"):
            parts.append(f"特点: {', '.join(profile['traits'][-5:])}")
        if profile.get("preferences"):
            parts.append(f"偏好: {', '.join(profile['preferences'][-5:])}")
        if profile.get("topics"):
            parts.append(f"常聊话题: {', '.join(profile['topics'][-5:])}")

        # Recent notes
        notes = profile.get("notes", [])
        if notes:
            recent = notes[-3:]
            note_texts = [f"  - {n['text']}" for n in recent]
            parts.append(f"近期备注:\n" + "\n".join(note_texts))

        msg_count = profile.get("message_count", 0)
        first_seen = profile.get("first_seen", "")
        if msg_count > 0:
            parts.append(f"互动 {msg_count} 次，认识于 {first_seen}")

        # Historical conversation summaries
        log = self.get_recent_log(open_id)
        if log:
            parts.append(f"历史对话记忆:\n{log}")

        return "\n".join(parts)

    def _fetch_name(self, open_id: str) -> str:
        """Fetch user's real name from Feishu API."""
        try:
            req = GetUserRequest.builder() \
                .user_id(open_id) \
                .user_id_type("open_id") \
                .build()
            resp = self._client.contact.v3.user.get(req)
            if resp.success() and resp.data and resp.data.user:
                name = resp.data.user.name or ""
                if name:
                    self._name_cache[open_id] = name
                    return name
            logger.warning(f"Failed to fetch name for {open_id}: {resp.msg if not resp.success() else 'no name'}")
        except Exception as e:
            logger.warning(f"Error fetching user name: {e}")
        return ""

    def list_contacts(self) -> list[dict]:
        """List all known contacts (for admin view)."""
        contacts = []
        for path in CONTACTS_DIR.glob("*.json"):
            try:
                profile = json.loads(path.read_text(encoding="utf-8"))
                contacts.append({
                    "name": profile.get("nickname") or profile.get("name") or path.stem,
                    "open_id": profile.get("open_id", path.stem),
                    "message_count": profile.get("message_count", 0),
                    "last_seen": profile.get("last_seen", ""),
                })
            except Exception:
                continue
        contacts.sort(key=lambda c: c.get("last_seen", ""), reverse=True)
        return contacts
