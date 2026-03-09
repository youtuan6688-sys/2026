import sqlite3
import tempfile
from pathlib import Path

import pytest

from src.storage.content_index import ContentIndex


@pytest.fixture
def index(tmp_path):
    db_path = str(tmp_path / "test.db")
    return ContentIndex(db_path)


class TestContentIndex:
    def test_init_creates_table(self, index):
        row = index.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='content'"
        ).fetchone()
        assert row is not None

    def test_exists_returns_false_for_new_url(self, index):
        assert index.exists("https://example.com/new") is False

    def test_add_and_exists(self, index):
        index.add(
            doc_id="abc123",
            url="https://example.com/article",
            title="Test",
            platform="generic",
            file_path="/vault/articles/test.md",
            tags=["test"],
            category="tech",
            summary="A test article",
        )
        assert index.exists("https://example.com/article") is True

    def test_exists_by_normalized_url(self, index):
        index.add(
            doc_id="abc123",
            url="https://example.com/article?utm_source=x",
            title="Test",
            platform="generic",
            file_path="/vault/articles/test.md",
            tags=["test"],
            category="tech",
            summary="A test article",
        )
        assert index.exists("https://example.com/article") is True

    def test_add_duplicate_replaces(self, index):
        for i in range(2):
            index.add(
                doc_id="abc123",
                url="https://example.com/article",
                title=f"Test {i}",
                platform="generic",
                file_path="/vault/test.md",
                tags=["test"],
                category="tech",
                summary=f"Summary {i}",
            )
        rows = index.conn.execute("SELECT COUNT(*) FROM content").fetchone()
        assert rows[0] == 1

    def test_get_all_summaries(self, index):
        for i in range(3):
            index.add(
                doc_id=f"id{i}",
                url=f"https://example.com/{i}",
                title=f"Title {i}",
                platform="generic",
                file_path=f"/vault/{i}.md",
                tags=[f"tag{i}"],
                category="tech",
                summary=f"Summary {i}",
            )
        summaries = index.get_all_summaries(limit=2)
        assert len(summaries) == 2
        assert "title" in summaries[0]
        assert "summary" in summaries[0]

    def test_get_all_summaries_empty(self, index):
        assert index.get_all_summaries() == []
