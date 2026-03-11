from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class MusicTrack:
    """A downloaded music track in the local library."""
    track_id: str               # MD5 of source_url
    title: str
    artist: str
    album: str
    source_url: str
    source_platform: str
    file_path: str              # Relative to MUSIC_ROOT
    format: str                 # "flac" or "mp3"
    duration_seconds: int = 0
    bitrate: int = 0            # kbps
    file_size_bytes: int = 0
    cover_art_path: str = ""    # Relative to MUSIC_ROOT
    added_at: str = ""          # ISO timestamp
    track_number: int = 0
    genre: str = ""
    year: int = 0
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Playlist:
    """A user-created playlist."""
    playlist_id: str
    name: str
    description: str = ""
    track_ids: tuple[str, ...] = ()
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class DownloadResult:
    """Result from a download attempt."""
    success: bool
    file_path: str = ""         # Absolute path to downloaded file
    title: str = ""
    artist: str = ""
    album: str = ""
    duration_seconds: int = 0
    format: str = ""
    cover_url: str = ""
    error: str = ""
    metadata: dict = field(default_factory=dict)
