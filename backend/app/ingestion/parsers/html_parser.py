"""
HTML parser for newspaper articles using trafilatura.
"""

import argparse
import json
import warnings
from datetime import datetime
from pathlib import Path
from typing import Any

import trafilatura
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from langchain_core.documents import Document
from loguru import logger

MIN_TEXT_CHARS = 120
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
MOJIBAKE_MARKERS = ("Ã", "â€", "Â")
MOJIBAKE_REPLACEMENTS = {
    "â€œ": '"',
    "â€": '"',
    "â€\x9d": '"',
    "â€˜": "'",
    "â€™": "'",
    "â€“": "-",
    "â€”": "-",
    "â€¦": "...",
}


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _normalize_whitespace(text: str | None) -> str | None:
    if not text:
        return None
    normalized = " ".join(_repair_mojibake(text).split())
    return normalized or None


def _mojibake_score(text: str) -> int:
    return sum(text.count(marker) for marker in MOJIBAKE_MARKERS)


def _repair_mojibake(text: str) -> str:
    if not any(marker in text for marker in MOJIBAKE_MARKERS):
        return text

    preprocessed = text
    for broken, fixed in MOJIBAKE_REPLACEMENTS.items():
        preprocessed = preprocessed.replace(broken, fixed)

    best_text = preprocessed
    best_score = _mojibake_score(preprocessed)
    for encoding in ("latin-1", "cp1252"):
        try:
            candidate = preprocessed.encode(encoding).decode("utf-8")
        except UnicodeError:
            continue
        candidate_score = _mojibake_score(candidate)
        if candidate_score < best_score:
            best_text = candidate
            best_score = candidate_score
    return best_text


def _read_sidecar(html_path: Path) -> dict[str, Any]:
    sidecar = html_path.with_suffix(".json")
    if not sidecar.exists():
        return {}

    try:
        return json.loads(sidecar.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        logger.warning(f"Sidecar JSON invalido, se ignora | path={sidecar} | error={exc}")
        return {}


def _meta_content(soup: BeautifulSoup, *selectors: tuple[str, str]) -> str | None:
    for key, value in selectors:
        tag = soup.find("meta", attrs={key: value})
        if tag and tag.get("content"):
            return _normalize_whitespace(str(tag["content"]))
    return None


def _metadata_value(metadata: Any, attribute: str) -> str | None:
    return _normalize_whitespace(str(getattr(metadata, attribute, "") or ""))


def _extract_trafilatura_metadata(html_text: str, source_url: str | None) -> Any | None:
    try:
        return trafilatura.extract_metadata(html_text, default_url=source_url)
    except Exception as exc:
        logger.debug(f"No se pudo extraer metadata con trafilatura | error={exc}")
        return None


def _extract_text(html_text: str, source_url: str | None) -> str | None:
    try:
        extracted = trafilatura.extract(
            html_text,
            url=source_url,
            output_format="txt",
            include_comments=False,
            include_links=False,
            include_images=False,
            include_tables=False,
            favor_precision=True,
            deduplicate=True,
        )
    except Exception as exc:
        logger.warning(f"Trafilatura fallo al extraer texto | source_url={source_url} | error={exc}")
        return None

    return _normalize_whitespace(extracted)


def _extract_title(soup: BeautifulSoup, trafilatura_metadata: Any | None) -> str | None:
    heading = soup.find(["h1", "h2"])
    return (
        _metadata_value(trafilatura_metadata, "title")
        or _meta_content(soup, ("property", "og:title"), ("name", "twitter:title"))
        or _normalize_whitespace(heading.get_text(" ", strip=True) if heading else None)
        or _normalize_whitespace(soup.title.string if soup.title else None)
    )


def _extract_author(soup: BeautifulSoup, trafilatura_metadata: Any | None) -> str | None:
    return _metadata_value(trafilatura_metadata, "author") or _meta_content(
        soup,
        ("name", "author"),
        ("property", "article:author"),
    )


def _extract_section(soup: BeautifulSoup) -> str | None:
    return _meta_content(
        soup,
        ("property", "article:section"),
        ("name", "section"),
        ("name", "categoria"),
    ) or _extract_section_from_markup(soup)


def _extract_section_from_markup(soup: BeautifulSoup) -> str | None:
    for candidate in soup.find_all(attrs={"class": True}):
        classes = candidate.get("class") or []
        class_text = " ".join(classes if isinstance(classes, list) else [str(classes)]).lower()
        if any(token in class_text for token in ("section", "seccion", "category", "categoria")):
            return _normalize_whitespace(candidate.get_text(" ", strip=True))
    return None


def _coerce_publication_date(raw_value: str | None) -> str | None:
    if not raw_value:
        return None

    value = raw_value.strip()
    if len(value) >= 10:
        candidate = value[:10]
        try:
            return datetime.fromisoformat(candidate).date().isoformat()
        except ValueError:
            pass
    return value


def _extract_publication_date(
    soup: BeautifulSoup,
    trafilatura_metadata: Any | None,
    sidecar: dict[str, Any],
) -> str | None:
    raw_value = (
        sidecar.get("publication_date")
        or _metadata_value(trafilatura_metadata, "date")
        or _meta_content(
            soup,
            ("property", "article:published_time"),
            ("name", "date"),
            ("name", "pubdate"),
            ("itemprop", "datePublished"),
        )
    )
    return _coerce_publication_date(str(raw_value)) if raw_value else None


def _source_id(html_path: Path, sidecar: dict[str, Any]) -> str:
    if sidecar.get("source_id"):
        return str(sidecar["source_id"])

    try:
        return html_path.resolve().relative_to(_project_root()).as_posix()
    except ValueError:
        return html_path.resolve().as_posix()


def parse_html_file(html_path: Path, min_text_chars: int = MIN_TEXT_CHARS) -> Document | None:
    html_path = Path(html_path)
    html_text = html_path.read_text(encoding="utf-8", errors="ignore")
    sidecar = _read_sidecar(html_path)
    source_url = sidecar.get("source_url")
    source_url = str(source_url) if source_url else None

    extracted_text = _extract_text(html_text, source_url)
    if not extracted_text or len(extracted_text) < min_text_chars:
        logger.warning(
            f"HTML omitido por poco texto extraido | path={html_path} | chars={len(extracted_text or '')}"
        )
        return None

    soup = BeautifulSoup(html_text, "lxml")
    trafilatura_metadata = _extract_trafilatura_metadata(html_text, source_url)
    source_id = _source_id(html_path, sidecar)

    return Document(
        page_content=extracted_text,
        metadata={
            "chunk_id": f"{source_id}::chunk::0",
            "source_id": source_id,
            "newspaper": sidecar.get("newspaper", "el_dia"),
            "source_type": "html",
            "granularity": "article",
            "publication_date": _extract_publication_date(soup, trafilatura_metadata, sidecar),
            "article_title": sidecar.get("article_title") or _extract_title(soup, trafilatura_metadata),
            "section": sidecar.get("section") or _extract_section(soup),
            "author": sidecar.get("author") or _extract_author(soup, trafilatura_metadata),
            "page_number": None,
            "source_url": source_url,
            "source_file": str(html_path),
        },
    )


def parse_html_directory(directory: Path, min_text_chars: int = MIN_TEXT_CHARS) -> list[Document]:
    directory = Path(directory)
    if not directory.exists():
        logger.warning(f"Directorio HTML no existe: {directory}")
        return []

    html_files = sorted(directory.rglob("*.html"))
    logger.info(f"HTML encontrados para parsear: {len(html_files)}")

    documents: list[Document] = []
    for index, html_path in enumerate(html_files, start=1):
        document = parse_html_file(html_path, min_text_chars=min_text_chars)
        if document is not None:
            documents.append(document)
            logger.info(f"Parse OK {index}/{len(html_files)} | path={html_path}")
        else:
            logger.info(f"Parse omitido {index}/{len(html_files)} | path={html_path}")

    logger.info(f"Parse HTML terminado | documentos={len(documents)}")
    return documents


def _document_to_payload(document: Document) -> dict[str, Any]:
    return {
        "page_content": document.page_content,
        "metadata": document.metadata,
    }


def write_parsed_documents(documents: list[Document], output_path: Path) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "total_documents": len(documents),
        "documents": [_document_to_payload(document) for document in documents],
    }

    tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(output_path)
    logger.info(f"Parse persistido | documentos={len(documents)} | output={output_path}")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, required=True, help="Directorio con HTML raw.")
    parser.add_argument("--output", type=Path, required=True, help="Archivo JSON de documentos parseados.")
    parser.add_argument("--min-text-chars", type=int, default=MIN_TEXT_CHARS)
    args = parser.parse_args()

    documents = parse_html_directory(args.input_dir, min_text_chars=args.min_text_chars)
    write_parsed_documents(documents, args.output)


if __name__ == "__main__":
    main()
