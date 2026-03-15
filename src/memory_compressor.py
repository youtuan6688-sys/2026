"""Memory file auto-compression.

Triggered after daily evolution to keep memory files within size limits.
Uses sonnet for summarization, following the compress_persona() pattern.
"""

import logging
import re
from datetime import date, timedelta
from pathlib import Path

from src.utils.subprocess_env import CLAUDE_PATH, safe_env

logger = logging.getLogger(__name__)

MEMORY_DIR = Path("/Users/tuanyou/Happycode2026/vault/memory")
ARCHIVE_DIR = MEMORY_DIR / "archive"

# Size thresholds (bytes) — compress when exceeded
_THRESHOLDS = {
    "tools.md": 8000,
    "learnings.md": 6000,
    "decisions.md": 5000,
}

# How many days of entries to keep uncompressed
_KEEP_RECENT_DAYS = 14

# Date pattern in entries: [2026-03-12] or (2026-03-12)
_DATE_RE = re.compile(r"[\[\(](\d{4}-\d{2}-\d{2})[\]\)]")
_SECTION_RE = re.compile(r"^##+ ", re.MULTILINE)


def _call_sonnet(prompt: str, timeout: int = 60) -> str:
    """Call Claude sonnet for compression."""
    import subprocess
    env = safe_env()
    result = subprocess.run(
        [CLAUDE_PATH, "-p", prompt, "--model", "sonnet",
         "--output-format", "text"],
        capture_output=True, text=True, timeout=timeout, env=env,
    )
    return result.stdout.strip()


def _split_by_age(content: str, cutoff: date) -> tuple[str, str]:
    """Split content into old entries (before cutoff) and recent entries.

    Returns (old_text, recent_text). If no date markers found, returns ("", content).
    """
    lines = content.split("\n")
    old_lines = []
    recent_lines = []
    current_date = None

    for line in lines:
        match = _DATE_RE.search(line)
        if match:
            try:
                current_date = date.fromisoformat(match.group(1))
            except ValueError:
                pass

        if current_date and current_date < cutoff:
            old_lines.append(line)
        else:
            recent_lines.append(line)

    return "\n".join(old_lines).strip(), "\n".join(recent_lines).strip()


def compress_file(name: str) -> bool:
    """Compress a single memory file if it exceeds threshold.

    Returns True if compression was performed.
    """
    path = MEMORY_DIR / name
    if not path.exists():
        return False

    content = path.read_text(encoding="utf-8")
    threshold = _THRESHOLDS.get(name, 8000)

    if len(content) < threshold:
        return False

    logger.info(f"Compressing {name} ({len(content)} bytes > {threshold} threshold)")

    cutoff = date.today() - timedelta(days=_KEEP_RECENT_DAYS)
    old_text, recent_text = _split_by_age(content, cutoff)

    if not old_text or len(old_text) < 200:
        logger.info(f"No old entries to compress in {name}")
        return False

    # Archive old entries before compression
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    archive_path = ARCHIVE_DIR / f"{name}.{date.today().isoformat()}.bak"
    archive_path.write_text(old_text, encoding="utf-8")
    logger.info(f"Archived old entries to {archive_path.name}")

    # Compress old entries with sonnet
    compress_prompt = (
        f"压缩以下 {name} 的旧条目为精华摘要。\n\n"
        "要求：\n"
        "- 合并重复和相似的条目\n"
        "- 保留有价值的具体知识点和决策\n"
        "- 删除过时或已不相关的内容\n"
        "- 输出 5-15 条精华（每条一行，前面加 -）\n"
        "- 不要加日期前缀\n\n"
        f"旧条目：\n{old_text}"
    )

    try:
        compressed = _call_sonnet(compress_prompt, timeout=60)
    except Exception as e:
        logger.warning(f"Compression failed for {name}: {e}")
        return False

    if not compressed or len(compressed) < 20:
        logger.warning(f"Compression returned too short result for {name}")
        return False

    # Rebuild file: compressed summary + recent entries
    new_content = (
        f"## 综合摘要（自动压缩于 {date.today().isoformat()}）\n"
        f"{compressed}\n\n"
        f"{recent_text}\n"
    )

    path.write_text(new_content, encoding="utf-8")
    logger.info(
        f"Compressed {name}: {len(content)} -> {len(new_content)} bytes "
        f"({len(content) - len(new_content)} saved)"
    )
    return True


def compress_all() -> dict[str, bool]:
    """Compress all memory files that exceed their thresholds.

    Returns dict of {filename: was_compressed}.
    """
    results = {}
    for name in _THRESHOLDS:
        try:
            results[name] = compress_file(name)
        except Exception as e:
            logger.error(f"Failed to compress {name}: {e}")
            results[name] = False

    # Also compress knowledge-synthesis.md (date-section based, not line-based)
    try:
        from scripts.weekly_synthesis import compress_synthesis
        compress_synthesis()
    except Exception as e:
        logger.warning(f"Knowledge-synthesis compression failed (non-fatal): {e}")

    return results
