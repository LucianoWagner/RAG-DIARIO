"""
LLM invocation and citation parsing.
"""

import re
from datetime import date, datetime

from langchain_core.documents import Document
from langchain_groq import ChatGroq

from app.config import get_settings
from app.models import (
    EvidenceResult,
    NewsChunkMetadata,
    RAGResponse,
    RetrievalMetadata,
    SourceCitation,
)


def get_llm() -> ChatGroq:
    settings = get_settings()
    if not settings.groq_api_key:
        raise ValueError("GROQ_API_KEY no encontrada. Agregala a tu archivo .env")

    return ChatGroq(
        model_name="llama-3.3-70b-versatile",
        api_key=settings.groq_api_key,
        temperature=0.0,
    )


def _coerce_date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value[:10]).date()
        except ValueError:
            return None
    return None


def generate_response(
    question: str,
    context_chunks: list[Document],
    evidence: EvidenceResult,
    messages: list[dict],
    llm: ChatGroq | None = None,
) -> RAGResponse:
    llm = llm or get_llm()
    response = llm.invoke(messages)
    answer_text = str(response.content)

    # Poblamos 'sources' con todos los chunks provistos en el contexto del LLM
    citations: list[SourceCitation] = []
    for index, chunk in enumerate(context_chunks):
        meta = chunk.metadata
        citations.append(
            SourceCitation(
                citation_id=index + 1,
                source_label=meta.get("article_title") or meta.get("source_url") or "Fuente sin título",
                source_url=meta.get("source_url"),
                publication_date=_coerce_date(meta.get("publication_date")),
                page_number=meta.get("page_number"),
                article_title=meta.get("article_title"),
                relevant_fragment=chunk.page_content,
                relevance_score=float(meta.get("rerank_score", meta.get("semantic_score", 0.0))),
            )
        )

    metadata_items = []
    for chunk in context_chunks:
        metadata = dict(chunk.metadata)
        metadata["text"] = chunk.page_content
        metadata.setdefault("text_clean", " ".join(chunk.page_content.split()))
        metadata_items.append(NewsChunkMetadata(**metadata))

    return RAGResponse(
        answer=answer_text,
        sources=citations,
        evidence=evidence,
        retrieval_metadata=RetrievalMetadata(
            question=question,
            chunks_used=len(context_chunks),
            chunks_metadata=metadata_items,
        ),
    )


def parse_citations(answer_text: str, chunks: list[Document]) -> list[SourceCitation]:
    """Mantenido para compatibilidad con tests existentes."""
    matches = re.findall(r"\[Fuente (\d+)\]", answer_text, re.IGNORECASE)
    citations: list[SourceCitation] = []
    seen: set[int] = set()

    for match in matches:
        index = int(match) - 1
        if index < 0 or index >= len(chunks) or index in seen:
            continue
        seen.add(index)
        chunk = chunks[index]
        meta = chunk.metadata
        citations.append(
            SourceCitation(
                citation_id=index + 1,
                source_label=meta.get("article_title") or meta.get("source_url") or "Fuente sin título",
                source_url=meta.get("source_url"),
                publication_date=_coerce_date(meta.get("publication_date")),
                page_number=meta.get("page_number"),
                article_title=meta.get("article_title"),
                relevant_fragment=chunk.page_content,
                relevance_score=float(meta.get("rerank_score", meta.get("semantic_score", 0.0))),
            )
        )

    return citations
