import hashlib
import logging
from collections import OrderedDict
from threading import Lock

logger = logging.getLogger(__name__)

_model = None

# LRU cache for embeddings — avoids recomputing for repeated/similar queries.
# Key: SHA-256 of truncated text, Value: embedding list.
_CACHE_MAX = 128
_cache: OrderedDict[str, list[float]] = OrderedDict()
_cache_lock = Lock()


def get_embedding_model():
    """Lazy-load the embedding model."""
    global _model
    if _model is None:
        logger.info("Loading embedding model BAAI/bge-small-zh-v1.5...")
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("BAAI/bge-small-zh-v1.5")
        logger.info("Embedding model loaded.")
    return _model


def _cache_key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def embed_text(text: str) -> list[float]:
    """Generate embedding for text (with LRU cache)."""
    truncated = text[:8192]
    key = _cache_key(truncated)

    with _cache_lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]

    model = get_embedding_model()
    embedding = model.encode(truncated, normalize_embeddings=True).tolist()

    with _cache_lock:
        _cache[key] = embedding
        if len(_cache) > _CACHE_MAX:
            _cache.popitem(last=False)

    return embedding
