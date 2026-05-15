"""
Phase 1 ingestion pipeline for El Dia HTML content.
"""

import argparse
import sys
import time
from pathlib import Path

from langchain_core.documents import Document
from loguru import logger

from app.config import get_settings
from app.ingestion.chunker import chunk_documents
from app.ingestion.metadata import enrich_metadata
from app.ingestion.parsers.html_parser import parse_html_directory
from app.ingestion.scrapers.eldia_web import scrape_year
from app.retrieval.vector_store import index_documents


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _data_path(relative_path: str) -> Path:
    return (_project_root() / relative_path).resolve()


def run_ingestion(
    force: bool = False,
    stage: str = "all",
    year: int | None = None,
) -> list[Document]:
    logger.remove()
    logger.add(
        sys.stderr,
        level="INFO",
        format="<green>{time:HH:mm:ss}</green> | <level>{level:<8}</level> | {message}",
    )

    settings = get_settings()
    target_year = year or settings.scraper_target_year
    raw_year_dir = _data_path(settings.raw_data_dir) / "eldia" / str(target_year)
    started_at = time.perf_counter()

    logger.info("=" * 72)
    logger.info("INGESTA HEMEROTECA - FASE 1")
    logger.info(f"stage={stage} | year={target_year} | force={force}")
    logger.info(f"raw_year_dir={raw_year_dir}")
    logger.info(f"qdrant={settings.qdrant_url} | collection={settings.qdrant_collection}")
    logger.info(f"embedding_model={settings.embedding_model}")
    logger.info("=" * 72)

    if stage in {"scrape", "all"}:
        logger.info("[1/5] Scraping El Dia")
        scraped_files = scrape_year(target_year, raw_year_dir)
        logger.info(f"[1/5] Scraping terminado | archivos HTML disponibles={len(scraped_files)}")
        if stage == "scrape":
            logger.info("Stage solicitado: scrape. Fin.")
            return []

    logger.info("[2/5] Parseando HTML con trafilatura")
    documents = parse_html_directory(raw_year_dir)
    logger.info(f"[2/5] Parse terminado | documentos validos={len(documents)}")
    if stage == "parse":
        logger.info("Stage solicitado: parse. Fin.")
        return documents

    logger.info("[3/5] Chunking en espanol")
    chunks = chunk_documents(documents)
    logger.info(f"[3/5] Chunking terminado | chunks={len(chunks)}")

    logger.info("[4/5] Enriqueciendo metadata con NER + gazetteer")
    chunks = enrich_metadata(chunks)
    logger.info(f"[4/5] Metadata enriquecida | chunks={len(chunks)}")
    if stage == "enrich":
        logger.info("Stage solicitado: enrich. Fin.")
        return chunks

    logger.info("[5/5] Indexando en Qdrant")
    indexed_count = index_documents(chunks, force=force)
    logger.info(f"[5/5] Indexacion terminada | puntos indexados={indexed_count}")
    logger.info(f"INGESTA COMPLETA | tiempo_total={time.perf_counter() - started_at:.1f}s")
    return chunks


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--stage", choices=("all", "scrape", "parse", "enrich", "index"), default="all")
    parser.add_argument("--year", type=int, default=None)
    args = parser.parse_args()

    stage = args.stage
    if stage == "index":
        stage = "all"

    run_ingestion(force=args.force, stage=stage, year=args.year)


if __name__ == "__main__":
    main()
