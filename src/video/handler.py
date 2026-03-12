"""Video breakdown handler — /video commands + auto-analysis for Feishu bot.

Analyzes viral videos using Gemini 2.5 Flash (native video understanding).
Pipeline: yt-dlp download → Gemini File API upload → AI breakdown → Feishu reply.
"""

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import atexit

from src.utils.url_utils import detect_platform

logger = logging.getLogger(__name__)

BREAKDOWN_DIR = Path(
    os.environ.get(
        "VIDEO_BREAKDOWN_DIR",
        str(Path(__file__).parent.parent.parent / "data" / "video_breakdowns"),
    )
)

# Video URL patterns
VIDEO_URL_HINTS = (
    "douyin.com", "v.douyin.com", "iesdouyin.com",
    "xiaohongshu.com", "xhslink.com",
    "bilibili.com/video", "b23.tv",
    "youtube.com/watch", "youtu.be",
    "youtube.com/shorts",
)


def is_video_url(url: str) -> bool:
    """Check if URL likely points to a video."""
    lower = url.lower()
    return any(hint in lower for hint in VIDEO_URL_HINTS)


class VideoHandler:
    """Handle /video commands and auto-analyze video URLs."""

    # Bounded pool; cancel_futures=True in atexit prevents process hang on exit
    _executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="video")

    @classmethod
    def shutdown_executor(cls) -> None:
        cls._executor.shutdown(wait=False, cancel_futures=True)

    def __init__(self, sender):
        self.sender = sender
        BREAKDOWN_DIR.mkdir(parents=True, exist_ok=True)

    def handle_command(self, command: str, sender_id: str) -> None:
        """/video commands: analyze, trend, history, crawl, help."""
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
        elif sub in ("search", "搜索", "搜"):
            if args:
                self._search_and_analyze(args.strip(), sender_id)
            else:
                self.sender.send_text(sender_id, "用法: /video search <关键词> [平台]\n例: /video search 漱口水 douyin")
        elif sub in ("trend", "趋势"):
            self._show_trends(sender_id)
        elif sub in ("history", "历史", "记录"):
            self._show_history(sender_id)
        elif sub in ("crawl", "爬取"):
            self._manual_crawl(sender_id, args)
        else:
            # Treat as URL
            from src.utils.url_utils import extract_urls
            urls = extract_urls(command[len("/video"):].strip())
            if urls:
                self._analyze_url(urls[0], sender_id)
            else:
                self.sender.send_text(sender_id, f"未知子命令: {sub}\n发 /video help 查看用法")

    def auto_analyze(self, url: str, sender_id: str) -> None:
        """Auto-analyze a video URL dropped in group chat (non-blocking)."""
        self._executor.submit(self._analyze_pipeline, url, sender_id)

    def _search_and_analyze(self, args: str, sender_id: str) -> None:
        """Search videos by keyword, then analyze the best match."""
        # Parse: "<keyword> [platform]"
        parts = args.rsplit(maxsplit=1)
        platform = ""
        keyword = args

        # Check if last word is a platform name
        platform_aliases = {
            "douyin": "douyin", "抖音": "douyin",
            "xiaohongshu": "xiaohongshu", "小红书": "xiaohongshu", "xhs": "xiaohongshu",
            "bilibili": "bilibili", "b站": "bilibili",
            "youtube": "youtube", "yt": "youtube",
        }
        if len(parts) > 1 and parts[-1].lower() in platform_aliases:
            platform = platform_aliases[parts[-1].lower()]
            keyword = parts[0]

        self.sender.send_text(
            sender_id,
            f"🔍 搜索: {keyword}" + (f" [{platform}]" if platform else " [全平台]") + "\n搜索中...",
        )

        def _run():
            try:
                from src.video.crawler import search_videos
                results = search_videos(keyword, platform=platform, count=5)

                if not results:
                    self.sender.send_text(sender_id, f"没有找到 '{keyword}' 相关视频")
                    return

                # Show search results
                lines = [f"找到 {len(results)} 个视频:"]
                for i, r in enumerate(results):
                    title = r.get("title", "")[:40] or r["url"][:60]
                    dur = r.get("duration", 0)
                    dur_str = f" [{dur}s]" if dur else ""
                    lines.append(f"  {i+1}. [{r['platform']}]{dur_str} {title}")
                lines.append(f"\n自动拆解第 1 个...")
                self.sender.send_text(sender_id, "\n".join(lines))

                # Analyze the first result
                self._analyze_pipeline(results[0]["url"], sender_id)

            except Exception as e:
                logger.exception("Search and analyze error")
                self.sender.send_text(sender_id, f"搜索失败: {str(e)[:200]}")

        self._executor.submit(_run)

    def _analyze_url(self, url: str, sender_id: str) -> None:
        """Analyze a video URL with full Gemini video understanding."""
        self.sender.send_text(
            sender_id,
            f"正在下载并拆解视频...\n{url[:80]}\n\n"
            "下载 + Gemini 分析，预计 1-2 分钟",
        )
        self._executor.submit(self._analyze_pipeline, url, sender_id)

    def _analyze_pipeline(self, url: str, sender_id: str) -> None:
        """Full pipeline: download → Gemini analysis → save → reply."""
        from src.video.downloader import download
        from src.video.analyzer import analyze_video

        try:
            # Step 1: Download video + extract metadata
            platform = detect_platform(url)
            logger.info(f"Video pipeline start: [{platform}] {url}")
            info = download(url, platform)

            if not info.title:
                info.title = "未知视频"

            has_video = bool(info.video_path)
            mode = "视频画面+音频" if has_video else "仅元数据（下载失败）"
            logger.info(f"Analysis mode: {mode} | {info.title}")

            # Step 2: Gemini analysis
            result = analyze_video(info)

            if result.error:
                self.sender.send_text(
                    sender_id,
                    f"拆解失败: {result.error[:200]}\n视频: {info.title}",
                )
                return

            # Step 3: Save breakdown
            self._save_breakdown(result)

            # Step 4: Format and send result
            report = self._format_report(result, has_video)
            self._send_long_text(sender_id, report)

            # Step 5: Cleanup video file after analysis
            if info.video_path:
                try:
                    Path(info.video_path).unlink(missing_ok=True)
                except OSError as e:
                    logger.warning("Failed to delete video file %s: %s", info.video_path, e)

        except Exception as e:
            logger.exception("Video pipeline error")
            self.sender.send_text(sender_id, f"拆解异常: {str(e)[:200]}")

    def _format_report(self, result, has_video: bool) -> str:
        """Format BreakdownResult into readable Feishu message."""
        bd = result.breakdown_json
        if not bd or bd.get("parse_error"):
            return f"拆解结果 (原始):\n{bd.get('raw_response', '无内容')[:3000]}"

        lines = []
        mode_tag = "🎬" if has_video else "📝"
        lines.append(f"{mode_tag} 爆款拆解: {result.title}")
        lines.append(f"{'='*30}")

        # Basic info
        basic = bd.get("basic_info", {})
        if basic:
            metrics = basic.get("metrics", {})
            lines.append(
                f"平台: {basic.get('platform', result.platform)} | "
                f"作者: {basic.get('author', '')} | "
                f"时长: {basic.get('duration_seconds', 0)}s"
            )
            if metrics:
                parts = []
                for label, key in [("播放", "views"), ("赞", "likes"), ("评论", "comments")]:
                    val = metrics.get(key)
                    if val:
                        try:
                            parts.append(f"{label} {int(val):,}")
                        except (ValueError, TypeError):
                            parts.append(f"{label} {val}")
                if parts:
                    lines.append(" | ".join(parts))
        lines.append("")

        # Hook
        hook = bd.get("hook", {})
        if hook:
            lines.append(f"**钩子** ({hook.get('type', '?')}) — 强度: {hook.get('hook_strength', '?')}/10")
            if hook.get("first_3s_description"):
                lines.append(f"  前3秒: {hook['first_3s_description']}")
            if hook.get("hook_technique"):
                lines.append(f"  技巧: {hook['hook_technique']}")
            lines.append("")

        # Structure timeline
        structure = bd.get("structure", {})
        if structure:
            lines.append(f"**结构**: {structure.get('type', '?')}")
            for seg in structure.get("timeline", []):
                lines.append(f"  {seg.get('time', '')} [{seg.get('element', '')}] {seg.get('description', '')}")
            lines.append("")

        # Visual + Audio (compact)
        visual = bd.get("visual", {})
        audio = bd.get("audio", {})
        if visual:
            lines.append(f"**视觉**: {visual.get('style', '')} | {visual.get('camera_work', '')}")
        if audio:
            lines.append(f"**音频**: {audio.get('bgm_description', '')} | {audio.get('voice_type', '')}")
        if visual or audio:
            lines.append("")

        # Reusable elements
        reusable = bd.get("reusable_elements", {})
        if reusable:
            can_rep = reusable.get("can_replicate", [])
            if can_rep:
                lines.append("**可复用**: " + "、".join(can_rep[:5]))
            needs_adapt = reusable.get("needs_adaptation", [])
            if needs_adapt:
                lines.append("**需改造**: " + "、".join(needs_adapt[:3]))
            lines.append("")

        # Score
        score = bd.get("overall_score", {})
        if isinstance(score, dict) and score.get("total"):
            score_parts = []
            for k in ("hook", "content", "visual", "audio", "engagement"):
                if score.get(k):
                    score_parts.append(f"{k}:{score[k]}")
            lines.append(f"**评分**: {' | '.join(score_parts)} → **总分 {score['total']}**")
            lines.append("")

        # Summary
        summary = bd.get("one_sentence_summary", result.summary)
        if summary:
            lines.append(f"**一句话**: {summary}")

        if not has_video:
            lines.append("\n⚠️ 视频下载失败，以上为元数据推测分析")

        return "\n".join(lines)

    def _save_breakdown(self, result) -> Path:
        """Save breakdown to JSONL for trend analysis."""
        entry = {
            "ts": result.analyzed_at,
            "date": date.today().isoformat(),
            "url": result.url,
            "title": result.title,
            "platform": result.platform,
            "total_score": result.total_score,
            "summary": result.summary,
            "breakdown": result.breakdown_json,
            "video_info": result.video_info,
        }
        filepath = BREAKDOWN_DIR / f"{date.today().isoformat()}.jsonl"
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        logger.info(f"Breakdown saved: {result.title} → {filepath}")
        return filepath

    def _show_trends(self, sender_id: str) -> None:
        """Trend analysis using Gemini on accumulated breakdowns."""
        from src.video.analyzer import analyze_trends

        breakdowns = self._load_recent_breakdowns(days=7, limit=50)
        if not breakdowns:
            self.sender.send_text(sender_id, "还没有视频拆解记录。先丢几个视频链接进来！")
            return

        self.sender.send_text(sender_id, f"正在分析 {len(breakdowns)} 条拆解记录的趋势...")

        def _run():
            try:
                trend_data = [b.get("breakdown", {}) for b in breakdowns if b.get("breakdown")]
                result = analyze_trends(trend_data)
                report = self._format_trend_report(result, len(breakdowns))
                self._send_long_text(sender_id, report)
            except Exception as e:
                logger.exception("Trend analysis error")
                self.sender.send_text(sender_id, f"趋势分析异常: {str(e)[:200]}")

        self._executor.submit(_run)

    def _format_trend_report(self, data: dict, sample_size: int) -> str:
        lines = [f"📊 爆款趋势分析 ({sample_size} 条样本)", "=" * 30, ""]

        scope = data.get("analysis_scope", {})
        if scope:
            lines.append(f"范围: {scope.get('category', '')} | {scope.get('period', '')}")
            lines.append("")

        patterns = data.get("trending_patterns", {})
        if patterns:
            hooks = patterns.get("hook_types", [])
            if hooks:
                lines.append("**热门钩子类型**:")
                for h in hooks[:5]:
                    lines.append(f"  • {h.get('type', '?')} ({h.get('frequency', '?')})")
            structs = patterns.get("structure_types", [])
            if structs:
                lines.append("**视频结构趋势**:")
                for s in structs[:5]:
                    lines.append(f"  • {s.get('type', '?')} ({s.get('frequency', '?')})")
            if patterns.get("duration_sweet_spot"):
                lines.append(f"**最优时长**: {patterns['duration_sweet_spot']}")
            lines.append("")

        gaps = data.get("content_gaps", [])
        if gaps:
            lines.append("**内容空白/机会点**:")
            for g in gaps[:5]:
                lines.append(f"  • {g}")
            lines.append("")

        recs = data.get("creation_recommendations", [])
        if recs:
            lines.append("**创作建议**:")
            for r in recs[:3]:
                lines.append(f"  {r.get('priority', '?')}. {r.get('suggestion', '?')}")
                if r.get("expected_impact"):
                    lines.append(f"     预期: {r['expected_impact']}")
            lines.append("")

        if data.get("weekly_summary"):
            lines.append(f"**本周一句话**: {data['weekly_summary']}")

        return "\n".join(lines)

    def _show_history(self, sender_id: str) -> None:
        """Show recent video breakdown history."""
        entries = self._load_recent_breakdowns(days=3, limit=10)
        if not entries:
            self.sender.send_text(sender_id, "还没有视频拆解记录。")
            return

        lines = [f"最近 {len(entries)} 条拆解记录:\n"]
        for e in entries:
            ts = e.get("ts", "")[:16].replace("T", " ")
            score = e.get("total_score", 0)
            score_str = f" ⭐{score}" if score else ""
            lines.append(
                f"• [{e.get('platform', '?')}] {e.get('title', '?')[:30]}{score_str}\n"
                f"  {e.get('summary', '')[:60]}\n"
                f"  {ts}"
            )
        self.sender.send_text(sender_id, "\n".join(lines))

    def _manual_crawl(self, sender_id: str, args: str) -> None:
        """Trigger manual crawl of trending videos."""
        self.sender.send_text(sender_id, "正在抓取热门视频...")

        def _run():
            try:
                from src.video.crawler import crawl_trending
                results = crawl_trending(
                    platform=args.strip() if args else "douyin",
                    count=10,
                )
                self.sender.send_text(
                    sender_id,
                    f"抓取完成，获取 {len(results)} 条热门视频\n"
                    f"自动分析已启动，结果会陆续发送",
                )
                for url in results[:5]:
                    self._executor.submit(self._analyze_pipeline, url, sender_id)
            except ImportError:
                self.sender.send_text(sender_id, "爬虫模块未就绪，请先用 /video analyze <链接> 手动分析")
            except Exception as e:
                self.sender.send_text(sender_id, f"抓取失败: {str(e)[:200]}")

        self._executor.submit(_run)

    def _load_recent_breakdowns(self, days: int = 7, limit: int = 50) -> list[dict]:
        """Load recent breakdown entries from JSONL files."""
        entries = []
        for f in sorted(BREAKDOWN_DIR.glob("*.jsonl"), reverse=True)[:days]:
            try:
                for line in f.read_text(encoding="utf-8").strip().split("\n"):
                    if line.strip():
                        entries.append(json.loads(line))
            except (OSError, json.JSONDecodeError, ValueError) as e:
                logger.warning("Failed to read breakdown file %s: %s", f, e)
        return entries[:limit]

    def _send_long_text(self, sender_id: str, text: str) -> None:
        """Send long text, splitting if needed."""
        max_len = 3800
        if len(text) <= max_len:
            self.sender.send_text(sender_id, text)
            return

        parts = []
        while text:
            if len(text) <= max_len:
                parts.append(text)
                break
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
            "  /video analyze <链接>     — Gemini 深度拆解（下载视频+AI看片）\n"
            "  /video <链接>             — 快速拆解\n"
            "  /video search <关键词>    — 搜索视频并拆解\n"
            "  /video search 漱口水 抖音 — 指定平台搜索\n"
            "  /video trend              — 本周爆款趋势分析\n"
            "  /video history            — 查看拆解记录\n"
            "  /video crawl [平台]       — 抓取热门视频\n\n"
            "也可以直接丢视频链接进群，bot 自动拆解！\n\n"
            "支持平台: 抖音、小红书、B站、YouTube\n"
            "搜索引擎: 抖音/小红书用 Brave，B站/YouTube 用 yt-dlp\n"
            "分析引擎: Gemini 2.5 Flash（原生视频理解）",
        )


atexit.register(VideoHandler.shutdown_executor)
