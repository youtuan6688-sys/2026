from unittest.mock import MagicMock, patch, PropertyMock

import pytest
import requests

from src.parsers.base import BaseParser, _run_playwright
from src.models.content import ParsedContent


class ConcreteParser(BaseParser):
    def parse(self, url: str) -> ParsedContent:
        return ParsedContent(url=url, platform="test", title="Test", content="")


class TestBaseParserFetch:
    def test_fetch_success(self):
        parser = ConcreteParser()
        mock_resp = MagicMock()
        mock_resp.text = "<html>content</html>"
        mock_resp.apparent_encoding = "utf-8"
        mock_resp.raise_for_status = MagicMock()

        with patch("src.parsers.base.requests.get", return_value=mock_resp):
            result = parser.fetch("https://example.com")
        assert result == "<html>content</html>"

    def test_fetch_uses_default_headers(self):
        parser = ConcreteParser()
        mock_resp = MagicMock()
        mock_resp.text = "ok"
        mock_resp.apparent_encoding = "utf-8"
        mock_resp.raise_for_status = MagicMock()

        with patch("src.parsers.base.requests.get", return_value=mock_resp) as mock_get:
            parser.fetch("https://example.com")
        call_kwargs = mock_get.call_args
        assert "User-Agent" in call_kwargs[1]["headers"]

    def test_fetch_custom_headers(self):
        parser = ConcreteParser()
        mock_resp = MagicMock()
        mock_resp.text = "ok"
        mock_resp.apparent_encoding = "utf-8"
        mock_resp.raise_for_status = MagicMock()

        with patch("src.parsers.base.requests.get", return_value=mock_resp) as mock_get:
            parser.fetch("https://example.com", headers={"X-Custom": "val"})
        headers = mock_get.call_args[1]["headers"]
        assert headers["X-Custom"] == "val"
        assert "User-Agent" in headers

    def test_fetch_raises_on_http_error(self):
        parser = ConcreteParser()
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.HTTPError("404")

        with patch("src.parsers.base.requests.get", return_value=mock_resp):
            with pytest.raises(requests.HTTPError):
                parser.fetch("https://example.com/missing")


class TestFetchWithBrowser:
    def test_fetch_with_browser_success(self):
        parser = ConcreteParser()
        with patch("src.parsers.base._browser_executor") as mock_executor:
            mock_future = MagicMock()
            mock_future.result.return_value = "<html>browser content</html>"
            mock_executor.submit.return_value = mock_future
            result = parser.fetch_with_browser("https://example.com")
        assert result == "<html>browser content</html>"

    def test_fetch_with_browser_fallback(self):
        parser = ConcreteParser()
        with patch("src.parsers.base._browser_executor") as mock_executor, \
             patch.object(parser, "fetch", return_value="<html>fallback</html>"):
            mock_future = MagicMock()
            mock_future.result.side_effect = Exception("browser crashed")
            mock_executor.submit.return_value = mock_future
            result = parser.fetch_with_browser("https://example.com")
        assert result == "<html>fallback</html>"
