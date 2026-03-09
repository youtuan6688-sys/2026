import logging
from bs4 import BeautifulSoup

from src.parsers.base import BaseParser
from src.models.content import ParsedContent

logger = logging.getLogger(__name__)


class XiaohongshuParser(BaseParser):
    """Parser for Xiaohongshu (小红书) posts.

    Xiaohongshu heavily blocks scraping, so we try multiple strategies:
    1. Fetch with mobile UA and extract meta tags
    2. Fall back to generic parser
    """

    def parse(self, url: str) -> ParsedContent:
        try:
            html = self.fetch(url)
            soup = BeautifulSoup(html, "lxml")

            # Try og meta tags first
            title = self._get_meta(soup, "og:title") or soup.title.get_text(strip=True) if soup.title else ""
            description = self._get_meta(soup, "og:description") or ""
            author = self._get_meta(soup, "og:author") or self._get_meta(soup, "author") or ""
            image = self._get_meta(soup, "og:image") or ""

            content = description
            if not content:
                # Try extracting from page content
                content_div = soup.find("div", class_="note-content") or soup.find("div", id="detail-desc")
                if content_div:
                    content = content_div.get_text(separator="\n", strip=True)

            images = [image] if image else []

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
