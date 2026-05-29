from unittest.mock import MagicMock, patch
import pytest
from langchain_core.documents import Document
from qdrant_client.http import models as qmodels

from app.retrieval.vector_store import QdrantSemanticRetriever


@patch("app.retrieval.vector_store.ensure_collection")
@patch("app.retrieval.vector_store.get_qdrant_client")
@patch("app.retrieval.vector_store.get_embedding_function")
def test_qdrant_semantic_retriever_filters(mock_get_embed, mock_get_client, mock_ensure):
    # Setup mocks
    mock_embeddings = MagicMock()
    mock_embeddings.embed_query.return_value = [0.1, 0.2, 0.3]
    mock_get_embed.return_value = mock_embeddings

    mock_client = MagicMock()
    # Mock search results returning a single mock Qdrant ScoredPoint
    mock_point = MagicMock()
    mock_point.score = 0.85
    mock_point.payload = {"text": "contenido de prueba", "year": 2005, "section": "elpais"}
    mock_client.search.return_value = [mock_point]
    mock_get_client.return_value = mock_client

    # Instantiate retriever
    retriever = QdrantSemanticRetriever()
    
    # Execute with filters
    filters = {"year": 2005, "section": "elpais", "empty_filter": None}
    docs = retriever.invoke(query="conflicto", filters=filters)
    
    # Assert embeddings and client search calls
    mock_embeddings.embed_query.assert_called_once_with("conflicto")
    
    # Assert search was called with correct filter object
    mock_client.search.assert_called_once()
    kwargs = mock_client.search.call_args.kwargs
    
    assert kwargs["collection_name"] == retriever.settings.qdrant_collection
    assert kwargs["query_vector"] == [0.1, 0.2, 0.3]
    assert kwargs["limit"] == retriever.settings.top_k
    assert kwargs["with_payload"] is True
    
    # Verify filter
    q_filter = kwargs["query_filter"]
    assert isinstance(q_filter, qmodels.Filter)
    assert len(q_filter.must) == 2
    
    # Check that conditions match
    cond_keys = {c.key for c in q_filter.must}
    assert cond_keys == {"year", "section"}
    
    for cond in q_filter.must:
        if cond.key == "year":
            assert cond.match.value == 2005
        elif cond.key == "section":
            assert cond.match.value == "elpais"
            
    # Verify document formatting
    assert len(docs) == 1
    assert docs[0].page_content == "contenido de prueba"
    assert docs[0].metadata["semantic_score"] == 0.85
    assert docs[0].metadata["year"] == 2005
    assert docs[0].metadata["section"] == "elpais"
