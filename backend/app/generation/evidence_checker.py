"""
Evidence checks for retrieved chunks.
"""

import re
from langchain_core.documents import Document

from app.config import get_settings
from app.models import EvidenceResult, EvidenceVerdict
from app.retrieval.hybrid import _determine_retrieval_weights


def check_evidence(query: str, reranked_chunks: list[Document]) -> EvidenceResult:
    settings = get_settings()
    if not reranked_chunks:
        return EvidenceResult(
            verdict=EvidenceVerdict.INSUFFICIENT,
            top_score=0.0,
            relevant_count=0,
            details="No se encontraron documentos recuperados.",
        )

    # 1. Comprobar consistencia temporal si se menciona un año en la query
    years_in_query = re.findall(r"\b(19\d{2}|20\d{2})\b", query)
    if years_in_query:
        matched_year = False
        for chunk in reranked_chunks:
            chunk_year = chunk.metadata.get("year")
            chunk_pub_date = chunk.metadata.get("publication_date")
            for y in years_in_query:
                # Comprobar año directo (numérico o texto) o parte del string de la fecha
                if chunk_year is not None and str(chunk_year) == y:
                    matched_year = True
                    break
                if chunk_pub_date and y in str(chunk_pub_date):
                    matched_year = True
                    break
            if matched_year:
                break
        
        if not matched_year:
            return EvidenceResult(
                verdict=EvidenceVerdict.INSUFFICIENT,
                top_score=0.0,
                relevant_count=0,
                details=f"Inconsistencia temporal: La consulta menciona {', '.join(years_in_query)} pero ningún chunk corresponde.",
            )

    # 2. Extraer métricas básicas de los chunks
    top_score = float(reranked_chunks[0].metadata.get("rerank_score", 0.0))
    relevant_chunks = [
        chunk for chunk in reranked_chunks
        if float(chunk.metadata.get("rerank_score", 0.0)) >= settings.relevance_threshold
    ]
    relevant_count = len(relevant_chunks)

    # Identificar artículos únicos
    def _get_source_id(doc):
        return (
            doc.metadata.get("source_id") or 
            doc.metadata.get("source_url") or 
            doc.metadata.get("title") or 
            "unknown"
        )

    unique_sources = {
        _get_source_id(chunk) for chunk in relevant_chunks
        if _get_source_id(chunk) != "unknown"
    }
    unique_sources_count = len(unique_sources)

    # 3. Determinar adaptativamente el tipo de consulta (fáctica/específica vs amplia/resumen)
    try:
        _, bm25_weight = _determine_retrieval_weights(query)
        is_puntual = bm25_weight > 0.5
    except Exception:
        is_puntual = True  # Fallback seguro

    if is_puntual:
        # Consulta puntual/específica:
        # Requiere al menos 1 artículo único y (2 chunks relevantes o al menos 1 chunk muy fuerte)
        has_strong_chunk = any(
            float(c.metadata.get("rerank_score", 0.0)) >= settings.min_top_score 
            for c in relevant_chunks
        )
        
        if unique_sources_count >= 1 and (relevant_count >= 2 or has_strong_chunk):
            return EvidenceResult(
                verdict=EvidenceVerdict.SUFFICIENT,
                top_score=top_score,
                relevant_count=relevant_count,
                details="Evidencia suficiente para consulta puntual.",
            )
        elif unique_sources_count >= 1:
            return EvidenceResult(
                verdict=EvidenceVerdict.LOW_CONFIDENCE,
                top_score=top_score,
                relevant_count=relevant_count,
                details="Confianza baja: consulta puntual con un solo chunk relevante sin puntaje muy fuerte.",
            )
        else:
            return EvidenceResult(
                verdict=EvidenceVerdict.INSUFFICIENT,
                top_score=top_score,
                relevant_count=relevant_count,
                details="Evidencia insuficiente para consulta puntual.",
            )
    else:
        # Consulta amplia/de resumen:
        # Requiere al menos 3 chunks relevantes distribuidos en al menos 2 artículos distintos
        if relevant_count >= 3 and unique_sources_count >= 2:
            return EvidenceResult(
                verdict=EvidenceVerdict.SUFFICIENT,
                top_score=top_score,
                relevant_count=relevant_count,
                details="Evidencia suficiente para consulta amplia/resumen.",
            )
        elif relevant_count >= 1 and unique_sources_count >= 1:
            return EvidenceResult(
                verdict=EvidenceVerdict.LOW_CONFIDENCE,
                top_score=top_score,
                relevant_count=relevant_count,
                details="Confianza baja: consulta amplia con volumen limitado de artículos/chunks.",
            )
        else:
            return EvidenceResult(
                verdict=EvidenceVerdict.INSUFFICIENT,
                top_score=top_score,
                relevant_count=relevant_count,
                details="Evidencia insuficiente para consulta amplia/resumen.",
            )


def get_abstention_response() -> str:
    return (
        "No tengo suficiente información en el archivo de Página/12 para responder a tu consulta.\n\n"
        "Probá reformular la consulta indicando una fecha, un tema, una sección o palabras clave más específicas."
    )
