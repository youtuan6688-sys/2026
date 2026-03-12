"""Trending video crawler — fetch hot video URLs from platforms.

Uses yt-dlp search for bilibili/youtube,
Brave Web Search for douyin/xiaohongshu (yt-dlp doesn't support their search pages).
"""

import json
import logging
import os
import re
import shutil
import subprocess
from datetime import date
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

YT_DLP = shutil.which("yt-dlp") or "/opt/homebrew/bin/yt-dlp"
TRENDING_CACHE_DIR = Path(
    os.environ.get(
        "VIDEO_TRENDING_DIR",
        str(Path(__file__).parent.parent.parent / "data" / "video_trending"),
    )
)

BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
MAX_QUERY_LEN = 200

# yt-dlp search prefixes for platforms that support it
_SEARCH_PREFIXES = {
    "youtube": "ytsearch",
    "bilibili": "bilisearch",
}

# URL patterns to extract valid video links from search results
_VIDEO_URL_PATTERNS = {
    "douyin": [
        re.compile(r"https?://www\.douyin\.com/video/\d+"),
        re.compile(r"https?://v\.douyin\.com/\w+"),
    ],
    "xiaohongshu": [
        re.compile(r"https?://www\.xiaohongshu\.com/explore/[\w]+"),
        re.compile(r"https?://www\.xiaohongshu\.com/discovery/item/[\w]+"),
        re.compile(r"https?://xhslink\.com/\w+"),
    ],
}

# Brave search query templates per platform
_BRAVE_SEARCH_TEMPLATES = {
    "douyin": "site:douyin.com/video {query}",
    "xiaohongshu": "site:xhslink.com {query}",  # XHS short links; best-effort
}


def _sanitize_query(query: str) -> str:
    """Sanitize user query: strip, truncate, escape braces."""
    return query.strip().replace("{", "").replace("}", "")[:MAX_QUERY_LEN]


def crawl_trending(platform: str = "douyin", count: int = 10,
                   query: str = "") -> list[str]:
    """Fetch trending video URLs for a platform.

    Returns a list of video URLs (may be fewer than count).
    """
    TRENDING_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    if platform == "douyin":
        return _crawl_via_brave(platform, count, query)
    elif platform in ("bilibili", "youtube"):
        return _crawl_via_ytdlp_search(platform, count, query)
    elif platform == "xiaohongshu":
        # XHS notes are poorly indexed by search engines;
        # Brave returns topic/user pages, not individual note URLs.
        # Use Brave as best-effort, but expect low hit rate.
        return _crawl_via_brave(platform, count, query)
    else:
        logger.warning("Unsupported crawl platform: %s", platform)
        return []


def search_videos(query: str, platform: str = "", count: int = 5) -> list[dict]:
    """Search videos by keyword across platforms.

    Returns list of dicts: {url, title, platform, source}.
    If platform is specified, searches only that platform.
    Otherwise searches douyin + bilibili (XHS has low hit rate).
    """
    results: list[dict] = []

    if platform:
        platforms = [platform]
    else:
        platforms = ["douyin", "bilibili"]

    per_platform = max(count, 3)  # fetch enough per platform, cap total at end

    for p in platforms:
        if p in ("douyin", "xiaohongshu"):
            urls = _crawl_via_brave(p, per_platform, query)
            for u in urls:
                results.append({"url": u, "title": "", "platform": p, "source": "brave"})
        elif p in ("bilibili", "youtube"):
            items = _search_via_ytdlp(p, per_platform, query)
            results.extend(items)

    return results[:count]


def _crawl_via_brave(platform: str, count: int, query: str) -> list[str]:
    """Search douyin/xiaohongshu videos via Brave Web Search."""
    api_key = os.environ.get("BRAVE_API_KEY", "")
    if not api_key:
        logger.warning("BRAVE_API_KEY not set, cannot search %s", platform)
        return []

    search_query = _sanitize_query(query) or "热门视频"
    template = _BRAVE_SEARCH_TEMPLATES.get(platform, "{query}")
    full_query = template.replace("{query}", search_query)

    try:
        resp = requests.get(
            BRAVE_SEARCH_URL,
            headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
            params={"q": full_query, "count": min(count * 3, 20)},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.Timeout:
        logger.error("Brave search timed out for %s", platform)
        return []
    except requests.exceptions.HTTPError as e:
        logger.error("Brave search HTTP %s for %s: %s", e.response.status_code, platform, e)
        return []
    except (requests.exceptions.ConnectionError, ValueError) as e:
        logger.error("Brave search error for %s: %s", platform, e)
        return []

    urls: list[str] = []
    patterns = _VIDEO_URL_PATTERNS.get(platform, [])

    for item in data.get("web", {}).get("results", []):
        page_url = item.get("url", "")
        for pattern in patterns:
            match = pattern.search(page_url)
            if match:
                video_url = match.group(0)
                if video_url not in urls:
                    urls.append(video_url)
                    logger.info("Brave found [%s]: %s → %s",
                                platform, item.get("title", "")[:40], video_url)
                break

    logger.info("Brave search [%s] q='%s': %d video URLs", platform, search_query, len(urls))
    _save_trending_cache(platform, urls)
    return urls[:count]


def _crawl_via_ytdlp_search(platform: str, count: int, query: str) -> list[str]:
    """Crawl bilibili/youtube using yt-dlp search."""
    items = _search_via_ytdlp(platform, count, query)
    urls = [item["url"] for item in items]
    _save_trending_cache(platform, urls)
    return urls


def _search_via_ytdlp(platform: str, count: int, query: str) -> list[dict]:
    """Search bilibili/youtube via yt-dlp, return list of {url, title, platform, source}."""
    prefix = _SEARCH_PREFIXES.get(platform, "ytsearch")
    search_term = _sanitize_query(query) or "热门视频"
    search_url = f"{prefix}{count}:{search_term}"

    results: list[dict] = []
    try:
        cmd = [
            YT_DLP,
            "--flat-playlist",
            "--dump-json",
            "--no-download",
            "--socket-timeout", "20",
            search_url,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

        if proc.returncode != 0 and not proc.stdout:
            logger.warning("%s yt-dlp failed (rc=%d): %s",
                           platform, proc.returncode, proc.stderr[:200])
            return []

        if proc.stdout:
            seen: set[str] = set()
            for line in proc.stdout.strip().split("\n"):
                try:
                    data = json.loads(line)
                    url = data.get("webpage_url") or data.get("url", "")
                    if url and url not in seen:
                        seen.add(url)
                        results.append({
                            "url": url,
                            "title": data.get("title", ""),
                            "platform": platform,
                            "source": "ytdlp",
                            "duration": data.get("duration", 0),
                        })
                except json.JSONDecodeError:
                    pass
    except subprocess.TimeoutExpired:
        logger.error("%s yt-dlp search timed out", platform)
    except FileNotFoundError:
        logger.error("yt-dlp not found at %s", YT_DLP)
    except OSError as e:
        logger.warning("%s search failed: %s", platform, e)

    return results[:count]


def _save_trending_cache(platform: str, urls: list[str]) -> None:
    """Cache crawled URLs for dedup. Overwrites corrupted files."""
    if not urls:
        return
    cache_file = TRENDING_CACHE_DIR / f"{platform}-{date.today().isoformat()}.json"
    try:
        existing: list[str] = []
        if cache_file.exists():
            try:
                existing = json.loads(cache_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, ValueError):
                logger.warning("Corrupt cache file %s, overwriting", cache_file)
                existing = []
        combined = list(dict.fromkeys(existing + urls))  # dedup preserving order
        # Atomic write via temp file
        tmp_file = cache_file.with_suffix(".tmp")
        tmp_file.write_text(
            json.dumps(combined, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        tmp_file.rename(cache_file)
    except OSError as e:
        logger.warning("Failed to save trending cache: %s", e)
