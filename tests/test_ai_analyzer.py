import json
from unittest.mock import MagicMock, patch

import pytest

from src.ai.analyzer import AIAnalyzer
from src.models.content import ParsedContent, AnalyzedContent
from config.settings import Settings


@pytest.fixture
def analyzer():
    settings = MagicMock(spec=Settings)
    settings.max_content_length = 50000
    mock_vector = MagicMock()
    return AIAnalyzer(settings, mock_vector)


class TestAIAnalyzer:
    @patch.object(AIAnalyzer, "_call_ai")
    def test_analyze_returns_analyzed_content(self, mock_call, analyzer, sample_parsed):
        # _call_ai now returns parsed dict/list directly (structured output)
        mock_call.return_value = {
            "tags": ["ai", "test"],
            "summary": "AI summary",
            "category": "tech",
            "key_points": ["point1"],
        }
        analyzer.vector_store.query_similar.return_value = []

        result = analyzer.analyze(sample_parsed)
        assert isinstance(result, AnalyzedContent)
        assert result.tags == ["ai", "test"]
        assert result.summary == "AI summary"
        assert result.category == "tech"

    @patch.object(AIAnalyzer, "_call_ai")
    def test_analyze_handles_json_error(self, mock_call, analyzer, sample_parsed):
        mock_call.side_effect = json.JSONDecodeError("bad json", "", 0)
        analyzer.vector_store.query_similar.return_value = []

        result = analyzer.analyze(sample_parsed)
        assert result.tags == []
        assert result.category == "other"

    @patch.object(AIAnalyzer, "_call_ai")
    def test_analyze_handles_api_failure(self, mock_call, analyzer, sample_parsed):
        mock_call.side_effect = Exception("API error")
        analyzer.vector_store.query_similar.return_value = []

        result = analyzer.analyze(sample_parsed)
        assert result.tags == []
        assert result.summary == sample_parsed.title

    def test_parse_json_response_plain(self, analyzer):
        text = '{"key": "value"}'
        result = analyzer._parse_json_response(text)
        assert result == {"key": "value"}

    def test_parse_json_response_with_fences(self, analyzer):
        text = '```json\n{"key": "value"}\n```'
        result = analyzer._parse_json_response(text)
        assert result == {"key": "value"}

    @patch.object(AIAnalyzer, "_call_ai")
    def test_find_related_with_vector_results(self, mock_call, analyzer, sample_parsed):
        analyzer.vector_store.query_similar.return_value = [
            {"id": "doc1", "title": "Related Doc", "summary": "A related doc"},
        ]
        # _call_ai now returns parsed list directly
        mock_call.return_value = [
            {"id": "doc1", "reason": "similar topic"}
        ]

        analysis = {"tags": ["test"], "summary": "test"}
        result = analyzer._find_related(analysis, sample_parsed)
        assert len(result) == 1
        assert result[0]["id"] == "doc1"
        assert result[0]["title"] == "Related Doc"

    @patch.object(AIAnalyzer, "_call_ai")
    def test_find_related_empty_when_no_similar(self, mock_call, analyzer, sample_parsed):
        analyzer.vector_store.query_similar.return_value = []
        analysis = {"tags": [], "summary": ""}
        result = analyzer._find_related(analysis, sample_parsed)
        assert result == []
