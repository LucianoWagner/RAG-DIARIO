"""
Qdrant-backed semantic retrieval for Hemeroteca RAG.
"""

import hashlib
from functools import lru_cache
from uuid import uuid5, NAMESPACE_URL

from langchain_core.documents import Document
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from sentence_transformers import SentenceTransformer
from loguru import logger

from app.config import get_settings


def _normalize_text(text: str) -> str:
    return " ".join(text.split())


class E5Embeddings:
    def __init__(self, model_name: str, cache_folder: str | None = None):
        logger.info(f"Cargando modelo de embeddings: {model_name}")
        self.model = SentenceTransformer(model_name, cache_folder=cache_folder)
        logger.info("Modelo de embeddings cargado")

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        passages = [f"passage: {_normalize_text(text)}" for text in texts]
        return self.model.encode(passages, normalize_embeddings=True).tolist()

    def embed_query(self, query: str) -> list[float]:
        return self.model.encode(
            [f"query: {_normalize_text(query)}"],
            normalize_embeddings=True,
        )[0].tolist()


@lru_cache()
def get_embedding_function() -> E5Embeddings:
    settings = get_settings()
    return E5Embeddings(settings.embedding_model, cache_folder=settings.model_cache_dir)


@lru_cache()
def get_qdrant_client() -> QdrantClient:
    settings = get_settings()
    return QdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key,
        prefer_grpc=settings.qdrant_prefer_grpc,
    )


def _build_point_id(chunk: Document) -> str:
    chunk_id = chunk.metadata.get("chunk_id")
    if chunk_id:
        return str(uuid5(NAMESPACE_URL, str(chunk_id)))
    digest = hashlib.sha1(chunk.page_content.encode("utf-8")).hexdigest()
    return str(uuid5(NAMESPACE_URL, digest))


def _is_valid_vector(vector: object) -> bool:
    return isinstance(vector, list) and bool(vector) and all(isinstance(value, (int, float)) for value in vector)


def _resolve_embeddings(chunks: list[Document]) -> list[list[float]]:
    embeddings: list[list[float] | None] = [None] * len(chunks)
    missing_indices: list[int] = []
    missing_texts: list[str] = []

    for index, chunk in enumerate(chunks):
        vector = chunk.metadata.get("_index_vector")
        if _is_valid_vector(vector):
            embeddings[index] = [float(value) for value in vector]
        else:
            missing_indices.append(index)
            missing_texts.append(chunk.page_content)

    reused_count = len(chunks) - len(missing_indices)
    if reused_count:
        logger.info(f"Reutilizando embeddings precomputados: {reused_count}/{len(chunks)}")

    if missing_texts:
        logger.info(f"Generando embeddings faltantes: {len(missing_texts)}")
        generated = get_embedding_function().embed_documents(missing_texts)
        for index, vector in zip(missing_indices, generated):
            embeddings[index] = vector

    return [vector for vector in embeddings if vector is not None]


def ensure_collection() -> None:
    settings = get_settings()
    client = get_qdrant_client()
    logger.info(f"Verificando coleccion Qdrant: {settings.qdrant_collection}")
    vector_size = len(get_embedding_function().embed_query("La Plata"))

    existing = {collection.name for collection in client.get_collections().collections}
    if settings.qdrant_collection in existing:
        logger.info(f"Coleccion existente: {settings.qdrant_collection}")
        ensure_payload_indexes()
        return

    logger.info(f"Creando coleccion Qdrant | vector_size={vector_size}")
    client.create_collection(
        collection_name=settings.qdrant_collection,
        vectors_config=qmodels.VectorParams(
            size=vector_size,
            distance=qmodels.Distance.COSINE,
        ),
    )

    ensure_payload_indexes()


def ensure_payload_indexes() -> None:
    settings = get_settings()
    client = get_qdrant_client()
    for field_name, schema in (
        ("year", qmodels.IntegerIndexParams(type="integer")),
        ("decade", qmodels.IntegerIndexParams(type="integer")),
        ("newspaper", qmodels.KeywordIndexParams(type="keyword")),
        ("section", qmodels.KeywordIndexParams(type="keyword")),
        ("country_scope", qmodels.KeywordIndexParams(type="keyword")),
        ("article_country_scope", qmodels.KeywordIndexParams(type="keyword")),
        ("primary_location", qmodels.KeywordIndexParams(type="keyword")),
        ("persons", qmodels.KeywordIndexParams(type="keyword")),
        ("organizations", qmodels.KeywordIndexParams(type="keyword")),
        ("publication_date", qmodels.KeywordIndexParams(type="keyword")),
    ):
        try:
            client.create_payload_index(
                collection_name=settings.qdrant_collection,
                field_name=field_name,
                field_schema=schema,
                wait=True,
            )
            logger.info(f"Indice payload creado: {field_name}")
        except Exception as exc:
            logger.debug(f"Indice payload omitido/existente {field_name}: {exc}")


def index_documents(chunks: list[Document], force: bool = False) -> int:
    settings = get_settings()
    client = get_qdrant_client()

    if force:
        logger.warning(f"force=True | borrando coleccion {settings.qdrant_collection}")
        existing = {collection.name for collection in client.get_collections().collections}
        if settings.qdrant_collection in existing:
            client.delete_collection(settings.qdrant_collection)
        ensure_collection()
    else:
        ensure_collection()

    if not chunks:
        logger.warning("No hay chunks para indexar")
        return 0

    logger.info(f"Resolviendo embeddings para {len(chunks)} chunks")
    embeddings = _resolve_embeddings(chunks)
    logger.info("Embeddings generados")
    points = []
    for chunk, vector in zip(chunks, embeddings):
        payload = dict(chunk.metadata)
        payload.pop("_index_vector", None)
        payload["text"] = chunk.page_content
        points.append(
            qmodels.PointStruct(
                id=_build_point_id(chunk),
                vector=vector,
                payload=payload,
            )
        )

    logger.info(f"Subiendo {len(points)} puntos a Qdrant")
    client.upsert(
        collection_name=settings.qdrant_collection,
        points=points,
        wait=True,
    )
    logger.info("Upsert Qdrant completado")
    return len(points)


class QdrantSemanticRetriever:
    def __init__(self):
        self.settings = get_settings()
        self.client = get_qdrant_client()
        self.embeddings = get_embedding_function()
        ensure_collection()

    def invoke(self, query: str, filters: dict | None = None) -> list[Document]:
        vector = self.embeddings.embed_query(query)
        
        conditions = []
        if filters:
            for key, value in filters.items():
                if value is not None:
                    conditions.append(
                        qmodels.FieldCondition(
                            key=key,
                            match=qmodels.MatchValue(value=value)
                        )
                    )
        q_filter = qmodels.Filter(must=conditions) if conditions else None

        results = self.client.search(
            collection_name=self.settings.qdrant_collection,
            query_vector=vector,
            limit=self.settings.top_k,
            query_filter=q_filter,
            with_payload=True,
        )

        documents: list[Document] = []
        for item in results:
            payload = dict(item.payload or {})
            page_content = str(payload.pop("text", ""))
            payload["semantic_score"] = float(item.score)
            documents.append(Document(page_content=page_content, metadata=payload))
        return documents


def get_vector_store() -> QdrantClient:
    ensure_collection()
    return get_qdrant_client()


def get_semantic_retriever() -> QdrantSemanticRetriever:
    return QdrantSemanticRetriever()
