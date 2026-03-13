"""Token budget estimation and optimization.

Estimates token usage per message component and trims context
to fit within a target budget. Logs usage for monitoring.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

USAGE_LOG = Path("/Users/tuanyou/Happycode2026/data/token_usage.jsonl")
DEFAULT_BUDGET = 4000  # Target max tokens per message


def estimate_tokens(text: str) -> int:
    """Rough token estimate: ~1.5 Chinese chars per token, ~4 English chars per token."""
    if not text:
        return 0
    chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    other_chars = len(text) - chinese_chars
    return int(chinese_chars / 1.5 + other_chars / 4)


def optimize_context(parts: dict[str, str], budget: int = DEFAULT_BUDGET) -> dict[str, str]:
    """Trim context parts to fit within token budget.

    Priority (highest first): user_msg > history > memory > kb_context
    Lower-priority parts get truncated first.
    """
    priority = ["user_msg", "history", "memory", "kb_context"]
    estimates = {k: estimate_tokens(v) for k, v in parts.items()}
    total = sum(estimates.values())

    if total <= budget:
        return dict(parts)  # New dict, no mutation

    # Trim from lowest priority upward
    result = dict(parts)
    for key in reversed(priority):
        if key not in result or not result[key]:
            continue
        excess = sum(estimate_tokens(v) for v in result.values()) - budget
        if excess <= 0:
            break

        current_tokens = estimate_tokens(result[key])
        target_tokens = max(0, current_tokens - excess)

        if target_tokens == 0:
            result[key] = ""
        else:
            # Rough char limit from token target
            char_limit = int(target_tokens * 2.5)  # Average chars per token
            result[key] = result[key][:char_limit] + "..."

    return result


def log_usage(user_msg: str, history: str, memory: str, kb_context: str,
              response: str = ""):
    """Log token usage breakdown to JSONL for monitoring."""
    try:
        USAGE_LOG.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": datetime.now().isoformat(),
            "user_msg": estimate_tokens(user_msg),
            "history": estimate_tokens(history),
            "memory": estimate_tokens(memory),
            "kb_context": estimate_tokens(kb_context),
            "response": estimate_tokens(response),
            "total_input": (estimate_tokens(user_msg) + estimate_tokens(history)
                           + estimate_tokens(memory) + estimate_tokens(kb_context)),
        }
        with open(USAGE_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.debug(f"Token usage logging failed: {e}")
