"""
Metadata enrichment for Hemeroteca chunks.
"""

from datetime import date, datetime
from collections import defaultdict

from langchain_core.documents import Document
from loguru import logger

from app.ingestion.enrichers.gazetteer import Gazetteer, load_gazetteer
from app.ingestion.enrichers.ner import extract_entities
from app.ingestion.enrichers.scope_classifier import ScopeClassifier, build_default_llm_client
from app.retrieval.vector_store import get_embedding_function


def _parse_date(raw_value: str | date | None) -> date:
    if isinstance(raw_value, date):
        return raw_value
    if raw_value:
        try:
            return datetime.fromisoformat(str(raw_value)[:10]).date()
        except ValueError:
            pass
    return date(1900, 1, 1)


def enrich_metadata(
    chunks: list[Document],
    gazetteer: Gazetteer | None = None,
    scope_classifier: ScopeClassifier | None = None,
) -> list[Document]:
    gazetteer = gazetteer or load_gazetteer()
    scope_classifier = scope_classifier or ScopeClassifier(
        embedder=get_embedding_function(),
        llm_client=build_default_llm_client(),
        gazetteer=gazetteer,
    )
    scope_stats = {"argentina": 0, "international": 0, "unknown": 0}
    logger.info(f"Enriqueciendo metadata | chunks={len(chunks)}")

    for index, chunk in enumerate(chunks, start=1):
        publication_date = _parse_date(chunk.metadata.get("publication_date"))
        entities = extract_entities(chunk.page_content)
        locations = gazetteer.find_locations(chunk.page_content)
        primary_location = gazetteer.pick_primary_location(locations)
        classifier_metadata = dict(chunk.metadata)
        classifier_metadata["organizations"] = entities["organizations"]
        classifier_metadata["location_mentions"] = locations
        country_scope, scope_signals = scope_classifier.classify(
            chunk.page_content,
            classifier_metadata,
        )
        scope_stats[country_scope] = scope_stats.get(country_scope, 0) + 1

        chunk.metadata["publication_date"] = publication_date.isoformat()
        chunk.metadata["year"] = publication_date.year
        chunk.metadata["decade"] = int(publication_date.year / 10) * 10
        chunk.metadata["persons"] = entities["persons"]
        chunk.metadata["organizations"] = entities["organizations"]
        chunk.metadata["location_mentions"] = locations
        chunk.metadata["primary_location"] = primary_location
        chunk.metadata["country_scope"] = country_scope
        chunk.metadata["scope_signals"] = scope_signals
        chunk.metadata["text"] = chunk.page_content
        chunk.metadata["text_clean"] = " ".join(chunk.page_content.split())
        chunk.metadata.setdefault("newspaper", "pagina12")
        chunk.metadata.setdefault("source_type", "html")
        chunk.metadata.setdefault("granularity", "article")
        chunk.metadata.setdefault("source_pdf_path", None)
        chunk.metadata.setdefault("ocr_confidence", None)
        chunk.metadata.setdefault("page_number", None)
        if index == 1 or index % 25 == 0 or index == len(chunks):
            logger.info(
                f"Metadata {index}/{len(chunks)} | "
                f"year={chunk.metadata['year']} | "
                f"locations={len(locations)} | persons={len(entities['persons'])}"
            )

    _apply_article_scope(chunks)
    logger.info(
        "Scope stats: "
        f"argentina={scope_stats.get('argentina', 0)}, "
        f"international={scope_stats.get('international', 0)}, "
        f"unknown={scope_stats.get('unknown', 0)}, "
        f"total={len(chunks)}"
    )
    logger.info("Metadata enrichment terminado")
    return chunks


def _apply_article_scope(chunks: list[Document]) -> None:
    grouped: dict[str, list[Document]] = defaultdict(list)
    for chunk in chunks:
        grouped[str(chunk.metadata.get("source_id", "unknown"))].append(chunk)

    article_stats = {"argentina": 0, "international": 0, "unknown": 0}
    for source_id, group in grouped.items():
        article_scope, article_signals = _resolve_article_scope(group)
        article_stats[article_scope] = article_stats.get(article_scope, 0) + 1
        for chunk in group:
            chunk.metadata["article_country_scope"] = article_scope
            chunk.metadata["article_scope_signals"] = article_signals
        logger.debug(
            f"Article scope | source_id={source_id} | "
            f"scope={article_scope} | signals={article_signals}"
        )

    logger.info(
        "Article scope stats: "
        f"argentina={article_stats.get('argentina', 0)}, "
        f"international={article_stats.get('international', 0)}, "
        f"unknown={article_stats.get('unknown', 0)}, "
        f"total={len(grouped)}"
    )


def _resolve_article_scope(chunks: list[Document]) -> tuple[str, list[str]]:
    argentina_non_llm: list[str] = []
    argentina_llm: list[str] = []
    international_signals: list[str] = []

    for chunk in chunks:
        scope = chunk.metadata.get("country_scope")
        signals = [str(signal) for signal in chunk.metadata.get("scope_signals", [])]
        chunk_ref = f"chunk:{chunk.metadata.get('chunk_index', 0)}"
        if scope == "argentina":
            if any(_is_non_llm_argentina_signal(signal) for signal in signals):
                argentina_non_llm.append(_article_signal(chunk_ref, signals))
            elif any(signal.startswith("llm_local:") for signal in signals):
                argentina_llm.append(_article_signal(chunk_ref, signals))
        elif scope == "international":
            international_signals.append(_article_signal(chunk_ref, signals))

    if argentina_non_llm:
        return "argentina", _dedupe(["article:chunk_argentina_non_llm", *argentina_non_llm])
    if len(argentina_llm) >= 2:
        return "argentina", _dedupe(["article:multi_llm_argentina", *argentina_llm])
    if international_signals:
        return "international", _dedupe(["article:chunk_international", *international_signals])
    return "unknown", []


def _is_non_llm_argentina_signal(signal: str) -> bool:
    return signal.startswith(
        ("seccion:", "gazetteer:", "institution:", "political_org:", "club:", "term:", "emb_")
    )


def _article_signal(chunk_ref: str, signals: list[str]) -> str:
    relevant = [signal for signal in signals if not signal.startswith("emb_")]
    if not relevant:
        relevant = signals[:1]
    return f"{chunk_ref}:{'|'.join(relevant[:2])}"


def _dedupe(values: list[str]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        if value and value not in deduped:
            deduped.append(value)
    return deduped
