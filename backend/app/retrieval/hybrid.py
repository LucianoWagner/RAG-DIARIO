"""
Hybrid Retriever — Combinación de búsqueda semántica y léxica.
"""

import re
from functools import lru_cache
from langchain_core.documents import Document
from loguru import logger

from app.config import get_settings


@lru_cache(maxsize=1)
def _get_spacy_model():
    """Carga y cachea el modelo spaCy en español."""
    import spacy
    logger.info("Cargando spaCy es_core_news_md para análisis de query híbrido.")
    return spacy.load("es_core_news_md")


def _fallback_determine_weights(query: str) -> tuple[float, float]:
    """Fallback simple basado en regex si spaCy no está disponible."""
    query_clean = query.strip()
    words = [w.lower() for w in re.findall(r"\b\w+\b", query_clean)]
    
    has_digits = bool(re.search(r"\b\d{2,4}\b", query_clean))
    months = {
        "enero", "febrero", "marzo", "abril", "mayo", "junio", 
        "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"
    }
    has_month = any(w in months for w in words)
    
    capitalized_middle = False
    query_words = re.findall(r"\b\w+\b", query_clean)
    if len(query_words) > 1:
        for w in query_words[1:]:
            if w and w[0].isupper():
                capitalized_middle = True
                break
                
    is_factual = has_digits or has_month or capitalized_middle
    
    conceptual_keywords = {
        "porque", "como", "explicacion", "concepto", "significado", 
        "analisis", "motivo", "razon", "teoria", "opinion", "debate"
    }
    has_conceptual_key = any(w in conceptual_keywords for w in words)
    is_conceptual = has_conceptual_key or (len(words) > 8 and not is_factual)
    
    if is_factual:
        return 0.4, 0.6
    elif is_conceptual:
        return 0.6, 0.4
    else:
        return 0.5, 0.5


@lru_cache(maxsize=128)
def _determine_retrieval_weights(query: str) -> tuple[float, float]:
    """
    Determina de forma adaptativa los pesos (semantic_weight, bm25_weight) 
    dependiendo de la naturaleza lingüística de la consulta usando spaCy.
    """
    try:
        nlp = _get_spacy_model()
        doc = nlp(query.strip())
    except Exception as exc:
        logger.warning(f"No se pudo analizar la query con spaCy, usando fallback: {exc}")
        return _fallback_determine_weights(query)

    # 1. Indicadores Fácticos (Favorecen BM25)
    # - Presencia de entidades nombradas (nombres de personas, organizaciones, lugares)
    has_entities = len(doc.ents) > 0
    
    # - Presencia de sustantivos propios (detectados por POS tagger, sin importar mayúsculas/minúsculas)
    has_propn = any(t.pos_ == "PROPN" for t in doc)
    
    # - Presencia de números cardinales (ej: "2005", "90", "tres")
    has_num = any(t.pos_ == "NUM" or t.like_num for t in doc)
    
    # - Presencia de meses del año
    months = {
        "enero", "febrero", "marzo", "abril", "mayo", "junio", 
        "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"
    }
    has_month = any(t.text.lower() in months for t in doc)
    
    # - Años de 2 o 4 dígitos detectados por regex
    has_year_regex = bool(re.search(r"\b(19\d{2}|20\d{2}|\d{2})\b", query))

    is_factual = has_entities or has_propn or has_num or has_month or has_year_regex

    # 2. Indicadores Conceptuales/Abstractos (Favorecen búsqueda Semántica)
    words = [t.text.lower() for t in doc]
    conceptual_keywords = {
        "porque", "como", "explicacion", "concepto", "significado", 
        "analisis", "motivo", "razon", "teoria", "opinion", "debate",
        "filosofia", "definicion", "resumen", "contexto"
    }
    has_conceptual_key = any(w in conceptual_keywords for w in words)
    
    # Check "por que"
    has_por_que = False
    for i in range(len(words) - 1):
        if words[i] == "por" and words[i+1] == "que":
            has_por_que = True
            break
            
    is_conceptual = has_conceptual_key or has_por_que or (len(doc) > 8 and not is_factual)

    if is_factual:
        # Factual: Prioridad a coincidencias léxicas exactas
        return 0.4, 0.6
    elif is_conceptual:
        # Conceptual: Prioridad a similitud semántica de ideas/temas
        return 0.6, 0.4
    else:
        # Por defecto equilibrado
        return 0.5, 0.5


class CustomHybridRetriever:
    """Implementación robusta para ensamble RRF con pesos adaptativos y filtros."""
    def __init__(self, retrievers, weights):
        self.retrievers = retrievers
        self.weights = weights

    def _get_doc_id(self, doc: Document) -> str:
        """Obtiene un identificador único para el documento."""
        chunk_id = doc.metadata.get("chunk_id")
        if chunk_id:
            return str(chunk_id)
        # Fallback a hash del texto
        import hashlib
        return hashlib.sha1(doc.page_content.encode("utf-8")).hexdigest()

    def invoke(self, query: str, filters: dict | None = None) -> list[Document]:
        # 1. Ajuste adaptativo de pesos basado en la consulta
        semantic_weight, bm25_weight = _determine_retrieval_weights(query)
        logger.info(
            f"Búsqueda híbrida para query: '{query}' | "
            f"Pesos adaptados: semántico={semantic_weight}, bm25={bm25_weight}"
        )
        
        # 2. Obtener resultados de todos los retrievers
        # El primero es semántico, el segundo es léxico (BM25)
        semantic_docs = self.retrievers[0].invoke(query, filters=filters)
        bm25_docs = self.retrievers[1].invoke(query, filters=filters)

        # 3. Aplicar matemática de RRF (Reciprocal Rank Fusion)
        rrf_score = {}
        doc_map = {}
        
        # Guardar rangos originales para auditabilidad en metadatos
        semantic_ranks = {self._get_doc_id(doc): rank for rank, doc in enumerate(semantic_docs)}
        bm25_ranks = {self._get_doc_id(doc): rank for rank, doc in enumerate(bm25_docs)}

        # Fusionar resultados del retriever semántico
        for rank, doc in enumerate(semantic_docs):
            doc_id = self._get_doc_id(doc)
            if doc_id not in doc_map:
                doc_map[doc_id] = doc
                rrf_score[doc_id] = 0.0
            rrf_score[doc_id] += semantic_weight * (1.0 / (60 + rank))

        # Fusionar resultados del retriever léxico (BM25)
        for rank, doc in enumerate(bm25_docs):
            doc_id = self._get_doc_id(doc)
            if doc_id not in doc_map:
                doc_map[doc_id] = doc
                rrf_score[doc_id] = 0.0
            rrf_score[doc_id] += bm25_weight * (1.0 / (60 + rank))

        # 4. Ordenar por score de RRF y construir documentos limpios
        sorted_ids = sorted(rrf_score.keys(), key=lambda x: rrf_score[x], reverse=True)
        
        final_docs = []
        for doc_id in sorted_ids:
            original_doc = doc_map[doc_id]
            # Crear copia superficial para no mutar los objetos en memoria del retriever BM25
            doc_copy = Document(page_content=original_doc.page_content, metadata=dict(original_doc.metadata))
            doc_copy.metadata["rrf_score"] = float(rrf_score[doc_id])
            doc_copy.metadata["semantic_rank"] = semantic_ranks.get(doc_id)
            doc_copy.metadata["bm25_rank"] = bm25_ranks.get(doc_id)
            final_docs.append(doc_copy)

        return final_docs


def create_hybrid_retriever(semantic_retriever, bm25_retriever) -> CustomHybridRetriever:
    """
    Crea un retriever híbrido que combina semántico + BM25 con RRF.
    """
    settings = get_settings()
    return CustomHybridRetriever(
        retrievers=[semantic_retriever, bm25_retriever],
        weights=[settings.semantic_weight, settings.bm25_weight]
    )


def retrieve(retriever: CustomHybridRetriever, query: str, filters: dict | None = None) -> list[Document]:
    """
    Ejecuta la búsqueda híbrida para una consulta con filtros opcionales.
    """
    results = retriever.invoke(query, filters=filters)
    logger.info(f"Búsqueda híbrida retornó {len(results)} documentos únicos para la consulta: '{query}'")
    return results
