import hashlib
import logging
import re
import unicodedata
from datetime import date, datetime
from pathlib import Path

from config.settings import Settings
from src.models.content import AnalyzedContent
from src.storage.content_index import ContentIndex
from src.storage.vector_store import VectorStore

logger = logging.getLogger(__name__)

FOLDER_MAP = {
    "wechat": "articles",
    "feishu": "docs",
    "xiaohongshu": "social",
    "douyin": "social",
    "twitter": "social",
    "generic": "articles",
}

PLATFORM_NAMES = {
    "wechat": "微信公众号",
    "feishu": "飞书",
    "xiaohongshu": "小红书",
    "douyin": "抖音",
    "twitter": "X/Twitter",
    "generic": "网页",
}


class ObsidianWriter:
    def __init__(self, settings: Settings, vector_store: VectorStore, content_index: ContentIndex):
        self.vault_path = Path(settings.vault_path)
        self.vector_store = vector_store
        self.content_index = content_index

    def save(self, analyzed: AnalyzedContent) -> Path:
        """Save analyzed content as an Obsidian markdown file."""
        parsed = analyzed.parsed
        folder = FOLDER_MAP.get(parsed.platform, "articles")
        slug = self._slugify(parsed.title)
        date_str = date.today().isoformat()
        doc_id = hashlib.md5(parsed.url.encode()).hexdigest()[:12]
        filename = f"{date_str}-{slug}-{doc_id}.md"

        filepath = self.vault_path / folder / filename
        filepath.parent.mkdir(parents=True, exist_ok=True)

        # Build markdown
        content = self._build_markdown(analyzed)
        filepath.write_text(content, encoding="utf-8")

        # Index in vector store
        try:
            self.vector_store.add(
                doc_id=doc_id,
                text=f"{parsed.title}\n{analyzed.summary}\n{parsed.content[:2000]}",
                metadata={
                    "title": parsed.title,
                    "summary": analyzed.summary,
                    "platform": parsed.platform,
                    "file_path": str(filepath),
                },
            )
        except Exception as e:
            logger.warning(f"Vector indexing failed: {e}")

        # Index in SQLite
        try:
            self.content_index.add(
                doc_id=doc_id,
                url=parsed.url,
                title=parsed.title,
                platform=parsed.platform,
                file_path=str(filepath),
                tags=analyzed.tags,
                category=analyzed.category,
                summary=analyzed.summary,
            )
        except Exception as e:
            logger.warning(f"SQLite indexing failed: {e}")

        return filepath

    def _build_markdown(self, analyzed: AnalyzedContent) -> str:
        parsed = analyzed.parsed
        platform_name = PLATFORM_NAMES.get(parsed.platform, parsed.platform)

        # YAML frontmatter
        tags_yaml = "\n".join(f"  - {tag}" for tag in analyzed.tags)
        related_yaml = ""
        if analyzed.related:
            related_links = "\n".join(
                f'  - "[[{r.get("title", r.get("id", ""))}]]"'
                for r in analyzed.related
            )
            related_yaml = f"\nrelated:\n{related_links}"

        publish_date = ""
        if parsed.publish_date:
            publish_date = f"\ndate_published: {parsed.publish_date.strftime('%Y-%m-%d')}"

        frontmatter = f"""---
title: "{self._escape_yaml(parsed.title)}"
source: "{parsed.url}"
platform: {parsed.platform}
author: "{self._escape_yaml(parsed.author or '未知')}"
date_saved: {date.today().isoformat()}{publish_date}
tags:
{tags_yaml}
category: {analyzed.category}
summary: >
  {analyzed.summary}{related_yaml}
---"""

        # Body
        key_points = ""
        if analyzed.key_points:
            points = "\n".join(f"- {p}" for p in analyzed.key_points)
            key_points = f"\n\n## 要点\n\n{points}"

        related_section = ""
        if analyzed.related:
            links = "\n".join(
                f"- [[{r.get('title', r.get('id', ''))}]] — {r.get('reason', '')}"
                for r in analyzed.related
            )
            related_section = f"\n\n## 相关内容\n\n{links}"

        images_section = ""
        if parsed.images:
            imgs = "\n".join(f"![image]({img})" for img in parsed.images)
            images_section = f"\n\n## 图片\n\n{imgs}"

        body = f"""

## 摘要

{analyzed.summary}
{key_points}
{images_section}

## 内容

{parsed.content}
{related_section}

## 来源

- 链接: [{platform_name}]({parsed.url})
- 平台: {platform_name}
- 作者: {parsed.author or '未知'}
- 保存时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}
"""

        return frontmatter + body

    def _slugify(self, text: str) -> str:
        """Create a filesystem-safe slug from text."""
        text = text[:50]
        # Keep Chinese characters, alphanumeric, hyphens
        text = re.sub(r'[^\w\u4e00-\u9fff\-]', '-', text)
        text = re.sub(r'-+', '-', text).strip('-')
        return text or "untitled"

    def _escape_yaml(self, text: str) -> str:
        """Escape special characters for YAML strings."""
        return text.replace('"', '\\"').replace("\n", " ")
