"""Daily batch evolution — run once per day with opus.

Processes the day's conversation buffer to:
1. Evolve group persona (extract patterns, memes, group dynamics)
2. Evolve contact profiles (traits, preferences, topics per user)
3. Extract knowledge (decisions, learnings)

Triggered by cron at 23:00 Beijing time (7:00 PST).
"""

import json
import logging
import os
import subprocess
from datetime import date, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

CLAUDE_PATH = "/Users/tuanyou/.local/bin/claude"
BUFFER_DIR = Path("/Users/tuanyou/Happycode2026/data/daily_buffer")
GROUP_PERSONA_FILE = Path("/Users/tuanyou/Happycode2026/team/roles/group_persona/memory.md")
CONTACTS_DIR = Path("/Users/tuanyou/Happycode2026/vault/memory/contacts")
MEMORY_DIR = Path("/Users/tuanyou/Happycode2026/vault/memory")


_ERROR_PATTERNS = [
    "you've hit your limit",
    "rate limit",
    "overloaded",
    "quota exceeded",
    "too many requests",
    "error:",
    "sorry, i",
]


class OpusCallError(Exception):
    """Raised when opus returns an error or rate-limit message."""


def _call_opus(prompt: str, timeout: int = 120) -> str:
    """Call Claude opus for deep analysis.

    Raises OpusCallError if the output looks like a rate-limit or error message.
    """
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    env["PATH"] = f"/Users/tuanyou/.local/bin:{env.get('PATH', '')}"
    result = subprocess.run(
        [CLAUDE_PATH, "-p", prompt, "--model", "opus"],
        capture_output=True, text=True, timeout=timeout, env=env,
    )
    output = result.stdout.strip()

    if result.returncode != 0:
        raise OpusCallError(f"opus exited with code {result.returncode}: {output[:200]}")

    if not output:
        raise OpusCallError("opus returned empty output")

    # Detect rate-limit / error messages in output
    output_lower = output.lower()
    for pattern in _ERROR_PATTERNS:
        if pattern in output_lower and len(output) < 200:
            raise OpusCallError(f"opus returned error-like output: {output[:200]}")

    return output


def load_buffer(target_date: date = None) -> list[dict]:
    """Load conversation buffer for a given date."""
    target_date = target_date or date.today()
    buffer_file = BUFFER_DIR / f"{target_date.isoformat()}.jsonl"
    if not buffer_file.exists():
        return []
    entries = []
    for line in buffer_file.read_text(encoding="utf-8").strip().split("\n"):
        if line.strip():
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def archive_buffer(target_date: date = None):
    """Move processed buffer to archive dir instead of deleting."""
    target_date = target_date or date.today()
    buffer_file = BUFFER_DIR / f"{target_date.isoformat()}.jsonl"
    if buffer_file.exists():
        archive_dir = BUFFER_DIR / "archive"
        archive_dir.mkdir(exist_ok=True)
        dest = archive_dir / buffer_file.name
        buffer_file.rename(dest)
        logger.info(f"Archived buffer: {buffer_file.name} -> archive/")


def evolve_persona(entries: list[dict]) -> str:
    """Analyze all group conversations and evolve persona."""
    group_entries = [e for e in entries if e.get("chat_type") == "group"]
    if not group_entries:
        return "No group conversations today."

    # Build conversation summary for opus
    conversations = []
    for e in group_entries[:50]:  # Cap at 50 entries
        user = e.get("user_name", e.get("user_id", "?"))
        conversations.append(f"[{user}] {e['user_msg'][:200]}")
        if e.get("bot_reply"):
            conversations.append(f"[小叼毛] {e['bot_reply'][:200]}")

    conv_text = "\n".join(conversations)

    prompt = (
        "你是小叼毛的人设进化模块。分析今天的全部群聊对话，提取值得记住的信息。\n\n"
        "输出格式（每条一行，前面加 -）：\n"
        "- 新认识的群友特点\n"
        "- 有趣的梗或常用表达\n"
        "- 群的氛围和话题趋势\n"
        "- 用户偏好\n\n"
        "只输出有价值的发现（3-5条），不要废话。\n"
        "如果今天对话太少或没有新发现，输出: SKIP\n\n"
        f"今日群聊记录：\n{conv_text}"
    )

    output = _call_opus(prompt)
    if not output or "SKIP" in output.upper():
        return "No notable persona updates today."

    # Append to persona file
    today = date.today().isoformat()
    with open(GROUP_PERSONA_FILE, "a", encoding="utf-8") as f:
        f.write(f"\n\n## 每日进化 [{today}]\n{output}")
    logger.info(f"Persona evolved with {len(output)} chars")
    return output


def evolve_contacts(entries: list[dict]) -> dict[str, str]:
    """Analyze conversations per user, update profiles, and write memory logs."""
    from src.contact_memory import ContactMemory
    from config.settings import settings as app_settings

    contact_mem = ContactMemory(app_settings)

    # Group entries by user
    by_user: dict[str, list[dict]] = {}
    for e in entries:
        uid = e.get("user_id", "")
        if uid:
            by_user.setdefault(uid, []).append(e)

    results = {}
    for user_id, user_entries in by_user.items():
        if len(user_entries) < 2:  # Skip if too few messages
            continue

        # Build user's conversation summary
        lines = []
        for e in user_entries[:20]:
            lines.append(f"用户: {e['user_msg'][:200]}")
            if e.get("bot_reply"):
                lines.append(f"助手: {e['bot_reply'][:200]}")

        conv_text = "\n".join(lines)
        user_name = user_entries[0].get("user_name", user_id)

        prompt = (
            "分析今天这个用户的全部对话，提取用户信息和对话摘要。只输出 JSON。\n"
            "如果没有新信息，输出: {}\n\n"
            "可提取的字段（都是可选的）:\n"
            '{"nickname":"昵称","traits":["特点"],"preferences":["偏好"],'
            '"topics":["话题"],"summary":"今日对话要点摘要（1-3句话）"}\n\n'
            f"用户名: {user_name}\n"
            f"今日对话:\n{conv_text}"
        )

        try:
            raw = _call_opus(prompt, timeout=60)
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            extracted = json.loads(raw)
            if extracted and isinstance(extracted, dict):
                # Update contact profile via ContactMemory
                contact_mem.update_from_conversation(user_id, extracted)

                # Write conversation summary to memory log
                summary = extracted.get("summary", "")
                if not summary:
                    # Generate a brief summary from topics
                    topics = extracted.get("topics", [])
                    summary = f"聊了{'、'.join(topics)}" if topics else f"对话 {len(user_entries)} 条"

                today = date.today().isoformat()
                log_entry = f"\n### {today} ({user_name})\n{summary}\n"
                contact_mem.append_log(user_id, log_entry)
                logger.info(f"Memory log written for {user_name} ({user_id})")

                results[user_id] = str(extracted)
        except Exception as e:
            logger.warning(f"Contact evolution failed for {user_id}: {e}")

    return results


def extract_knowledge(entries: list[dict]) -> str:
    """Extract decisions and learnings from the day's private conversations."""
    private_entries = [e for e in entries if e.get("chat_type") == "p2p"]
    if not private_entries:
        return "No private conversations today."

    # Build summary
    lines = []
    for e in private_entries[:30]:
        lines.append(f"用户: {e['user_msg'][:300]}")
        if e.get("bot_reply"):
            lines.append(f"助手: {e['bot_reply'][:500]}")
        lines.append("---")

    conv_text = "\n".join(lines)

    prompt = (
        "你是一个自我进化的 AI 助手的学习模块。分析今天的全部私聊交互，提取：\n\n"
        "## 1. 决策 (用户今天做了哪些决策)\n"
        "每条格式: DECISION: <描述>\n\n"
        "## 2. 知识 (值得长期记住的内容)\n"
        "每条格式:\n"
        "FILE: <decisions.md 或 learnings.md 或 profile.md 或 patterns.md>\n"
        "CONTENT: <要追加的内容>\n\n"
        "如果没有值得提取的，输出: SKIP\n\n"
        f"今日私聊记录:\n{conv_text}"
    )

    output = _call_opus(prompt)
    if not output or "SKIP" in output.upper():
        return "No notable learnings today."

    # Parse and save
    current_file = None
    for line in output.split("\n"):
        if line.startswith("DECISION:"):
            decision = line.split(":", 1)[1].strip()
            _append_to_memory("decisions.md", f"- [{date.today().isoformat()}] {decision}")
        elif line.startswith("FILE:"):
            current_file = line.split(":", 1)[1].strip()
        elif line.startswith("CONTENT:") and current_file:
            content = line.split(":", 1)[1].strip()
            if current_file in {"decisions.md", "learnings.md", "profile.md", "patterns.md"}:
                _append_to_memory(current_file, f"- [{date.today().isoformat()}] {content}")

    logger.info(f"Knowledge extracted: {len(output)} chars")
    return output


def _append_to_memory(filename: str, text: str):
    """Append a line to a memory file."""
    allowed = {"decisions.md", "learnings.md", "profile.md", "patterns.md"}
    if filename not in allowed:
        return
    path = MEMORY_DIR / filename
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"\n{text}")


def run_daily_evolution(target_date: date = None):
    """Main entry point: run all evolution tasks for a given date."""
    target_date = target_date or date.today()
    logger.info(f"=== Daily Evolution Start: {target_date} ===")

    entries = load_buffer(target_date)
    if not entries:
        logger.info("No conversation buffer found, skipping evolution.")
        return

    logger.info(f"Processing {len(entries)} conversation entries")
    failures = 0

    # 1. Persona evolution
    try:
        persona_result = evolve_persona(entries)
        logger.info(f"Persona: {persona_result[:100]}")
    except OpusCallError as e:
        failures += 1
        logger.warning(f"Persona evolution skipped (opus error): {e}")
    except Exception as e:
        failures += 1
        logger.error(f"Persona evolution failed: {e}", exc_info=True)

    # 2. Contact evolution
    try:
        contact_results = evolve_contacts(entries)
        logger.info(f"Contacts updated: {len(contact_results)} users")
    except OpusCallError as e:
        failures += 1
        logger.warning(f"Contact evolution skipped (opus error): {e}")
    except Exception as e:
        failures += 1
        logger.error(f"Contact evolution failed: {e}", exc_info=True)

    # 3. Knowledge extraction
    try:
        knowledge_result = extract_knowledge(entries)
        logger.info(f"Knowledge: {knowledge_result[:100]}")
    except OpusCallError as e:
        failures += 1
        logger.warning(f"Knowledge extraction skipped (opus error): {e}")
    except Exception as e:
        failures += 1
        logger.error(f"Knowledge extraction failed: {e}", exc_info=True)

    # Only archive buffer if all tasks succeeded; keep for retry otherwise
    if failures == 0:
        archive_buffer(target_date)
        logger.info("=== Daily Evolution Complete (all succeeded) ===")
    else:
        logger.warning(
            f"=== Daily Evolution Partial ({failures}/3 failed) — buffer kept for retry ==="
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    # Can be called with yesterday's date for catch-up
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "yesterday":
        run_daily_evolution(date.today() - timedelta(days=1))
    else:
        run_daily_evolution()
