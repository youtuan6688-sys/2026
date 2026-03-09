import logging
from bs4 import BeautifulSoup

from src.parsers.base import BaseParser
from src.models.content import ParsedContent

logger = logging.getLogger(__name__)


class DouyinParser(BaseParser):
    """Parser for Douyin (抖音) videos.

    Uses Playwright browser to get rendered page content.
    Extracts title, description from meta tags and page content.
    """

    def parse(self, url: str) -> ParsedContent:
        try:
            # Use browser for better content extraction
            html = self.fetch_with_browser(url, wait_seconds=3.0)
            soup = BeautifulSoup(html, "lxml")

            title = self._get_meta(soup, "og:title") or ""
            if not title and soup.title:
                title = soup.title.get_text(strip=True)

            description = self._get_meta(soup, "og:description") or ""
            author = self._get_meta(soup, "og:author") or ""
            image = self._get_meta(soup, "og:image") or ""

            # Try to get more content from rendered page
            content_parts = []
            if title:
                content_parts.append(title)
            if description:
                content_parts.append(description)

            # Look for video description in rendered DOM
            desc_el = soup.select_one("span[class*='desc'], div[class*='desc']")
            if desc_el:
                desc_text = desc_el.get_text(strip=True)
                if desc_text and desc_text not in content_parts:
                    content_parts.append(desc_text)

            content = "\n\n".join(content_parts) if content_parts else ""
            images = [image] if image else []

            return ParsedContent(
                url=url,
                platform="douyin",
                title=title or "抖音视频",
                content=content or f"[视频内容需手动查看: {url}]",
                author=author or None,
                images=images,
                metadata={"type": "video"},
            )
        except Exception as e:
            logger.warning(f"Douyin parse failed: {e}")
            return ParsedContent(
                url=url,
                platform="douyin",
                title="抖音视频",
                content=f"[无法自动提取内容，请手动查看: {url}]",
                metadata={"type": "video"},
            )

    def _get_meta(self, soup: BeautifulSoup, prop: str) -> str:
        tag = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
        return tag["content"] if tag and tag.get("content") else ""
