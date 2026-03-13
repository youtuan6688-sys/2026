import logging

import chromadb

from src.ai.embeddings import embed_text

logger = logging.getLogger(__name__)


class VectorStore:
    """ChromaDB-based vector store for content similarity search."""

    def __init__(self, persist_path: str):
        self.client = chromadb.PersistentClient(path=persist_path)
        self.collection = self.client.get_or_create_collection(
            name="knowledge_base",
            metadata={"hnsw:space": "cosine"},
        )

    def add(self, doc_id: str, text: str, metadata: dict):
        """Add a document with its embedding."""
        embedding = embed_text(text[:8192])
        self.collection.add(
            ids=[doc_id],
            embeddings=[embedding],
            documents=[text[:1000]],  # Store truncated text for display
            metadatas=[metadata],
        )

    def query_similar(self, text: str, top_k: int = 5) -> list[dict]:
        """Find similar documents by text content."""
        if self.collection.count() == 0:
            return []

        embedding = embed_text(text[:8192])
        results = self.collection.query(
            query_embeddings=[embedding],
            n_results=min(top_k, self.collection.count()),
        )

        similar = []
        if results and results["ids"] and results["ids"][0]:
            for i, doc_id in enumerate(results["ids"][0]):
                meta = (results["metadatas"][0][i] if results["metadatas"] else None) or {}
                similar.append({
                    "id": doc_id,
                    "title": meta.get("title", ""),
                    "summary": meta.get("summary", ""),
                    "distance": results["distances"][0][i] if results["distances"] else 0,
                })
        return similar
