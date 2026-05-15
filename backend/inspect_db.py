"""
Inspect the Qdrant collection used by the Hemeroteca RAG.
"""

from app.config import get_settings
from app.retrieval.vector_store import get_qdrant_client


def inspect_qdrant(limit: int = 5) -> None:
    settings = get_settings()
    client = get_qdrant_client()

    print(f"Qdrant: {settings.qdrant_url}")
    print(f"Collection: {settings.qdrant_collection}")

    try:
        collection_info = client.get_collection(settings.qdrant_collection)
    except Exception as exc:
        print(f"No se pudo leer la coleccion: {exc}")
        return

    print(f"Total puntos: {collection_info.points_count}")
    print("=" * 80)

    points, _ = client.scroll(
        collection_name=settings.qdrant_collection,
        limit=limit,
        with_payload=True,
        with_vectors=False,
    )

    if not points:
        print("La coleccion esta vacia.")
        return

    for point in points:
        payload = point.payload or {}
        preview = str(payload.get("text", ""))[:180].replace("\n", " ")
        print(f"ID: {point.id}")
        print(f"Fecha: {payload.get('publication_date')} | Diario: {payload.get('newspaper')}")
        print(f"Titulo: {payload.get('article_title')}")
        print(f"URL: {payload.get('source_url')}")
        print(f"Texto: {preview}...")
        print("-" * 80)


if __name__ == "__main__":
    inspect_qdrant()
