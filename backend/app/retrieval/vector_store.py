"""
Qdrant-backed semantic retrieval for Hemeroteca RAG.
"""

import hashlib
from functools import lru_cache
from uuid import uuid5, NAMESPACE_URL

import httpx
from langchain_core.documents import Document
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from sentence_transformers import SentenceTransformer
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

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


class GeminiEmbeddings:
    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("GEMINI_API_KEY no encontrada en la configuración o el archivo .env")
        self.api_key = api_key
        self.url_single = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:embedContent?key={self.api_key}"
        self.url_batch = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:batchEmbedContents?key={self.api_key}"
        logger.info("Inicializado proveedor de embeddings Gemini (API)")

    @retry(stop=stop_after_attempt(7), wait=wait_exponential(multiplier=2, min=4, max=30))
    def _post_with_retry(self, url: str, payload: dict) -> httpx.Response:
        with httpx.Client(timeout=30.0) as client:
            headers = {
                "Content-Type": "application/json"
            }
            response = client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            return response

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        
        batch_size = 20
        all_embeddings = []
        import time
        
        for i in range(0, len(texts), batch_size):
            if i > 0:
                logger.info("Esperando 4s antes del siguiente lote de embeddings para evitar límite de tasa (429)...")
                time.sleep(4.0)

            chunk = texts[i:i + batch_size]
            requests = [
                {
                    "model": "models/gemini-embedding-001",
                    "content": {
                        "parts": [{"text": _normalize_text(text)}]
                    }
                }
                for text in chunk
            ]
            payload = {"requests": requests}
            
            try:
                response = self._post_with_retry(self.url_batch, payload)
                data = response.json()
                for item in data.get("embeddings", []):
                    all_embeddings.append(item["values"])
            except Exception as e:
                logger.error(f"Error llamando a Gemini embeddings API (batch): {e}")
                raise e
                
        return all_embeddings

    def embed_query(self, query: str) -> list[float]:
        payload = {
            "model": "models/gemini-embedding-001",
            "content": {
                "parts": [{"text": _normalize_text(query)}]
            }
        }
        try:
            response = self._post_with_retry(self.url_single, payload)
            data = response.json()
            return data["embedding"]["values"]
        except Exception as e:
            logger.error(f"Error llamando a Gemini embeddings API (single): {e}")
            raise e


@lru_cache()
def get_embedding_function():
    settings = get_settings()
    if settings.embedding_provider == "gemini":
        return GeminiEmbeddings(api_key=settings.gemini_api_key)
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
    import time
    for attempt in range(5):
        try:
            client.create_collection(
                collection_name=settings.qdrant_collection,
                vectors_config=qmodels.VectorParams(
                    size=vector_size,
                    distance=qmodels.Distance.COSINE,
                ),
            )
            break
        except Exception as exc:
            if attempt == 4:
                raise exc
            logger.warning(f"Fallo al crear coleccion (intento {attempt + 1}/5): {exc}. Reintentando en 1s...")
            time.sleep(1)

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
            # Esperar a que Qdrant libere completamente la coleccion
            import time
            for _ in range(10):
                existing_now = {c.name for c in client.get_collections().collections}
                if settings.qdrant_collection not in existing_now:
                    break
                time.sleep(0.5)
            # Pequeño sleep extra por seguridad para liberar locks internos
            time.sleep(1)
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

        response = self.client.query_points(
            collection_name=self.settings.qdrant_collection,
            query=vector,
            limit=self.settings.top_k,
            query_filter=q_filter,
            with_payload=True,
        )
        results = response.points

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
