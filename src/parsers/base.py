from abc import ABC, abstractmethod
import logging

import requests

from src.models.content import ParsedContent
from src.utils.retry import retry

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
}


class BaseParser(ABC):
    @abstractmethod
    def parse(self, url: str) -> ParsedContent:
        ...

    @retry(max_attempts=3, delay=1.0)
    def fetch(self, url: str, headers: dict | None = None) -> str:
        """Fetch URL content with retry."""
        h = {**DEFAULT_HEADERS, **(headers or {})}
        resp = requests.get(url, headers=h, timeout=30, allow_redirects=True)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or "utf-8"
        return resp.text
