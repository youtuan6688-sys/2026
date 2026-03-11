"""Audio metadata reading/writing using mutagen."""
import logging
from pathlib import Path

import mutagen
from mutagen.flac import FLAC, Picture
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TRCK, TCON, TDRC, COMM, APIC
from mutagen.mp4 import MP4

logger = logging.getLogger(__name__)


def read_tags(file_path: Path) -> dict:
    """Read metadata tags from an audio file.

    Returns dict with keys: title, artist, album, track_number, genre, year, comment.
    """
    try:
        audio = mutagen.File(str(file_path), easy=True)
        if audio is None:
            return {}

        return {
            "title": _first(audio.get("title")),
            "artist": _first(audio.get("artist")),
            "album": _first(audio.get("album")),
            "track_number": _first(audio.get("tracknumber")),
            "genre": _first(audio.get("genre")),
            "year": _first(audio.get("date")),
            "duration_seconds": int(audio.info.length) if audio.info else 0,
            "bitrate": int(audio.info.bitrate / 1000) if hasattr(audio.info, "bitrate") and audio.info.bitrate else 0,
        }
    except Exception as e:
        logger.warning(f"Failed to read tags from {file_path}: {e}")
        return {}


def write_tags(file_path: Path, tags: dict) -> None:
    """Write metadata tags to an audio file.

    Args:
        file_path: Path to the audio file.
        tags: Dict with keys: title, artist, album, track_number, genre, year, comment.
    """
    ext = file_path.suffix.lower()
    try:
        if ext == ".flac":
            _write_flac_tags(file_path, tags)
        elif ext == ".mp3":
            _write_mp3_tags(file_path, tags)
        elif ext in (".m4a", ".mp4", ".aac"):
            _write_mp4_tags(file_path, tags)
        else:
            # Try easy tags as fallback
            audio = mutagen.File(str(file_path), easy=True)
            if audio is not None:
                _set_easy_tags(audio, tags)
                audio.save()
    except Exception as e:
        logger.warning(f"Failed to write tags to {file_path}: {e}")


def embed_cover_art(file_path: Path, cover_data: bytes, mime_type: str = "image/jpeg") -> None:
    """Embed album art into an audio file.

    Args:
        file_path: Path to the audio file.
        cover_data: Raw image bytes.
        mime_type: MIME type of the image (image/jpeg or image/png).
    """
    ext = file_path.suffix.lower()
    try:
        if ext == ".flac":
            audio = FLAC(str(file_path))
            pic = Picture()
            pic.type = 3  # Front cover
            pic.mime = mime_type
            pic.data = cover_data
            audio.clear_pictures()
            audio.add_picture(pic)
            audio.save()

        elif ext == ".mp3":
            audio = MP3(str(file_path))
            if audio.tags is None:
                audio.add_tags()
            # Remove existing cover art
            audio.tags.delall("APIC")
            audio.tags.add(APIC(
                encoding=3,  # UTF-8
                mime=mime_type,
                type=3,  # Front cover
                data=cover_data,
            ))
            audio.save()

        elif ext in (".m4a", ".mp4"):
            audio = MP4(str(file_path))
            fmt = MP4.Cover.FORMAT_JPEG if "jpeg" in mime_type else MP4.Cover.FORMAT_PNG
            audio.tags["covr"] = [mutagen.mp4.MP4Cover(cover_data, imageformat=fmt)]
            audio.save()

    except Exception as e:
        logger.warning(f"Failed to embed cover art in {file_path}: {e}")


def _first(val) -> str:
    """Extract first value from a tag list, or empty string."""
    if isinstance(val, list) and val:
        return str(val[0])
    if val is not None:
        return str(val)
    return ""


def _write_flac_tags(file_path: Path, tags: dict) -> None:
    audio = FLAC(str(file_path))
    if tags.get("title"):
        audio["title"] = tags["title"]
    if tags.get("artist"):
        audio["artist"] = tags["artist"]
    if tags.get("album"):
        audio["album"] = tags["album"]
    if tags.get("track_number"):
        audio["tracknumber"] = str(tags["track_number"])
    if tags.get("genre"):
        audio["genre"] = tags["genre"]
    if tags.get("year"):
        audio["date"] = str(tags["year"])
    if tags.get("comment"):
        audio["comment"] = tags["comment"]
    audio.save()


def _write_mp3_tags(file_path: Path, tags: dict) -> None:
    audio = MP3(str(file_path))
    if audio.tags is None:
        audio.add_tags()
    tag = audio.tags
    if tags.get("title"):
        tag.add(TIT2(encoding=3, text=[tags["title"]]))
    if tags.get("artist"):
        tag.add(TPE1(encoding=3, text=[tags["artist"]]))
    if tags.get("album"):
        tag.add(TALB(encoding=3, text=[tags["album"]]))
    if tags.get("track_number"):
        tag.add(TRCK(encoding=3, text=[str(tags["track_number"])]))
    if tags.get("genre"):
        tag.add(TCON(encoding=3, text=[tags["genre"]]))
    if tags.get("year"):
        tag.add(TDRC(encoding=3, text=[str(tags["year"])]))
    if tags.get("comment"):
        tag.add(COMM(encoding=3, lang="zho", text=[tags["comment"]]))
    audio.save()


def _write_mp4_tags(file_path: Path, tags: dict) -> None:
    audio = MP4(str(file_path))
    if audio.tags is None:
        audio.add_tags()
    tag = audio.tags
    if tags.get("title"):
        tag["\xa9nam"] = [tags["title"]]
    if tags.get("artist"):
        tag["\xa9ART"] = [tags["artist"]]
    if tags.get("album"):
        tag["\xa9alb"] = [tags["album"]]
    if tags.get("track_number"):
        tag["trkn"] = [(int(tags["track_number"]), 0)]
    if tags.get("genre"):
        tag["\xa9gen"] = [tags["genre"]]
    if tags.get("year"):
        tag["\xa9day"] = [str(tags["year"])]
    audio.save()


def _set_easy_tags(audio, tags: dict) -> None:
    if tags.get("title"):
        audio["title"] = tags["title"]
    if tags.get("artist"):
        audio["artist"] = tags["artist"]
    if tags.get("album"):
        audio["album"] = tags["album"]
    if tags.get("genre"):
        audio["genre"] = tags["genre"]
