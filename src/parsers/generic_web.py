import logging
from bs4 import BeautifulSoup
from readability import Document

from src.parsers.base import BaseParser
from src.models.content import ParsedContent

logger = logging.getLogger(__name__)


class GenericWebParser(BaseParser):
    """Fallback parser using readability-lxml for any web page."""

    def parse(self, url: str) -> ParsedContent:
        html = self.fetch(url)
        doc = Document(html)

        title = doc.title() or ""
        content_html = doc.summary()

        # Extract clean text from readability output
        soup = BeautifulSoup(content_html, "lxml")
        content_text = soup.get_text(separator="\n", strip=True)

        # Extract metadata from original HTML
        original_soup = BeautifulSoup(html, "lxml")
        author = self._extract_meta(original_soup, ["author", "og:author", "article:author"])
        images = [img.get("src") for img in soup.find_all("img") if img.get("src")]

        return ParsedContent(
            url=url,
            platform="generic",
            title=title,
            content=content_text,
            author=author,
            images=images,
        )

    def _extract_meta(self, soup: BeautifulSoup, names: list[str]) -> str | None:
        for name in names:
            tag = soup.find("meta", attrs={"name": name}) or soup.find("meta", attrs={"property": name})
            if tag and tag.get("content"):
                return tag["content"]
        return None
