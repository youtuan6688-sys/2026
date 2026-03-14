import logging
import re
from bs4 import BeautifulSoup
from readability import Document

from src.parsers.base import BaseParser
from src.models.content import ParsedContent

logger = logging.getLogger(__name__)

# SPA domains that require browser rendering
_SPA_DOMAINS = re.compile(
    r"wolai\.com|notion\.so|notion\.site|yuque\.com|feishu\.cn/wiki|"
    r"shimo\.im|airtable\.com|coda\.io|zhihu\.com/p/"
)

# Minimum content length to consider a fetch successful (chars)
_MIN_CONTENT_LENGTH = 200


class GenericWebParser(BaseParser):
    """Fallback parser using readability-lxml for any web page.

    Automatically falls back to browser rendering when:
    1. URL matches known SPA domains, or
    2. Initial requests-based fetch yields too little content.
    """

    def parse(self, url: str) -> ParsedContent:
        use_browser = bool(_SPA_DOMAINS.search(url))

        if use_browser:
            logger.info(f"SPA domain detected, using browser: {url}")
            html = self.fetch_with_browser(url, wait_seconds=4.0)
        else:
            html = self.fetch(url)

        title, content_text, author, images = self._extract(html)

        # Fallback: if requests fetch got too little, retry with browser
        if not use_browser and len(content_text) < _MIN_CONTENT_LENGTH:
            logger.info(
                f"Content too short ({len(content_text)} chars), "
                f"retrying with browser: {url}"
            )
            try:
                html = self.fetch_with_browser(url, wait_seconds=4.0)
                title2, content2, author2, images2 = self._extract(html)
                if len(content2) > len(content_text):
                    title = title2 or title
                    content_text = content2
                    author = author2 or author
                    images = images2 or images
            except Exception as e:
                logger.warning(f"Browser fallback failed: {e}")

        return ParsedContent(
            url=url,
            platform="generic",
            title=title,
            content=content_text,
            author=author,
            images=images,
        )

    @staticmethod
    def _extract(html: str) -> tuple[str, str, str | None, list[str]]:
        """Extract title, content, author, images from HTML."""
        doc = Document(html)
        title = doc.title() or ""
        content_html = doc.summary()

        soup = BeautifulSoup(content_html, "lxml")
        content_text = soup.get_text(separator="\n", strip=True)

        original_soup = BeautifulSoup(html, "lxml")
        author = None
        for name in ["author", "og:author", "article:author"]:
            tag = (original_soup.find("meta", attrs={"name": name})
                   or original_soup.find("meta", attrs={"property": name}))
            if tag and tag.get("content"):
                author = tag["content"]
                break

        images = [img.get("src") for img in soup.find_all("img") if img.get("src")]
        return title, content_text, author, images
