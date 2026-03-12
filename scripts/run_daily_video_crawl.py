"""Daily video crawl: fetch trending → download → Gemini analyze → save."""

import json
import logging
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.video.crawler import crawl_trending
from src.video.downloader import download, cleanup_old_videos
from src.video.analyzer import analyze_video

BREAKDOWN_DIR = Path(__file__).parent.parent / "data" / "video_breakdowns"

logger = logging.getLogger("daily_crawl")


def save_breakdown(result) -> None:
    """Save analysis result to daily JSONL file."""
    BREAKDOWN_DIR.mkdir(parents=True, exist_ok=True)
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
        "source": "daily_crawl",
    }
    filepath = BREAKDOWN_DIR / f"{date.today().isoformat()}.jsonl"
    with open(filepath, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    # Cleanup old video files first
    deleted = cleanup_old_videos(max_age_days=3)
    if deleted:
        logger.info("Cleaned up %d old video files", deleted)

    # Crawl each platform
    all_urls: list[tuple[str, str]] = []  # (url, platform)
    for platform in ["douyin", "xiaohongshu", "bilibili"]:
        try:
            urls = crawl_trending(platform, count=10)
            logger.info("%s: got %d URLs", platform, len(urls))
            all_urls.extend((u, platform) for u in urls)
        except Exception:
            logger.exception("%s crawl failed", platform)

    logger.info("Total URLs to analyze: %d", len(all_urls))

    # Analyze top 5 (to stay within Gemini free tier)
    for i, (url, platform) in enumerate(all_urls[:5]):
        info = None
        try:
            logger.info("Analyzing %d/5: %s", i + 1, url[:80])
            info = download(url, platform)
            result = analyze_video(info)
            if result.error:
                logger.warning("Analysis failed: %s", result.error[:100])
            else:
                logger.info("Done: %s (score: %s)", result.title, result.total_score)
                save_breakdown(result)
        except Exception:
            logger.exception("Failed to analyze %s", url[:50])
        finally:
            # Cleanup video file
            if info and info.video_path:
                try:
                    Path(info.video_path).unlink(missing_ok=True)
                except OSError as e:
                    logger.warning("Failed to delete %s: %s", info.video_path, e)

    logger.info("Daily video crawl complete")


if __name__ == "__main__":
    main()
