from datetime import datetime

from src.models.content import ParsedContent, AnalyzedContent


class TestParsedContent:
    def test_defaults(self):
        pc = ParsedContent(url="https://x.com", platform="twitter",
                          title="Test", content="Body")
        assert pc.author is None
        assert pc.publish_date is None
        assert pc.images == []
        assert pc.metadata == {}

    def test_with_all_fields(self):
        now = datetime.now()
        pc = ParsedContent(
            url="https://x.com", platform="twitter",
            title="Full", content="Body",
            author="Author", publish_date=now,
            images=["img1"], metadata={"key": "val"},
        )
        assert pc.author == "Author"
        assert pc.publish_date == now
        assert pc.images == ["img1"]
        assert pc.metadata == {"key": "val"}


class TestAnalyzedContent:
    def test_defaults(self):
        parsed = ParsedContent(url="u", platform="p", title="t", content="c")
        ac = AnalyzedContent(parsed=parsed)
        assert ac.tags == []
        assert ac.summary == ""
        assert ac.category == "other"
        assert ac.key_points == []
        assert ac.related == []
        assert ac.embedding == []

    def test_with_analysis(self):
        parsed = ParsedContent(url="u", platform="p", title="t", content="c")
        ac = AnalyzedContent(
            parsed=parsed, tags=["a", "b"],
            summary="Sum", category="tech",
            key_points=["p1"], related=[{"id": "1"}],
        )
        assert ac.tags == ["a", "b"]
        assert ac.category == "tech"
