"""Music handler — orchestrates download → tag → organize → respond."""
import logging
import shutil
import threading
import urllib.request
from datetime import datetime
from pathlib import Path

from src.music import downloader
from src.music import tagger
from src.music.library import MusicLibrary, MUSIC_ROOT
from src.music.playlist_manager import PlaylistManager
from src.music.models import DownloadResult, MusicTrack

logger = logging.getLogger(__name__)

TRACKS_DIR = MUSIC_ROOT / "tracks"


class MusicHandler:
    """Orchestrate music download pipeline and Feishu responses."""

    def __init__(self, sender):
        self.sender = sender
        self.library = MusicLibrary()
        self.playlists = PlaylistManager(self.library)

    def handle_music_url(self, url: str, platform: str, sender_id: str) -> None:
        """Full pipeline: download -> tag -> organize -> respond.
        Runs download in a background thread.
        """
        existing = self.library.find_by_url(url)
        if existing:
            self.sender.send_text(
                sender_id,
                f"这首歌已经在曲库里了: {existing.artist} - {existing.title}\n"
                f"格式: {existing.format.upper()} | 路径: {existing.file_path}",
            )
            return

        self.sender.send_text(sender_id, f"正在从 {platform} 下载音乐，稍等...")

        thread = threading.Thread(
            target=self._download_pipeline,
            args=(url, platform, sender_id),
            daemon=True,
        )
        thread.start()

    def _download_pipeline(self, url: str, platform: str, sender_id: str) -> None:
        """Background download pipeline."""
        try:
            result = downloader.download(url, platform)
            if not result.success:
                self.sender.send_text(sender_id, f"下载失败: {result.error}")
                return

            track_info = self._organize_track(result, url, platform)
            if not track_info:
                self.sender.send_text(sender_id, "下载成功但整理文件失败")
                return

            track_id, dest_path = track_info
            track = self.library.get_track(track_id)
            duration = track.duration_seconds if track else 0
            file_size = dest_path.stat().st_size

            duration_str = f"{duration // 60}:{duration % 60:02d}" if duration else "未知"
            size_str = f"{file_size / (1024 * 1024):.1f}MB"
            self.sender.send_text(
                sender_id,
                f"下载完成!\n"
                f"  {result.artist} - {result.title}\n"
                f"  专辑: {result.album or 'Singles'}\n"
                f"  格式: {result.format.upper()} | 时长: {duration_str} | 大小: {size_str}\n"
                f"  路径: {dest_path}\n\n"
                f"发 /music list 查看曲库, /music playlist <名称> 创建歌单",
            )
            self._cleanup_temp()

        except Exception as e:
            logger.exception(f"Music download pipeline error: {e}")
            self.sender.send_text(sender_id, f"下载过程出错: {str(e)[:200]}")

    def handle_command(self, command: str, sender_id: str) -> None:
        """Handle /music commands."""
        parts = command.strip().split(maxsplit=2)
        if len(parts) < 2:
            self._send_help(sender_id)
            return

        sub = parts[1].lower()
        args = parts[2] if len(parts) > 2 else ""

        if sub == "list":
            self._cmd_list(sender_id)
        elif sub == "search":
            self._cmd_search(args, sender_id)
        elif sub == "stats":
            self._cmd_stats(sender_id)
        elif sub == "playlist":
            self._cmd_playlist(args, sender_id)
        elif sub == "add":
            self._cmd_add_to_playlist(args, sender_id)
        elif sub == "export":
            self._cmd_export(args, sender_id)
        elif sub == "batch":
            self._cmd_batch(args, sender_id)
        elif sub == "delete":
            self._cmd_delete(args, sender_id)
        else:
            self._send_help(sender_id)

    def _cmd_list(self, sender_id: str) -> None:
        tracks = self.library.list_recent(15)
        if not tracks:
            self.sender.send_text(sender_id, "曲库是空的，发一个音乐链接给我试试!")
            return
        lines = ["最近下载的歌曲:"]
        for i, t in enumerate(tracks, 1):
            dur = f"{t.duration_seconds // 60}:{t.duration_seconds % 60:02d}" if t.duration_seconds else ""
            lines.append(f"{i}. {t.artist} - {t.title}  [{t.format.upper()}] {dur}")
        self.sender.send_text(sender_id, "\n".join(lines))

    def _cmd_search(self, query: str, sender_id: str) -> None:
        if not query:
            self.sender.send_text(sender_id, "用法: /music search <关键词>")
            return
        results = self.library.search(query)
        if not results:
            self.sender.send_text(sender_id, f"没找到包含「{query}」的歌曲")
            return
        lines = [f"搜索「{query}」结果:"]
        for t in results:
            lines.append(f"  {t.artist} - {t.title} [{t.format.upper()}] (ID: {t.track_id})")
        self.sender.send_text(sender_id, "\n".join(lines))

    def _cmd_stats(self, sender_id: str) -> None:
        stats = self.library.get_stats()
        fmt_str = ", ".join(f"{k}: {v}" for k, v in stats["formats"].items())
        plat_str = ", ".join(f"{k}: {v}" for k, v in stats["platforms"].items())
        self.sender.send_text(
            sender_id,
            f"曲库统计:\n"
            f"  总曲目: {stats['total_tracks']}\n"
            f"  总大小: {stats['total_size_mb']} MB\n"
            f"  总时长: {stats['total_duration_hours']} 小时\n"
            f"  格式: {fmt_str or '无'}\n"
            f"  来源: {plat_str or '无'}",
        )

    def _cmd_playlist(self, args: str, sender_id: str) -> None:
        if not args or args.lower() == "list":
            playlists = self.playlists.list_all()
            if not playlists:
                self.sender.send_text(sender_id, "还没有歌单。用 /music playlist <名称> 创建一个!")
                return
            lines = ["歌单列表:"]
            for pl in playlists:
                lines.append(f"  {pl.name} ({len(pl.track_ids)} 首) ID: {pl.playlist_id}")
            self.sender.send_text(sender_id, "\n".join(lines))
            return

        existing = self.playlists.find_by_name(args)
        if existing:
            tracks_info = []
            for tid in existing.track_ids:
                t = self.library.get_track(tid)
                if t:
                    tracks_info.append(f"  {t.artist} - {t.title}")
            lines = [f"歌单「{existing.name}」({len(existing.track_ids)} 首):"]
            lines.extend(tracks_info or ["  (空歌单)"])
            self.sender.send_text(sender_id, "\n".join(lines))
        else:
            pl = self.playlists.create(args)
            self.sender.send_text(sender_id, f"歌单「{pl.name}」已创建! ID: {pl.playlist_id}")

    def _cmd_add_to_playlist(self, args: str, sender_id: str) -> None:
        parts = args.split(maxsplit=1)
        if len(parts) < 2:
            self.sender.send_text(sender_id, "用法: /music add <歌单名> <歌曲关键词>")
            return
        playlist_name, query = parts
        pl = self.playlists.find_by_name(playlist_name)
        if not pl:
            self.sender.send_text(sender_id, f"歌单「{playlist_name}」不存在")
            return
        results = self.library.search(query)
        if not results:
            self.sender.send_text(sender_id, f"没找到包含「{query}」的歌曲")
            return
        track = results[0]
        updated = self.playlists.add_tracks(pl.playlist_id, [track.track_id])
        if updated:
            self.sender.send_text(
                sender_id,
                f"已添加 {track.artist} - {track.title} 到歌单「{playlist_name}」",
            )

    def _cmd_export(self, args: str, sender_id: str) -> None:
        if not args:
            self.sender.send_text(sender_id, "用法: /music export <歌单名>")
            return
        pl = self.playlists.find_by_name(args)
        if not pl:
            self.sender.send_text(sender_id, f"歌单「{args}」不存在")
            return
        path = self.playlists.export_m3u8(pl.playlist_id)
        if path:
            self.sender.send_text(sender_id, f"歌单已导出: {path}\n用 IINA 或其他播放器打开即可播放")
        else:
            self.sender.send_text(sender_id, "导出失败")

    def _cmd_delete(self, track_id: str, sender_id: str) -> None:
        if not track_id:
            self.sender.send_text(sender_id, "用法: /music delete <track_id>")
            return
        track = self.library.get_track(track_id.strip())
        if not track:
            self.sender.send_text(sender_id, f"没找到 ID 为 {track_id} 的歌曲")
            return
        self.library.remove_track(track_id.strip())
        self.sender.send_text(sender_id, f"已删除: {track.artist} - {track.title}")

    def _cmd_batch(self, args: str, sender_id: str) -> None:
        """Batch download songs by name, create playlist, send MP3 files.

        Format:
            /music batch 歌单名
            歌手 - 歌名
            歌手 - 歌名
            ...
        """
        lines = [line.strip() for line in args.strip().split("\n") if line.strip()]
        if not lines:
            self.sender.send_text(
                sender_id,
                "用法:\n/music batch 我的歌单\n周杰伦 - 晴天\n陈奕迅 - 十年\n邓紫棋 - 光年之外",
            )
            return

        playlist_name = lines[0]
        songs = lines[1:] if len(lines) > 1 else []

        if not songs:
            self.sender.send_text(sender_id, f"歌单「{playlist_name}」里没有歌曲，请在歌单名后换行写歌名")
            return

        max_batch = 30
        if len(songs) > max_batch:
            self.sender.send_text(sender_id, f"一次最多批量下载 {max_batch} 首，你发了 {len(songs)} 首，请分批")
            return

        self.sender.send_text(
            sender_id,
            f"开始批量下载歌单「{playlist_name}」({len(songs)} 首)\n"
            f"每首下载完会转 MP3 发给你，请稍等...",
        )

        thread = threading.Thread(
            target=self._batch_pipeline,
            args=(playlist_name, songs, sender_id),
            daemon=True,
        )
        thread.start()

    def _batch_pipeline(self, playlist_name: str, songs: list[str], sender_id: str) -> None:
        """Background batch download pipeline."""
        # Create playlist
        pl = self.playlists.find_by_name(playlist_name) or self.playlists.create(playlist_name)

        succeeded = []
        failed = []

        for i, query in enumerate(songs, 1):
            self.sender.send_text(sender_id, f"[{i}/{len(songs)}] 搜索下载: {query}")

            try:
                result = downloader.download_by_query(query)
                if not result.success:
                    failed.append((query, result.error))
                    self.sender.send_text(sender_id, f"  失败: {result.error}")
                    continue

                # Tag & organize (reuse single-track logic)
                track_info = self._organize_track(result, result.metadata.get("source_url", ""), "youtube_music")
                if not track_info:
                    failed.append((query, "整理文件失败"))
                    continue

                track_id, dest_path = track_info

                # Add to playlist
                self.playlists.add_tracks(pl.playlist_id, [track_id])
                succeeded.append(f"{result.artist} - {result.title}")

                # Convert to MP3 and send via Feishu
                mp3_path = downloader.convert_to_mp3(dest_path)
                try:
                    if mp3_path and mp3_path.exists():
                        display_name = f"{result.artist} - {result.title}.mp3"
                        self.sender.send_file(sender_id, str(mp3_path), display_name)
                        self.sender.send_text(
                            sender_id,
                            f"  [{i}/{len(songs)}] {result.artist} - {result.title}",
                        )
                    else:
                        self.sender.send_text(sender_id, f"  下载成功但 MP3 转码失败: {result.title}")
                finally:
                    # Always clean up temp MP3
                    if mp3_path and mp3_path != dest_path:
                        mp3_path.unlink(missing_ok=True)
                        try:
                            mp3_path.parent.rmdir()  # Remove empty temp dir
                        except OSError:
                            pass

            except Exception as e:
                logger.exception(f"Batch item error for '{query}': {e}")
                failed.append((query, str(e)[:100]))

        self._cleanup_temp()

        # Summary
        summary_lines = [f"歌单「{playlist_name}」批量下载完成!"]
        summary_lines.append(f"成功: {len(succeeded)} 首 | 失败: {len(failed)} 首")
        if succeeded:
            summary_lines.append("\n成功:")
            for s in succeeded:
                summary_lines.append(f"  {s}")
        if failed:
            summary_lines.append("\n失败:")
            for name, err in failed:
                summary_lines.append(f"  {name}: {err}")
        summary_lines.append(f"\n发 /music playlist {playlist_name} 查看歌单")
        self.sender.send_text(sender_id, "\n".join(summary_lines))

    def _organize_track(self, result: DownloadResult, source_url: str, platform: str) -> tuple[str, Path] | None:
        """Organize a downloaded track: tag, move to library, index.

        Returns (track_id, dest_path) on success, None on failure.
        """
        try:
            downloaded_path = Path(result.file_path)

            # Download cover art
            cover_path = ""
            if result.cover_url:
                cover_path = self._download_cover(result.cover_url, downloaded_path)

            # Write metadata tags
            tag_data = {
                "title": result.title,
                "artist": result.artist,
                "album": result.album or "Singles",
                "genre": result.metadata.get("genre", ""),
                "year": result.metadata.get("year", ""),
                "track_number": result.metadata.get("track_number", 0),
                "comment": f"Source: {source_url}",
            }
            tagger.write_tags(downloaded_path, tag_data)

            if cover_path:
                cover_file = Path(cover_path)
                if cover_file.exists():
                    mime = "image/png" if cover_file.suffix == ".png" else "image/jpeg"
                    tagger.embed_cover_art(downloaded_path, cover_file.read_bytes(), mime)

            # Organize to Artist/Album/
            artist = _sanitize_filename(result.artist or "Unknown")
            album = _sanitize_filename(result.album or "Singles")
            title = _sanitize_filename(result.title)
            track_num = result.metadata.get("track_number", 0)

            dest_dir = TRACKS_DIR / artist / album
            dest_dir.mkdir(parents=True, exist_ok=True)

            prefix = f"{track_num:02d} - " if track_num else ""
            dest_name = f"{prefix}{title}.{result.format}"
            dest_path = dest_dir / dest_name

            counter = 1
            while dest_path.exists():
                dest_name = f"{prefix}{title} ({counter}).{result.format}"
                dest_path = dest_dir / dest_name
                counter += 1

            shutil.move(str(downloaded_path), str(dest_path))

            # Move cover art
            cover_rel = ""
            if cover_path:
                cover_dest = dest_dir / "cover.jpg"
                if not cover_dest.exists():
                    shutil.move(cover_path, str(cover_dest))
                    cover_rel = str(cover_dest.relative_to(MUSIC_ROOT))

            # Get file info
            file_size = dest_path.stat().st_size
            tags = tagger.read_tags(dest_path)
            bitrate = tags.get("bitrate", 0)
            duration = result.duration_seconds or tags.get("duration_seconds", 0)

            # Generate track_id from source URL or query
            track_id = self.library.url_id(source_url) if source_url else self.library.url_id(result.title)

            track = MusicTrack(
                track_id=track_id,
                title=result.title,
                artist=result.artist,
                album=result.album or "Singles",
                source_url=source_url,
                source_platform=platform,
                file_path=str(dest_path.relative_to(MUSIC_ROOT)),
                format=result.format,
                duration_seconds=duration,
                bitrate=bitrate,
                file_size_bytes=file_size,
                cover_art_path=cover_rel,
                added_at=datetime.now().isoformat(),
                track_number=result.metadata.get("track_number", 0),
                genre=result.metadata.get("genre", ""),
                year=int(result.metadata.get("year", 0) or 0),
            )
            self.library.add_track(track)

            return track_id, dest_path

        except Exception as e:
            logger.exception(f"Organize track error: {e}")
            return None

    def _send_help(self, sender_id: str) -> None:
        self.sender.send_text(
            sender_id,
            "音乐管理命令:\n"
            "  /music list — 列出最近下载\n"
            "  /music search <关键词> — 搜索曲库\n"
            "  /music stats — 曲库统计\n"
            "  /music batch <歌单名>\\n歌曲列表 — 批量下载并发送 MP3\n"
            "  /music playlist <名称> — 创建或查看歌单\n"
            "  /music playlist list — 列出所有歌单\n"
            "  /music add <歌单名> <歌曲关键词> — 加歌到歌单\n"
            "  /music export <歌单名> — 导出 M3U8\n"
            "  /music delete <track_id> — 删除歌曲\n\n"
            "或者直接发音乐链接给我，我会自动下载!",
        )

    def _download_cover(self, cover_url: str, audio_path: Path) -> str:
        try:
            cover_path = audio_path.parent / "cover.jpg"
            urllib.request.urlretrieve(cover_url, str(cover_path))
            return str(cover_path)
        except Exception as e:
            logger.warning(f"Failed to download cover art: {e}")
            return ""

    def _cleanup_temp(self) -> None:
        temp_dir = MUSIC_ROOT / "temp"
        if temp_dir.exists():
            for f in temp_dir.iterdir():
                if f.is_file():
                    try:
                        f.unlink()
                    except OSError:
                        pass


def _sanitize_filename(name: str) -> str:
    if not name:
        return "Unknown"
    for ch in ['/', '\\', ':', '*', '?', '"', '<', '>', '|']:
        name = name.replace(ch, '_')
    return name.strip().strip('.')[:100]
