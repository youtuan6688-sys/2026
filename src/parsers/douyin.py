import logging
from bs4 import BeautifulSoup

from src.parsers.base import BaseParser
from src.models.content import ParsedContent

logger = logging.getLogger(__name__)


class DouyinParser(BaseParser):
    """Parser for Douyin (抖音) videos.

    Extracts title and description from meta tags.
    Video transcription is not supported in v1.
    """

    def parse(self, url: str) -> ParsedContent:
        try:
            html = self.fetch(url)
            soup = BeautifulSoup(html, "lxml")

            title = self._get_meta(soup, "og:title") or ""
            if not title and soup.title:
                title = soup.title.get_text(strip=True)

            description = self._get_meta(soup, "og:description") or ""
            author = self._get_meta(soup, "og:author") or ""
            image = self._get_meta(soup, "og:image") or ""

            content = f"{title}\n\n{description}" if description else title
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
