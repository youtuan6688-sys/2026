#!/usr/bin/env python3
"""Weekly knowledge synthesis — connects dots across all sources.

Runs every Sunday at 11pm PST (Monday 3pm Beijing).
Reads: vault articles, memory files, group observations, briefing digests.
Outputs: weekly synthesis report to vault + memory update.

Usage: python scripts/weekly_synthesis.py
"""

import json
import logging
import os
import re
import subprocess
from datetime import date, timedelta
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)

PROJECT_DIR = Path("/Users/tuanyou/Happycode2026")
VAULT_DIR = PROJECT_DIR / "vault"
MEMORY_DIR = VAULT_DIR / "memory"
CLAUDE_PATH = os.environ.get("CLAUDE_PATH", "claude")


def _call_sonnet(prompt: str, timeout: int = 120) -> str:
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    env["PATH"] = f"/Users/tuanyou/.local/bin:{env.get('PATH', '')}"
    result = subprocess.run(
        [CLAUDE_PATH, "-p", prompt, "--model", "sonnet",
         "--output-format", "text"],
        capture_output=True, text=True, timeout=timeout, env=env,
    )
    return result.stdout.strip()


def gather_week_articles(days: int = 7) -> list[dict]:
    """Gather articles from the past N days."""
    cutoff = date.today() - timedelta(days=days)
    articles = []

    for folder in [VAULT_DIR / "articles", VAULT_DIR / "social"]:
        if not folder.exists():
            continue
        for f in folder.iterdir():
            if not f.suffix == ".md":
                continue
            # Check modification time
            mtime = date.fromtimestamp(f.stat().st_mtime)
            if mtime < cutoff:
                continue

            content = f.read_text(encoding="utf-8")
            title_match = re.search(r'title:\s*["\']?(.+?)["\']?\s*$', content, re.MULTILINE)
            summary_match = re.search(r'summary:\s*["\']?(.+?)["\']?\s*$', content, re.MULTILINE)
            tags_match = re.findall(r'^\s+-\s+(.+)$', content[:1000], re.MULTILINE)

            articles.append({
                "title": title_match.group(1) if title_match else f.stem,
                "summary": summary_match.group(1) if summary_match else "",
                "tags": tags_match[:5],
                "date": mtime.isoformat(),
                "file": f.name,
            })

    articles.sort(key=lambda x: x["date"], reverse=True)
    return articles


def gather_week_memory() -> dict:
    """Gather memory file contents from the past week."""
    result = {}
    for name in ["learnings.md", "trends.md", "decisions.md", "briefing-digest.md",
                  "knowledge-synthesis.md"]:
        filepath = MEMORY_DIR / name
        if filepath.exists():
            content = filepath.read_text(encoding="utf-8")
            # Only take recent sections (last 3000 chars)
            result[name] = content[-3000:]
    return result


def gather_group_observations() -> str:
    """Gather recent group chat observations."""
    groups_dir = MEMORY_DIR / "groups"
    if not groups_dir.exists():
        return ""

    observations = []
    for f in groups_dir.iterdir():
        if not f.suffix == ".json":
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            for obs in data.get("observations", [])[-10:]:
                observations.append(f"[{obs.get('date', '?')}] {obs.get('content', '')}")
        except (json.JSONDecodeError, KeyError):
            continue

    return "\n".join(observations[-20:])


def run_synthesis():
    """Main weekly synthesis."""
    today = date.today().isoformat()
    logger.info(f"Running weekly synthesis for week ending {today}")

    # Gather data
    articles = gather_week_articles()
    memory = gather_week_memory()
    group_obs = gather_group_observations()

    if not articles and not memory:
        logger.info("No data to synthesize")
        return

    # Build context
    article_text = "\n".join(
        f"- [{a['title']}] ({a['date']}) {a['summary'][:100]}"
        for a in articles[:25]
    )

    memory_text = "\n\n".join(
        f"### {name}\n{content[-1500:]}"
        for name, content in memory.items()
    )

    prompt = (
        f"今天是 {today}。你是 AI 助手的周度知识综合模块。\n\n"
        "分析本周所有积累的知识，生成一份周度综合报告。\n\n"
        f"## 本周文章 ({len(articles)} 篇)\n{article_text}\n\n"
        f"## 记忆文件摘要\n{memory_text}\n\n"
        f"## 群聊观察\n{group_obs or '无'}\n\n"
        "请输出以下格式的报告：\n\n"
        "# 周度知识综合\n\n"
        "## 1. 本周核心主题 (3-5 个)\n"
        "每个主题：标题 + 相关文章 + 一句话洞察\n\n"
        "## 2. 知识质量评估\n"
        "- 高价值知识（可直接行动）\n"
        "- 中等价值（参考备用）\n"
        "- 低价值/重复（建议清理）\n\n"
        "## 3. 进化建议\n"
        "- 基于本周积累，下周应该：\n"
        "  - 重点关注什么领域\n"
        "  - 哪些知识缺口需要补充\n"
        "  - 哪些来源产出最高\n"
        "  - 建议新增的信息源\n\n"
        "## 4. 内容创作池 (Top 3)\n"
        "从本周知识中提炼最有传播价值的内容方向\n\n"
        "## 5. 群聊需求洞察\n"
        "从群友互动中发现的需求、痛点、兴趣点\n\n"
        "简洁有力，每节 3-5 条。"
    )

    result = _call_sonnet(prompt, timeout=180)
    if not result or len(result) < 100:
        logger.warning("Synthesis output too short, skipping")
        return

    # Save to vault
    report_file = VAULT_DIR / "logs" / f"weekly-synthesis-{today}.md"
    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text(
        f"---\ntitle: \"周度知识综合 {today}\"\n"
        f"source: weekly-synthesis\ndate_saved: {today}\n"
        f"tags:\n  - 周报\n  - 知识综合\n  - 进化\ncategory: synthesis\n---\n\n"
        f"{result}\n",
        encoding="utf-8",
    )
    logger.info(f"Weekly synthesis saved: {report_file}")

    # Extract evolution suggestions and save to memory
    evolution_section = ""
    if "## 3. 进化建议" in result:
        match = re.search(r'## 3\. 进化建议\n(.*?)(?=\n## |\Z)', result, re.DOTALL)
        if match:
            evolution_section = match.group(1).strip()

    if evolution_section:
        synthesis_file = MEMORY_DIR / "knowledge-synthesis.md"
        header = f"## {today} - 周度进化建议"
        # Dedup check
        if synthesis_file.exists():
            existing = synthesis_file.read_text(encoding="utf-8")
            if header in existing:
                logger.info("Weekly evolution suggestions already written, skipping")
                return

        with open(synthesis_file, "a", encoding="utf-8") as f:
            f.write(f"\n\n{header}\n{evolution_section}\n")
        logger.info("Evolution suggestions saved to knowledge-synthesis.md")

    # Compress old daily synthesis entries (keep last 7 days + this weekly)
    _compress_daily_synthesis()


def _compress_daily_synthesis():
    """Remove daily synthesis entries older than 7 days (weekly replaces them)."""
    synthesis_file = MEMORY_DIR / "knowledge-synthesis.md"
    if not synthesis_file.exists():
        return

    content = synthesis_file.read_text(encoding="utf-8")
    if len(content) < 5000:
        return  # Not big enough to need compression

    cutoff = (date.today() - timedelta(days=7)).isoformat()
    sections = re.split(r'(?=## \d{4}-\d{2}-\d{2})', content)
    kept = []
    for section in sections:
        date_match = re.match(r'## (\d{4}-\d{2}-\d{2})', section)
        if not date_match or date_match.group(1) >= cutoff or "周度" in section:
            kept.append(section)

    new_content = "".join(kept)
    if len(new_content) < len(content):
        synthesis_file.write_text(new_content, encoding="utf-8")
        logger.info(f"Compressed knowledge-synthesis.md: {len(content)} → {len(new_content)} chars")


if __name__ == "__main__":
    run_synthesis()
