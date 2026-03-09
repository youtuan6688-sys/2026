import os
import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from config.settings import Settings
from src.models.content import ParsedContent, AnalyzedContent


@pytest.fixture
def tmp_dir(tmp_path):
    """Provide a temporary directory for test data."""
    return tmp_path


@pytest.fixture
def settings(tmp_dir):
    """Settings with temporary paths."""
    return Settings(
        feishu_app_id="test_app_id",
        feishu_app_secret="test_secret",
        feishu_encrypt_key="test_encrypt",
        feishu_verification_token="test_token",
        ai_api_key="test_key",
        vault_path=str(tmp_dir / "vault"),
        chromadb_path=str(tmp_dir / "chromadb"),
        sqlite_path=str(tmp_dir / "content.db"),
    )


@pytest.fixture
def sample_parsed():
    """Sample ParsedContent for testing."""
    return ParsedContent(
        url="https://example.com/article",
        platform="generic",
        title="Test Article Title",
        content="This is the test article content with enough text for analysis.",
        author="Test Author",
        images=["https://example.com/img1.jpg"],
    )


@pytest.fixture
def sample_analyzed(sample_parsed):
    """Sample AnalyzedContent for testing."""
    return AnalyzedContent(
        parsed=sample_parsed,
        tags=["test", "article", "example"],
        summary="This is a test summary.",
        category="tech",
        key_points=["Point 1", "Point 2"],
        related=[],
    )


@pytest.fixture
def mock_sender():
    """Mocked FeishuSender."""
    sender = MagicMock()
    sender.send_text = MagicMock()
    sender.send_card = MagicMock()
    sender.send_error = MagicMock()
    return sender
