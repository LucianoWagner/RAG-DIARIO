from unittest.mock import MagicMock, patch
import pytest
from langchain_core.documents import Document
from app.models import EvidenceVerdict
from app.retrieval.reranker import rerank_documents
from app.pipeline import RAGPipeline


@patch("app.retrieval.reranker.CrossEncoder")
def test_reranker_cross_encoder(mock_cross_encoder):
    # Setup mock
    mock_model = MagicMock()
    mock_model.predict.return_value = [0.9, 0.4]
    mock_cross_encoder.return_value = mock_model
    
    docs = [
        Document(page_content="Texto B", metadata={"id": 2}),
        Document(page_content="Texto A", metadata={"id": 1}),
    ]
    
    with patch("app.retrieval.reranker.get_settings") as mock_settings:
        settings = MagicMock()
        settings.reranker_type = "cross-encoder"
        settings.reranker_model_name = "cross-encoder/ms-marco-MiniLM-L-6-v2"
        settings.rerank_top_n = 2
        settings.model_cache_dir = None
        mock_settings.return_value = settings
        
        ranked = rerank_documents("consulta de prueba", docs)
        
        # Verify call format
        mock_model.predict.assert_called_once_with([
            ["consulta de prueba", "Texto B"],
            ["consulta de prueba", "Texto A"],
        ])
        
        # Assert reordered by score
        assert len(ranked) == 2
        assert ranked[0].page_content == "Texto B"
        assert ranked[0].metadata["rerank_score"] == 0.9
        assert ranked[0].metadata["rerank_position"] == 1
        
        assert ranked[1].page_content == "Texto A"
        assert ranked[1].metadata["rerank_score"] == 0.4
        assert ranked[1].metadata["rerank_position"] == 2


@patch("app.pipeline.get_qdrant_client")
@patch("app.pipeline.get_semantic_retriever")
@patch("app.pipeline.create_bm25_retriever")
@patch("app.pipeline.create_hybrid_retriever")
@patch("app.pipeline.get_llm")
def test_pipeline_scrolling(mock_llm, mock_hybrid, mock_bm25, mock_semantic, mock_qdrant_client):
    # Mock client scrolling
    mock_client = MagicMock()
    
    # Page 1 scroll
    point1 = MagicMock()
    point1.payload = {"text": "Doc 1", "year": 2005}
    point2 = MagicMock()
    point2.payload = {"text": "Doc 2", "year": 2005}
    
    # Page 2 scroll
    point3 = MagicMock()
    point3.payload = {"text": "Doc 3", "year": 2006}
    
    # Mock scroll call sequence
    mock_client.scroll.side_effect = [
        ([point1, point2], "offset_token_1"),
        ([point3], None)
    ]
    mock_qdrant_client.return_value = mock_client
    
    pipeline = RAGPipeline()
    
    # Verify the documents loaded during initialization and passed to create_bm25_retriever
    mock_bm25.assert_called_once()
    loaded_docs = mock_bm25.call_args[0][0]
    
    assert len(loaded_docs) == 3
    assert loaded_docs[0].page_content == "Doc 1"
    assert loaded_docs[2].page_content == "Doc 3"
    assert mock_client.scroll.call_count == 2


@patch("app.pipeline.get_qdrant_client")
@patch("app.pipeline.get_semantic_retriever")
@patch("app.pipeline.create_bm25_retriever")
@patch("app.pipeline.create_hybrid_retriever")
@patch("app.pipeline.get_llm")
@patch("app.pipeline.QueryPlanner")
@patch("app.pipeline.retrieve")
@patch("app.pipeline.rerank_documents")
@patch("app.pipeline.check_evidence")
@patch("app.pipeline.generate_response")
def test_pipeline_run_routing(
    mock_gen_response, mock_check_evidence, mock_rerank, mock_retrieve, mock_planner_cls,
    mock_llm, mock_hybrid, mock_bm25, mock_semantic, mock_qdrant_client
):
    # Setup pipeline mocks
    mock_planner = MagicMock()
    mock_planner_cls.return_value = mock_planner
    
    # Setup scroll to avoid errors on init
    mock_client = MagicMock()
    mock_client.scroll.return_value = ([], None)
    mock_qdrant_client.return_value = mock_client
    
    pipeline = RAGPipeline()
    
    # Scenario A: CHITCHAT
    plan_chitchat = MagicMock()
    plan_chitchat.intent = "CHITCHAT"
    mock_planner.plan_query.return_value = plan_chitchat
    
    with patch("app.pipeline.get_chitchat_response") as mock_chitchat_resp:
        mock_chitchat_resp.return_value = "Hola, ¿cómo estás?"
        res = pipeline.run("hola")
        assert res.answer == "Hola, ¿cómo estás?"
        assert res.retrieval_metadata.status == "chit-chat"
        
    # Scenario B: OUT_OF_SCOPE
    plan_oos = MagicMock()
    plan_oos.intent = "OUT_OF_SCOPE"
    mock_planner.plan_query.return_value = plan_oos
    
    res = pipeline.run("escribe codigo en python")
    assert "solo puedo responder consultas referidas a la hemeroteca" in res.answer
    assert res.retrieval_metadata.status == "out-of-scope"
    
    # Scenario C: ARCHIVE_SEARCH with filters
    plan_search = MagicMock()
    plan_search.intent = "ARCHIVE_SEARCH"
    plan_search.search_query = "conflicto docente"
    plan_search.year = 2005
    plan_search.section = "elpais"
    plan_search.decade = None
    plan_search.publication_date = None
    plan_search.newspaper = "pagina12"
    mock_planner.plan_query.return_value = plan_search
    
    mock_retrieve.return_value = [Document(page_content="doc")]
    mock_rerank.return_value = [Document(page_content="doc")]
    
    # Evidence verdict Sufficient
    mock_evidence = MagicMock()
    mock_evidence.verdict = EvidenceVerdict.SUFFICIENT
    mock_check_evidence.return_value = mock_evidence
    
    mock_gen_response.return_value = "Respuesta del modelo"
    
    res = pipeline.run("¿Qué pasó con el conflicto docente en elpais en 2005?")
    
    # Verify that retrieve was called with the cleaned search_query and filters dict
    mock_retrieve.assert_called_once_with(
        pipeline.hybrid_retriever,
        "conflicto docente",
        filters={"year": 2005, "section": "elpais", "newspaper": "pagina12"}
    )
