"""Data models for video analysis."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class VideoInfo:
    """Metadata about a downloaded video."""
    url: str
    platform: str
    video_path: str = ""          # local file path after download
    title: str = ""
    author: str = ""
    duration: int = 0             # seconds
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    description: str = ""
    publish_date: str = ""
    file_size_mb: float = 0.0
    thumbnail_url: str = ""


@dataclass
class BreakdownResult:
    """Result of a video breakdown analysis."""
    url: str
    platform: str
    title: str
    breakdown_json: dict = field(default_factory=dict)
    summary: str = ""             # one_sentence_summary
    total_score: float = 0.0
    analyzed_at: str = field(default_factory=lambda: datetime.now().isoformat())
    video_info: dict = field(default_factory=dict)  # serialized VideoInfo
    error: str = ""
