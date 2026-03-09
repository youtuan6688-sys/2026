from unittest.mock import MagicMock, patch

import pytest
import requests

from src.parsers.twitter import TwitterParser
from src.models.content import ParsedContent


@pytest.fixture
def parser():
    return TwitterParser()


class TestExtractTweetId:
    def test_standard_url(self, parser):
        assert parser._extract_tweet_id("https://x.com/user/status/12345") == "12345"

    def test_twitter_url(self, parser):
        assert parser._extract_tweet_id("https://twitter.com/user/status/99999") == "99999"

    def test_no_status(self, parser):
        assert parser._extract_tweet_id("https://x.com/user/profile") is None


class TestFetchJina:
    def test_success(self, parser):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        # Must be > 100 chars to pass length check
        mock_resp.text = "Title\n\nSome real content here about AI and machine learning that is interesting\nMore content about technology and innovation in the modern world"
        with patch("src.parsers.twitter.requests.get", return_value=mock_resp):
            result = parser._fetch_jina("https://x.com/user/status/123")
        assert "Some real content" in result

    def test_filters_noise(self, parser):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        # Must be > 100 chars total to pass length check
        mock_resp.text = "Log in\nSign up\nDon't miss what's happening\nActual tweet content here with enough text to pass the minimum length check for jina reader"
        with patch("src.parsers.twitter.requests.get", return_value=mock_resp):
            result = parser._fetch_jina("https://x.com/user/status/123")
        assert "Log in" not in result
        assert "Actual tweet content" in result

    def test_returns_none_on_short_response(self, parser):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "short"
        with patch("src.parsers.twitter.requests.get", return_value=mock_resp):
            result = parser._fetch_jina("https://x.com/user/status/123")
        assert result is None

    def test_returns_none_on_error(self, parser):
        with patch("src.parsers.twitter.requests.get", side_effect=Exception("timeout")):
            result = parser._fetch_jina("https://x.com/user/status/123")
        assert result is None

    def test_returns_none_on_non_200(self, parser):
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        with patch("src.parsers.twitter.requests.get", return_value=mock_resp):
            result = parser._fetch_jina("https://x.com/user/status/123")
        assert result is None


class TestFetchVxtwitter:
    def test_success(self, parser):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"text": "Tweet text", "likes": 100}
        mock_resp.raise_for_status = MagicMock()
        with patch("src.parsers.twitter.requests.get", return_value=mock_resp):
            result = parser._fetch_vxtwitter_safe("12345")
        assert result["text"] == "Tweet text"

    def test_ssl_error_retries(self, parser):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"text": "ok"}
        mock_resp.raise_for_status = MagicMock()
        with patch("src.parsers.twitter.requests.get",
                    side_effect=[requests.exceptions.SSLError(), mock_resp]):
            with patch("src.parsers.twitter.time.sleep"):
                result = parser._fetch_vxtwitter_safe("12345")
        assert result["text"] == "ok"

    def test_returns_none_on_all_failures(self, parser):
        with patch("src.parsers.twitter.requests.get",
                    side_effect=requests.exceptions.SSLError()):
            with patch("src.parsers.twitter.time.sleep"):
                result = parser._fetch_vxtwitter_safe("12345")
        assert result is None

    def test_returns_none_on_other_exception(self, parser):
        with patch("src.parsers.twitter.requests.get",
                    side_effect=ValueError("bad json")):
            result = parser._fetch_vxtwitter_safe("12345")
        assert result is None


class TestBuildFromJina:
    def test_with_vx_data(self, parser):
        vx_data = {
            "user_name": "John",
            "user_screen_name": "john_doe",
            "likes": 50,
            "retweets": 10,
            "replies": 5,
            "text": "Great tweet about AI",
            "media_extended": [{"type": "image", "url": "https://img.com/1.jpg"}],
            "article": None,
        }
        result = parser._build_from_jina(
            "https://x.com/john_doe/status/123", "123",
            "Full content from Jina", vx_data,
        )
        assert result.author == "John (@john_doe)"
        assert result.platform == "twitter"
        assert "Full content from Jina" in result.content
        assert len(result.images) == 1

    def test_with_article_title(self, parser):
        vx_data = {
            "user_name": "John", "user_screen_name": "john",
            "likes": 10, "retweets": 5,
            "text": "Check this article",
            "media_extended": [],
            "article": {"title": "AI Revolution", "image": "https://img.com/art.jpg"},
        }
        result = parser._build_from_jina(
            "https://x.com/john/status/1", "1",
            "Full article content", vx_data,
        )
        assert result.title == "AI Revolution"
        assert "https://img.com/art.jpg" in result.images

    def test_without_vx_data(self, parser):
        result = parser._build_from_jina(
            "https://x.com/u/status/1", "1",
            "Short line\nAnother line with enough content to use", None,
        )
        assert result.title != ""
        assert result.author is None

    def test_no_title_fallback(self, parser):
        result = parser._build_from_jina(
            "https://x.com/u/status/1", "1",
            "http://some.url\nhttp://other.url", None,
        )
        assert "Twitter" in result.title or "推文" in result.title


class TestBuildFromVxtwitter:
    def test_basic(self, parser):
        data = {
            "text": "Hello world",
            "user_name": "Alice",
            "user_screen_name": "alice",
            "likes": 100, "retweets": 20, "replies": 5,
            "media_extended": [],
            "article": None,
        }
        with patch.object(parser, "_follow_embedded_urls", return_value=""):
            result = parser._build_from_vxtwitter("https://x.com/alice/status/1", "1", data)
        assert result.title == "Hello world"
        assert result.author == "Alice (@alice)"

    def test_with_article(self, parser):
        data = {
            "text": "New blog post",
            "user_name": "Bob",
            "user_screen_name": "bob",
            "likes": 50, "retweets": 10, "replies": 2,
            "media_extended": [{"type": "image", "url": "https://img.com/bob.jpg"}],
            "article": {"title": "My Blog", "preview_text": "Preview of blog"},
        }
        with patch.object(parser, "_follow_embedded_urls", return_value=""):
            result = parser._build_from_vxtwitter("https://x.com/bob/status/2", "2", data)
        assert result.title == "My Blog"
        assert "Preview of blog" in result.content
        assert len(result.images) == 1

    def test_empty_text_uses_author_title(self, parser):
        data = {
            "text": "", "user_name": "Eve", "user_screen_name": "eve",
            "likes": 0, "retweets": 0, "replies": 0,
            "media_extended": [], "article": None,
        }
        with patch.object(parser, "_follow_embedded_urls", return_value=""):
            result = parser._build_from_vxtwitter("https://x.com/eve/status/3", "3", data)
        assert "Eve" in result.title


class TestFollowEmbeddedUrls:
    def test_follows_tco_links(self, parser):
        mock_head = MagicMock()
        mock_head.url = "https://example.com/article"
        mock_get = MagicMock()
        # readability needs a substantial HTML document to extract content
        mock_get.text = (
            "<html><head><title>Test Article</title></head><body>"
            "<article><p>Article content here that is long enough to pass the minimum "
            "length threshold for extraction by readability and beautifulsoup parsers</p></article>"
            "</body></html>"
        )
        mock_get.apparent_encoding = "utf-8"

        with patch("src.parsers.twitter.requests.head", return_value=mock_head), \
             patch("src.parsers.twitter.requests.get", return_value=mock_get):
            result = parser._follow_embedded_urls("Check https://t.co/abc123")
        assert "Article content" in result

    def test_skips_pic_twitter(self, parser):
        mock_head = MagicMock()
        mock_head.url = "https://pic.twitter.com/abc"
        with patch("src.parsers.twitter.requests.head", return_value=mock_head):
            result = parser._follow_embedded_urls("Image https://t.co/img123")
        assert result == ""

    def test_handles_failure_gracefully(self, parser):
        with patch("src.parsers.twitter.requests.head", side_effect=Exception("timeout")):
            result = parser._follow_embedded_urls("https://t.co/broken")
        assert result == ""

    def test_no_urls(self, parser):
        result = parser._follow_embedded_urls("Just plain text without links")
        assert result == ""


class TestParseOembed:
    def test_success(self, parser):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "html": "<blockquote>Tweet content here</blockquote>",
            "author_name": "TestUser",
        }
        mock_resp.raise_for_status = MagicMock()
        with patch("src.parsers.twitter.requests.get", return_value=mock_resp):
            result = parser._parse_oembed("https://x.com/test/status/1")
        assert result.author == "TestUser"
        assert "Tweet content" in result.content


class TestParse:
    def test_no_tweet_id(self, parser):
        result = parser.parse("https://x.com/user/profile")
        assert "推文" in result.title

    def test_jina_path(self, parser):
        with patch.object(parser, "_extract_tweet_id", return_value="123"), \
             patch.object(parser, "_fetch_vxtwitter_safe", return_value=None), \
             patch.object(parser, "_fetch_jina", return_value="Full jina content"), \
             patch.object(parser, "_build_from_jina") as mock_build:
            mock_build.return_value = ParsedContent(
                url="u", platform="twitter", title="T", content="C",
            )
            parser.parse("https://x.com/user/status/123")
            mock_build.assert_called_once()

    def test_vx_only_path(self, parser):
        vx = {"text": "hello"}
        with patch.object(parser, "_extract_tweet_id", return_value="123"), \
             patch.object(parser, "_fetch_vxtwitter_safe", return_value=vx), \
             patch.object(parser, "_fetch_jina", return_value=None), \
             patch.object(parser, "_build_from_vxtwitter") as mock_build:
            mock_build.return_value = ParsedContent(
                url="u", platform="twitter", title="T", content="C",
            )
            parser.parse("https://x.com/user/status/123")
            mock_build.assert_called_once()

    def test_oembed_fallback(self, parser):
        with patch.object(parser, "_extract_tweet_id", return_value="123"), \
             patch.object(parser, "_fetch_vxtwitter_safe", return_value=None), \
             patch.object(parser, "_fetch_jina", return_value=None), \
             patch.object(parser, "_parse_oembed") as mock_oembed:
            mock_oembed.return_value = ParsedContent(
                url="u", platform="twitter", title="T", content="C",
            )
            parser.parse("https://x.com/user/status/123")
            mock_oembed.assert_called_once()

    def test_all_fail_fallback(self, parser):
        with patch.object(parser, "_extract_tweet_id", return_value="123"), \
             patch.object(parser, "_fetch_vxtwitter_safe", return_value=None), \
             patch.object(parser, "_fetch_jina", return_value=None), \
             patch.object(parser, "_parse_oembed", side_effect=Exception("fail")):
            result = parser.parse("https://x.com/user/status/123")
        assert "推文" in result.title
