"""
Phase 1 ingestion pipeline for Pagina 12 HTML content.
"""

import argparse
import json
import sys
import time
from pathlib import Path

from langchain_core.documents import Document
from loguru import logger

from app.config import get_settings
from app.ingestion.parsers.html_parser import parse_html_file, write_parsed_documents
from app.ingestion.scrapers.pagina12 import (
    build_articles_output_dir,
    build_output_path,
    discover_urls_for_date,
    download_articles_from_url_file,
    parse_date_arg,
)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _data_path(relative_path: str) -> Path:
    return (_project_root() / relative_path).resolve()


def _parse_html_files(html_files: list[Path]) -> list[Document]:
    documents: list[Document] = []
    for index, html_path in enumerate(html_files, start=1):
        document = parse_html_file(html_path)
        if document is not None:
            documents.append(document)
            logger.info(f"Parse OK {index}/{len(html_files)} | path={html_path}")
        else:
            logger.info(f"Parse omitido {index}/{len(html_files)} | path={html_path}")

    return documents


def _parse_html_for_date(raw_date_dir: Path, parsed_date) -> list[Document]:
    html_files = sorted(raw_date_dir.glob(f"*-{parsed_date:%Y-%m-%d}.html"))
    logger.info(f"HTML encontrados para la fecha: {len(html_files)}")
    return _parse_html_files(html_files)


def _preview_chunks(chunks: list[Document], limit: int, content_chars: int) -> None:
    logger.info("=" * 72)
    logger.info(f"PREVIEW CHUNKS ENRIQUECIDOS | mostrando={min(limit, len(chunks))}/{len(chunks)}")
    for index, chunk in enumerate(chunks[:limit], start=1):
        preview_metadata = {
            "chunk_id": chunk.metadata.get("chunk_id"),
            "source_id": chunk.metadata.get("source_id"),
            "newspaper": chunk.metadata.get("newspaper"),
            "publication_date": chunk.metadata.get("publication_date"),
            "year": chunk.metadata.get("year"),
            "decade": chunk.metadata.get("decade"),
            "article_title": chunk.metadata.get("article_title"),
            "section": chunk.metadata.get("section"),
            "source_url": chunk.metadata.get("source_url"),
            "primary_location": chunk.metadata.get("primary_location"),
            "location_mentions": chunk.metadata.get("location_mentions"),
            "persons": chunk.metadata.get("persons"),
            "organizations": chunk.metadata.get("organizations"),
            "chunk_index": chunk.metadata.get("chunk_index"),
            "total_chunks": chunk.metadata.get("total_chunks"),
        }
        logger.info("-" * 72)
        logger.info(f"CHUNK {index}")
        logger.info("metadata=" + json.dumps(preview_metadata, ensure_ascii=False, indent=2))
        logger.info(f"contenido={chunk.page_content[:content_chars]}")
    logger.info("=" * 72)


def run_ingestion(
    force: bool = False,
    stage: str = "all",
    date: str | None = None,
    max_articles: int | None = None,
    preview_limit: int = 3,
    preview_chars: int = 800,
) -> list[Document]:
    logger.remove()
    logger.add(
        sys.stderr,
        level="INFO",
        format="<green>{time:HH:mm:ss}</green> | <level>{level:<8}</level> | {message}",
    )

    settings = get_settings()
    target_date = date or settings.scraper_target_date
    parsed_date = parse_date_arg(target_date)
    urls_path = build_output_path(target_date)
    raw_date_dir = build_articles_output_dir(target_date)
    parsed_output_path = (
        _data_path(settings.parsed_data_dir)
        / "pagina12"
        / str(parsed_date.year)
        / f"{parsed_date.month:02d}"
        / f"documents_{target_date}.json"
    )
    started_at = time.perf_counter()

    logger.info("=" * 72)
    logger.info("INGESTA HEMEROTECA - FASE 1")
    logger.info(f"source=pagina12 | stage={stage} | date={target_date} | force={force}")
    logger.info(f"urls_path={urls_path}")
    logger.info(f"raw_date_dir={raw_date_dir}")
    logger.info(f"parsed_output={parsed_output_path}")
    logger.info(f"qdrant={settings.qdrant_url} | collection={settings.qdrant_collection}")
    logger.info(f"embedding_model={settings.embedding_model}")
    logger.info("=" * 72)

    scraped_files: list[Path] | None = None
    if stage in {"scrape", "all", "preview"}:
        logger.info("[1/5] Scraping Pagina 12")
        urls_path = discover_urls_for_date(target_date)
        scraped_files = download_articles_from_url_file(
            urls_path=urls_path,
            force=force,
            max_articles=max_articles,
        )
        logger.info(f"[1/5] Scraping terminado | archivos HTML disponibles={len(scraped_files)}")
        if stage == "scrape":
            logger.info("Stage solicitado: scrape. Fin.")
            return []

    logger.info("[2/5] Parseando HTML con trafilatura")
    if scraped_files is not None:
        logger.info(f"Parse limitado a archivos del scraping actual: {len(scraped_files)}")
        documents = _parse_html_files(scraped_files)
    else:
        documents = _parse_html_for_date(raw_date_dir, parsed_date)
    write_parsed_documents(documents, parsed_output_path)
    logger.info(f"[2/5] Parse terminado | documentos validos={len(documents)}")
    if stage == "parse":
        logger.info("Stage solicitado: parse. Fin.")
        return documents

    logger.info("[3/5] Chunking en espanol")
    from app.ingestion.chunker import chunk_documents

    chunks = chunk_documents(documents)
    logger.info(f"[3/5] Chunking terminado | chunks={len(chunks)}")

    logger.info("[4/5] Enriqueciendo metadata con NER + gazetteer")
    from app.ingestion.metadata import enrich_metadata

    chunks = enrich_metadata(chunks)
    logger.info(f"[4/5] Metadata enriquecida | chunks={len(chunks)}")
    if stage == "preview":
        _preview_chunks(chunks, preview_limit, preview_chars)
        logger.info("Stage solicitado: preview. Fin sin indexar.")
        return chunks
    if stage == "enrich":
        logger.info("Stage solicitado: enrich. Fin.")
        return chunks

    logger.info("[5/5] Indexando en Qdrant")
    from app.retrieval.vector_store import index_documents

    indexed_count = index_documents(chunks, force=force)
    logger.info(f"[5/5] Indexacion terminada | puntos indexados={indexed_count}")
    logger.info(f"INGESTA COMPLETA | tiempo_total={time.perf_counter() - started_at:.1f}s")
    return chunks


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--stage", choices=("all", "scrape", "parse", "enrich", "preview", "index"), default="all")
    parser.add_argument("--date", default=None, help="Fecha Pagina/12 en formato DD-MM-YYYY.")
    parser.add_argument("--max-articles", type=int, default=None, help="Limite opcional para pruebas.")
    parser.add_argument("--preview-limit", type=int, default=3, help="Cantidad de chunks enriquecidos a imprimir.")
    parser.add_argument("--preview-chars", type=int, default=800, help="Caracteres de contenido a imprimir por chunk.")
    args = parser.parse_args()

    stage = args.stage
    if stage == "index":
        stage = "all"

    run_ingestion(
        force=args.force,
        stage=stage,
        date=args.date,
        max_articles=args.max_articles,
        preview_limit=args.preview_limit,
        preview_chars=args.preview_chars,
    )


if __name__ == "__main__":
    main()
