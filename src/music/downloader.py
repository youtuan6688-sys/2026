"""Music downloader using yt-dlp with platform-specific configurations."""
import json
import logging
import re
import subprocess
import uuid
from hashlib import md5
from pathlib import Path

from src.music.models import DownloadResult

logger = logging.getLogger(__name__)

YT_DLP = "/opt/homebrew/bin/yt-dlp"
FFMPEG = "/opt/homebrew/bin/ffmpeg"
MUSIC_ROOT = Path.home() / "Music" / "HappyLibrary"
TEMP_DIR = MUSIC_ROOT / "temp"

# Platform configs: yt-dlp extractor names and capabilities
PLATFORM_CONFIG = {
    "youtube_music": {
        "lossless": True,
        "needs_search": False,
    },
    "youtube": {
        "lossless": True,
        "needs_search": False,
    },
    "qqmusic": {
        "lossless": True,
        "needs_search": False,
    },
    "netease": {
        "lossless": True,
        "needs_search": False,
    },
    "bilibili": {
        "lossless": True,
        "needs_search": False,
    },
    "spotify": {
        "lossless": False,
        "needs_search": True,  # Extract metadata, search on YouTube Music
    },
    "apple_music": {
        "lossless": False,
        "needs_search": True,
    },
    "qishui": {
        "lossless": False,
        "needs_search": True,  # 汽水音乐 (抖音) — extract title, search YouTube
    },
    "kugou": {
        "lossless": True,
        "needs_search": False,
    },
    "kuwo": {
        "lossless": True,
        "needs_search": False,
    },
}


def _url_id(url: str) -> str:
    """Generate a stable ID from URL."""
    return md5(url.encode()).hexdigest()[:12]


def _extract_metadata_for_search(url: str) -> tuple[str, str]:
    """Extract song title and artist from a URL page for search fallback.

    Used for platforms yt-dlp can't download from (Spotify, Apple Music).
    Fetches the page HTML and parses og:title / meta tags.
    Returns (title, artist) or ("", "").
    """
    import urllib.request

    # 1. Try oEmbed API (works for Spotify and Apple Music, no auth needed)
    oembed_url = ""
    if "spotify.com" in url:
        oembed_url = f"https://open.spotify.com/oembed?url={url}"
    elif "music.apple.com" in url:
        oembed_url = f"https://music.apple.com/oembed?url={url}"

    if oembed_url:
        try:
            req = urllib.request.Request(oembed_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            title = data.get("title", "")
            # oEmbed title is usually just the song name; artist may be in the iframe title
            # Parse "Spotify Embed: Song Name" or just "Song Name"
            if title:
                logger.info(f"oEmbed extracted: title={title}")
                return title, ""  # Artist not in oEmbed, but title is enough for search
        except Exception as e:
            logger.debug(f"oEmbed extraction failed for {url}: {e}")

    # 2. Fetch page HTML and parse <meta> og:title / og:description
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0.0.0 Safari/537.36",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        # Spotify og:title format: "歌名 - song and target by 歌手 | Spotify"
        # Apple Music: "歌名 - Single by 歌手 on Apple Music"
        og_title = _extract_meta(html, "og:title") or _extract_meta(html, "title")
        og_desc = _extract_meta(html, "og:description") or ""

        if og_title:
            title, artist = _parse_og_title(og_title)
            if title:
                logger.info(f"Extracted from page meta: title={title}, artist={artist}")
                return title, artist

        # Try og:description as fallback
        if og_desc:
            title, artist = _parse_og_title(og_desc)
            if title:
                return title, artist

    except Exception as e:
        logger.debug(f"HTML metadata extraction failed for {url}: {e}")

    # 2. Fallback: try yt-dlp (works for some platforms)
    try:
        result = subprocess.run(
            [YT_DLP, "--dump-json", "--no-download", url],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            info = json.loads(result.stdout.strip())
            title = info.get("track") or info.get("title", "")
            artist = info.get("artist") or info.get("uploader") or info.get("creator", "")
            if title:
                return title, artist
    except Exception as e:
        logger.debug(f"yt-dlp metadata extraction failed for {url}: {e}")

    return "", ""


def _extract_meta(html: str, name: str) -> str:
    """Extract content from <meta property='name'> or <meta name='name'> or <title>."""
    if name == "title":
        match = re.search(r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE)
        return match.group(1).strip() if match else ""
    # Try property= first (og:title), then name=
    for attr in ("property", "name"):
        pattern = rf'<meta\s+{attr}=["\']?{re.escape(name)}["\']?\s+content=["\']([^"\']+)["\']'
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        # Also try reversed attribute order
        pattern2 = rf'<meta\s+content=["\']([^"\']+)["\']\s+{attr}=["\']?{re.escape(name)}["\']?'
        match2 = re.search(pattern2, html, re.IGNORECASE)
        if match2:
            return match2.group(1).strip()
    return ""


def _parse_og_title(title: str) -> tuple[str, str]:
    """Parse song title and artist from og:title strings.

    Common formats:
    - Spotify: "Song Name - song and target by Artist | Spotify"
    - Spotify: "Song Name · Artist"
    - Apple Music: "Song Name - Single by Artist on Apple Music"
    - Generic: "Song Name by Artist"
    - Generic: "Artist - Song Name"
    """
    # Remove trailing platform names and decorators
    # Remove " | PlatformName" or " - PlatformName" suffixes
    title = re.sub(r"\s*[|｜]\s*(?:Spotify|Apple Music|网易云音乐|QQ音乐|酷狗音乐|酷我音乐|汽水音乐)\s*$", "", title)
    title = re.sub(r"\s*[-–—]\s*(?:Spotify|Apple Music|网易云音乐|QQ音乐|酷狗音乐|酷我音乐|汽水音乐)\s*$", "", title)
    title = re.sub(r"\s+on Apple Music\s*$", "", title)

    # Remove Chinese platform @mentions: @汽水音乐, @网易云音乐, @QQ音乐, etc.
    title = re.sub(r"\s*@[\u4e00-\u9fffA-Za-z0-9]+音乐\s*$", "", title)
    title = re.sub(r"\s*@[\u4e00-\u9fffA-Za-z0-9]+$", "", title)

    # Remove Chinese book title marks 《》
    match = re.match(r"^《(.+?)》$", title.strip())
    if match:
        title = match.group(1)

    # "Song · Artist" (Spotify uses middle dot)
    if " · " in title:
        parts = title.split(" · ", 1)
        return parts[0].strip(), parts[1].strip()

    # "Song - song and target by Artist" or "Song - Single by Artist"
    match = re.match(r"(.+?)\s*[-–—]\s*(?:song.*?by|single.*?by|.*?by)\s+(.+)", title, re.IGNORECASE)
    if match:
        return match.group(1).strip(), match.group(2).strip()

    # "Song by Artist"
    match = re.match(r"(.+?)\s+by\s+(.+)", title, re.IGNORECASE)
    if match:
        return match.group(1).strip(), match.group(2).strip()

    # "Artist - Song" (common format)
    if " - " in title:
        parts = title.split(" - ", 1)
        return parts[1].strip(), parts[0].strip()

    # Can't parse, use full title as search query
    return title.strip(), ""


def _run_ytdlp(url: str, audio_format: str) -> tuple[DownloadResult, dict, Path]:
    """Run yt-dlp in an isolated temp directory.

    Returns (result, info_dict, job_dir).
    On failure, result.success is False and info/job_dir may be empty.
    """
    job_dir = TEMP_DIR / uuid.uuid4().hex[:8]
    job_dir.mkdir(parents=True, exist_ok=True)

    output_template = str(job_dir / "%(title)s.%(ext)s")
    cmd = [
        YT_DLP,
        "-x",
        "--audio-format", audio_format,
        "--audio-quality", "0",
        "--embed-thumbnail",
        "--add-metadata",
        "--no-playlist",
        "--ffmpeg-location", FFMPEG,
        "-o", output_template,
        "--print-json",
        url,
    ]

    logger.info(f"Downloading: {url} -> {job_dir}")

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        if proc.returncode != 0:
            error_msg = proc.stderr.strip().split("\n")[-1] if proc.stderr else "Unknown error"
            logger.error(f"yt-dlp failed: {error_msg}")
            return DownloadResult(success=False, error=error_msg), {}, job_dir

        info = {}
        for line in reversed(proc.stdout.strip().split("\n")):
            try:
                info = json.loads(line)
                break
            except json.JSONDecodeError:
                continue

        if not info:
            return DownloadResult(success=False, error="无法解析下载结果"), {}, job_dir

        filepath = info.get("filepath") or info.get("_filename", "")

        if filepath:
            actual_path = Path(filepath)
            converted = actual_path.with_suffix(f".{audio_format}")
            if converted.exists():
                actual_path = converted
            elif not actual_path.exists():
                actual_path = _find_latest_file(job_dir, audio_format)
        else:
            actual_path = _find_latest_file(job_dir, audio_format)

        if not actual_path or not actual_path.exists():
            return DownloadResult(success=False, error="下载文件未找到"), info, job_dir

        return DownloadResult(success=True, file_path=str(actual_path)), info, job_dir

    except subprocess.TimeoutExpired:
        return DownloadResult(success=False, error="下载超时（5分钟）"), {}, job_dir
    except Exception as e:
        logger.exception(f"Download error: {e}")
        return DownloadResult(success=False, error=str(e)), {}, job_dir


def download(url: str, platform: str) -> DownloadResult:
    """Download audio from URL using yt-dlp.

    Args:
        url: The music URL to download.
        platform: Platform key from detect_music_platform().

    Returns:
        DownloadResult with file path and metadata on success.
    """
    config = PLATFORM_CONFIG.get(platform, {"lossless": False, "needs_search": False})

    # For platforms needing search (Spotify, Apple Music):
    # extract metadata and search on YouTube Music
    actual_url = url
    if config["needs_search"]:
        title, artist = _extract_metadata_for_search(url)
        if not title:
            return DownloadResult(
                success=False,
                error=f"无法从 {platform} 链接提取歌曲信息，请直接发送歌曲名",
            )
        search_query = f"{artist} {title}".strip()
        actual_url = f"ytsearch1:{search_query}"
        logger.info(f"Platform {platform} needs search, query: {search_query}")

    audio_format = "flac" if config["lossless"] else "mp3"

    result, info, job_dir = _run_ytdlp(actual_url, audio_format)
    if not result.success:
        return result

    return DownloadResult(
        success=True,
        file_path=result.file_path,
        title=info.get("track") or info.get("title", Path(result.file_path).stem),
        artist=info.get("artist") or info.get("uploader") or info.get("creator", "Unknown"),
        album=info.get("album", ""),
        duration_seconds=int(info.get("duration", 0)),
        format=audio_format,
        cover_url=info.get("thumbnail", ""),
        metadata={
            "track_number": info.get("track_number", 0),
            "genre": info.get("genre", ""),
            "year": info.get("release_year") or info.get("upload_date", "")[:4] if info.get("upload_date") else "",
            "source_platform": platform,
            "source_url": url,
        },
    )


def download_by_query(query: str) -> DownloadResult:
    """Download audio by searching YouTube Music with a text query.

    Args:
        query: Search query like "周杰伦 晴天" or "artist - title".

    Returns:
        DownloadResult with file path and metadata on success.
    """
    search_url = f"ytsearch1:{query}"
    logger.info(f"Searching YouTube Music for: {query}")

    result, info, job_dir = _run_ytdlp(search_url, "flac")
    if not result.success:
        return result

    source_url = info.get("webpage_url", "")
    return DownloadResult(
        success=True,
        file_path=result.file_path,
        title=info.get("track") or info.get("title", Path(result.file_path).stem),
        artist=info.get("artist") or info.get("uploader") or info.get("creator", "Unknown"),
        album=info.get("album", ""),
        duration_seconds=int(info.get("duration", 0)),
        format="flac",
        cover_url=info.get("thumbnail", ""),
        metadata={
            "track_number": info.get("track_number", 0),
            "genre": info.get("genre", ""),
            "year": info.get("release_year") or info.get("upload_date", "")[:4] if info.get("upload_date") else "",
            "source_platform": "youtube_music",
            "source_url": source_url,
        },
    )


def convert_to_mp3(source_path: Path) -> Path | None:
    """Convert an audio file to MP3 320kbps using ffmpeg.

    Returns the MP3 path in TEMP_DIR on success, None on failure.
    The caller is responsible for cleaning up the returned file.
    """
    if source_path.suffix.lower() == ".mp3":
        return source_path

    # Write to isolated temp dir to avoid polluting library
    mp3_dir = TEMP_DIR / f"mp3_{uuid.uuid4().hex[:8]}"
    mp3_dir.mkdir(parents=True, exist_ok=True)
    mp3_path = mp3_dir / f"{source_path.stem}.mp3"

    cmd = [
        FFMPEG, "-i", str(source_path),
        "-codec:a", "libmp3lame",
        "-b:a", "320k",
        "-y",
        str(mp3_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode == 0 and mp3_path.exists():
            logger.info(f"Converted to MP3: {mp3_path}")
            return mp3_path
        logger.error(f"ffmpeg conversion failed: {result.stderr[:200]}")
    except subprocess.TimeoutExpired:
        logger.error(f"ffmpeg timed out converting {source_path}")
    except Exception as e:
        logger.error(f"MP3 conversion error: {e}")
    return None


def _find_latest_file(directory: Path, ext: str) -> Path | None:
    """Find the most recently modified file with given extension in directory."""
    files = list(directory.glob(f"*.{ext}"))
    if not files:
        # Try common audio extensions
        for fallback_ext in ["flac", "mp3", "m4a", "opus", "webm", "wav"]:
            files = list(directory.glob(f"*.{fallback_ext}"))
            if files:
                break
    if not files:
        return None
    return max(files, key=lambda f: f.stat().st_mtime)
