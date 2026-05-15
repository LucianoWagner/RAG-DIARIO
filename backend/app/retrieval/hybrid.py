"""
Hybrid Retriever — Combinación de búsqueda semántica y léxica.

Responsabilidad:
- Combinar resultados de ChromaDB (semántico) y BM25 (léxico)
- Usar Reciprocal Rank Fusion (RRF) para fusionar rankings
- Ponderar la contribución de cada retriever
"""

from langchain_core.documents import Document
from loguru import logger

from app.config import get_settings

class CustomHybridRetriever:
    """Implementación robusta e independiente de versión para ensamble RRF."""
    def __init__(self, retrievers, weights):
        self.retrievers = retrievers
        self.weights = weights

    def invoke(self, query: str) -> list[Document]:
        # 1. Obtener resultados de todos los retrievers
        all_results = []
        for r in self.retrievers:
            # invocación a Chroma y BM25
            all_results.append(r.invoke(query))

        # 2. Aplicar matemática de RRF (Reciprocal Rank Fusion)
        rrf_score = {}
        doc_map = {}
        for weight, docs in zip(self.weights, all_results):
            for rank, doc in enumerate(docs):
                # La llave para des-duplicar es el texto crudo del chunk
                key = doc.page_content
                if key not in doc_map:
                    doc_map[key] = doc
                    rrf_score[key] = 0.0
                # Formula RRF penalizada por el peso configurado (.env)
                rrf_score[key] += weight * (1.0 / (60 + rank))

        # 3. Ordenar por el score RRF resultante
        sorted_keys = sorted(rrf_score.keys(), key=lambda x: rrf_score[x], reverse=True)
        return [doc_map[k] for k in sorted_keys]


def create_hybrid_retriever(semantic_retriever, bm25_retriever) -> CustomHybridRetriever:
    """
    Crea un retriever híbrido que combina semántico + BM25 con RRF.
    """
    settings = get_settings()
    logger.info(
        f"Creando hybrid retriever | "
        f"Semántico: {settings.semantic_weight} | BM25: {settings.bm25_weight}"
    )

    return CustomHybridRetriever(
        retrievers=[semantic_retriever, bm25_retriever],
        weights=[settings.semantic_weight, settings.bm25_weight]
    )

def retrieve(retriever: CustomHybridRetriever, query: str) -> list[Document]:
    """
    Ejecuta la búsqueda híbrida para una consulta.
    """
    results = retriever.invoke(query)
    
    # La de-duplicación ya ocurre nativamente por diseño en nuestro nuevo CustomHybridRetriever
    logger.info(f"Búsqueda híbrida retornó {len(results)} documentos únicos para: '{query}'")
    
    return results
