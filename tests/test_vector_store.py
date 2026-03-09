from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_chromadb(tmp_path):
    """Mock chromadb to avoid heavy dependencies in tests."""
    mock_collection = MagicMock()
    mock_collection.count.return_value = 0

    mock_client = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_collection

    with patch("src.storage.vector_store.chromadb") as mock_cdb, \
         patch("src.storage.vector_store.embed_text", return_value=[0.1] * 384):
        mock_cdb.PersistentClient.return_value = mock_client
        from src.storage.vector_store import VectorStore
        store = VectorStore(str(tmp_path / "chromadb"))
    yield store, mock_collection


class TestVectorStore:
    def test_init_creates_collection(self, mock_chromadb):
        store, collection = mock_chromadb
        assert store.collection is collection

    def test_add_document(self, mock_chromadb):
        store, collection = mock_chromadb
        with patch("src.storage.vector_store.embed_text", return_value=[0.1] * 384):
            store.add("doc1", "Hello world", {"title": "Test"})
        collection.add.assert_called_once()
        call_kwargs = collection.add.call_args
        assert call_kwargs[1]["ids"] == ["doc1"] or call_kwargs[0][0] == ["doc1"]

    def test_query_empty_collection(self, mock_chromadb):
        store, collection = mock_chromadb
        collection.count.return_value = 0
        result = store.query_similar("test query")
        assert result == []

    def test_query_with_results(self, mock_chromadb):
        store, collection = mock_chromadb
        collection.count.return_value = 5
        collection.query.return_value = {
            "ids": [["doc1", "doc2"]],
            "metadatas": [[{"title": "A", "summary": "Sa"}, {"title": "B", "summary": "Sb"}]],
            "distances": [[0.2, 0.5]],
        }
        with patch("src.storage.vector_store.embed_text", return_value=[0.1] * 384):
            results = store.query_similar("test", top_k=3)
        assert len(results) == 2
        assert results[0]["title"] == "A"
        assert results[0]["distance"] == 0.2
        assert results[1]["title"] == "B"

    def test_query_no_metadatas(self, mock_chromadb):
        store, collection = mock_chromadb
        collection.count.return_value = 3
        collection.query.return_value = {
            "ids": [["doc1"]],
            "metadatas": None,
            "distances": [[0.3]],
        }
        with patch("src.storage.vector_store.embed_text", return_value=[0.1] * 384):
            results = store.query_similar("test")
        assert len(results) == 1
        assert results[0]["title"] == ""

    def test_query_respects_top_k(self, mock_chromadb):
        store, collection = mock_chromadb
        collection.count.return_value = 10
        collection.query.return_value = {
            "ids": [[]], "metadatas": [[]], "distances": [[]],
        }
        with patch("src.storage.vector_store.embed_text", return_value=[0.1] * 384):
            store.query_similar("test", top_k=2)
        call_kwargs = collection.query.call_args[1]
        assert call_kwargs["n_results"] == 2
