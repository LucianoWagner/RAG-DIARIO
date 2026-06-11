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
        
        try:
            logger.info(f"=== TOP {len(reranked_chunks)} CHUNKS RECUPERADOS Y RERANKEADOS ===")
            for idx, chunk in enumerate(reranked_chunks, start=1):
                title = chunk.metadata.get("article_title") or "Sin titulo"
                date = chunk.metadata.get("publication_date") or "Sin fecha"
                section = chunk.metadata.get("section") or "Sin seccion"
                rrf = chunk.metadata.get("rrf_score", 0.0)
                rerank = chunk.metadata.get("rerank_score", 0.0)
                text_preview = chunk.page_content[:120].replace('\n', ' ').strip() + "..."
                logger.info(
                    f"[{idx}] Score={float(rerank):.4f} (RRF={float(rrf):.4f}) | "
                    f"Fecha={date} | Seccion={section} | Titulo='{title}' | "
                    f"Texto: {text_preview}"
                )
            logger.info("=========================================================")
        except Exception as e:
            logger.warning(f"Error logueando chunks recuperados: {e}")

        evidence = check_evidence(search_q, reranked_chunks)
        try:
            logger.info(
                f"Veredicto Evidencia: {str(evidence.verdict).upper()} | "
                f"Top Score={float(evidence.top_score):.4f} | "
                f"Chunks Relevantes={int(evidence.relevant_count)} | "
                f"Detalles: {evidence.details}"
            )
        except Exception:
            logger.info(
                f"Veredicto Evidencia: {evidence.verdict} | "
                f"Top Score={evidence.top_score} | "
                f"Chunks Relevantes={evidence.relevant_count} | "
                f"Detalles: {evidence.details}"
            )
        
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

        # 6. Reconstrucción de artículos completos para evitar pérdida de contexto
        logger.info("Reconstruyendo artículos a partir de los chunks seleccionados...")
        reconstructed_docs = self._reconstruct_articles(reranked_chunks, max_articles=3)
        logger.info(f"Reconstruidos {len(reconstructed_docs)} artículos completos como contexto.")

        # 7. Generación de respuesta con contexto consolidado
        context = format_context(reconstructed_docs)
        messages = build_messages(question, context)
        return generate_response(question, reconstructed_docs, evidence, messages, llm=self.llm)

    def _reconstruct_articles(self, chunks: list[Document], max_articles: int = 3) -> list[Document]:
        """
        Toma los chunks seleccionados, agrupa por source_id, y reconstruye
        los artículos completos consultando todos los chunks de dicho source_id en Qdrant.
        Esto evita problemas de pérdida de contexto debido al chunking.
        """
        from qdrant_client.http import models as qmodels
        
        unique_source_ids = []
        seen = set()
        for chunk in chunks:
            source_id = chunk.metadata.get("source_id")
            if source_id and source_id not in seen:
                seen.add(source_id)
                unique_source_ids.append(source_id)
                if len(unique_source_ids) >= max_articles:
                    break
                    
        if not unique_source_ids:
            return chunks[:max_articles]
            
        merged_docs = []
        for source_id in unique_source_ids:
            # Recuperar todos los chunks de este artículo
            scroll_result, _ = self.client.scroll(
                collection_name=self.settings.qdrant_collection,
                scroll_filter=qmodels.Filter(
                    must=[
                        qmodels.FieldCondition(key="source_id", match=qmodels.MatchValue(value=source_id))
                    ]
                ),
                limit=100,
                with_payload=True,
            )
            
            # Agrupar y ordenar por chunk_index
            article_chunks = []
            for point in scroll_result:
                payload = dict(point.payload or {})
                page_content = str(payload.pop("text", ""))
                article_chunks.append((payload.get("chunk_index", 0), page_content, payload))
                
            article_chunks.sort(key=lambda x: x[0])
            
            if not article_chunks:
                # Si por alguna razón no se encuentran chunks en Qdrant (ej. en mocks de tests),
                # buscamos si el chunk original con este source_id estaba en la lista de entrada.
                matching_input_chunks = [c for c in chunks if c.metadata.get("source_id") == source_id]
                if matching_input_chunks:
                    merged_docs.append(matching_input_chunks[0])
                continue
                
            # Reconstruir texto completo
            full_text = "\n\n".join(chunk_text for _, chunk_text, _ in article_chunks)
            base_metadata = article_chunks[0][2]
            
            # Conservar el score del chunk original más relevante de este artículo
            matching_input_chunks = [c for c in chunks if c.metadata.get("source_id") == source_id]
            if matching_input_chunks:
                base_metadata["rerank_score"] = matching_input_chunks[0].metadata.get("rerank_score", 0.0)
                base_metadata["semantic_score"] = matching_input_chunks[0].metadata.get("semantic_score", 0.0)
            
            merged_docs.append(Document(page_content=full_text, metadata=base_metadata))
            
        return merged_docs

