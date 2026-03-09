import pytest

from src.utils.url_utils import extract_urls, detect_platform, normalize_url, _is_real_url


class TestExtractUrls:
    def test_single_url(self):
        text = "Check this out https://example.com/article"
        assert extract_urls(text) == ["https://example.com/article"]

    def test_multiple_urls(self):
        text = "See https://a.com and https://b.com/path"
        result = extract_urls(text)
        assert len(result) == 2
        assert "https://a.com" in result
        assert "https://b.com/path" in result

    def test_no_urls(self):
        assert extract_urls("no links here") == []

    def test_filters_fake_urls(self):
        text = "See http://tools.md and http://memory.md for details"
        assert extract_urls(text) == []

    def test_filters_urls_ending_with_paren(self):
        text = "http://example.com/path)"
        assert extract_urls(text) == []

    def test_empty_string(self):
        assert extract_urls("") == []

    def test_real_url_with_path(self):
        text = "Visit https://mp.weixin.qq.com/s/abc123"
        result = extract_urls(text)
        assert len(result) == 1
        assert "mp.weixin.qq.com" in result[0]


class TestDetectPlatform:
    @pytest.mark.parametrize("url,expected", [
        ("https://mp.weixin.qq.com/s/abc", "wechat"),
        ("https://www.xiaohongshu.com/explore/123", "xiaohongshu"),
        ("https://xhslink.com/abc", "xiaohongshu"),
        ("https://www.douyin.com/video/123", "douyin"),
        ("https://v.douyin.com/abc", "douyin"),
        ("https://twitter.com/user/status/123", "twitter"),
        ("https://x.com/user/status/123", "twitter"),
        ("https://t.co/abc", "twitter"),
        ("https://feishu.cn/docs/abc", "feishu"),
        ("https://larksuite.com/docs/abc", "feishu"),
        ("https://example.com/page", "generic"),
        ("https://github.com/repo", "generic"),
    ])
    def test_platform_detection(self, url, expected):
        assert detect_platform(url) == expected


class TestNormalizeUrl:
    def test_removes_query_params(self):
        url = "https://example.com/article?utm_source=twitter&ref=123"
        result = normalize_url(url)
        assert result == "https://example.com/article"

    def test_preserves_path(self):
        url = "https://example.com/path/to/page"
        result = normalize_url(url)
        assert result == "https://example.com/path/to/page"

    def test_preserves_scheme_and_host(self):
        url = "https://mp.weixin.qq.com/s/abc"
        result = normalize_url(url)
        assert "https://mp.weixin.qq.com" in result


class TestIsRealUrl:
    def test_valid_url(self):
        assert _is_real_url("https://example.com/page") is True

    def test_md_file_url(self):
        assert _is_real_url("http://tools.md") is False

    def test_no_dot_in_host(self):
        assert _is_real_url("http://localhost/path") is False

    def test_url_ending_with_paren(self):
        assert _is_real_url("https://example.com/path)") is False
