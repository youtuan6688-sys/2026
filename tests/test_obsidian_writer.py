from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from config.settings import Settings
from src.models.content import ParsedContent, AnalyzedContent
from src.storage.obsidian_writer import ObsidianWriter, FOLDER_MAP, PLATFORM_NAMES


@pytest.fixture
def writer(settings):
    mock_vector = MagicMock()
    mock_index = MagicMock()
    return ObsidianWriter(settings, mock_vector, mock_index)


class TestObsidianWriter:
    def test_save_creates_file(self, writer, sample_analyzed, tmp_dir):
        filepath = writer.save(sample_analyzed)
        assert filepath.exists()
        assert filepath.suffix == ".md"

    def test_save_in_correct_folder(self, writer, sample_analyzed, tmp_dir):
        filepath = writer.save(sample_analyzed)
        assert "articles" in str(filepath)

    def test_save_social_platform(self, writer, tmp_dir):
        parsed = ParsedContent(
            url="https://twitter.com/user/status/123",
            platform="twitter", title="Tweet", content="Hello",
        )
        analyzed = AnalyzedContent(parsed=parsed, tags=["test"], summary="Sum", category="tech")
        filepath = writer.save(analyzed)
        assert "social" in str(filepath)

    def test_save_calls_vector_store(self, writer, sample_analyzed, settings):
        writer.save(sample_analyzed)
        writer.vector_store.add.assert_called_once()

    def test_save_calls_content_index(self, writer, sample_analyzed, settings):
        writer.save(sample_analyzed)
        writer.content_index.add.assert_called_once()

    def test_save_vector_failure_doesnt_crash(self, writer, sample_analyzed, settings):
        writer.vector_store.add.side_effect = Exception("vector fail")
        filepath = writer.save(sample_analyzed)
        assert filepath.exists()

    def test_save_index_failure_doesnt_crash(self, writer, sample_analyzed, settings):
        writer.content_index.add.side_effect = Exception("index fail")
        filepath = writer.save(sample_analyzed)
        assert filepath.exists()

    def test_markdown_has_frontmatter(self, writer, sample_analyzed):
        filepath = writer.save(sample_analyzed)
        content = filepath.read_text(encoding="utf-8")
        assert content.startswith("---")
        assert "title:" in content
        assert "tags:" in content
        assert "category:" in content

    def test_markdown_has_body_sections(self, writer, sample_analyzed):
        filepath = writer.save(sample_analyzed)
        content = filepath.read_text(encoding="utf-8")
        assert "## 摘要" in content
        assert "## 内容" in content
        assert "## 来源" in content

    def test_markdown_has_key_points(self, writer, sample_analyzed):
        filepath = writer.save(sample_analyzed)
        content = filepath.read_text(encoding="utf-8")
        assert "## 要点" in content
        assert "Point 1" in content

    def test_related_content_section(self, writer, sample_analyzed):
        sample_analyzed.related = [{"id": "r1", "title": "Related", "reason": "similar topic"}]
        filepath = writer.save(sample_analyzed)
        content = filepath.read_text(encoding="utf-8")
        assert "## 相关内容" in content
        assert "Related" in content


class TestSlugify:
    def test_basic(self, writer):
        assert writer._slugify("Hello World") == "Hello-World"

    def test_chinese(self, writer):
        result = writer._slugify("测试文章标题")
        assert "测试文章标题" in result

    def test_special_chars(self, writer):
        result = writer._slugify("Test: Article! @#$")
        assert "@" not in result
        assert "#" not in result

    def test_long_text_truncated(self, writer):
        result = writer._slugify("x" * 100)
        assert len(result) <= 50

    def test_empty_returns_untitled(self, writer):
        assert writer._slugify("!!!") == "untitled"


class TestEscapeYaml:
    def test_escapes_quotes(self, writer):
        assert '\\"' in writer._escape_yaml('say "hello"')

    def test_replaces_newlines(self, writer):
        assert "\n" not in writer._escape_yaml("line1\nline2")


class TestFolderMap:
    @pytest.mark.parametrize("platform,folder", [
        ("wechat", "articles"),
        ("twitter", "social"),
        ("xiaohongshu", "social"),
        ("douyin", "social"),
        ("feishu", "docs"),
        ("generic", "articles"),
    ])
    def test_folder_mapping(self, platform, folder):
        assert FOLDER_MAP[platform] == folder
