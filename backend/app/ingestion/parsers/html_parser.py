"""
HTML parser for El Dia articles using trafilatura.
"""

import json
from pathlib import Path

from bs4 import BeautifulSoup
from langchain_core.documents import Document
import trafilatura
from loguru import logger


def _read_sidecar(html_path: Path) -> dict:
    sidecar = html_path.with_suffix(".json")
    if not sidecar.exists():
        return {}
    return json.loads(sidecar.read_text(encoding="utf-8"))


def _extract_title(html_text: str) -> str | None:
    soup = BeautifulSoup(html_text, "lxml")
    if soup.title and soup.title.string:
        return soup.title.string.strip()
    headline = soup.find(["h1", "h2"])
    return headline.get_text(" ", strip=True) if headline else None


def _extract_section(html_text: str) -> str | None:
    soup = BeautifulSoup(html_text, "lxml")
    candidate = soup.find(attrs={"class": lambda value: value and "section" in " ".join(value if isinstance(value, list) else [value]).lower()})
    if candidate:
        return candidate.get_text(" ", strip=True)
    return None


def parse_html_file(html_path: Path) -> Document | None:
    html_text = html_path.read_text(encoding="utf-8", errors="ignore")
    extracted = trafilatura.extract(
        html_text,
        output_format="txt",
        include_links=False,
        include_images=False,
        favor_precision=True,
    )
    if not extracted or len(extracted.strip()) < 120:
        logger.warning(f"HTML omitido por poco texto extraido: {html_path}")
        return None

    sidecar = _read_sidecar(html_path)
    publication_date = sidecar.get("publication_date")
    title = _extract_title(html_text)
    section = _extract_section(html_text)
    source_id = html_path.relative_to(html_path.parents[3]).as_posix()

    return Document(
        page_content=extracted.strip(),
        metadata={
            "chunk_id": f"{source_id}::chunk::0",
            "source_id": source_id,
            "newspaper": sidecar.get("newspaper", "el_dia"),
            "source_type": "html",
            "granularity": "article",
            "publication_date": publication_date,
            "article_title": title,
            "section": section,
            "author": None,
            "page_number": None,
            "source_url": sidecar.get("source_url"),
            "source_file": str(html_path),
        },
    )


def parse_html_directory(directory: Path) -> list[Document]:
    if not directory.exists():
        logger.warning(f"Directorio HTML no existe: {directory}")
        return []
    documents = []
    html_files = sorted(directory.rglob("*.html"))
    logger.info(f"HTML encontrados para parsear: {len(html_files)}")
    for index, html_path in enumerate(html_files, start=1):
        document = parse_html_file(html_path)
        if document is not None:
            documents.append(document)
            logger.info(f"[{index}/{len(html_files)}] Parse OK: {html_path.name}")
        else:
            logger.info(f"[{index}/{len(html_files)}] Parse omitido: {html_path.name}")
    logger.info(f"Parse HTML terminado | documentos={len(documents)}")
    return documents
