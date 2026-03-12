"""Video breakdown handler — /video command + auto-analysis for Feishu bot.

Analyzes viral videos from douyin/xiaohongshu/bilibili/youtube links.
Uses Claude (sonnet) for deep content analysis based on video metadata.
"""

import json
import logging
import threading
from datetime import date, datetime
from pathlib import Path

from src.parsers import get_parser
from src.utils.url_utils import detect_platform

logger = logging.getLogger(__name__)

# Where breakdown results are stored
BREAKDOWN_DIR = Path("/Users/tuanyou/Happycode2026/data/video_breakdowns")
PROMPT_PATH = Path("/Users/tuanyou/Happycode2026/projects/viral-video-analyzer/prompts/video_breakdown.md")
TREND_PROMPT_PATH = Path("/Users/tuanyou/Happycode2026/projects/viral-video-analyzer/prompts/trend_analysis.md")

# Platforms that contain video content worth analyzing
VIDEO_PLATFORMS = frozenset({"douyin", "xiaohongshu", "bilibili", "youtube", "generic"})

# Video URL patterns (broader than platform detection — catches short links)
VIDEO_URL_HINTS = (
    "douyin.com", "v.douyin.com", "iesdouyin.com",
    "xiaohongshu.com", "xhslink.com",
    "bilibili.com/video", "b23.tv",
    "youtube.com/watch", "youtu.be",
    "youtube.com/shorts",
)


def is_video_url(url: str) -> bool:
    """Check if URL likely points to a video (not music, not article)."""
    lower = url.lower()
    return any(hint in lower for hint in VIDEO_URL_HINTS)


class VideoHandler:
    """Handle /video commands and auto-analyze video URLs in group chat."""

    def __init__(self, sender, quota_tracker):
        self.sender = sender
        self.quota = quota_tracker
        BREAKDOWN_DIR.mkdir(parents=True, exist_ok=True)

    def handle_command(self, command: str, sender_id: str) -> None:
        """Handle /video commands.

        Usage:
            /video              — show help
            /video analyze <url> — deep breakdown of a video
            /video trend        — this week's viral trends summary
            /video history      — recent breakdowns
        """
        parts = command.strip().split(maxsplit=2)

        if len(parts) < 2:
            self._send_help(sender_id)
            return

        sub = parts[1].strip().lower()
        args = parts[2] if len(parts) > 2 else ""

        if sub in ("help", "帮助"):
            self._send_help(sender_id)
        elif sub in ("analyze", "分析", "拆解"):
            if args:
                self._analyze_url(args.strip(), sender_id)
            else:
                self.sender.send_text(sender_id, "用法: /video analyze <视频链接>")
        elif sub in ("trend", "趋势"):
            self._show_trends(sender_id)
        elif sub in ("history", "历史", "记录"):
            self._show_history(sender_id)
        else:
            # Treat as URL if it looks like one
            full_arg = command[len("/video"):].strip()
            from src.utils.url_utils import extract_urls
            urls = extract_urls(full_arg)
            if urls:
                self._analyze_url(urls[0], sender_id)
            else:
                self.sender.send_text(
                    sender_id,
                    f"未知子命令: {sub}\n发 /video help 查看用法",
                )

    def auto_analyze(self, url: str, sender_id: str) -> None:
        """Auto-analyze a video URL dropped in group chat (non-blocking)."""
        thread = threading.Thread(
            target=self._analyze_pipeline,
            args=(url, sender_id, False),
            daemon=True,
        )
        thread.start()

    def _analyze_url(self, url: str, sender_id: str) -> None:
        """Analyze a video URL (deep mode, blocking notification)."""
        self.sender.send_text(
            sender_id,
            f"正在拆解视频...\n{url[:80]}\n\n预计 30-60s，请稍等",
        )
        thread = threading.Thread(
            target=self._analyze_pipeline,
            args=(url, sender_id, True),
            daemon=True,
        )
        thread.start()

    def _analyze_pipeline(self, url: str, sender_id: str, deep: bool) -> None:
        """Background pipeline: fetch metadata → Claude analysis → save & reply."""
        try:
            # Step 1: Fetch video metadata via parser
            platform = detect_platform(url)
            parser = get_parser(platform)
            parsed = parser.parse(url)

            title = parsed.title or "未知视频"
            content = parsed.content or ""
            author = parsed.author or "未知"
            metadata = parsed.metadata or {}

            # Step 2: Build analysis prompt
            breakdown_prompt = self._load_prompt()
            video_info = (
                f"视频信息:\n"
                f"- 标题: {title}\n"
                f"- 作者: {author}\n"
                f"- 平台: {platform}\n"
                f"- 链接: {url}\n"
                f"- 描述/文案: {content[:2000]}\n"
            )

            if metadata:
                video_info += f"- 元数据: {json.dumps(metadata, ensure_ascii=False)[:500]}\n"

            analysis_depth = "深度拆解" if deep else "快速拆解"
            full_prompt = (
                f"{breakdown_prompt}\n\n"
                f"---\n\n"
                f"请对以下视频进行{analysis_depth}:\n\n"
                f"{video_info}\n\n"
                f"注意:\n"
                f"- 你无法直接观看视频，请根据标题、文案、平台等信息推断分析\n"
                f"- 推测性结论请标注「⚠️ 推测」\n"
                f"- 输出格式用中文 markdown（不要 JSON），方便在飞书群内阅读\n"
                f"- {'包含完整维度分析' if deep else '重点分析钩子、结构、可复用元素三个维度'}"
            )

            # Step 3: Call Claude for analysis
            output = self.quota.call_claude(
                full_prompt, "sonnet", timeout=120,
                extra_args=["--permission-mode", "auto", "--verbose"],
            )

            if not output:
                self.sender.send_text(sender_id, f"拆解失败，AI 无返回\n视频: {title}")
                return

            # Step 4: Save breakdown
            self._save_breakdown(url, title, platform, author, output)

            # Step 5: Send result
            header = f"🎬 爆款拆解: {title}\n作者: {author} | 平台: {platform}\n{'='*30}\n\n"
            self._send_long_text(sender_id, header + output)

        except Exception as e:
            logger.exception(f"Video analysis pipeline error: {e}")
            self.sender.send_text(sender_id, f"拆解异常: {str(e)[:200]}")

    def _load_prompt(self) -> str:
        """Load the video breakdown prompt template."""
        try:
            return PROMPT_PATH.read_text(encoding="utf-8")
        except FileNotFoundError:
            return (
                "你是一位资深短视频内容策略师。请从以下维度拆解视频:\n"
                "1. 钩子（前3秒）\n2. 结构（时间线）\n3. 画面\n"
                "4. 音频\n5. 文案\n6. 可复用元素\n7. 评分与一句话总结"
            )

    def _save_breakdown(self, url: str, title: str, platform: str,
                        author: str, analysis: str) -> Path:
        """Save breakdown to JSONL file for trend analysis."""
        entry = {
            "ts": datetime.now().isoformat(),
            "date": date.today().isoformat(),
            "url": url,
            "title": title,
            "platform": platform,
            "author": author,
            "analysis": analysis[:5000],
        }
        filepath = BREAKDOWN_DIR / f"{date.today().isoformat()}.jsonl"
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        logger.info(f"Video breakdown saved: {title} → {filepath}")
        return filepath

    def _show_trends(self, sender_id: str) -> None:
        """Show weekly trend analysis from accumulated breakdowns."""
        # Collect recent breakdowns
        breakdowns = []
        for f in sorted(BREAKDOWN_DIR.glob("*.jsonl"), reverse=True)[:7]:
            try:
                for line in f.read_text(encoding="utf-8").strip().split("\n"):
                    if line.strip():
                        breakdowns.append(json.loads(line))
            except Exception as e:
                logger.warning(f"Failed to read breakdown file {f}: {e}")

        if not breakdowns:
            self.sender.send_text(
                sender_id,
                "还没有视频拆解记录。\n先丢几个视频链接进来让我拆解吧！",
            )
            return

        self.sender.send_text(
            sender_id,
            f"正在分析 {len(breakdowns)} 条拆解记录的趋势...",
        )

        # Build trend prompt
        try:
            trend_prompt = TREND_PROMPT_PATH.read_text(encoding="utf-8")
        except FileNotFoundError:
            trend_prompt = "请分析以下视频拆解数据，提取共性模式和趋势信号。"

        summaries = []
        for b in breakdowns[:30]:
            summaries.append(
                f"- [{b.get('platform', '?')}] {b.get('title', '?')} "
                f"(by {b.get('author', '?')})\n"
                f"  {b.get('analysis', '')[:300]}"
            )

        full_prompt = (
            f"{trend_prompt}\n\n"
            f"---\n\n"
            f"最近 {len(breakdowns)} 条视频拆解摘要:\n\n"
            f"{''.join(summaries)}\n\n"
            f"请用中文 markdown 输出趋势分析报告，重点:\n"
            f"1. 当前热门钩子类型\n"
            f"2. 视频结构趋势\n"
            f"3. 内容空白/机会点\n"
            f"4. 具体创作建议（3条）"
        )

        def _run():
            try:
                output = self.quota.call_claude(
                    full_prompt, "sonnet", timeout=120,
                    extra_args=["--permission-mode", "auto", "--verbose"],
                )
                if output:
                    self._send_long_text(
                        sender_id,
                        f"📊 爆款趋势分析 ({len(breakdowns)} 条样本)\n{'='*30}\n\n{output}",
                    )
                else:
                    self.sender.send_text(sender_id, "趋势分析失败，AI 无返回")
            except Exception as e:
                logger.exception(f"Trend analysis error: {e}")
                self.sender.send_text(sender_id, f"趋势分析异常: {str(e)[:200]}")

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()

    def _show_history(self, sender_id: str) -> None:
        """Show recent video breakdown history."""
        entries = []
        for f in sorted(BREAKDOWN_DIR.glob("*.jsonl"), reverse=True)[:3]:
            try:
                for line in f.read_text(encoding="utf-8").strip().split("\n"):
                    if line.strip():
                        entries.append(json.loads(line))
            except Exception:
                pass

        if not entries:
            self.sender.send_text(sender_id, "还没有视频拆解记录。")
            return

        lines = [f"最近 {len(entries)} 条拆解记录:\n"]
        for e in entries[:10]:
            ts = e.get("ts", "")[:16].replace("T", " ")
            lines.append(
                f"• [{e.get('platform', '?')}] {e.get('title', '?')[:30]}\n"
                f"  作者: {e.get('author', '?')} | {ts}"
            )
        self.sender.send_text(sender_id, "\n".join(lines))

    def _send_long_text(self, sender_id: str, text: str) -> None:
        """Send long text, splitting if needed (飞书 limit ~4000 chars)."""
        max_len = 3800
        if len(text) <= max_len:
            self.sender.send_text(sender_id, text)
            return

        parts = []
        while text:
            if len(text) <= max_len:
                parts.append(text)
                break
            # Find a good split point
            split_at = text.rfind("\n", 0, max_len)
            if split_at < max_len // 2:
                split_at = max_len
            parts.append(text[:split_at])
            text = text[split_at:].lstrip("\n")

        for i, part in enumerate(parts):
            if len(parts) > 1:
                part = f"[{i+1}/{len(parts)}]\n{part}"
            self.sender.send_text(sender_id, part)

    def _send_help(self, sender_id: str) -> None:
        self.sender.send_text(
            sender_id,
            "🎬 爆款视频拆解命令:\n\n"
            "  /video analyze <链接>  — 深度拆解一个视频\n"
            "  /video <链接>          — 快速拆解\n"
            "  /video trend           — 本周爆款趋势分析\n"
            "  /video history         — 查看拆解记录\n\n"
            "也可以直接丢视频链接进群，bot 自动拆解！\n\n"
            "支持平台: 抖音、小红书、B站、YouTube",
        )
