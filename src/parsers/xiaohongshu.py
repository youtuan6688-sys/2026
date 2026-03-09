import logging
from bs4 import BeautifulSoup

from src.parsers.base import BaseParser
from src.models.content import ParsedContent

logger = logging.getLogger(__name__)


class XiaohongshuParser(BaseParser):
    """Parser for Xiaohongshu (小红书) posts.

    Uses Playwright browser to bypass anti-scraping protections.
    Falls back to meta tag extraction if browser fails.
    """

    def parse(self, url: str) -> ParsedContent:
        try:
            # Use browser for better content extraction
            html = self.fetch_with_browser(url, wait_seconds=3.0)
            soup = BeautifulSoup(html, "lxml")

            # Try og meta tags first
            title = self._get_meta(soup, "og:title") or ""
            if not title and soup.title:
                title = soup.title.get_text(strip=True)

            description = self._get_meta(soup, "og:description") or ""
            author = self._get_meta(soup, "og:author") or self._get_meta(soup, "author") or ""
            image = self._get_meta(soup, "og:image") or ""

            # Try extracting full content from rendered page
            content = ""
            content_div = soup.find("div", id="detail-desc") or soup.find("div", class_="note-content")
            if content_div:
                content = content_div.get_text(separator="\n", strip=True)

            # Also try span-based content (common in rendered XHS pages)
            if not content:
                desc_spans = soup.select("span.note-text, span[class*='desc']")
                if desc_spans:
                    content = "\n".join(s.get_text(strip=True) for s in desc_spans)

            if not content:
                content = description

            images = [image] if image else []
            # Collect more images from page
            for img in soup.select("img[src*='xhscdn'], img[src*='xiaohongshu']"):
                src = img.get("src", "")
                if src and src not in images:
                    images.append(src)

            return ParsedContent(
                url=url,
                platform="xiaohongshu",
                title=title or "小红书笔记",
                content=content or f"[内容需手动查看: {url}]",
                author=author or None,
                images=images,
            )
        except Exception as e:
            logger.warning(f"Xiaohongshu parse failed: {e}")
            return ParsedContent(
                url=url,
                platform="xiaohongshu",
                title="小红书笔记",
                content=f"[无法自动提取内容，请手动查看: {url}]",
            )

    def _get_meta(self, soup: BeautifulSoup, prop: str) -> str:
        tag = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
        return tag["content"] if tag and tag.get("content") else ""
