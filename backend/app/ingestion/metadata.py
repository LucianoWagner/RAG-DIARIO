"""
Metadata enrichment for Hemeroteca chunks.
"""

from datetime import date, datetime

from langchain_core.documents import Document
from loguru import logger

from app.ingestion.enrichers.gazetteer import Gazetteer, load_gazetteer
from app.ingestion.enrichers.ner import extract_entities


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
) -> list[Document]:
    gazetteer = gazetteer or load_gazetteer()
    logger.info(f"Enriqueciendo metadata | chunks={len(chunks)}")

    for index, chunk in enumerate(chunks, start=1):
        publication_date = _parse_date(chunk.metadata.get("publication_date"))
        entities = extract_entities(chunk.page_content)
        locations = gazetteer.find_locations(chunk.page_content)
        primary_location = gazetteer.pick_primary_location(locations)

        chunk.metadata["publication_date"] = publication_date.isoformat()
        chunk.metadata["year"] = publication_date.year
        chunk.metadata["decade"] = int(publication_date.year / 10) * 10
        chunk.metadata["persons"] = entities["persons"]
        chunk.metadata["organizations"] = entities["organizations"]
        chunk.metadata["location_mentions"] = locations
        chunk.metadata["primary_location"] = primary_location
        chunk.metadata["text"] = chunk.page_content
        chunk.metadata["text_clean"] = " ".join(chunk.page_content.split())
        chunk.metadata.setdefault("newspaper", "el_dia")
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

    logger.info("Metadata enrichment terminado")
    return chunks
