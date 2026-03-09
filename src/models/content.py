from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class ParsedContent:
    """Raw content extracted from a platform."""
    url: str
    platform: str
    title: str
    content: str
    author: Optional[str] = None
    publish_date: Optional[datetime] = None
    images: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@dataclass
class AnalyzedContent:
    """Content after AI analysis."""
    parsed: ParsedContent
    tags: list[str] = field(default_factory=list)
    summary: str = ""
    category: str = "other"
    key_points: list[str] = field(default_factory=list)
    related: list[dict] = field(default_factory=list)  # [{"id": ..., "title": ..., "reason": ...}]
    embedding: list[float] = field(default_factory=list)
