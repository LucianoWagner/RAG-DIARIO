"""
Reranking for retrieved chunks using FlashRank or CrossEncoder.
"""

from flashrank import Ranker, RerankRequest
from langchain_core.documents import Document
from loguru import logger
from sentence_transformers import CrossEncoder

from app.config import get_settings

_ranker = None
_current_model_name = None
_current_reranker_type = None


def _init_ranker(settings):
    """Inicializa de forma perezosa y cacheada el reranker adecuado."""
    global _ranker, _current_model_name, _current_reranker_type
    
    if (_ranker is not None 
            and _current_model_name == settings.reranker_model_name 
            and _current_reranker_type == settings.reranker_type):
        return
        
    _current_model_name = settings.reranker_model_name
    _current_reranker_type = settings.reranker_type
    
    if settings.reranker_type == "cross-encoder":
        logger.info(f"Cargando CrossEncoder de sentence-transformers: {settings.reranker_model_name}")
        _ranker = CrossEncoder(settings.reranker_model_name, cache_folder=settings.model_cache_dir)
    else:
        logger.info(f"Cargando FlashRank: {settings.reranker_model_name}")
        _ranker = Ranker(model_name=settings.reranker_model_name)


def rerank_documents(query: str, documents: list[Document]) -> list[Document]:
    settings = get_settings()
    if not documents:
        return []

    try:
        _init_ranker(settings)
    except Exception as exc:
        logger.error(
            f"Error inicializando el reranker ({settings.reranker_type}): {exc}. "
            f"Retornando documentos originales sin rerank."
        )
        return documents[:settings.rerank_top_n]

    if settings.reranker_type == "cross-encoder":
        # Flujo de CrossEncoder (sentence-transformers)
        pairs = [[query, doc.page_content] for doc in documents]
        try:
            scores = _ranker.predict(pairs)
            scored_docs = list(zip(documents, scores))
            # Ordenar por puntaje descendente
            scored_docs.sort(key=lambda x: x[1], reverse=True)
            
            ranked_docs = []
            for rank, (doc, score) in enumerate(scored_docs[:settings.rerank_top_n], start=1):
                doc_copy = Document(page_content=doc.page_content, metadata=dict(doc.metadata))
                doc_copy.metadata["rerank_score"] = float(score)
                doc_copy.metadata["rerank_position"] = rank
                ranked_docs.append(doc_copy)
            return ranked_docs
        except Exception as exc:
            logger.error(f"Error ejecutando CrossEncoder: {exc}. Retornando documentos sin rerank.")
            return documents[:settings.rerank_top_n]
    else:
        # Flujo de FlashRank
        passages = [
            {"id": index, "text": document.page_content, "meta": document.metadata}
            for index, document in enumerate(documents)
        ]
        try:
            results = _ranker.rerank(RerankRequest(query=query, passages=passages))
            ranked_docs = []
            for rank, result in enumerate(results[:settings.rerank_top_n], start=1):
                doc = Document(page_content=result["text"], metadata=result.get("meta", {}))
                doc.metadata["rerank_score"] = float(result.get("score", 0.0))
                doc.metadata["rerank_position"] = rank
                ranked_docs.append(doc)
            return ranked_docs
        except Exception as exc:
            logger.error(f"Error ejecutando FlashRank: {exc}. Retornando documentos sin rerank.")
            return documents[:settings.rerank_top_n]
