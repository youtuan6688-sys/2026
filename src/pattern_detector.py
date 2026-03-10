"""Pattern detection — learn user behavior patterns from repeated actions.

When a user does the same thing 3+ times, the bot learns and can auto-act.
Patterns are stored in each user's contact JSON under "patterns" field.
"""

import logging
import uuid
from datetime import date

logger = logging.getLogger(__name__)

# Pre-defined pattern types
EXCEL_AUTO_ANALYZE = "excel_auto_analyze"
FILE_SPLIT_PREFERENCE = "file_split_preference"
TOPIC_INTEREST = "topic_interest"

AUTO_THRESHOLD = 3  # Activate auto-act after N occurrences


def _generate_id() -> str:
    return uuid.uuid4().hex[:8]


def new_pattern(action: str, trigger: str, response: str,
                context: str = "") -> dict:
    """Create a new pattern dict."""
    return {
        "pattern_id": _generate_id(),
        "action": action,
        "trigger": trigger,
        "response": response,
        "context": context,
        "count": 1,
        "last_seen": date.today().isoformat(),
        "auto_enabled": False,
        "disabled_by_user": False,
    }


def increment_pattern(patterns: list[dict], action: str, trigger: str,
                       response: str = "", context: str = "") -> list[dict]:
    """Increment count for matching pattern or create new one.

    Returns updated patterns list (new copy).
    """
    updated = [p.copy() for p in patterns]

    for p in updated:
        if p["action"] == action and p["trigger"] == trigger:
            p["count"] = p.get("count", 0) + 1
            p["last_seen"] = date.today().isoformat()
            if p["count"] >= AUTO_THRESHOLD and not p.get("disabled_by_user"):
                p["auto_enabled"] = True
                logger.info(
                    f"Pattern auto-enabled: {action}/{trigger} "
                    f"(count={p['count']})"
                )
            return updated

    # New pattern
    p = new_pattern(action, trigger, response, context)
    updated.append(p)
    return updated


def should_auto_act(patterns: list[dict], trigger: str) -> dict | None:
    """Check if any auto-enabled pattern matches the trigger.

    Returns the matching pattern dict, or None.
    """
    for p in patterns:
        if (p.get("auto_enabled")
                and not p.get("disabled_by_user")
                and p["trigger"] == trigger):
            return p
    return None


def disable_pattern(patterns: list[dict], action: str = "",
                     pattern_id: str = "") -> list[dict]:
    """Disable a pattern by action name or pattern_id.

    Returns updated patterns list (new copy).
    """
    updated = [p.copy() for p in patterns]
    for p in updated:
        if pattern_id and p["pattern_id"] == pattern_id:
            p["disabled_by_user"] = True
            p["auto_enabled"] = False
            logger.info(f"Pattern disabled: {p['action']}/{p['trigger']}")
            return updated
        if action and p["action"] == action:
            p["disabled_by_user"] = True
            p["auto_enabled"] = False
            logger.info(f"Pattern disabled: {action}/{p['trigger']}")
            return updated
    return updated


def detect_patterns_from_entries(entries: list[dict]) -> list[dict]:
    """Analyze daily buffer entries to detect behavioral patterns.

    Returns list of detected pattern dicts:
    [{"user_id": ..., "action": ..., "trigger": ..., "response": ..., "context": ...}]
    """
    detections = []
    user_actions: dict[str, list[str]] = {}

    for e in entries:
        user_id = e.get("sender_open_id", e.get("sender_id", ""))
        if not user_id:
            continue

        user_msg = e.get("user_msg", "").lower()

        # Detect: user sends Excel and asks for analysis
        if e.get("file_name", ""):
            fname = e["file_name"].lower()
            if fname.endswith((".xlsx", ".xls", ".csv")):
                user_actions.setdefault(user_id, []).append("excel_upload")

        # Detect: user asks for split
        if any(kw in user_msg for kw in ("拆分", "分开", "拆成", "按.*分")):
            user_actions.setdefault(user_id, []).append("split_request")

    # Aggregate into pattern detections
    for user_id, actions in user_actions.items():
        excel_count = actions.count("excel_upload")
        if excel_count >= 1:
            detections.append({
                "user_id": user_id,
                "action": EXCEL_AUTO_ANALYZE,
                "trigger": "excel_upload",
                "response": "auto_analyze",
                "context": f"今日发送 {excel_count} 个 Excel 文件",
            })

        split_count = actions.count("split_request")
        if split_count >= 1:
            detections.append({
                "user_id": user_id,
                "action": FILE_SPLIT_PREFERENCE,
                "trigger": "excel_upload_with_split",
                "response": "auto_split",
                "context": f"今日请求拆分 {split_count} 次",
            })

    return detections
