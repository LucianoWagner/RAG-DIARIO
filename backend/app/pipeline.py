"""
Main Hemeroteca RAG pipeline.
"""

from langchain_core.documents import Document
from loguru import logger

from app.config import get_settings
from app.models import EvidenceResult, EvidenceVerdict, RAGResponse, RetrievalMetadata
from app.generation.generator import get_llm, generate_response
from app.retrieval.bm25_retriever import create_bm25_retriever
from app.retrieval.hybrid import create_hybrid_retriever, retrieve
from app.retrieval.vector_store import get_qdrant_client, get_semantic_retriever
from app.generation.query_planner import QueryPlanner
from app.generation.evidence_checker import check_evidence, get_abstention_response
from app.generation.prompt_templates import build_messages, format_context
from app.generation.router import get_chitchat_response
from app.retrieval.reranker import rerank_documents


class RAGPipeline:
    def __init__(self):
        self.settings = get_settings()
        self.client = get_qdrant_client()
        self.semantic_retriever = get_semantic_retriever()
        self.bm25_retriever = create_bm25_retriever(self._load_documents_for_bm25())
        self.hybrid_retriever = create_hybrid_retriever(
            self.semantic_retriever,
            self.bm25_retriever,
        )
        self.llm = get_llm()

    def _load_documents_for_bm25(self) -> list[Document]:
        """Carga todos los documentos de Qdrant usando scroll paginado."""
        logger.info("Iniciando scroll paginado de Qdrant para BM25...")
        documents = []
        offset = None
        page_size = 1000
        
        while True:
            scroll, next_offset = self.client.scroll(
                collection_name=self.settings.qdrant_collection,
                with_payload=True,
                limit=page_size,
                offset=offset,
            )
            for point in scroll:
                payload = dict(point.payload or {})
                page_content = str(payload.pop("text", ""))
                documents.append(Document(page_content=page_content, metadata=payload))
            
            logger.info(f"Cargados {len(documents)} documentos...")
            if next_offset is None:
                break
            offset = next_offset
            
        logger.info(f"Scroll finalizado. Total cargado para BM25: {len(documents)} documentos.")
        return documents

    def run(self, question: str) -> RAGResponse:
        # 1. Planificar consulta y extraer intención / filtros
        planner = QueryPlanner(self.llm)
        plan = planner.plan_query(question)

        # 2. Enrutar según la intención
        if plan.intent == "CHITCHAT":
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
            
        if plan.intent == "OUT_OF_SCOPE":
            return RAGResponse(
                answer="Disculpa, pero solo puedo responder consultas referidas a la hemeroteca y el archivo histórico de Página/12.",
                sources=[],
                evidence=EvidenceResult(
                    verdict=EvidenceVerdict.INSUFFICIENT,
                    top_score=0.0,
                    relevant_count=0,
                    details="Out of scope",
                ),
                retrieval_metadata=RetrievalMetadata(
                    question=question,
                    chunks_used=0,
                    status="out-of-scope",
                ),
            )

        # 3. Construir filtros para la búsqueda
        filters = {}
        for field in ["year", "decade", "publication_date", "section", "newspaper"]:
            val = getattr(plan, field, None)
            if val is not None:
                filters[field] = val

        # 4. Recuperación híbrida con filtros aplicados
        search_q = plan.search_query or question
        retrieved_chunks = retrieve(self.hybrid_retriever, search_q, filters=filters)
        
        # 5. Rerankeo y verificación de evidencia
        reranked_chunks = rerank_documents(search_q, retrieved_chunks)
        evidence = check_evidence(search_q, reranked_chunks)
        
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

        # 6. Generación de respuesta con contexto
        context = format_context(reranked_chunks)
        messages = build_messages(question, context)
        return generate_response(question, reranked_chunks, evidence, messages, llm=self.llm)
