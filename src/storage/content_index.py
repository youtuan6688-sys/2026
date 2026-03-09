import json
import sqlite3
import logging
from datetime import datetime

from src.utils.url_utils import normalize_url

logger = logging.getLogger(__name__)


class ContentIndex:
    """SQLite-based metadata index for deduplication and search."""

    def __init__(self, db_path: str):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS content (
                id TEXT PRIMARY KEY,
                url TEXT UNIQUE,
                url_normalized TEXT,
                title TEXT,
                platform TEXT,
                file_path TEXT,
                tags TEXT,
                category TEXT,
                summary TEXT,
                saved_at TEXT
            )
        """)
        self.conn.commit()

    def exists(self, url: str) -> bool:
        """Check if a URL has already been saved."""
        normalized = normalize_url(url)
        row = self.conn.execute(
            "SELECT 1 FROM content WHERE url = ? OR url_normalized = ?",
            (url, normalized),
        ).fetchone()
        return row is not None

    def add(self, doc_id: str, url: str, title: str, platform: str,
            file_path: str, tags: list[str], category: str, summary: str):
        """Add a new content entry."""
        self.conn.execute(
            "INSERT OR REPLACE INTO content (id, url, url_normalized, title, platform, file_path, tags, category, summary, saved_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (doc_id, url, normalize_url(url), title, platform, file_path,
             json.dumps(tags, ensure_ascii=False), category, summary,
             datetime.now().isoformat()),
        )
        self.conn.commit()

    def get_all_summaries(self, limit: int = 100) -> list[dict]:
        """Get recent content summaries for relation analysis."""
        rows = self.conn.execute(
            "SELECT id, title, summary, tags FROM content ORDER BY saved_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
