#!/usr/bin/env python3
"""Re-index all vault content (articles + memory) into ChromaDB vector store."""
import hashlib
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import settings
from src.storage.vector_store import VectorStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

VAULT = Path(settings.vault_path)
ARTICLE_DIRS = ["articles", "social", "docs"]
MEMORY_DIR = VAULT / "memory"


def extract_frontmatter(text: str) -> dict:
    """Extract YAML frontmatter metadata."""
    meta = {}
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            for line in parts[1].strip().split("\n"):
                if ":" in line and not line.startswith("  "):
                    key, val = line.split(":", 1)
                    meta[key.strip()] = val.strip().strip('"').strip("'")
    return meta


def reindex_articles(store: VectorStore) -> int:
    """Index all articles from vault subdirectories."""
    count = 0
    for subdir in ARTICLE_DIRS:
        dir_path = VAULT / subdir
        if not dir_path.exists():
            continue
        for md_file in sorted(dir_path.glob("*.md")):
            text = md_file.read_text(encoding="utf-8")
            meta = extract_frontmatter(text)
            title = meta.get("title", md_file.stem)
            summary = meta.get("summary", "")
            platform = meta.get("platform", "unknown")
            url = meta.get("source", "")

            doc_id = hashlib.md5(url.encode()).hexdigest()[:12] if url else hashlib.md5(md_file.name.encode()).hexdigest()[:12]

            # Use title + summary + first 2000 chars of content for embedding
            content_for_embed = f"{title}\n{summary}\n{text[:2000]}"

            try:
                store.add(
                    doc_id=doc_id,
                    text=content_for_embed,
                    metadata={
                        "title": title,
                        "summary": summary[:500],
                        "platform": platform,
                        "file_path": str(md_file),
                        "type": "article",
                    },
                )
                count += 1
                logger.info(f"  Indexed: {title[:60]}")
            except Exception as e:
                logger.warning(f"  Failed to index {md_file.name}: {e}")
    return count


def reindex_memory(store: VectorStore) -> int:
    """Index memory files for semantic search."""
    if not MEMORY_DIR.exists():
        return 0

    count = 0
    for md_file in sorted(MEMORY_DIR.glob("*.md")):
        text = md_file.read_text(encoding="utf-8").strip()
        if not text or len(text) < 50:
            continue

        doc_id = f"memory_{md_file.stem}"

        # Split large memory files into chunks (~1500 chars each)
        chunks = split_into_chunks(text, max_chars=1500)
        for i, chunk in enumerate(chunks):
            chunk_id = f"{doc_id}_{i}" if len(chunks) > 1 else doc_id
            try:
                store.add(
                    doc_id=chunk_id,
                    text=f"[Memory: {md_file.stem}]\n{chunk}",
                    metadata={
                        "title": f"Memory: {md_file.stem}",
                        "summary": chunk[:200],
                        "platform": "memory",
                        "file_path": str(md_file),
                        "type": "memory",
                    },
                )
                count += 1
                logger.info(f"  Indexed memory chunk: {md_file.stem} [{i}]")
            except Exception as e:
                logger.warning(f"  Failed to index {md_file.name} chunk {i}: {e}")
    return count


def split_into_chunks(text: str, max_chars: int = 1500) -> list[str]:
    """Split text by sections (##) or by size."""
    import re
    sections = re.split(r'\n(?=## )', text)
    chunks = []
    current = ""
    for section in sections:
        if len(current) + len(section) > max_chars and current:
            chunks.append(current.strip())
            current = section
        else:
            current += "\n" + section if current else section
    if current.strip():
        chunks.append(current.strip())
    return chunks if chunks else [text[:max_chars]]


def main():
    logger.info("=== Vault Re-Index Starting ===")

    # Clear and rebuild
    store = VectorStore(settings.chromadb_path)
    old_count = store.collection.count()
    logger.info(f"Current vector store count: {old_count}")

    # Delete all existing docs to avoid duplicates
    if old_count > 0:
        existing = store.collection.get()
        store.collection.delete(ids=existing["ids"])
        logger.info(f"Cleared {old_count} existing documents")

    article_count = reindex_articles(store)
    memory_count = reindex_memory(store)
    total = store.collection.count()

    logger.info(f"=== Re-Index Complete ===")
    logger.info(f"  Articles indexed: {article_count}")
    logger.info(f"  Memory chunks indexed: {memory_count}")
    logger.info(f"  Total vectors: {total}")


if __name__ == "__main__":
    main()
