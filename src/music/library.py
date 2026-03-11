"""Music library index management with JSON persistence."""
import json
import logging
import shutil
import threading
from hashlib import md5
from datetime import datetime
from pathlib import Path

from src.music.models import MusicTrack

logger = logging.getLogger(__name__)

MUSIC_ROOT = Path.home() / "Music" / "HappyLibrary"
LIBRARY_FILE = MUSIC_ROOT / "library.json"


class MusicLibrary:
    """Thread-safe JSON-based music library index."""

    def __init__(self, library_file: Path = LIBRARY_FILE):
        self._file = library_file
        self._lock = threading.Lock()
        self._tracks: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if self._file.exists():
            try:
                data = json.loads(self._file.read_text(encoding="utf-8"))
                self._tracks = data.get("tracks", {})
            except Exception as e:
                logger.error(f"Failed to load library: {e}")
                self._tracks = {}

    def _save(self) -> None:
        self._file.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": 1,
            "updated_at": datetime.now().isoformat(),
            "track_count": len(self._tracks),
            "tracks": self._tracks,
        }
        tmp = self._file.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self._file)

    @staticmethod
    def url_id(url: str) -> str:
        return md5(url.encode()).hexdigest()[:12]

    def add_track(self, track: MusicTrack) -> MusicTrack:
        """Add a track to the library. Returns the track."""
        with self._lock:
            self._tracks[track.track_id] = {
                "track_id": track.track_id,
                "title": track.title,
                "artist": track.artist,
                "album": track.album,
                "source_url": track.source_url,
                "source_platform": track.source_platform,
                "file_path": track.file_path,
                "format": track.format,
                "duration_seconds": track.duration_seconds,
                "bitrate": track.bitrate,
                "file_size_bytes": track.file_size_bytes,
                "cover_art_path": track.cover_art_path,
                "added_at": track.added_at,
                "track_number": track.track_number,
                "genre": track.genre,
                "year": track.year,
            }
            self._save()
        return track

    def remove_track(self, track_id: str) -> bool:
        """Remove a track from the library and delete the file."""
        with self._lock:
            entry = self._tracks.pop(track_id, None)
            if entry is None:
                return False
            # Delete the audio file
            file_path = MUSIC_ROOT / entry["file_path"]
            if file_path.exists():
                file_path.unlink()
            self._save()
        return True

    def find_by_url(self, url: str) -> MusicTrack | None:
        """Check if a track from this URL already exists (dedup)."""
        track_id = self.url_id(url)
        with self._lock:
            entry = self._tracks.get(track_id)
        if entry:
            return _dict_to_track(entry)
        return None

    def get_track(self, track_id: str) -> MusicTrack | None:
        with self._lock:
            entry = self._tracks.get(track_id)
        if entry:
            return _dict_to_track(entry)
        return None

    def search(self, query: str) -> list[MusicTrack]:
        """Search tracks by title, artist, or album."""
        query_lower = query.lower()
        results = []
        with self._lock:
            for entry in self._tracks.values():
                combined = f"{entry.get('title', '')} {entry.get('artist', '')} {entry.get('album', '')}".lower()
                if query_lower in combined:
                    results.append(_dict_to_track(entry))
        return results[:20]

    def list_recent(self, limit: int = 20) -> list[MusicTrack]:
        """List most recently added tracks."""
        with self._lock:
            sorted_entries = sorted(
                self._tracks.values(),
                key=lambda e: e.get("added_at", ""),
                reverse=True,
            )
        return [_dict_to_track(e) for e in sorted_entries[:limit]]

    def get_stats(self) -> dict:
        """Get library statistics."""
        with self._lock:
            tracks = list(self._tracks.values())

        total_size = sum(e.get("file_size_bytes", 0) for e in tracks)
        total_duration = sum(e.get("duration_seconds", 0) for e in tracks)
        formats = {}
        platforms = {}
        for e in tracks:
            fmt = e.get("format", "unknown")
            formats[fmt] = formats.get(fmt, 0) + 1
            plat = e.get("source_platform", "unknown")
            platforms[plat] = platforms.get(plat, 0) + 1

        return {
            "total_tracks": len(tracks),
            "total_size_mb": round(total_size / (1024 * 1024), 1),
            "total_duration_hours": round(total_duration / 3600, 1),
            "formats": formats,
            "platforms": platforms,
        }

    def all_track_ids(self) -> list[str]:
        with self._lock:
            return list(self._tracks.keys())


def _dict_to_track(d: dict) -> MusicTrack:
    return MusicTrack(
        track_id=d["track_id"],
        title=d.get("title", ""),
        artist=d.get("artist", ""),
        album=d.get("album", ""),
        source_url=d.get("source_url", ""),
        source_platform=d.get("source_platform", ""),
        file_path=d.get("file_path", ""),
        format=d.get("format", ""),
        duration_seconds=d.get("duration_seconds", 0),
        bitrate=d.get("bitrate", 0),
        file_size_bytes=d.get("file_size_bytes", 0),
        cover_art_path=d.get("cover_art_path", ""),
        added_at=d.get("added_at", ""),
        track_number=d.get("track_number", 0),
        genre=d.get("genre", ""),
        year=d.get("year", 0),
    )
