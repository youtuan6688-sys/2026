"""Video downloader using yt-dlp with ADB+scrcpy fallback for cookie-gated platforms."""

import json
import logging
import re
import subprocess
import time
from pathlib import Path

from src.video.models import VideoInfo

logger = logging.getLogger(__name__)

YT_DLP = "/opt/homebrew/bin/yt-dlp"
SCRCPY = "/opt/homebrew/bin/scrcpy"
ADB = "/opt/homebrew/bin/adb"
DOWNLOAD_DIR = Path("/Users/tuanyou/Happycode2026/data/video_raw")
MAX_DURATION = 600       # 10 min
MAX_FILE_SIZE_MB = 100   # Gemini File API limit
PREFERRED_FORMAT = "bestvideo[height<=720]+bestaudio/best[height<=720]/best"

# Douyin deeplink: snssdk1128://aweme/detail/{video_id}
_DOUYIN_ID_RE = re.compile(r"/video/(\d+)")
_DOUYIN_SHORT_RE = re.compile(r"v\.douyin\.com/\S+")

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

    # Fallback: ADB screen-record for platforms that need cookies
    if not info.video_path and platform in ("douyin", "xiaohongshu"):
        logger.info(f"yt-dlp failed, trying ADB+scrcpy fallback for {platform}")
        adb_path = _adb_record_video(url, info.duration or 60)
        if adb_path:
            info.video_path = str(adb_path)
            info.file_size_mb = round(adb_path.stat().st_size / (1024 * 1024), 1)
            logger.info(f"ADB fallback succeeded: {adb_path.name} ({info.file_size_mb}MB)")

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


def _adb_device_connected() -> bool:
    """Check if an ADB device is connected."""
    try:
        result = subprocess.run(
            [ADB, "devices"], capture_output=True, text=True, timeout=5,
        )
        lines = result.stdout.strip().split("\n")
        return any("device" in line and "devices" not in line for line in lines)
    except Exception:
        return False


def _resolve_douyin_video_id(url: str) -> str:
    """Extract Douyin video ID from URL (handles short links)."""
    m = _DOUYIN_ID_RE.search(url)
    if m:
        return m.group(1)
    # Resolve short URL
    if _DOUYIN_SHORT_RE.search(url):
        try:
            result = subprocess.run(
                ["curl", "-sL", "-o", "/dev/null", "-w", "%{url_effective}", url],
                capture_output=True, text=True, timeout=10,
            )
            m = _DOUYIN_ID_RE.search(result.stdout)
            if m:
                return m.group(1)
        except Exception as e:
            logger.warning(f"Failed to resolve Douyin short URL: {e}")
    return ""


def _adb_record_video(url: str, duration: int) -> Path | None:
    """Fallback: open video in phone app via ADB, record screen with scrcpy.

    Requires: connected Android device with Douyin installed, scrcpy on host.
    Returns path to recorded mp4 or None.
    """
    if not _adb_device_connected():
        logger.info("No ADB device connected, skipping fallback")
        return None

    # Only Douyin supported for now
    video_id = _resolve_douyin_video_id(url)
    if not video_id:
        logger.warning(f"Could not extract Douyin video ID from: {url}")
        return None

    deeplink = f"snssdk1128://aweme/detail/{video_id}"
    record_time = min(duration + 8, MAX_DURATION)  # extra buffer for load time
    output = DOWNLOAD_DIR / f"adb_{video_id}.mp4"

    try:
        # Open video in Douyin app
        subprocess.run(
            [ADB, "shell", "am", "start", "-a", "android.intent.action.VIEW",
             "-d", deeplink, "com.ss.android.ugc.aweme"],
            capture_output=True, text=True, timeout=10,
        )
        time.sleep(4)  # wait for video to load

        # Record screen with scrcpy (no display, video only)
        result = subprocess.run(
            [SCRCPY, "--no-playback", "--no-audio",
             f"--record={output}", "--max-size=720",
             f"--time-limit={record_time}"],
            capture_output=True, text=True, timeout=record_time + 15,
        )

        if output.exists() and output.stat().st_size > 100_000:
            # Trim first 3s (app transition) with ffmpeg
            trimmed = DOWNLOAD_DIR / f"adb_{video_id}_trimmed.mp4"
            trim_result = subprocess.run(
                ["ffmpeg", "-y", "-i", str(output),
                 "-ss", "3", "-t", str(duration + 2),
                 "-c:v", "libx264", "-preset", "fast", "-crf", "28",
                 "-an", "-vf", "scale=720:-2", str(trimmed)],
                capture_output=True, text=True, timeout=60,
            )
            output.unlink(missing_ok=True)
            if trimmed.exists() and trimmed.stat().st_size > 50_000:
                return trimmed
            logger.warning(f"ffmpeg trim failed: {trim_result.stderr[:200]}")
            return None

        logger.warning(f"scrcpy recording failed or too small: {result.stderr[:200]}")
        output.unlink(missing_ok=True)
        return None

    except subprocess.TimeoutExpired:
        logger.error("ADB recording timed out")
        output.unlink(missing_ok=True)
        return None
    except Exception as e:
        logger.error(f"ADB recording error: {e}")
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
