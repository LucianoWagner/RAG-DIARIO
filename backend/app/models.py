"""
Pydantic models for the Hemeroteca RAG pipeline.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class NewsChunkMetadata(BaseModel):
    chunk_id: str
    source_id: str
    newspaper: str
    source_type: Literal["html", "ocr_pdf"]
    granularity: Literal["article", "page_block"]
    publication_date: date
    year: int
    decade: int
    location_mentions: list[str] = Field(default_factory=list)
    primary_location: str | None = None
    country_scope: Literal["argentina", "international", "unknown"] = "unknown"
    scope_signals: list[str] = Field(default_factory=list)
    article_country_scope: Literal["argentina", "international", "unknown"] = "unknown"
    article_scope_signals: list[str] = Field(default_factory=list)
    article_title: str | None = None
    section: str | None = None
    author: str | None = None
    page_number: int | None = None
    persons: list[str] = Field(default_factory=list)
    organizations: list[str] = Field(default_factory=list)
    source_url: str | None = None
    source_pdf_path: str | None = None
    ocr_confidence: float | None = None
    source_file: str | None = None
    text: str = ""
    text_clean: str = ""
    chunk_index: int = 0
    total_chunks: int = 0


class SourceCitation(BaseModel):
    citation_id: int
    source_label: str
    source_url: str | None = None
    publication_date: date | None = None
    page_number: int | None = None
    article_title: str | None = None
    relevant_fragment: str
    relevance_score: float = 0.0


class EvidenceVerdict(str):
    SUFFICIENT = "sufficient"
    LOW_CONFIDENCE = "low_confidence"
    INSUFFICIENT = "insufficient"


class EvidenceResult(BaseModel):
    verdict: str
    top_score: float
    relevant_count: int
    details: str = ""


class QueryRequest(BaseModel):
    question: str


class RetrievalMetadata(BaseModel):
    question: str
    status: str | None = None
    chunks_used: int
    chunks_metadata: list[NewsChunkMetadata] = Field(default_factory=list)


class RAGResponse(BaseModel):
    answer: str
    sources: list[SourceCitation] = Field(default_factory=list)
    evidence: EvidenceResult
    retrieval_metadata: RetrievalMetadata


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = "hemeroteca-rag-assistant"
    messages: list[ChatMessage] = Field(default_factory=list)
    temperature: float = Field(default=0.0, ge=0, le=2)
    stream: bool = False
