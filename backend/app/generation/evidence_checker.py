"""
Evidence checks for retrieved chunks.
"""

from langchain_core.documents import Document

from app.config import get_settings
from app.models import EvidenceResult, EvidenceVerdict


def check_evidence(query: str, reranked_chunks: list[Document]) -> EvidenceResult:
    settings = get_settings()
    if not reranked_chunks:
        return EvidenceResult(
            verdict=EvidenceVerdict.INSUFFICIENT,
            top_score=0.0,
            relevant_count=0,
            details="No se encontraron documentos recuperados.",
        )

    top_score = float(reranked_chunks[0].metadata.get("rerank_score", 0.0))
    relevant_count = sum(
        1
        for chunk in reranked_chunks
        if float(chunk.metadata.get("rerank_score", 0.0)) >= settings.relevance_threshold
    )

    if top_score < settings.min_top_score:
        return EvidenceResult(
            verdict=EvidenceVerdict.INSUFFICIENT,
            top_score=top_score,
            relevant_count=relevant_count,
            details="Top score insuficiente.",
        )

    if relevant_count < settings.min_relevant_chunks:
        return EvidenceResult(
            verdict=EvidenceVerdict.LOW_CONFIDENCE,
            top_score=top_score,
            relevant_count=relevant_count,
            details="Pocos chunks relevantes.",
        )

    return EvidenceResult(
        verdict=EvidenceVerdict.SUFFICIENT,
        top_score=top_score,
        relevant_count=relevant_count,
        details="Evidencia suficiente.",
    )


def get_abstention_response() -> str:
    return (
        "No tengo suficiente informacion en el archivo consultado.\n\n"
        "Proba reformular la consulta con una fecha, un lugar o una persona mas especifica."
    )
