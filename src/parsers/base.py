from abc import ABC, abstractmethod
import logging
from concurrent.futures import ThreadPoolExecutor

import requests

from src.models.content import ParsedContent
from src.utils.retry import retry

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
}

# Shared thread pool for running Playwright (sync API) outside asyncio event loop
_browser_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="playwright")


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

    def fetch_with_browser(self, url: str, wait_seconds: float = 3.0) -> str:
        """Fetch URL using Playwright Chromium for JS-rendered pages.

        Runs Playwright in a separate thread to avoid conflicts with asyncio
        event loop (lark-oapi WebSocket runs in asyncio).
        Falls back to requests-based fetch if Playwright fails.
        """
        try:
            future = _browser_executor.submit(
                _run_playwright, url, wait_seconds
            )
            return future.result(timeout=60)
        except Exception as e:
            logger.warning(f"Browser fetch failed for {url}, falling back to requests: {e}")
            return self.fetch(url)


def _run_playwright(url: str, wait_seconds: float) -> str:
    """Run Playwright in a dedicated thread (not in asyncio event loop)."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                       "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                       "Version/17.0 Mobile/15E148 Safari/604.1",
            viewport={"width": 390, "height": 844},
            locale="zh-CN",
        )
        page = context.new_page()
        page.goto(url, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(int(wait_seconds * 1000))
        html = page.content()
        browser.close()
        return html
