"""
Inspect Qdrant payloads for the Hemeroteca collection.
"""

import argparse
from collections import Counter

from qdrant_client.http import models as qmodels

from app.config import get_settings
from app.retrieval.vector_store import get_qdrant_client


def _condition(key: str, value: str) -> qmodels.FieldCondition:
    return qmodels.FieldCondition(key=key, match=qmodels.MatchValue(value=value))


def _build_filter(args: argparse.Namespace) -> qmodels.Filter | None:
    conditions: list[qmodels.FieldCondition] = []
    if args.date:
        conditions.append(_condition("publication_date", args.date))
    if args.article_scope:
        conditions.append(_condition("article_country_scope", args.article_scope))
    if args.scope:
        conditions.append(_condition("country_scope", args.scope))
    if args.section:
        conditions.append(_condition("section", args.section))
    if not conditions:
        return None
    return qmodels.Filter(must=conditions)


def _shorten(text: str, max_chars: int) -> str:
    text = " ".join(str(text or "").split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def inspect_store(args: argparse.Namespace) -> None:
    settings = get_settings()
    client = get_qdrant_client()
    query_filter = _build_filter(args)
    points, _ = client.scroll(
        collection_name=settings.qdrant_collection,
        scroll_filter=query_filter,
        limit=args.limit,
        with_payload=True,
        with_vectors=args.with_vectors,
    )

    print("=" * 100)
    print(f"Collection: {settings.qdrant_collection}")
    print(f"Qdrant:     {settings.qdrant_url}")
    print(f"Results:    {len(points)}")
    print(
        "Filters:    "
        f"date={args.date or '*'} | "
        f"article_scope={args.article_scope or '*'} | "
        f"scope={args.scope or '*'} | "
        f"section={args.section or '*'}"
    )
    print("=" * 100)

    article_scopes = Counter()
    chunk_scopes = Counter()
    sections = Counter()
    for point in points:
        payload = point.payload or {}
        article_scopes[str(payload.get("article_country_scope", "missing"))] += 1
        chunk_scopes[str(payload.get("country_scope", "missing"))] += 1
        sections[str(payload.get("section", "missing"))] += 1

    print(f"Article scopes: {dict(article_scopes)}")
    print(f"Chunk scopes:   {dict(chunk_scopes)}")
    print(f"Sections:       {dict(sections)}")
    print("=" * 100)

    for index, point in enumerate(points, start=1):
        payload = point.payload or {}
        print(f"\n[{index}] id={point.id}")
        print(f"date={payload.get('publication_date')} | section={payload.get('section')}")
        print(f"title={payload.get('article_title')}")
        print(f"url={payload.get('source_url')}")
        print(
            f"chunk_scope={payload.get('country_scope')} | "
            f"article_scope={payload.get('article_country_scope')}"
        )
        print(f"scope_signals={payload.get('scope_signals')}")
        print(f"article_scope_signals={payload.get('article_scope_signals')}")
        print(f"locations={payload.get('location_mentions')}")
        print(f"persons={payload.get('persons')}")
        print(f"organizations={payload.get('organizations')}")
        print(f"chunk={payload.get('chunk_index')}/{payload.get('total_chunks')}")
        print(f"text={_shorten(str(payload.get('text') or ''), args.chars)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=None, help="Fecha ISO YYYY-MM-DD, ej: 2005-01-02.")
    parser.add_argument("--article-scope", default=None, choices=("argentina", "international", "unknown"))
    parser.add_argument("--scope", default=None, choices=("argentina", "international", "unknown"))
    parser.add_argument("--section", default=None)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--chars", type=int, default=500)
    parser.add_argument("--with-vectors", action="store_true")
    args = parser.parse_args()
    inspect_store(args)


if __name__ == "__main__":
    main()
