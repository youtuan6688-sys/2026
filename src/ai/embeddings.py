import logging

logger = logging.getLogger(__name__)

_model = None


def get_embedding_model():
    """Lazy-load the embedding model (bge-m3, ~2GB)."""
    global _model
    if _model is None:
        logger.info("Loading embedding model BAAI/bge-small-zh-v1.5...")
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("BAAI/bge-small-zh-v1.5")
        logger.info("Embedding model loaded.")
    return _model


def embed_text(text: str) -> list[float]:
    """Generate embedding for text."""
    model = get_embedding_model()
    # Truncate to model's max length
    embedding = model.encode(text[:8192], normalize_embeddings=True)
    return embedding.tolist()
