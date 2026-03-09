from unittest.mock import MagicMock, patch
import numpy as np

import pytest


class TestEmbeddings:
    def test_get_embedding_model_lazy_loads(self):
        mock_model = MagicMock()
        import src.ai.embeddings as emb
        original = emb._model
        try:
            emb._model = None
            with patch("sentence_transformers.SentenceTransformer", return_value=mock_model) as mock_cls:
                result = emb.get_embedding_model()
                mock_cls.assert_called_once_with("BAAI/bge-small-zh-v1.5")
                assert result is mock_model
        finally:
            emb._model = original

    def test_get_embedding_model_caches(self):
        mock_model = MagicMock()
        import src.ai.embeddings as emb
        original = emb._model
        try:
            emb._model = None
            with patch("sentence_transformers.SentenceTransformer", return_value=mock_model) as mock_cls:
                result1 = emb.get_embedding_model()
                result2 = emb.get_embedding_model()
                mock_cls.assert_called_once()
                assert result1 is result2
        finally:
            emb._model = original

    def test_embed_text(self):
        mock_model = MagicMock()
        mock_model.encode.return_value = np.array([0.1, 0.2, 0.3])
        with patch("src.ai.embeddings.get_embedding_model", return_value=mock_model):
            from src.ai.embeddings import embed_text
            result = embed_text("hello world")
        mock_model.encode.assert_called_once()
        assert result == [0.1, 0.2, 0.3]

    def test_embed_text_truncates(self):
        mock_model = MagicMock()
        mock_model.encode.return_value = np.array([0.1])
        with patch("src.ai.embeddings.get_embedding_model", return_value=mock_model):
            from src.ai.embeddings import embed_text
            long_text = "x" * 20000
            embed_text(long_text)
        call_args = mock_model.encode.call_args[0][0]
        assert len(call_args) == 8192
