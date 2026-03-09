import logging
import re
from bs4 import BeautifulSoup

from src.parsers.base import BaseParser
from src.models.content import ParsedContent

logger = logging.getLogger(__name__)


class WechatArticleParser(BaseParser):
    """Parser for WeChat Official Account articles (mp.weixin.qq.com)."""

    def parse(self, url: str) -> ParsedContent:
        html = self.fetch(url)
        soup = BeautifulSoup(html, "lxml")

        # Title
        title_tag = soup.find("h1", id="activity-name") or soup.find("h1")
        title = title_tag.get_text(strip=True) if title_tag else ""

        # Author
        author_tag = soup.find("span", class_="rich_media_meta_text") or soup.find("a", id="js_name")
        author = author_tag.get_text(strip=True) if author_tag else None

        # Content
        content_div = soup.find("div", id="js_content") or soup.find("div", class_="rich_media_content")
        if content_div:
            content_text = content_div.get_text(separator="\n", strip=True)
            images = [img.get("data-src") or img.get("src") for img in content_div.find_all("img") if img.get("data-src") or img.get("src")]
        else:
            content_text = soup.get_text(separator="\n", strip=True)
            images = []

        # Publish date
        publish_date = None
        date_match = re.search(r'var ct\s*=\s*"(\d+)"', html)
        if date_match:
            from datetime import datetime
            try:
                publish_date = datetime.fromtimestamp(int(date_match.group(1)))
            except (ValueError, OSError):
                pass

        return ParsedContent(
            url=url,
            platform="wechat",
            title=title,
            content=content_text,
            author=author,
            publish_date=publish_date,
            images=images,
        )
