from unittest.mock import patch, MagicMock

import pytest

from src.parsers import get_parser
from src.parsers.base import BaseParser
from src.parsers.generic_web import GenericWebParser
from src.parsers.wechat_article import WechatArticleParser
from src.parsers.twitter import TwitterParser
from src.parsers.xiaohongshu import XiaohongshuParser
from src.parsers.douyin import DouyinParser
from src.parsers.feishu_doc import FeishuDocParser
from src.models.content import ParsedContent


class TestGetParser:
    def test_generic(self):
        assert isinstance(get_parser("generic"), GenericWebParser)

    def test_wechat(self):
        assert isinstance(get_parser("wechat"), WechatArticleParser)

    def test_twitter(self):
        assert isinstance(get_parser("twitter"), TwitterParser)

    def test_xiaohongshu(self):
        assert isinstance(get_parser("xiaohongshu"), XiaohongshuParser)

    def test_douyin(self):
        assert isinstance(get_parser("douyin"), DouyinParser)

    def test_feishu(self):
        assert isinstance(get_parser("feishu"), FeishuDocParser)

    def test_unknown_falls_back_to_generic(self):
        assert isinstance(get_parser("unknown_platform"), GenericWebParser)


class TestGenericWebParser:
    @patch.object(GenericWebParser, "fetch")
    def test_parse_basic_html(self, mock_fetch):
        mock_fetch.return_value = """
        <html>
        <head>
            <title>Test Page</title>
            <meta name="author" content="John">
        </head>
        <body>
            <article>
                <p>Article content here with enough text to extract.</p>
                <img src="https://example.com/img.jpg">
            </article>
        </body>
        </html>
        """
        parser = GenericWebParser()
        result = parser.parse("https://example.com/page")
        assert isinstance(result, ParsedContent)
        assert result.platform == "generic"
        assert result.url == "https://example.com/page"

    @patch.object(GenericWebParser, "fetch")
    def test_parse_extracts_author(self, mock_fetch):
        mock_fetch.return_value = """
        <html>
        <head><meta name="author" content="Test Author"></head>
        <body><p>Content</p></body>
        </html>
        """
        result = GenericWebParser().parse("https://example.com")
        assert result.author == "Test Author"

    @patch.object(GenericWebParser, "fetch")
    def test_parse_no_author(self, mock_fetch):
        mock_fetch.return_value = "<html><body><p>Content</p></body></html>"
        result = GenericWebParser().parse("https://example.com")
        assert result.author is None


class TestWechatArticleParser:
    @patch.object(WechatArticleParser, "fetch")
    def test_parse_wechat(self, mock_fetch):
        mock_fetch.return_value = """
        <html>
        <head><title>WeChat Article</title></head>
        <body>
            <h1 id="activity-name">公众号文章标题</h1>
            <span class="rich_media_meta_text">作者名</span>
            <div id="js_content">
                <p>文章正文内容</p>
                <img data-src="https://img.weixin.com/1.jpg">
            </div>
        </body>
        </html>
        """
        result = WechatArticleParser().parse("https://mp.weixin.qq.com/s/abc")
        assert result.platform == "wechat"
        assert result.title == "公众号文章标题"
        assert result.author == "作者名"
        assert "文章正文内容" in result.content
        assert len(result.images) >= 1

    @patch.object(WechatArticleParser, "fetch")
    def test_parse_wechat_with_date(self, mock_fetch):
        mock_fetch.return_value = """
        <html>
        <body>
            <h1>Title</h1>
            <div id="js_content"><p>Content</p></div>
            <script>var ct = "1700000000";</script>
        </body>
        </html>
        """
        result = WechatArticleParser().parse("https://mp.weixin.qq.com/s/abc")
        assert result.publish_date is not None


class TestTwitterParser:
    def test_extract_tweet_id(self):
        parser = TwitterParser()
        assert parser._extract_tweet_id("https://x.com/user/status/12345") == "12345"
        assert parser._extract_tweet_id("https://twitter.com/u/status/99") == "99"
        assert parser._extract_tweet_id("https://example.com/page") is None

    @patch.object(TwitterParser, "_fetch_jina", return_value=None)
    @patch.object(TwitterParser, "_fetch_vxtwitter_safe", return_value=None)
    @patch.object(TwitterParser, "_parse_oembed")
    def test_fallback_chain(self, mock_oembed, mock_vx, mock_jina):
        mock_oembed.side_effect = Exception("fail")
        parser = TwitterParser()
        result = parser.parse("https://x.com/user/status/123")
        assert result.platform == "twitter"
        assert "无法自动提取" in result.content

    @patch.object(TwitterParser, "_fetch_jina")
    @patch.object(TwitterParser, "_fetch_vxtwitter_safe")
    def test_jina_priority(self, mock_vx, mock_jina):
        mock_jina.return_value = "Full article content from Jina reader"
        mock_vx.return_value = {
            "user_name": "John",
            "user_screen_name": "john",
            "text": "Tweet text",
            "likes": 100,
            "retweets": 50,
            "media_extended": [],
        }
        parser = TwitterParser()
        result = parser.parse("https://x.com/john/status/123")
        assert "John" in (result.author or "")
        assert result.platform == "twitter"

    @patch.object(TwitterParser, "_fetch_jina", return_value=None)
    @patch.object(TwitterParser, "_fetch_vxtwitter_safe")
    def test_vxtwitter_fallback(self, mock_vx, mock_jina):
        mock_vx.return_value = {
            "user_name": "Jane",
            "user_screen_name": "jane",
            "text": "Hello world",
            "likes": 10,
            "retweets": 5,
            "replies": 2,
            "media_extended": [{"type": "image", "url": "https://img.com/1.jpg"}],
            "article": None,
        }
        parser = TwitterParser()
        result = parser.parse("https://x.com/jane/status/456")
        assert result.author == "Jane (@jane)"
        assert "Hello world" in result.content
        assert len(result.images) >= 1


class TestXiaohongshuParser:
    @patch.object(XiaohongshuParser, "fetch_with_browser")
    def test_parse_with_meta(self, mock_fetch):
        mock_fetch.return_value = """
        <html>
        <head>
            <meta property="og:title" content="小红书笔记标题">
            <meta property="og:description" content="笔记内容描述">
            <meta property="og:author" content="作者">
            <meta property="og:image" content="https://img.xhscdn.com/1.jpg">
        </head>
        <body></body>
        </html>
        """
        result = XiaohongshuParser().parse("https://xiaohongshu.com/explore/123")
        assert result.platform == "xiaohongshu"
        assert result.title == "小红书笔记标题"
        assert result.author == "作者"

    @patch.object(XiaohongshuParser, "fetch_with_browser")
    def test_parse_failure_returns_fallback(self, mock_fetch):
        mock_fetch.side_effect = Exception("browser fail")
        result = XiaohongshuParser().parse("https://xiaohongshu.com/123")
        assert result.platform == "xiaohongshu"
        assert "无法自动提取" in result.content


class TestDouyinParser:
    @patch.object(DouyinParser, "fetch_with_browser")
    def test_parse_with_meta(self, mock_fetch):
        mock_fetch.return_value = """
        <html>
        <head>
            <meta property="og:title" content="抖音视频标题">
            <meta property="og:description" content="视频描述">
            <meta property="og:image" content="https://img.douyin.com/cover.jpg">
        </head>
        <body></body>
        </html>
        """
        result = DouyinParser().parse("https://www.douyin.com/video/123")
        assert result.platform == "douyin"
        assert result.title == "抖音视频标题"
        assert result.metadata.get("type") == "video"

    @patch.object(DouyinParser, "fetch_with_browser")
    def test_parse_failure_returns_fallback(self, mock_fetch):
        mock_fetch.side_effect = Exception("timeout")
        result = DouyinParser().parse("https://www.douyin.com/video/123")
        assert "无法自动提取" in result.content


class TestFeishuDocParser:
    @patch.object(GenericWebParser, "parse")
    def test_delegates_to_generic(self, mock_parse):
        mock_parse.return_value = ParsedContent(
            url="https://feishu.cn/docs/abc",
            platform="generic", title="Feishu Doc", content="Content",
        )
        result = FeishuDocParser().parse("https://feishu.cn/docs/abc")
        assert result.platform == "feishu"

    @patch.object(GenericWebParser, "parse")
    def test_failure_returns_fallback(self, mock_parse):
        mock_parse.side_effect = Exception("fail")
        result = FeishuDocParser().parse("https://feishu.cn/docs/abc")
        assert result.platform == "feishu"
        assert "需要登录" in result.content
