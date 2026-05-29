from unittest.mock import MagicMock, patch
from datetime import date
import pytest
from langchain_core.documents import Document
from app.models import EvidenceVerdict, EvidenceResult
from app.generation.evidence_checker import check_evidence
from app.generation.generator import generate_response


def test_evidence_checker_temporal_consistency():
    # Query mentions 2005
    query = "¿Qué pasó en las elecciones de 2005?"
    
    # Retrieved chunk is from 2006 (mismatch)
    chunks_mismatch = [
        Document(page_content="Contenido", metadata={"year": 2006, "publication_date": "15-05-2006", "rerank_score": 0.9})
    ]
    res = check_evidence(query, chunks_mismatch)
    assert res.verdict == EvidenceVerdict.INSUFFICIENT
    assert "Inconsistencia temporal" in res.details

    # Retrieved chunk matches 2005
    chunks_match = [
        Document(page_content="Contenido", metadata={"year": 2005, "publication_date": "15-05-2005", "rerank_score": 0.9})
    ]
    res_ok = check_evidence(query, chunks_match)
    assert "Inconsistencia temporal" not in res_ok.details


@patch("app.generation.evidence_checker._determine_retrieval_weights")
def test_evidence_checker_specific_vs_broad(mock_weights):
    # 1. Caso Fáctico / Puntual (bm25_weight > 0.5)
    mock_weights.return_value = (0.4, 0.6) # semantic, bm25 (is_puntual = True)
    
    # 1 artículo, 1 chunk fuerte (score >= 0.3) -> Suficiente
    chunks_strong = [
        Document(page_content="A", metadata={"source_id": "art1", "rerank_score": 0.4})
    ]
    res1 = check_evidence("Nestor Kirchner", chunks_strong)
    assert res1.verdict == EvidenceVerdict.SUFFICIENT
    assert "suficiente" in res1.details.lower()
    
    # 1 artículo, 1 chunk débil (score 0.26, menor a min_top_score de 0.3) -> Low confidence
    chunks_weak = [
        Document(page_content="A", metadata={"source_id": "art1", "rerank_score": 0.26})
    ]
    res2 = check_evidence("Nestor Kirchner", chunks_weak)
    assert res2.verdict == EvidenceVerdict.LOW_CONFIDENCE
    
    # 2. Caso Amplio / Resumen (bm25_weight <= 0.5)
    mock_weights.return_value = (0.6, 0.4) # conceptual (is_puntual = False)
    
    # Requiere al menos 3 chunks relevantes y 2 artículos distintos
    chunks_broad_ok = [
        Document(page_content="A", metadata={"source_id": "art1", "rerank_score": 0.35}),
        Document(page_content="B", metadata={"source_id": "art2", "rerank_score": 0.30}),
        Document(page_content="C", metadata={"source_id": "art1", "rerank_score": 0.28}),
    ]
    res3 = check_evidence("explicacion del debate de soberania", chunks_broad_ok)
    assert res3.verdict == EvidenceVerdict.SUFFICIENT
    
    # Falla por tener 1 solo artículo único (retorna LOW_CONFIDENCE)
    chunks_broad_fail = [
        Document(page_content="A", metadata={"source_id": "art1", "rerank_score": 0.35}),
        Document(page_content="B", metadata={"source_id": "art1", "rerank_score": 0.30}),
        Document(page_content="C", metadata={"source_id": "art1", "rerank_score": 0.28}),
    ]
    res4 = check_evidence("explicacion del debate de soberania", chunks_broad_fail)
    assert res4.verdict == EvidenceVerdict.LOW_CONFIDENCE


def test_generator_populates_all_sources():
    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "Texto de respuesta"
    mock_llm.invoke.return_value = mock_response
    
    # Proveer todos los metadatos obligatorios para NewsChunkMetadata
    chunks = [
        Document(
            page_content="Fragmento uno", 
            metadata={
                "chunk_id": "c1",
                "source_id": "s1",
                "newspaper": "pagina12",
                "source_type": "html",
                "granularity": "article",
                "publication_date": date(2005, 3, 12),
                "year": 2005,
                "decade": 2000,
                "article_title": "Titulo A", 
                "source_url": "urlA"
            }
        ),
        Document(
            page_content="Fragmento dos", 
            metadata={
                "chunk_id": "c2",
                "source_id": "s2",
                "newspaper": "pagina12",
                "source_type": "html",
                "granularity": "article",
                "publication_date": date(2005, 4, 18),
                "year": 2005,
                "decade": 2000,
                "article_title": "Titulo B", 
                "source_url": "urlB"
            }
        ),
    ]
    
    evidence = EvidenceResult(
        verdict=EvidenceVerdict.SUFFICIENT,
        top_score=0.9,
        relevant_count=2,
        details="Evidencia ok"
    )
    messages = [{"role": "user", "content": "pregunta"}]
    
    res = generate_response("pregunta", chunks, evidence, messages, llm=mock_llm)
    
    assert res.answer == "Texto de respuesta"
    assert len(res.sources) == 2
    assert res.sources[0].article_title == "Titulo A"
    assert res.sources[0].source_url == "urlA"
    assert res.sources[1].article_title == "Titulo B"
    assert res.sources[1].source_url == "urlB"
