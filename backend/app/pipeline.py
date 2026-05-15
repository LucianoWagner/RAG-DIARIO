"""
Main Hemeroteca RAG pipeline.
"""

from langchain_core.documents import Document

from app.config import get_settings
from app.models import EvidenceResult, EvidenceVerdict, RAGResponse, RetrievalMetadata


class RAGPipeline:
    def __init__(self):
        self.settings = get_settings()

        from app.generation.generator import get_llm
        from app.retrieval.bm25_retriever import create_bm25_retriever
        from app.retrieval.hybrid import create_hybrid_retriever
        from app.retrieval.vector_store import get_qdrant_client, get_semantic_retriever

        self.client = get_qdrant_client()
        self.semantic_retriever = get_semantic_retriever()
        self.bm25_retriever = create_bm25_retriever(self._load_documents_for_bm25())
        self.hybrid_retriever = create_hybrid_retriever(
            self.semantic_retriever,
            self.bm25_retriever,
        )
        self.llm = get_llm()

    def _load_documents_for_bm25(self) -> list[Document]:
        scroll, _ = self.client.scroll(
            collection_name=self.settings.qdrant_collection,
            with_payload=True,
            limit=5000,
        )
        documents = []
        for point in scroll:
            payload = dict(point.payload or {})
            page_content = str(payload.pop("text", ""))
            documents.append(Document(page_content=page_content, metadata=payload))
        return documents

    def run(self, question: str) -> RAGResponse:
        from app.generation.evidence_checker import check_evidence, get_abstention_response
        from app.generation.generator import generate_response
        from app.generation.prompt_templates import build_messages, format_context
        from app.generation.router import get_chitchat_response, route_query
        from app.retrieval.hybrid import retrieve
        from app.retrieval.reranker import rerank_documents

        intent = route_query(self.llm, question)
        if intent == "CHITCHAT":
            return RAGResponse(
                answer=get_chitchat_response(self.llm, question),
                sources=[],
                evidence=EvidenceResult(
                    verdict=EvidenceVerdict.SUFFICIENT,
                    top_score=1.0,
                    relevant_count=0,
                    details="Chit-chat",
                ),
                retrieval_metadata=RetrievalMetadata(
                    question=question,
                    chunks_used=0,
                    status="chit-chat",
                ),
            )

        retrieved_chunks = retrieve(self.hybrid_retriever, question)
        reranked_chunks = rerank_documents(question, retrieved_chunks)
        evidence = check_evidence(question, reranked_chunks)
        if evidence.verdict == EvidenceVerdict.INSUFFICIENT:
            return RAGResponse(
                answer=get_abstention_response(),
                sources=[],
                evidence=evidence,
                retrieval_metadata=RetrievalMetadata(
                    question=question,
                    chunks_used=0,
                    status="abstained",
                ),
            )

        context = format_context(reranked_chunks)
        messages = build_messages(question, context)
        return generate_response(question, reranked_chunks, evidence, messages, llm=self.llm)
