from unittest.mock import MagicMock
import pytest
from langchain_core.documents import Document

from app.retrieval.hybrid import CustomHybridRetriever, _determine_retrieval_weights


def test_determine_retrieval_weights():
    # Consultas factuales (con números/fechas o nombres propios)
    w_sem, w_lex = _determine_retrieval_weights("¿Qué ocurrió el 12 de marzo de 2005?")
    assert w_sem == 0.4 and w_lex == 0.6
    
    # Consulta factual con nombre propio (mayúscula en medio)
    w_sem_np, w_lex_np = _determine_retrieval_weights("noticias sobre Nestor Kirchner")
    assert w_sem_np == 0.4 and w_lex_np == 0.6

    # Consulta factual con nombre propio todo en minúsculas (gracias a spaCy)
    w_sem_lc, w_lex_lc = _determine_retrieval_weights("noticias sobre nestor kirchner")
    assert w_sem_lc == 0.4 and w_lex_lc == 0.6
    
    # Consulta factual con año directo
    w_sem_y, w_lex_y = _determine_retrieval_weights("noticias del 2005")
    assert w_sem_y == 0.4 and w_lex_y == 0.6
    
    # Consulta factual con década
    w_sem_dec, w_lex_dec = _determine_retrieval_weights("sucesos en los 90")
    assert w_sem_dec == 0.4 and w_lex_dec == 0.6
    
    # Consulta factual con mes
    w_sem_mon, w_lex_mon = _determine_retrieval_weights("elecciones en mayo")
    assert w_sem_mon == 0.4 and w_lex_mon == 0.6
    
    # Consultas conceptuales
    w_sem_c, w_lex_c = _determine_retrieval_weights("explicación del debate sobre teorías de soberanía")
    assert w_sem_c == 0.6 and w_lex_c == 0.4

    # Consulta conceptual con "por que"
    w_sem_pq, w_lex_pq = _determine_retrieval_weights("por que aumento el desempleo")
    assert w_sem_pq == 0.6 and w_lex_pq == 0.4
    
    # Consulta mixta (contiene palabra conceptual pero también un año/número -> prima lo fáctico)
    w_sem_mix, w_lex_mix = _determine_retrieval_weights("explicacion de la ley de 1996")
    assert w_sem_mix == 0.4 and w_lex_mix == 0.6
    
    # Consultas generales / default
    w_sem_d, w_lex_d = _determine_retrieval_weights("conflicto docente")
    assert w_sem_d == 0.5 and w_lex_d == 0.5


def test_hybrid_retriever_merging_and_metadata():
    # Mock retrievers
    mock_semantic = MagicMock()
    mock_bm25 = MagicMock()
    
    # Documentos devueltos por el semántico
    doc1 = Document(page_content="Texto uno", metadata={"chunk_id": "c1", "other": "val1"})
    doc2 = Document(page_content="Texto dos", metadata={"chunk_id": "c2"})
    mock_semantic.invoke.return_value = [doc1, doc2]
    
    # Documentos devueltos por BM25
    doc3 = Document(page_content="Texto tres", metadata={"chunk_id": "c3"})
    doc1_bm25 = Document(page_content="Texto uno", metadata={"chunk_id": "c1", "other": "val1"})
    mock_bm25.invoke.return_value = [doc3, doc1_bm25]
    
    retriever = CustomHybridRetriever([mock_semantic, mock_bm25], weights=[0.5, 0.5])
    
    filters = {"year": 2005}
    results = retriever.invoke("consulta docente", filters=filters)
    
    # Verificar que se pasaron los filtros
    mock_semantic.invoke.assert_called_once_with("consulta docente", filters=filters)
    mock_bm25.invoke.assert_called_once_with("consulta docente", filters=filters)
    
    # Verificar la de-duplicación por chunk_id (debería haber c1, c2, c3 en total)
    assert len(results) == 3
    
    # Verificar la presencia de metadatos rrf
    c1_doc = next(d for d in results if d.metadata["chunk_id"] == "c1")
    assert "rrf_score" in c1_doc.metadata
    assert c1_doc.metadata["semantic_rank"] == 0
    assert c1_doc.metadata["bm25_rank"] == 1
    
    c2_doc = next(d for d in results if d.metadata["chunk_id"] == "c2")
    assert c2_doc.metadata["semantic_rank"] == 1
    assert c2_doc.metadata["bm25_rank"] is None
    
    c3_doc = next(d for d in results if d.metadata["chunk_id"] == "c3")
    assert c3_doc.metadata["semantic_rank"] is None
    assert c3_doc.metadata["bm25_rank"] == 0
