import re
from urllib.parse import urlparse

PLATFORM_PATTERNS = {
    "xiaohongshu": [r"xiaohongshu\.com", r"xhslink\.com"],
    "douyin": [r"douyin\.com", r"v\.douyin\.com", r"iesdouyin\.com"],
    "twitter": [r"twitter\.com", r"x\.com", r"t\.co"],
    "wechat": [r"mp\.weixin\.qq\.com"],
    "feishu": [r"feishu\.cn", r"larksuite\.com"],
}

URL_REGEX = re.compile(r'https?://[^\s<>"{}|\\^`\[\]]+')


def _is_real_url(url: str) -> bool:
    """Filter out fake URLs like http://learnings.md/) that come from markdown text."""
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    # Must have at least one dot in the domain
    if "." not in host:
        return False
    # Filter out single-word TLDs that are likely file extensions mistaken as URLs
    # e.g. http://tools.md, http://memory.md
    parts = host.split(".")
    if len(parts) == 2 and parts[1] in ("md", "txt", "py", "js", "ts", "css", "html", "json", "yaml", "yml", "toml", "cfg", "ini", "log", "sh", "bat"):
        return False
    # Strip trailing punctuation from path that got included
    if parsed.path.endswith(")") or parsed.path.endswith("）"):
        return False
    return True


def extract_urls(text: str) -> list[str]:
    """Extract all URLs from text."""
    urls = URL_REGEX.findall(text)
    return [u for u in urls if _is_real_url(u)]


def detect_platform(url: str) -> str:
    """Detect which platform a URL belongs to."""
    for platform, patterns in PLATFORM_PATTERNS.items():
        if any(re.search(p, url) for p in patterns):
            return platform
    return "generic"


def normalize_url(url: str) -> str:
    """Remove tracking parameters from URL."""
    parsed = urlparse(url)
    # Keep the base URL without common tracking params
    clean = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    return clean
