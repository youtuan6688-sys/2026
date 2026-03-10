#!/usr/bin/env python3
"""Deep absorption: extract actionable knowledge from daily briefing reports.

Runs after the briefing completes. Reads the report, identifies high-value
content, deep-reads linked articles, and extracts knowledge into memory files.

Uses sonnet (not opus) to keep costs low.
"""

import json
import logging
import os
import re
import subprocess
import sys
import urllib.request
import urllib.error
from datetime import date
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)

PROJECT_DIR = Path("/Users/tuanyou/Happycode2026")
VAULT_DIR = PROJECT_DIR / "vault"
MEMORY_DIR = VAULT_DIR / "memory"
VAULT_LOGS_DIR = VAULT_DIR / "logs"
VAULT_ARTICLES_DIR = VAULT_DIR / "articles"
WATCH_LIST = PROJECT_DIR / "config" / "watch_list.yaml"
CLAUDE_PATH = os.environ.get("CLAUDE_PATH", "claude")

# Output files
TRENDS_FILE = MEMORY_DIR / "trends.md"
LEARNINGS_FILE = MEMORY_DIR / "learnings.md"
TOOLS_FILE = MEMORY_DIR / "tools.md"

# Limits
MAX_DEEP_READ_URLS = 5
MAX_EXTRACT_CHARS = 30000

# Watch list state (for delta tracking)
WATCH_STATE_FILE = PROJECT_DIR / "data" / "watch_state.json"


def _call_sonnet(prompt: str, timeout: int = 90, tools: str = "") -> str:
    """Call Claude sonnet for knowledge extraction."""
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    env["PATH"] = f"/Users/tuanyou/.local/bin:{env.get('PATH', '')}"
    cmd = [CLAUDE_PATH, "-p", prompt, "--model", "sonnet"]
    if tools:
        cmd.extend(["--allowedTools", tools])
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, env=env,
    )
    return result.stdout.strip()


def extract_urls(report_text: str) -> list[str]:
    """Extract URLs from the briefing report."""
    url_pattern = re.compile(r'https?://[^\s\)>\]]+')
    urls = url_pattern.findall(report_text)
    # Deduplicate while preserving order
    seen = set()
    unique = []
    for url in urls:
        url = url.rstrip(".,;:)")
        if url not in seen:
            seen.add(url)
            unique.append(url)
    return unique


def select_high_value_urls(report_text: str, urls: list[str]) -> list[str]:
    """Use sonnet to select the most valuable URLs for deep reading."""
    if len(urls) <= MAX_DEEP_READ_URLS:
        return urls

    url_list = "\n".join(f"{i+1}. {u}" for i, u in enumerate(urls[:30]))

    prompt = (
        "从以下简报中提取的 URL 列表中，选出最值得深度阅读的 5 个。\n\n"
        "优先级：\n"
        "1. 可直接复用的代码/配置/工具（GitHub repo、技术博客）\n"
        "2. Claude/Anthropic 官方更新\n"
        "3. 有深度的技术分析文章\n"
        "4. 跳过：Twitter 链接、状态页、一般新闻\n\n"
        f"URL 列表：\n{url_list}\n\n"
        "只输出选中的 URL，每行一个，不要编号或解释。"
    )
    result = _call_sonnet(prompt, timeout=30)
    selected = [line.strip() for line in result.split("\n") if line.strip().startswith("http")]
    return selected[:MAX_DEEP_READ_URLS]


def deep_read_and_extract(report_text: str) -> dict:
    """Read the briefing report and extract structured knowledge.

    Returns dict with keys: trends, learnings, tools, actions.
    """
    today = date.today().isoformat()

    prompt = (
        f"你是一个 AI 知识提取模块。今天是 {today}。\n"
        "阅读以下每日简报，提取以下四类知识：\n\n"
        "1. **trends**: 行业趋势洞察（3-5 条，每条一行）\n"
        "   格式: - [趋势描述]\n\n"
        "2. **learnings**: 可复用的技术知识（代码模式、配置片段、prompt 技巧）\n"
        "   格式: - [知识点]: [具体内容]\n\n"
        "3. **tools**: 新发现的工具/库/MCP/Skill（附评估）\n"
        "   格式: - [工具名] ([链接]): [一句话说明] — [可直接用/需适配/参考]\n\n"
        "4. **actions**: 建议自动执行的安全操作\n"
        "   格式: - [操作描述]\n\n"
        "用 JSON 格式输出，key 为上述四个类别，value 为对应的文本（多行字符串）。\n"
        "如果某个类别没有内容，value 设为空字符串。\n"
        "只输出 JSON，不要其他文字。\n\n"
        f"简报内容（截取前 {MAX_EXTRACT_CHARS} 字）：\n"
        f"{report_text[:MAX_EXTRACT_CHARS]}"
    )

    result = _call_sonnet(prompt, timeout=120)

    # Parse JSON from result
    try:
        # Try to find JSON in the output
        json_match = re.search(r'\{[\s\S]*\}', result)
        if json_match:
            return json.loads(json_match.group())
    except json.JSONDecodeError:
        logger.warning(f"Failed to parse extraction result as JSON: {result[:200]}")

    return {"trends": "", "learnings": "", "tools": "", "actions": ""}


def write_to_memory(extracted: dict):
    """Write extracted knowledge to memory files."""
    today = date.today().isoformat()

    # Trends → trends.md
    if extracted.get("trends"):
        _append_section(TRENDS_FILE, f"## {today}\n{extracted['trends']}")

    # Learnings → learnings.md
    if extracted.get("learnings"):
        _append_section(LEARNINGS_FILE, f"## {today} - 深度吸收\n{extracted['learnings']}")

    # Tools → tools.md (under "待评估" section)
    if extracted.get("tools"):
        _append_section(TOOLS_FILE, f"### {today} - 新发现工具\n{extracted['tools']}")

    # Actions → pending-actions.md
    if extracted.get("actions"):
        pending_file = MEMORY_DIR / "pending-actions.md"
        _append_section(pending_file, f"## {today} - 深度吸收建议\n{extracted['actions']}")

    logger.info("Knowledge written to memory files")


def _append_section(filepath: Path, content: str):
    """Append a section to a file, creating if needed. Deduplicates by section header."""
    filepath.parent.mkdir(parents=True, exist_ok=True)

    # Dedup: if the section header already exists today, skip
    if filepath.exists():
        existing = filepath.read_text(encoding="utf-8")
        # Extract the first line as section header for dedup check
        header = content.split("\n")[0].strip()
        if header and header in existing:
            logger.info(f"Skipping duplicate section '{header}' in {filepath.name}")
            return

    with open(filepath, "a", encoding="utf-8") as f:
        f.write(f"\n\n{content}\n")


def compress_trends():
    """Keep trends.md under control — compress entries older than 30 days."""
    if not TRENDS_FILE.exists():
        return
    content = TRENDS_FILE.read_text(encoding="utf-8")
    if len(content) < 10000:
        return

    # Find section headers
    sections = re.findall(r"## (\d{4}-\d{2}-\d{2})", content)
    if len(sections) <= 30:
        return

    # Use sonnet to compress old entries
    prompt = (
        "压缩以下趋势记录，合并重复主题，保留最重要的 15 条洞察。\n"
        "输出格式：每条一行，前面加 -\n\n"
        f"{content[:15000]}"
    )
    compressed = _call_sonnet(prompt, timeout=60)
    if compressed and len(compressed) > 50:
        today = date.today().isoformat()
        # Keep recent entries (last 7 days) + compressed
        lines = content.split("\n")
        recent_start = None
        for i, line in enumerate(lines):
            if line.startswith("## ") and len(sections) > 7:
                match = re.match(r"## (\d{4}-\d{2}-\d{2})", line)
                if match and match.group(1) >= sections[-7]:
                    recent_start = i
                    break

        recent = "\n".join(lines[recent_start:]) if recent_start else ""
        new_content = f"# 趋势洞察\n\n## 综合压缩 (截至 {today})\n{compressed}\n\n{recent}"
        TRENDS_FILE.write_text(new_content, encoding="utf-8")
        logger.info("Trends file compressed")


def save_briefing_to_vault(report_path: Path, today: str):
    """Save full briefing to Obsidian vault with frontmatter for content creation.

    Makes briefings searchable in Obsidian and usable as素材 for 公众号/小红书.
    """
    content = report_path.read_text(encoding="utf-8")
    if not content.strip():
        return

    VAULT_ARTICLES_DIR.mkdir(parents=True, exist_ok=True)
    vault_file = VAULT_ARTICLES_DIR / f"briefing-{today}.md"

    frontmatter = f"""---
title: "每日情报简报 {today}"
source: "daily-briefing"
platform: briefing
date_saved: {today}
tags:
  - 简报
  - AI生态
  - Claude
  - 趋势
  - 内容素材
category: briefing
content_use:
  - 公众号文章素材
  - 小红书笔记素材
  - 行业分析参考
---

"""
    vault_file.write_text(frontmatter + content, encoding="utf-8")
    logger.info(f"Briefing saved to vault: {vault_file}")


def extract_content_ideas(report_text: str, today: str):
    """Extract content creation ideas from briefing for 公众号/小红书素材池."""
    prompt = (
        "你是一个内容策划助手。从以下 AI 行业简报中提取可用于公众号文章和小红书笔记的素材。\n\n"
        "输出格式（每条一行）：\n"
        "- [话题标签] 一句话洞察 | 适合: 公众号/小红书/both | 角度: 具体内容切入点\n\n"
        "要求：\n"
        "- 只提取有传播价值的 3-5 条\n"
        "- 公众号适合：深度分析、行业趋势、工具评测\n"
        "- 小红书适合：实用技巧、效率提升、AI工具推荐、震惊体\n"
        "- 给出具体的内容角度（不是泛泛的'可以写'）\n"
        "- 如果没有值得写的素材，输出 SKIP\n\n"
        f"简报内容：\n{report_text[:8000]}"
    )

    result = _call_sonnet(prompt)
    if not result or "SKIP" in result.upper():
        logger.info("No notable content ideas today")
        return

    # Save to trends file (content idea pool)
    _append_section(TRENDS_FILE, f"## {today} - 内容素材\n{result}")
    logger.info(f"Content ideas saved to trends.md")


def save_evolution_to_vault(today: str):
    """Save today's evolution analysis to Obsidian vault.

    Called from daily_evolution.py or standalone.
    Reads the daily buffer and evolution results to create a structured vault entry.
    """
    VAULT_LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_file = VAULT_LOGS_DIR / f"evolution-{today}.md"

    # Read metrics if available
    metrics_file = PROJECT_DIR / "data" / "evolution_metrics.json"
    metrics_section = "无数据"
    if metrics_file.exists():
        try:
            all_metrics = json.loads(metrics_file.read_text(encoding="utf-8"))
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

    # Read persona file for latest evolution entry
    persona_file = PROJECT_DIR / "team" / "roles" / "group_persona" / "memory.md"
    persona_section = "无更新"
    if persona_file.exists():
        text = persona_file.read_text(encoding="utf-8")
        match = re.search(rf"## 每日进化 \[{today}\]\n(.*?)(?=\n## |\Z)", text, re.DOTALL)
        if match:
            persona_section = match.group(1).strip()

    # Read daily summary
    summary_file = MEMORY_DIR / "daily_summary.md"
    summary_section = ""
    if summary_file.exists():
        text = summary_file.read_text(encoding="utf-8")
        match = re.search(rf"### {today}\n(.*?)(?=\n### |\Z)", text, re.DOTALL)
        if match:
            summary_section = match.group(1).strip()

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
{summary_section or '无数据'}

## 人设进化
{persona_section}

## 数据指标
{metrics_section}
"""
    log_file.write_text(content, encoding="utf-8")
    logger.info(f"Evolution log saved to vault: {log_file}")


def _parse_watch_list() -> dict:
    """Parse watch_list.yaml without PyYAML (simple key-value format)."""
    if not WATCH_LIST.exists():
        return {}
    result = {"github_repos": [], "x_accounts": [], "topics": []}
    current_key = None
    for line in WATCH_LIST.read_text(encoding="utf-8").split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.endswith(":") and not stripped.startswith("-"):
            current_key = stripped.rstrip(":")
            continue
        if stripped.startswith("- ") and current_key:
            value = stripped[2:].split("#")[0].strip().strip('"')
            if value and current_key in result:
                result[current_key].append(value)
    return result


def _github_api(path: str) -> dict | list | None:
    """Call GitHub API (unauthenticated, 60 req/hour limit)."""
    url = f"https://api.github.com{path}"
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "HappyBot/1.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as e:
        logger.debug(f"GitHub API failed for {path}: {e}")
        return None


def _load_watch_state() -> dict:
    """Load previous watch state for delta comparison."""
    if WATCH_STATE_FILE.exists():
        try:
            return json.loads(WATCH_STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_watch_state(state: dict):
    """Save current watch state."""
    WATCH_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    WATCH_STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8",
    )


def check_watched_repos() -> str:
    """Check watch_list repos for notable changes since last check.

    Tracks: star count delta, latest release, recent activity.
    Returns a markdown summary of changes, or empty string if nothing notable.
    """
    watch = _parse_watch_list()
    repos = watch.get("github_repos", [])
    if not repos:
        return ""

    prev_state = _load_watch_state()
    new_state = {}
    changes = []

    for repo in repos:
        data = _github_api(f"/repos/{repo}")
        if not data:
            continue

        stars = data.get("stargazers_count", 0)
        pushed_at = data.get("pushed_at", "")[:10]
        description = (data.get("description") or "")[:80]

        # Check latest release
        releases = _github_api(f"/repos/{repo}/releases?per_page=1")
        latest_release = ""
        if releases and isinstance(releases, list) and releases:
            latest_release = releases[0].get("tag_name", "")
            release_date = releases[0].get("published_at", "")[:10]
            latest_release = f"{latest_release} ({release_date})"

        # Build current state
        current = {
            "stars": stars,
            "latest_release": latest_release,
            "pushed_at": pushed_at,
        }
        new_state[repo] = current

        # Compare with previous state
        prev = prev_state.get(repo, {})
        notable = []

        prev_stars = prev.get("stars", 0)
        if prev_stars and stars - prev_stars >= 10:
            notable.append(f"⭐ +{stars - prev_stars} stars ({stars} total)")

        if latest_release and latest_release != prev.get("latest_release", ""):
            notable.append(f"🚀 新版本: {latest_release}")

        if pushed_at > prev.get("pushed_at", "") and pushed_at == date.today().isoformat():
            notable.append("📝 今日有更新")

        if notable:
            changes.append(f"**{repo}**: {'; '.join(notable)}")
        elif not prev:
            # First time tracking — record baseline
            changes.append(f"**{repo}**: 首次追踪 (⭐{stars}, {description})")

    _save_watch_state(new_state)

    if not changes:
        logger.info(f"Checked {len(repos)} repos, no notable changes")
        return ""

    result = "### 追踪仓库动态\n" + "\n".join(f"- {c}" for c in changes)
    logger.info(f"Watch list: {len(changes)} notable changes from {len(repos)} repos")
    return result


def score_vault_articles(today: str) -> list[dict]:
    """Score recent vault articles by quality and relevance.

    Returns list of {file, title, score, reason} sorted by score desc.
    Scores 1-10: 8+ = high value, 5-7 = medium, <5 = low.
    """
    articles_dir = VAULT_ARTICLES_DIR
    social_dir = VAULT_DIR / "social"
    recent_files = []

    for folder in [articles_dir, social_dir]:
        if not folder.exists():
            continue
        for f in folder.iterdir():
            if f.suffix == ".md" and f.name.startswith(today[:8]):  # Same month
                recent_files.append(f)

    if not recent_files:
        return []

    # Build article list for scoring
    article_summaries = []
    for f in sorted(recent_files, key=lambda x: x.stat().st_mtime, reverse=True)[:20]:
        content = f.read_text(encoding="utf-8")
        # Extract title from frontmatter
        title_match = re.search(r'title:\s*["\']?(.+?)["\']?\s*$', content, re.MULTILINE)
        title = title_match.group(1) if title_match else f.stem
        # Extract summary
        summary_match = re.search(r'summary:\s*["\']?(.+?)["\']?\s*$', content, re.MULTILINE)
        summary = summary_match.group(1) if summary_match else content[500:800]
        article_summaries.append({"file": str(f), "title": title, "summary": summary[:200]})

    if not article_summaries:
        return []

    summaries_text = "\n".join(
        f"{i+1}. [{a['title']}] {a['summary']}" for i, a in enumerate(article_summaries)
    )

    prompt = (
        "你是知识质量评估模块。对以下文章评分 (1-10)，基于：\n"
        "- 可复用性（能否直接用于我们的项目/工作流？）\n"
        "- 深度（是否有独到洞察，而非泛泛介绍？）\n"
        "- 时效性（是否涉及最新技术/趋势？）\n"
        "- 与我们相关性（AI工具、Claude生态、知识管理、内容创作）\n\n"
        f"文章列表：\n{summaries_text}\n\n"
        "输出 JSON 数组，每项：{\"index\": N, \"score\": X, \"reason\": \"一句话\"}\n"
        "只输出 JSON。"
    )

    result = _call_sonnet(prompt, timeout=60)
    try:
        json_match = re.search(r'\[[\s\S]*\]', result)
        if json_match:
            scores = json.loads(json_match.group())
            scored = []
            for s in scores:
                idx = s.get("index", 0) - 1
                if 0 <= idx < len(article_summaries):
                    scored.append({
                        **article_summaries[idx],
                        "score": s.get("score", 5),
                        "reason": s.get("reason", ""),
                    })
            scored.sort(key=lambda x: x["score"], reverse=True)
            logger.info(f"Scored {len(scored)} articles, top: {scored[0]['title']} ({scored[0]['score']}/10)" if scored else "No scores")
            return scored
    except (json.JSONDecodeError, IndexError) as e:
        logger.warning(f"Failed to parse article scores: {e}")
    return []


def synthesize_knowledge(today: str):
    """Cross-reference recent articles and memory to find patterns and connections.

    This is the 'thinking' step — connecting dots across sources.
    """
    # Read recent learnings and trends
    learnings = LEARNINGS_FILE.read_text(encoding="utf-8") if LEARNINGS_FILE.exists() else ""
    trends = TRENDS_FILE.read_text(encoding="utf-8") if TRENDS_FILE.exists() else ""

    # Read recent article titles
    article_titles = []
    for folder in [VAULT_ARTICLES_DIR, VAULT_DIR / "social"]:
        if not folder.exists():
            continue
        for f in sorted(folder.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True)[:15]:
            if f.suffix == ".md":
                content = f.read_text(encoding="utf-8")[:500]
                title_match = re.search(r'title:\s*["\']?(.+?)["\']?\s*$', content, re.MULTILINE)
                if title_match:
                    article_titles.append(title_match.group(1))

    if not article_titles:
        return

    titles_text = "\n".join(f"- {t}" for t in article_titles)

    prompt = (
        f"今天是 {today}。你是知识综合模块。\n\n"
        "任务：分析最近积累的知识，找出跨来源的规律和可行动的洞察。\n\n"
        f"最近文章标题：\n{titles_text}\n\n"
        f"最近趋势（最后 2000 字）：\n{trends[-2000:]}\n\n"
        f"最近学习（最后 1500 字）：\n{learnings[-1500:]}\n\n"
        "输出：\n"
        "## 知识连接\n"
        "- 找出 2-3 个跨文章/跨来源的共同主题或趋势\n\n"
        "## 行动建议\n"
        "- 基于综合分析，给出 2-3 个具体可行动的建议\n\n"
        "## 知识缺口\n"
        "- 指出 1-2 个我们应该关注但还没覆盖的领域\n\n"
        "简洁输出，每个小节 2-3 条即可。"
    )

    result = _call_sonnet(prompt, timeout=90)
    if result and len(result) > 50:
        synthesis_file = MEMORY_DIR / "knowledge-synthesis.md"
        _append_section(synthesis_file, f"## {today} - 知识综合\n{result}")
        logger.info("Knowledge synthesis written")


def run(report_path: str):
    """Main entry: deep absorb from a briefing report."""
    report_file = Path(report_path)
    if not report_file.exists():
        logger.error(f"Report file not found: {report_path}")
        return

    report_text = report_file.read_text(encoding="utf-8")
    if len(report_text) < 100:
        logger.warning("Report too short, skipping deep absorption")
        return

    today = date.today().isoformat()
    logger.info(f"Deep absorbing from {report_path} ({len(report_text)} chars)")

    # Step 1: Save full briefing to Obsidian vault
    try:
        save_briefing_to_vault(report_file, today)
    except Exception as e:
        logger.warning(f"Failed to save briefing to vault: {e}")

    # Step 2: Extract structured knowledge from the report
    extracted = deep_read_and_extract(report_text)

    # Step 3: Write to memory files (with dedup)
    write_to_memory(extracted)

    # Step 4: Score recent vault articles by quality
    try:
        scores = score_vault_articles(today)
        if scores:
            high_value = [s for s in scores if s["score"] >= 8]
            low_value = [s for s in scores if s["score"] <= 3]
            if high_value:
                logger.info(f"High-value articles ({len(high_value)}): " +
                           ", ".join(f"{s['title']}({s['score']})" for s in high_value[:3]))
            if low_value:
                logger.info(f"Low-value articles ({len(low_value)}): consider cleanup")
    except Exception as e:
        logger.warning(f"Article scoring failed (non-fatal): {e}")

    # Step 5: Extract content creation ideas (公众号/小红书素材)
    try:
        extract_content_ideas(report_text, today)
    except Exception as e:
        logger.warning(f"Failed to extract content ideas: {e}")

    # Step 6: Save evolution log to vault
    try:
        save_evolution_to_vault(today)
    except Exception as e:
        logger.warning(f"Failed to save evolution log: {e}")

    # Step 7: Check watched repos for notable changes
    try:
        watch_report = check_watched_repos()
        if watch_report:
            _append_section(TRENDS_FILE, f"## {today} - 追踪动态\n{watch_report}")
    except Exception as e:
        logger.warning(f"Watch list check failed (non-fatal): {e}")

    # Step 8: Cross-reference and synthesize knowledge
    try:
        synthesize_knowledge(today)
    except Exception as e:
        logger.warning(f"Knowledge synthesis failed (non-fatal): {e}")

    # Step 9: Compress trends if needed
    try:
        compress_trends()
    except Exception as e:
        logger.warning(f"Trends compression failed (non-fatal): {e}")

    logger.info("Deep absorption complete")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: deep_absorb.py <report_file>")
        sys.exit(1)
    run(sys.argv[1])
