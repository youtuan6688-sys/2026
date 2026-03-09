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


def extract_urls(text: str) -> list[str]:
    """Extract all URLs from text."""
    return URL_REGEX.findall(text)


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
