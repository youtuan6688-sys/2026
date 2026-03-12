"""Video downloader using yt-dlp. Supports douyin, xiaohongshu, bilibili, youtube."""

import json
import logging
import subprocess
import time
from pathlib import Path

from src.video.models import VideoInfo

logger = logging.getLogger(__name__)

YT_DLP = "/opt/homebrew/bin/yt-dlp"
DOWNLOAD_DIR = Path("/Users/tuanyou/Happycode2026/data/video_raw")
MAX_DURATION = 600       # 10 min
MAX_FILE_SIZE_MB = 100   # Gemini File API limit
PREFERRED_FORMAT = "bestvideo[height<=720]+bestaudio/best[height<=720]/best"

# Platform-specific yt-dlp options
_PLATFORM_OPTS: dict[str, list[str]] = {
    "douyin": ["--no-check-certificates"],
    "xiaohongshu": ["--no-check-certificates"],
    "bilibili": [],
    "youtube": [],
}


def download(url: str, platform: str = "generic") -> VideoInfo:
    """Download video and extract metadata. Returns VideoInfo with video_path set."""
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    info = _extract_info(url, platform)

    # Check duration
    if info.duration > MAX_DURATION:
        info.video_path = ""
        logger.warning(f"Video too long ({info.duration}s > {MAX_DURATION}s): {url}")
        return info

    # Download
    output_template = str(DOWNLOAD_DIR / "%(id)s.%(ext)s")
    cmd = [
        YT_DLP,
        "--format", PREFERRED_FORMAT,
        "--merge-output-format", "mp4",
        "--output", output_template,
        "--no-playlist",
        "--socket-timeout", "30",
        "--retries", "3",
        *_PLATFORM_OPTS.get(platform, []),
        url,
    ]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=180,
        )
        if result.returncode != 0:
            logger.error(f"yt-dlp failed: {result.stderr[:500]}")
            return info

        # Find the downloaded file
        video_path = _find_downloaded_file(info, output_template)
        if video_path:
            info.video_path = str(video_path)
            info.file_size_mb = round(video_path.stat().st_size / (1024 * 1024), 1)
            logger.info(f"Downloaded: {video_path.name} ({info.file_size_mb}MB)")

            if info.file_size_mb > MAX_FILE_SIZE_MB:
                logger.warning(f"File too large ({info.file_size_mb}MB), removing")
                video_path.unlink(missing_ok=True)
                info.video_path = ""
        else:
            logger.error(f"Download succeeded but file not found for: {url}")

    except subprocess.TimeoutExpired:
        logger.error(f"Download timed out: {url}")
    except Exception as e:
        logger.error(f"Download error: {e}")

    return info


def _extract_info(url: str, platform: str) -> VideoInfo:
    """Extract video metadata without downloading."""
    cmd = [
        YT_DLP,
        "--dump-json",
        "--no-download",
        "--no-playlist",
        "--socket-timeout", "20",
        *_PLATFORM_OPTS.get(platform, []),
        url,
    ]

    info = VideoInfo(url=url, platform=platform)

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60,
        )
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout)
            info.title = data.get("title", "")
            info.author = data.get("uploader", "") or data.get("channel", "")
            info.duration = int(data.get("duration", 0) or 0)
            info.views = int(data.get("view_count", 0) or 0)
            info.likes = int(data.get("like_count", 0) or 0)
            info.comments = int(data.get("comment_count", 0) or 0)
            info.description = (data.get("description", "") or "")[:1000]
            info.publish_date = data.get("upload_date", "")
            info.thumbnail_url = data.get("thumbnail", "")
        else:
            logger.warning(f"Failed to extract info: {result.stderr[:300]}")
    except Exception as e:
        logger.warning(f"Info extraction error: {e}")

    return info


def _find_downloaded_file(info: VideoInfo, output_template: str) -> Path | None:
    """Find the downloaded video file in DOWNLOAD_DIR."""
    # yt-dlp uses %(id)s, check recent files
    for f in sorted(DOWNLOAD_DIR.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True):
        # File modified in last 5 minutes
        if time.time() - f.stat().st_mtime < 300:
            return f
    # Also check other formats
    for ext in ("mkv", "webm", "flv"):
        for f in sorted(DOWNLOAD_DIR.glob(f"*.{ext}"), key=lambda p: p.stat().st_mtime, reverse=True):
            if time.time() - f.stat().st_mtime < 300:
                return f
    return None


def cleanup_old_videos(max_age_days: int = 7) -> int:
    """Delete video files older than max_age_days. Returns count deleted."""
    if not DOWNLOAD_DIR.exists():
        return 0
    cutoff = time.time() - max_age_days * 86400
    deleted = 0
    for f in DOWNLOAD_DIR.iterdir():
        if f.is_file() and f.stat().st_mtime < cutoff:
            f.unlink()
            deleted += 1
    if deleted:
        logger.info(f"Cleaned up {deleted} old video files")
    return deleted
