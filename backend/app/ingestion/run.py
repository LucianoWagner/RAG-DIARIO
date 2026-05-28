"""
Phase 1 ingestion pipeline for Pagina 12 HTML content.
"""

import argparse
import json
import sys
import time
from datetime import date as date_type
from datetime import timedelta
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


def _preview_metadata(chunk: Document) -> dict:
    return {
        "chunk_id": chunk.metadata.get("chunk_id"),
        "source_id": chunk.metadata.get("source_id"),
        "newspaper": chunk.metadata.get("newspaper"),
        "publication_date": chunk.metadata.get("publication_date"),
        "year": chunk.metadata.get("year"),
        "decade": chunk.metadata.get("decade"),
        "article_title": chunk.metadata.get("article_title"),
        "section": chunk.metadata.get("section"),
        "source_url": chunk.metadata.get("source_url"),
        "country_scope": chunk.metadata.get("country_scope"),
        "scope_signals": chunk.metadata.get("scope_signals"),
        "article_country_scope": chunk.metadata.get("article_country_scope"),
        "article_scope_signals": chunk.metadata.get("article_scope_signals"),
        "primary_location": chunk.metadata.get("primary_location"),
        "location_mentions": chunk.metadata.get("location_mentions"),
        "persons": chunk.metadata.get("persons"),
        "organizations": chunk.metadata.get("organizations"),
        "chunk_index": chunk.metadata.get("chunk_index"),
        "total_chunks": chunk.metadata.get("total_chunks"),
    }


def _log_preview_chunk(label: str, chunk: Document, content_chars: int) -> None:
    logger.info("-" * 72)
    logger.info(label)
    logger.info("metadata=" + json.dumps(_preview_metadata(chunk), ensure_ascii=False, indent=2))
    logger.info(f"contenido={chunk.page_content[:content_chars]}")


def _scope_signals(chunk: Document) -> list[str]:
    values = chunk.metadata.get("scope_signals") or []
    return [str(value) for value in values]


def _first_chunk_with_signal(chunks: list[Document], prefixes: tuple[str, ...]) -> Document | None:
    for chunk in chunks:
        if any(signal.startswith(prefixes) for signal in _scope_signals(chunk)):
            return chunk
    return None


def _preview_signal_cases(chunks: list[Document], content_chars: int) -> None:
    cases = [
        ("CASO CAPA 1 - SECCION", ("seccion:",)),
        ("CASO CAPA 1 - GAZETTEER/TERMINOS", ("gazetteer:", "term:", "institution:", "political_org:", "club:")),
        ("CASO CAPA 2 - EMBEDDINGS", ("emb_",)),
        ("CASO CAPA 3 - LLM", ("llm_",)),
    ]
    logger.info("=" * 72)
    logger.info("PREVIEW CASOS POR SENAL")
    for label, prefixes in cases:
        chunk = _first_chunk_with_signal(chunks, prefixes)
        if chunk is None:
            logger.info("-" * 72)
            logger.info(f"{label}: no encontrado en esta muestra")
            continue
        _log_preview_chunk(label, chunk, content_chars)
    logger.info("=" * 72)


def _preview_chunks(chunks: list[Document], limit: int, content_chars: int) -> None:
    logger.info("=" * 72)
    logger.info(f"PREVIEW CHUNKS ENRIQUECIDOS | mostrando={min(limit, len(chunks))}/{len(chunks)}")
    for index, chunk in enumerate(chunks[:limit], start=1):
        _log_preview_chunk(f"CHUNK {index}", chunk, content_chars)
    logger.info("=" * 72)
    _preview_signal_cases(chunks, content_chars)


def _iter_dates(start_date: date_type, end_date: date_type):
    current = start_date
    while current <= end_date:
        yield current
        current += timedelta(days=1)


def _parse_cli_date(raw_date: str) -> date_type:
    return parse_date_arg(raw_date)


def _filter_chunks_for_index(chunks: list[Document], index_scope: str) -> list[Document]:
    normalized = (index_scope or "argentina").strip().lower()
    if normalized == "all":
        return chunks

    allowed_scopes = {scope.strip() for scope in normalized.split(",") if scope.strip()}
    if not allowed_scopes:
        allowed_scopes = {"argentina"}

    filtered = [
        chunk
        for chunk in chunks
        if str(chunk.metadata.get("article_country_scope") or chunk.metadata.get("country_scope") or "").lower()
        in allowed_scopes
    ]
    logger.info(
        f"Filtro index_scope={index_scope} | chunks_indexables={len(filtered)}/{len(chunks)}"
    )
    return filtered


def run_ingestion(
    force: bool = False,
    reset_index: bool = False,
    stage: str = "all",
    date: str | None = None,
    max_articles: int | None = None,
    max_articles_per_section: int | None = None,
    sections: list[str] | None = None,
    index_scope: str = "argentina",
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
    logger.info(
        f"source=pagina12 | stage={stage} | date={target_date} | "
        f"force_download={force} | reset_index={reset_index}"
    )
    logger.info(
        f"sections={','.join(sections or ['*'])} | max_articles={max_articles} | "
        f"max_articles_per_section={max_articles_per_section}"
    )
    logger.info(f"index_scope={index_scope}")
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
            max_articles_per_section=max_articles_per_section,
            sections=sections,
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

    chunks_to_index = _filter_chunks_for_index(chunks, index_scope=index_scope)
    indexed_count = index_documents(chunks_to_index, force=reset_index)
    logger.info(f"[5/5] Indexacion terminada | puntos indexados={indexed_count}")
    logger.info(f"INGESTA COMPLETA | tiempo_total={time.perf_counter() - started_at:.1f}s")
    return chunks


def run_ingestion_range(
    start_date: date_type,
    end_date: date_type,
    force: bool = False,
    reset_index: bool = False,
    stage: str = "all",
    max_articles: int | None = None,
    max_articles_per_section: int | None = None,
    sections: list[str] | None = None,
    index_scope: str = "argentina",
    continue_on_error: bool = True,
    preview_limit: int = 3,
    preview_chars: int = 800,
) -> list[Document]:
    all_chunks: list[Document] = []
    total_days = (end_date - start_date).days + 1
    logger.info(
        f"INGESTA POR RANGO | desde={start_date:%d-%m-%Y} | "
        f"hasta={end_date:%d-%m-%Y} | dias={total_days}"
    )

    for day_index, current_date in enumerate(_iter_dates(start_date, end_date), start=1):
        raw_date = current_date.strftime("%d-%m-%Y")
        logger.info("=" * 72)
        logger.info(f"DIA {day_index}/{total_days} | date={raw_date}")
        try:
            chunks = run_ingestion(
                force=force,
                reset_index=reset_index and day_index == 1,
                stage=stage,
                date=raw_date,
                max_articles=max_articles,
                max_articles_per_section=max_articles_per_section,
                sections=sections,
                index_scope=index_scope,
                preview_limit=preview_limit,
                preview_chars=preview_chars,
            )
            all_chunks.extend(chunks)
        except Exception as exc:
            logger.exception(f"Fallo ingesta date={raw_date}: {exc}")
            if not continue_on_error:
                raise

    logger.info(
        f"INGESTA POR RANGO TERMINADA | desde={start_date:%d-%m-%Y} | "
        f"hasta={end_date:%d-%m-%Y} | chunks_totales={len(all_chunks)}"
    )
    return all_chunks


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--reset-index", action="store_true", help="Borra y recrea la coleccion Qdrant antes de indexar.")
    parser.add_argument("--stage", choices=("all", "scrape", "parse", "enrich", "preview", "index"), default="all")
    parser.add_argument("--date", default=None, help="Fecha Pagina/12 en formato DD-MM-YYYY.")
    parser.add_argument("--year", type=int, default=None, help="Procesa un año completo, ej: 2005.")
    parser.add_argument("--date-from", default=None, help="Fecha inicial en formato DD-MM-YYYY.")
    parser.add_argument("--date-to", default=None, help="Fecha final en formato DD-MM-YYYY.")
    parser.add_argument("--max-articles", type=int, default=None, help="Limite opcional para pruebas.")
    parser.add_argument(
        "--max-articles-per-section",
        type=int,
        default=None,
        help="Limite opcional de articulos por seccion para muestras balanceadas.",
    )
    parser.add_argument(
        "--sections",
        default=None,
        help="Lista separada por coma de secciones a procesar, ej: elmundo,deportes,suplementos/libros.",
    )
    parser.add_argument(
        "--index-scope",
        default="argentina",
        help="Scopes de articulo a indexar: argentina, unknown, international, argentina,unknown o all.",
    )
    parser.add_argument(
        "--stop-on-error",
        action="store_true",
        help="Detiene la ingesta por rango ante el primer error.",
    )
    parser.add_argument("--preview-limit", type=int, default=3, help="Cantidad de chunks enriquecidos a imprimir.")
    parser.add_argument("--preview-chars", type=int, default=800, help="Caracteres de contenido a imprimir por chunk.")
    args = parser.parse_args()

    stage = args.stage
    if stage == "index":
        stage = "all"

    sections = args.sections.split(",") if args.sections else None
    if args.year or args.date_from or args.date_to:
        if args.year:
            start_date = date_type(args.year, 1, 1)
            end_date = date_type(args.year, 12, 31)
        else:
            start_date = _parse_cli_date(args.date_from)
            end_date = _parse_cli_date(args.date_to)
        if args.date_from:
            start_date = _parse_cli_date(args.date_from)
        if args.date_to:
            end_date = _parse_cli_date(args.date_to)
        if end_date < start_date:
            raise ValueError("--date-to no puede ser anterior a --date-from")

        run_ingestion_range(
            start_date=start_date,
            end_date=end_date,
            force=args.force,
            reset_index=args.reset_index,
            stage=stage,
            max_articles=args.max_articles,
            max_articles_per_section=args.max_articles_per_section,
            sections=sections,
            index_scope=args.index_scope,
            continue_on_error=not args.stop_on_error,
            preview_limit=args.preview_limit,
            preview_chars=args.preview_chars,
        )
        return

    run_ingestion(
        force=args.force,
        reset_index=args.reset_index,
        stage=stage,
        date=args.date,
        max_articles=args.max_articles,
        max_articles_per_section=args.max_articles_per_section,
        sections=sections,
        index_scope=args.index_scope,
        preview_limit=args.preview_limit,
        preview_chars=args.preview_chars,
    )


if __name__ == "__main__":
    main()
