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
import re
import subprocess
from datetime import date, timedelta
from pathlib import Path

from src.utils.subprocess_env import CLAUDE_PATH, safe_env

logger = logging.getLogger(__name__)

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
    env = safe_env()
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

    # Compress old entries to keep file small
    try:
        compress_persona()
    except Exception as e:
        logger.warning(f"Persona compression failed (non-fatal): {e}")

    return output


def _call_sonnet(prompt: str, timeout: int = 60) -> str:
    """Call Claude sonnet for lighter tasks (compression, summarization)."""
    env = safe_env()
    result = subprocess.run(
        [CLAUDE_PATH, "-p", prompt, "--model", "sonnet"],
        capture_output=True, text=True, timeout=timeout, env=env,
    )
    return result.stdout.strip()


_EVOLUTION_HEADER_RE = re.compile(r"^## 每日进化 \[(\d{4}-\d{2}-\d{2})\]", re.MULTILINE)
_MAX_RECENT_DAYS = 7


def compress_persona():
    """Keep only recent evolution entries; compress older ones into a summary.

    Uses sonnet (not opus) since this is a summarization task.
    """
    if not GROUP_PERSONA_FILE.exists():
        return

    content = GROUP_PERSONA_FILE.read_text(encoding="utf-8")

    # Find all evolution entry positions
    matches = list(_EVOLUTION_HEADER_RE.finditer(content))
    if len(matches) <= _MAX_RECENT_DAYS:
        return  # Nothing to compress

    # Split: entries to compress (old) vs keep (recent)
    cutoff_idx = len(matches) - _MAX_RECENT_DAYS
    old_start = matches[0].start()
    keep_start = matches[cutoff_idx].start()

    base_content = content[:old_start].rstrip()
    old_entries = content[old_start:keep_start].strip()
    recent_entries = content[keep_start:].strip()

    if not old_entries:
        return

    # Check if there's already a compressed section
    compressed_marker = "## 综合记忆"
    existing_compressed = ""
    if compressed_marker in base_content:
        parts = base_content.split(compressed_marker, 1)
        base_before = parts[0].rstrip()
        # Extract existing compressed content (everything between 综合记忆 and next ##)
        rest = parts[1]
        next_section = rest.find("\n## ")
        if next_section > 0:
            existing_compressed = rest[:next_section].strip()
            base_content = base_before + "\n\n" + rest[next_section:]
        else:
            existing_compressed = rest.strip()
            base_content = base_before

    # Use sonnet to compress old entries
    compress_prompt = (
        "你是小叼毛的记忆压缩模块。将以下旧的每日进化记录压缩成精华要点。\n\n"
        "要求：\n"
        "- 保留有价值的群友画像、常用梗、核心需求\n"
        "- 合并重复信息\n"
        "- 输出 5-10 条精华（每条一行，前面加 -）\n"
        "- 不要日期前缀，只保留内容本身\n\n"
    )
    if existing_compressed:
        compress_prompt += f"已有的综合记忆（需要合并）：\n{existing_compressed}\n\n"
    compress_prompt += f"需要压缩的旧记录：\n{old_entries}"

    compressed = _call_sonnet(compress_prompt, timeout=60)
    if not compressed or len(compressed) < 20:
        logger.warning("Persona compression returned empty result, skipping")
        return

    # Rebuild file: base + compressed + recent
    new_content = (
        f"{base_content}\n\n"
        f"## 综合记忆\n{compressed}\n\n"
        f"{recent_entries}\n"
    )

    GROUP_PERSONA_FILE.write_text(new_content, encoding="utf-8")
    old_count = cutoff_idx
    logger.info(f"Persona compressed: {old_count} old entries merged, {_MAX_RECENT_DAYS} recent kept")


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


def extract_pending_tasks(entries: list[dict], target_date: date | None = None):
    """Extract pending tasks from today's conversations using sonnet.

    Looks for: explicit commitments, unsatisfied requests, time-bound tasks.
    Saves them via pending_tasks.add_task().
    """
    from src import pending_tasks
    from src.contact_memory import ContactMemory
    from config.settings import settings

    if not entries:
        logger.info("No entries for pending task extraction")
        return

    source_date = (target_date or date.today()).isoformat()
    cm = ContactMemory(settings)

    # Build conversation summary for sonnet
    lines = []
    for e in entries[:40]:
        user_id = e.get("sender_open_id", e.get("sender_id", ""))
        user_name = cm.get_name(user_id) if user_id else "未知"
        chat_type = e.get("chat_type", "p2p")
        lines.append(f"[{chat_type}] {user_name}({user_id[:10]}): {e['user_msg'][:300]}")
        if e.get("bot_reply"):
            lines.append(f"  Bot: {e['bot_reply'][:300]}")
        lines.append("")

    conv_text = "\n".join(lines)

    prompt = (
        "分析以下对话记录，提取需要后续跟进的任务。\n\n"
        "提取类型：\n"
        "1. 明确承诺（如：明天发给你、下次帮你看）\n"
        "2. 未满足的请求（用户要求了但 bot 没能完成的）\n"
        "3. 时间绑定任务（如：周五前、下周一）\n\n"
        "输出 JSON 数组，每条格式：\n"
        '{"user_id": "ou_xxx...", "user_name": "名字", "description": "任务描述", '
        '"due_date": "YYYY-MM-DD或null", "chat_id": "oc_或ou_xxx", "chat_type": "group或p2p"}\n\n'
        "如果没有需要跟进的任务，输出空数组: []\n\n"
        f"对话记录:\n{conv_text}"
    )

    try:
        output = _call_sonnet(prompt, timeout=60)
        if not output:
            return

        # Extract JSON from output (may have markdown wrapping)
        json_start = output.find("[")
        json_end = output.rfind("]") + 1
        if json_start < 0 or json_end <= json_start:
            logger.info("No pending tasks extracted (no JSON array)")
            return

        tasks = json.loads(output[json_start:json_end])
        if not tasks:
            logger.info("No pending tasks extracted (empty array)")
            return

        added = 0
        for t in tasks[:10]:  # Cap at 10 tasks per day
            user_id = t.get("user_id", "")
            if not user_id:
                continue
            pending_tasks.add_task(
                user_id=user_id,
                user_name=t.get("user_name", ""),
                description=t.get("description", ""),
                source_date=source_date,
                chat_id=t.get("chat_id", user_id),
                chat_type=t.get("chat_type", "p2p"),
                due_date=t.get("due_date"),
            )
            added += 1

        logger.info(f"Pending tasks extracted: {added} tasks")

    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse pending tasks JSON: {e}")
    except Exception as e:
        logger.error(f"Pending task extraction failed: {e}", exc_info=True)


def detect_and_update_patterns(entries: list[dict]):
    """Detect behavior patterns from today's entries and update contact profiles.

    No AI call — pure rule-based detection from pattern_detector.
    """
    from src.pattern_detector import detect_patterns_from_entries, increment_pattern
    from src.contact_memory import ContactMemory
    from config.settings import settings

    detections = detect_patterns_from_entries(entries)
    if not detections:
        logger.info("No behavior patterns detected today")
        return

    cm = ContactMemory(settings)
    updated_users = set()

    for d in detections:
        user_id = d["user_id"]
        patterns = cm.get_patterns(user_id)
        new_patterns = increment_pattern(
            patterns,
            action=d["action"],
            trigger=d["trigger"],
            response=d.get("response", ""),
            context=d.get("context", ""),
        )
        cm.update_patterns(user_id, new_patterns)
        updated_users.add(user_id)

    logger.info(f"Patterns updated for {len(updated_users)} users: "
                f"{len(detections)} detections")


def detect_capability_gaps(entries: list[dict]):
    """Detect things the bot couldn't do and log them as capability gaps.

    Scans for bot replies containing "不支持"、"做不到"、"暂时无法" etc.
    Writes gaps to vault/memory/pending-actions.md for briefing to pick up.
    """
    gap_phrases = [
        "不支持", "做不到", "暂时无法", "暂不支持", "没有这个功能",
        "目前不能", "还不能", "无法完成", "不了这个",
    ]

    gaps = []
    for e in entries:
        reply = e.get("bot_reply", "")
        if not reply:
            continue
        for phrase in gap_phrases:
            if phrase in reply:
                gaps.append({
                    "user_msg": e.get("user_msg", "")[:200],
                    "bot_reply_snippet": reply[:200],
                    "phrase": phrase,
                })
                break  # One match per entry is enough

    if not gaps:
        logger.info("No capability gaps detected today")
        return

    # Write to pending-actions.md for briefing to pick up
    actions_file = MEMORY_DIR / "pending-actions.md"
    today = date.today().isoformat()

    lines = [f"\n## 能力缺口 [{today}]"]
    for g in gaps[:10]:  # Cap at 10
        lines.append(
            f"- 用户说: {g['user_msg'][:100]}\n"
            f"  Bot回复含「{g['phrase']}」: {g['bot_reply_snippet'][:100]}"
        )

    with open(actions_file, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    logger.info(f"Capability gaps logged: {len(gaps)} items")


def _append_to_memory(filename: str, text: str):
    """Append a line to a memory file."""
    allowed = {"decisions.md", "learnings.md", "profile.md", "patterns.md"}
    if filename not in allowed:
        return
    path = MEMORY_DIR / filename
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"\n{text}")


DAILY_SUMMARY_FILE = MEMORY_DIR / "daily_summary.md"
METRICS_FILE = Path("/Users/tuanyou/Happycode2026/data/evolution_metrics.json")
_MAX_SUMMARY_DAYS = 7

# Positive signals in user messages (after bot reply)
_POSITIVE_SIGNALS = {"谢谢", "感谢", "牛", "厉害", "好的", "收到", "可以", "不错", "666", "赞", "nice", "perfect", "thanks", "👍"}
_NEGATIVE_SIGNALS = {"不对", "错了", "什么意思", "没用", "重来", "不是这个", "废话", "答非所问"}


def track_metrics(target_date: date, entries: list[dict],
                  persona_updated: bool, contacts_updated: int,
                  knowledge_extracted: bool):
    """Track lightweight evolution metrics per day."""
    # Count stats
    unique_users = set()
    group_msgs = 0
    p2p_msgs = 0
    positive = 0
    negative = 0

    for e in entries:
        uid = e.get("user_id", "")
        if uid:
            unique_users.add(uid)
        if e.get("chat_type") == "group":
            group_msgs += 1
        else:
            p2p_msgs += 1

        # Check user message for satisfaction signals
        msg = e.get("user_msg", "").lower()
        if any(s in msg for s in _POSITIVE_SIGNALS):
            positive += 1
        if any(s in msg for s in _NEGATIVE_SIGNALS):
            negative += 1

    day_metrics = {
        "date": target_date.isoformat(),
        "total_messages": len(entries),
        "group_messages": group_msgs,
        "p2p_messages": p2p_msgs,
        "unique_users": len(unique_users),
        "positive_signals": positive,
        "negative_signals": negative,
        "persona_updated": persona_updated,
        "contacts_updated": contacts_updated,
        "knowledge_extracted": knowledge_extracted,
    }

    # Load existing metrics
    all_metrics = []
    if METRICS_FILE.exists():
        try:
            all_metrics = json.loads(METRICS_FILE.read_text(encoding="utf-8"))
        except Exception:
            all_metrics = []

    # Remove existing entry for same date (idempotent)
    all_metrics = [m for m in all_metrics if m.get("date") != target_date.isoformat()]
    all_metrics.append(day_metrics)

    # Keep last 90 days
    all_metrics = sorted(all_metrics, key=lambda m: m.get("date", ""))[-90:]

    METRICS_FILE.parent.mkdir(parents=True, exist_ok=True)
    METRICS_FILE.write_text(json.dumps(all_metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"Metrics tracked for {target_date}: {len(entries)} msgs, {len(unique_users)} users, +{positive}/-{negative}")


def _write_daily_summary(target_date: date, entries: list[dict],
                          persona_result: str, contact_results: dict):
    """Write a concise cross-day summary for context continuity.

    Keeps last 7 days, no AI call needed — just structured extraction.
    """
    group_count = sum(1 for e in entries if e.get("chat_type") == "group")
    p2p_count = sum(1 for e in entries if e.get("chat_type") == "p2p")

    # Extract active users
    users = {}
    for e in entries:
        uid = e.get("user_id", "")
        name = e.get("user_name", "")
        if uid:
            users[uid] = name

    # Extract main topics from user messages (first 100 chars of each)
    topics = set()
    for e in entries[:30]:
        msg = e.get("user_msg", "")[:50]
        if len(msg) > 10:
            topics.add(msg)

    user_list = ", ".join(n or uid[:8] for uid, n in users.items()) or "无"
    topic_sample = "; ".join(list(topics)[:5]) or "无"

    today_summary = (
        f"### {target_date}\n"
        f"- 群聊 {group_count} 条, 私聊 {p2p_count} 条\n"
        f"- 活跃用户: {user_list}\n"
        f"- 话题: {topic_sample}\n"
    )

    if persona_result and "No notable" not in persona_result and "No group" not in persona_result:
        # Take first line of persona result as key insight
        first_line = persona_result.strip().split("\n")[0]
        today_summary += f"- 进化要点: {first_line}\n"

    # Load existing summary, append today, keep last N days
    existing = ""
    if DAILY_SUMMARY_FILE.exists():
        existing = DAILY_SUMMARY_FILE.read_text(encoding="utf-8")

    # Parse existing days
    day_sections = []
    current_section = []
    for line in existing.split("\n"):
        if line.startswith("### ") and current_section:
            day_sections.append("\n".join(current_section))
            current_section = [line]
        else:
            current_section.append(line)
    if current_section and any(l.strip() for l in current_section):
        day_sections.append("\n".join(current_section))

    # Add today and keep last N
    day_sections.append(today_summary)
    day_sections = day_sections[-_MAX_SUMMARY_DAYS:]

    DAILY_SUMMARY_FILE.write_text(
        "\n".join(day_sections).strip() + "\n",
        encoding="utf-8",
    )
    logger.info(f"Daily summary written for {target_date}")


def _format_metrics_summary(target_date: date) -> str:
    """Format today's metrics as a concise text block for the admin report."""
    if not METRICS_FILE.exists():
        return ""
    try:
        all_metrics = json.loads(METRICS_FILE.read_text(encoding="utf-8"))
        today_m = next((m for m in all_metrics if m.get("date") == target_date.isoformat()), None)
        if not today_m:
            return ""

        lines = [
            f"- 消息: {today_m['total_messages']} (群聊 {today_m['group_messages']}, 私聊 {today_m['p2p_messages']})",
            f"- 活跃用户: {today_m['unique_users']}",
            f"- 满意度: +{today_m['positive_signals']} / -{today_m['negative_signals']}",
        ]

        # Compare with yesterday
        yesterday = (target_date - timedelta(days=1)).isoformat()
        prev_m = next((m for m in all_metrics if m.get("date") == yesterday), None)
        if prev_m and prev_m["total_messages"] > 0:
            delta = today_m["total_messages"] - prev_m["total_messages"]
            sign = "+" if delta >= 0 else ""
            lines.append(f"- 环比: {sign}{delta} 条 vs 昨日")

        return "\n".join(lines)
    except Exception:
        return ""


def _generate_weekly_report(target_date: date) -> str:
    """Generate a 3-line weekly trend summary using sonnet (Sundays only)."""
    if not METRICS_FILE.exists():
        return ""
    try:
        all_metrics = json.loads(METRICS_FILE.read_text(encoding="utf-8"))
        week_start = (target_date - timedelta(days=6)).isoformat()
        week_data = [m for m in all_metrics if m.get("date", "") >= week_start]

        if len(week_data) < 2:
            return ""

        # Build a compact summary for sonnet
        data_text = json.dumps(week_data, ensure_ascii=False)
        prompt = (
            "根据以下一周的 bot 进化指标数据，生成 3 行趋势摘要。\n"
            "重点关注：消息量趋势、用户活跃度变化、满意度信号。\n"
            "直接输出 3 行，不要标题。\n\n"
            f"数据：{data_text}"
        )
        return _call_sonnet(prompt, timeout=30)
    except Exception as e:
        logger.warning(f"Weekly report generation failed: {e}")
        return ""


def _notify_admin(target_date: date, persona_result: str,
                   contact_results: dict, knowledge_result: str):
    """Send evolution summary to admin (private chat only, not to groups)."""
    try:
        from config.settings import settings as app_settings
        from src.feishu_sender import FeishuSender

        ADMIN_ID = "ou_4a18a2e35a5b04262a24f41731046d15"
        sections = [f"🧬 每日进化报告 [{target_date}]"]

        # Metrics summary
        metrics_text = _format_metrics_summary(target_date)
        if metrics_text:
            sections.append(f"\n📊 数据指标:\n{metrics_text}")

        # Persona
        if persona_result and "No notable" not in persona_result and "No group" not in persona_result:
            sections.append(f"\n🎭 人设更新:\n{persona_result[:500]}")

        # Contacts
        if contact_results:
            sections.append(f"\n👥 联系人更新: {len(contact_results)} 人")

        # Knowledge
        if knowledge_result and "No notable" not in knowledge_result and "No private" not in knowledge_result:
            sections.append(f"\n📚 新知识:\n{knowledge_result[:500]}")

        # Weekly report on Sundays
        if target_date.weekday() == 6:  # Sunday
            weekly = _generate_weekly_report(target_date)
            if weekly:
                sections.append(f"\n📈 周报:\n{weekly}")

        # Only send if there's actual content beyond the header
        if len(sections) > 1:
            sender = FeishuSender(app_settings)
            sender.send_text(ADMIN_ID, "\n".join(sections))
            logger.info("Evolution summary sent to admin")
        else:
            logger.info("No evolution updates to report")
    except Exception as e:
        logger.warning(f"Failed to send evolution summary to admin: {e}")


VAULT_LOGS_DIR = Path("/Users/tuanyou/Happycode2026/vault/logs")


def _save_evolution_to_vault(target_date: date, entries: list[dict],
                              persona_result: str, contact_results: dict):
    """Save evolution analysis to Obsidian vault for content creation.

    Creates a structured markdown file with frontmatter, searchable in Obsidian.
    Useful as素材 for 公众号/小红书 (Bot 成长日记、AI 产品案例).
    """
    VAULT_LOGS_DIR.mkdir(parents=True, exist_ok=True)
    today = target_date.isoformat()
    log_file = VAULT_LOGS_DIR / f"evolution-{today}.md"

    # Metrics section
    metrics_section = "无数据"
    if METRICS_FILE.exists():
        try:
            all_metrics = json.loads(METRICS_FILE.read_text(encoding="utf-8"))
            today_m = next((m for m in all_metrics if m.get("date") == today), None)
            if today_m:
                metrics_section = (
                    f"- 总消息: {today_m.get('total_messages', 0)}\n"
                    f"- 群聊: {today_m.get('group_messages', 0)}, 私聊: {today_m.get('p2p_messages', 0)}\n"
                    f"- 活跃用户: {today_m.get('unique_users', 0)}\n"
                    f"- 正面信号: {today_m.get('positive_signals', 0)}, 负面: {today_m.get('negative_signals', 0)}"
                )
        except Exception:
            pass

    # Active users
    users = {}
    for e in entries:
        uid = e.get("user_id", "")
        name = e.get("user_name", "")
        if uid:
            users[uid] = name
    user_list = ", ".join(n or uid[:8] for uid, n in users.items()) or "无"

    # Contact updates
    contact_lines = ""
    if contact_results:
        lines = [f"- {name}: {result[:150]}" for name, result in list(contact_results.items())[:10]]
        contact_lines = "\n".join(lines)

    content = f"""---
title: "进化日志 {today}"
source: "daily-evolution"
platform: evolution
date_saved: {today}
tags:
  - 进化日志
  - Bot成长
  - 用户洞察
  - 内容素材
category: evolution
content_use:
  - Bot成长复盘
  - 用户行为分析素材
  - AI产品案例素材
---

# 进化日志 {today}

## 今日概况
- 活跃用户: {user_list}
- 消息总量: {len(entries)}

## 人设进化
{persona_result or '无更新'}

## 联系人更新
{contact_lines or '无更新'}

## 数据指标
{metrics_section}
"""
    log_file.write_text(content, encoding="utf-8")
    logger.info(f"Evolution log saved to vault: {log_file}")


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
    persona_result = ""
    contact_results = {}
    knowledge_result = ""

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

    # 4. Pending task extraction (sonnet, non-fatal)
    try:
        extract_pending_tasks(entries, target_date)
    except Exception as e:
        logger.warning(f"Pending task extraction failed (non-fatal): {e}")

    # 5. Pattern detection (no AI call, pure analysis)
    try:
        detect_and_update_patterns(entries)
    except Exception as e:
        logger.warning(f"Pattern detection failed (non-fatal): {e}")

    # 6. Capability gap detection (sonnet, non-fatal)
    try:
        detect_capability_gaps(entries)
    except Exception as e:
        logger.warning(f"Capability gap detection failed (non-fatal): {e}")

    # Track evolution metrics
    try:
        track_metrics(
            target_date, entries,
            persona_updated=bool(persona_result and "No notable" not in persona_result),
            contacts_updated=len(contact_results),
            knowledge_extracted=bool(knowledge_result and "No notable" not in knowledge_result),
        )
    except Exception as e:
        logger.warning(f"Metrics tracking failed (non-fatal): {e}")

    # Generate cross-day summary
    try:
        _write_daily_summary(target_date, entries, persona_result, contact_results)
    except Exception as e:
        logger.warning(f"Daily summary generation failed (non-fatal): {e}")

    # Save evolution log to Obsidian vault
    try:
        _save_evolution_to_vault(target_date, entries, persona_result, contact_results)
    except Exception as e:
        logger.warning(f"Failed to save evolution to vault (non-fatal): {e}")

    # Notify admin with evolution results
    _notify_admin(target_date, persona_result, contact_results, knowledge_result)

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
