import json
import logging

import requests

from src.parsers.base import BaseParser
from src.models.content import ParsedContent

logger = logging.getLogger(__name__)


class TwitterParser(BaseParser):
    """Parser for X/Twitter posts using oembed API."""

    OEMBED_URL = "https://publish.twitter.com/oembed"

    def parse(self, url: str) -> ParsedContent:
        # Normalize x.com to twitter.com for oembed
        normalized = url.replace("x.com", "twitter.com")

        try:
            resp = requests.get(
                self.OEMBED_URL,
                params={"url": normalized, "omit_script": "true"},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()

            # oembed returns HTML with the tweet text
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(data.get("html", ""), "lxml")
            content = soup.get_text(separator="\n", strip=True)
            author = data.get("author_name", None)
            title = f"Tweet by {author}" if author else "Tweet"

            return ParsedContent(
                url=url,
                platform="twitter",
                title=title,
                content=content,
                author=author,
            )
        except Exception as e:
            logger.warning(f"Twitter oembed failed, falling back to generic: {e}")
            from src.parsers.generic_web import GenericWebParser
            return GenericWebParser().parse(url)
