"""Playlist management with M3U8 export."""
import json
import logging
import threading
from datetime import datetime
from hashlib import md5
from pathlib import Path

from src.music.models import Playlist
from src.music.library import MusicLibrary, MUSIC_ROOT

logger = logging.getLogger(__name__)

PLAYLISTS_FILE = MUSIC_ROOT / "playlists" / "playlists.json"
EXPORTS_DIR = MUSIC_ROOT / "playlists" / "exports"


class PlaylistManager:
    """Manage playlists with JSON persistence and M3U8 export."""

    def __init__(self, library: MusicLibrary):
        self._library = library
        self._lock = threading.Lock()
        self._playlists: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if PLAYLISTS_FILE.exists():
            try:
                data = json.loads(PLAYLISTS_FILE.read_text(encoding="utf-8"))
                self._playlists = data.get("playlists", {})
            except Exception as e:
                logger.error(f"Failed to load playlists: {e}")

    def _save(self) -> None:
        PLAYLISTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": 1,
            "updated_at": datetime.now().isoformat(),
            "playlists": self._playlists,
        }
        tmp = PLAYLISTS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(PLAYLISTS_FILE)

    def create(self, name: str, description: str = "") -> Playlist:
        """Create a new playlist."""
        pid = md5(f"{name}-{datetime.now().isoformat()}".encode()).hexdigest()[:8]
        now = datetime.now().isoformat()
        with self._lock:
            self._playlists[pid] = {
                "playlist_id": pid,
                "name": name,
                "description": description,
                "track_ids": [],
                "created_at": now,
                "updated_at": now,
            }
            self._save()
        return self._to_playlist(self._playlists[pid])

    def add_tracks(self, playlist_id: str, track_ids: list[str]) -> Playlist | None:
        """Add tracks to a playlist."""
        with self._lock:
            pl = self._playlists.get(playlist_id)
            if not pl:
                return None
            existing = set(pl["track_ids"])
            for tid in track_ids:
                if tid not in existing:
                    pl["track_ids"].append(tid)
                    existing.add(tid)
            pl["updated_at"] = datetime.now().isoformat()
            self._save()
        return self._to_playlist(pl)

    def remove_tracks(self, playlist_id: str, track_ids: list[str]) -> Playlist | None:
        """Remove tracks from a playlist."""
        remove_set = set(track_ids)
        with self._lock:
            pl = self._playlists.get(playlist_id)
            if not pl:
                return None
            pl["track_ids"] = [t for t in pl["track_ids"] if t not in remove_set]
            pl["updated_at"] = datetime.now().isoformat()
            self._save()
        return self._to_playlist(pl)

    def delete(self, playlist_id: str) -> bool:
        """Delete a playlist."""
        with self._lock:
            removed = self._playlists.pop(playlist_id, None)
            if removed:
                self._save()
                # Clean up exported M3U8
                m3u_path = EXPORTS_DIR / f"{removed['name']}.m3u8"
                if m3u_path.exists():
                    m3u_path.unlink()
            return removed is not None

    def find_by_name(self, name: str) -> Playlist | None:
        """Find a playlist by name (case-insensitive)."""
        name_lower = name.lower()
        with self._lock:
            for pl in self._playlists.values():
                if pl["name"].lower() == name_lower:
                    return self._to_playlist(pl)
        return None

    def list_all(self) -> list[Playlist]:
        """List all playlists."""
        with self._lock:
            return [self._to_playlist(pl) for pl in self._playlists.values()]

    def export_m3u8(self, playlist_id: str) -> Path | None:
        """Export a playlist as M3U8 file for local players."""
        with self._lock:
            pl = self._playlists.get(playlist_id)
        if not pl:
            return None

        EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
        m3u_path = EXPORTS_DIR / f"{pl['name']}.m3u8"

        lines = ["#EXTM3U", f"# Playlist: {pl['name']}", f"# Exported: {datetime.now().isoformat()}", ""]
        for tid in pl["track_ids"]:
            track = self._library.get_track(tid)
            if track:
                duration = track.duration_seconds
                display = f"{track.artist} - {track.title}"
                abs_path = MUSIC_ROOT / track.file_path
                lines.append(f"#EXTINF:{duration},{display}")
                lines.append(str(abs_path))

        m3u_path.write_text("\n".join(lines), encoding="utf-8")
        return m3u_path

    @staticmethod
    def _to_playlist(d: dict) -> Playlist:
        return Playlist(
            playlist_id=d["playlist_id"],
            name=d["name"],
            description=d.get("description", ""),
            track_ids=tuple(d.get("track_ids", [])),
            created_at=d.get("created_at", ""),
            updated_at=d.get("updated_at", ""),
        )
