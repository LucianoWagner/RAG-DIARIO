"""
Limited El Dia scraper for Phase 1.
"""

import gzip
import html
import json
import re
import time
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

import httpx
from bs4 import BeautifulSoup
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import get_settings

_YEAR_URL_RE = re.compile(r"/(?P<year>19\d{2}|20\d{2})/")
_EDIS_DATE_RE = re.compile(r"/edis/(?P<date>(?P<year>19\d{2}|20\d{2})\d{4})(?:/|$)")
_NOTE_URL_RE = re.compile(r"/nota/(?P<year>19\d{2}|20\d{2})-(?P<month>\d{1,2})-(?P<day>\d{1,2})-")
_LOC_RE = re.compile(rb"<loc>\s*(.*?)\s*</loc>", re.IGNORECASE | re.DOTALL)
_SKIP_EXTENSIONS = (".gif", ".jpg", ".jpeg", ".png", ".webp", ".css", ".js", ".ico", ".pdf")


def _http_client() -> httpx.Client:
    settings = get_settings()
    return httpx.Client(
        headers={"User-Agent": settings.scraper_user_agent},
        timeout=settings.request_timeout_seconds,
        follow_redirects=True,
    )


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
def _fetch_bytes(client: httpx.Client, url: str) -> bytes:
    logger.debug(f"GET {url}")
    response = client.get(url)
    response.raise_for_status()
    content_type = response.headers.get("content-type", "unknown")
    logger.debug(f"OK {response.status_code} | bytes={len(response.content)} | content-type={content_type} | {url}")
    return response.content


def _maybe_decompress(raw_content: bytes, url: str) -> bytes:
    if url.endswith(".gz") or raw_content[:2] == b"\x1f\x8b":
        return gzip.decompress(raw_content)
    return raw_content


def _extract_sitemap_urls(root_xml: bytes) -> list[str]:
    try:
        root = ElementTree.fromstring(root_xml)
        namespace = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        sitemap_nodes = root.findall(".//sm:sitemap/sm:loc", namespace)
        if sitemap_nodes:
            return [node.text.strip() for node in sitemap_nodes if node.text]
        url_nodes = root.findall(".//sm:url/sm:loc", namespace)
        return [node.text.strip() for node in url_nodes if node.text]
    except ElementTree.ParseError as exc:
        # Some legacy El Dia sitemap responses contain malformed XML. The loc
        # extraction is still recoverable and avoids aborting the whole ingest.
        matches = _LOC_RE.findall(root_xml)
        if not matches:
            logger.warning(f"Sitemap omitido: XML invalido sin <loc> recuperables ({exc})")
            return []
        logger.warning(f"Sitemap XML invalido; recuperando {len(matches)} URLs por regex ({exc})")
        return [html.unescape(match.decode("utf-8", errors="ignore").strip()) for match in matches]


def _url_year(article_url: str) -> int | None:
    note_match = _NOTE_URL_RE.search(article_url)
    if note_match:
        return int(note_match.group("year"))
    edis_match = _EDIS_DATE_RE.search(article_url)
    if edis_match:
        return int(edis_match.group("year"))
    year_match = _YEAR_URL_RE.search(article_url)
    if year_match:
        return int(year_match.group("year"))
    return None


def _is_note_url(url: str, target_year: int) -> bool:
    parsed = urlparse(url)
    if parsed.netloc and parsed.netloc not in {"www.eldia.com", "eldia.com"}:
        return False
    match = _NOTE_URL_RE.search(parsed.path)
    if not match:
        return False
    return int(match.group("year")) == target_year


def _is_sitemap_url(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.lower()
    if path.endswith((".xml", ".xml.gz")):
        return True
    return "sitemap" in path or "news_" in path


def _collect_note_urls(urls: list[str], target_year: int) -> list[str]:
    return [url for url in urls if _is_note_url(url, target_year)]


def _iter_sitemap_article_urls(target_year: int) -> list[str]:
    settings = get_settings()
    article_urls: list[str] = []
    seed_urls = [
        settings.eldia_sitemap_url,
        urljoin(settings.eldia_base_url, "/news_1.xml"),
    ]

    with _http_client() as client:
        for seed_index, seed_url in enumerate(seed_urls, start=1):
            logger.info(f"Sitemap semilla {seed_index}/{len(seed_urls)}: {seed_url}")
            try:
                root_content = _maybe_decompress(_fetch_bytes(client, seed_url), seed_url)
            except Exception as exc:
                logger.warning(f"No se pudo leer sitemap semilla {seed_url}: {exc}")
                continue

            root_urls = _extract_sitemap_urls(root_content)
            direct_matches = _collect_note_urls(root_urls, target_year)
            article_urls.extend(direct_matches)
            logger.info(
                f"Sitemap semilla procesado | locs={len(root_urls)} | "
                f"notas_directas_{target_year}={len(direct_matches)}"
            )

            sitemap_urls = [url for url in root_urls if _is_sitemap_url(url)]
            logger.info(f"Sub-sitemaps detectados: {len(sitemap_urls)}")
            for index, sitemap_url in enumerate(sitemap_urls, start=1):
                logger.info(f"Sub-sitemap {index}/{len(sitemap_urls)}: {sitemap_url}")
                try:
                    raw_content = _maybe_decompress(_fetch_bytes(client, sitemap_url), sitemap_url)
                except Exception as exc:
                    logger.warning(f"No se pudo leer sub-sitemap {sitemap_url}: {exc}")
                    continue

                sitemap_locs = _extract_sitemap_urls(raw_content)
                matches = _collect_note_urls(sitemap_locs, target_year)
                article_urls.extend(matches)
                logger.info(
                    f"Sub-sitemap procesado | locs={len(sitemap_locs)} | "
                    f"matches_{target_year}={len(matches)}"
                )

    unique_urls = sorted(set(article_urls))
    logger.info(f"Sitemap discovery {target_year} | URLs candidatas={len(unique_urls)}")
    return unique_urls


def _search_discovery_urls(target_year: int) -> list[str]:
    settings = get_settings()
    terms = [term.strip() for term in settings.scraper_search_terms.split(",") if term.strip()]
    if not terms:
        terms = ["La Plata"]

    discovered: list[str] = []
    with _http_client() as client:
        for term in terms:
            for page_index in range(settings.scraper_max_search_pages):
                first = page_index * 10 + 1
                query = f"site:eldia.com/nota/{target_year}- {term}"
                search_url = "https://www.bing.com/search"
                logger.info(
                    f"Busqueda publica | term='{term}' | page={page_index + 1}/"
                    f"{settings.scraper_max_search_pages}"
                )
                try:
                    response = client.get(search_url, params={"q": query, "first": first})
                    response.raise_for_status()
                except Exception as exc:
                    logger.warning(f"No se pudo consultar Bing para '{term}': {exc}")
                    continue

                soup = BeautifulSoup(response.text, "lxml")
                before_count = len(discovered)
                for anchor in soup.find_all("a", href=True):
                    url = str(anchor["href"]).split("#", 1)[0]
                    if _is_note_url(url, target_year) and url not in discovered:
                        discovered.append(url)
                logger.info(
                    f"Busqueda publica | nuevos={len(discovered) - before_count} | "
                    f"total={len(discovered)}"
                )
                time.sleep(settings.scraper_rate_limit_seconds)

    return sorted(set(discovered))


def _iter_year_dates(year: int) -> list[date]:
    settings = get_settings()
    current = date(year, 1, 1)
    end = date(year + 1, 1, 1)
    dates: list[date] = []
    while current < end:
        dates.append(current)
        current += timedelta(days=1)
        if settings.scraper_max_days is not None and len(dates) >= settings.scraper_max_days:
            break
    return dates


def _is_probable_article_url(url: str, date_key: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.lower()
    if f"/edis/{date_key}/" not in path:
        return False
    if path.rstrip("/").endswith(f"/edis/{date_key}"):
        return False
    if path.endswith(_SKIP_EXTENSIONS):
        return False
    if "/fotos" in path or "/fotos_g" in path or "/imagenes" in path:
        return False
    return True


def _extract_archive_links(index_url: str, html_text: str, date_key: str) -> list[str]:
    soup = BeautifulSoup(html_text, "lxml")
    urls: list[str] = []
    for anchor in soup.find_all("a", href=True):
        absolute_url = urljoin(index_url, str(anchor["href"]))
        if _is_probable_article_url(absolute_url, date_key) and absolute_url not in urls:
            urls.append(absolute_url)
    return urls


def _iter_archive_article_urls(target_year: int) -> list[str]:
    settings = get_settings()
    candidate_urls: list[str] = []
    dates = _iter_year_dates(target_year)
    logger.info(
        f"Usando archivo historico /edis/ para {target_year} | "
        f"dias_a_recorrer={len(dates)}"
    )

    with _http_client() as client:
        for index, current_date in enumerate(dates, start=1):
            date_key = current_date.strftime("%Y%m%d")
            index_url = f"{settings.eldia_archive_base_url}/{date_key}/"
            logger.info(f"Archivo diario {index}/{len(dates)}: {index_url}")
            try:
                html_bytes = _fetch_bytes(client, index_url)
            except Exception as exc:
                logger.warning(f"No se pudo leer archivo diario {date_key}: {exc}")
                continue

            html_text = html_bytes.decode("utf-8", errors="ignore")
            article_urls = _extract_archive_links(index_url, html_text, date_key)
            logger.info(f"Archivo diario {date_key} | notas_detectadas={len(article_urls)}")
            candidate_urls.extend(article_urls)
            time.sleep(settings.scraper_rate_limit_seconds)

    unique_urls = sorted(set(candidate_urls))
    logger.info(f"Archivo historico {target_year} | URLs candidatas={len(unique_urls)}")
    return unique_urls


def _iter_article_urls(target_year: int) -> list[str]:
    settings = get_settings()
    mode = settings.scraper_discovery_mode.lower().strip()
    if mode not in {"auto", "archive", "search", "sitemap"}:
        logger.warning(f"SCRAPER_DISCOVERY_MODE invalido: {mode}. Usando auto.")
        mode = "auto"

    if mode in {"auto", "sitemap"}:
        sitemap_urls = _iter_sitemap_article_urls(target_year)
        if sitemap_urls or mode == "sitemap":
            return sitemap_urls
        logger.warning("Sitemap sin URLs de notas para el ano. Probando archivo historico.")

    if target_year <= 2017 and mode in {"auto", "archive"}:
        archive_urls = _iter_archive_article_urls(target_year)
        if archive_urls or mode == "archive":
            return archive_urls
        logger.warning("Archivo historico sin URLs. Probando busqueda publica.")

    if mode in {"auto", "search"}:
        search_urls = _search_discovery_urls(target_year)
        if search_urls or mode == "search":
            logger.info(f"Busqueda publica devolvio {len(search_urls)} URLs")
            return search_urls

    return []


def _target_path(base_dir: Path, article_url: str) -> Path:
    parsed = urlparse(article_url)
    parts = [part for part in parsed.path.split("/") if part]
    edis_match = _EDIS_DATE_RE.search(parsed.path)
    if edis_match:
        date_value = edis_match.group("date")
        month = date_value[4:6]
        slug = re.sub(r"[^a-zA-Z0-9-]+", "-", parsed.path.strip("/")) or date_value
    elif len(parts) >= 3:
        month = parts[1]
        slug = parts[-1]
    else:
        month = "00"
        slug = re.sub(r"[^a-zA-Z0-9-]+", "-", parsed.path.strip("/")) or "article"
    return base_dir / month / f"{slug}.html"


def _date_from_url(article_url: str) -> str | None:
    edis_match = _EDIS_DATE_RE.search(article_url)
    if not edis_match:
        return None
    date_value = edis_match.group("date")
    return f"{date_value[:4]}-{date_value[4:6]}-{date_value[6:8]}"


def _extract_embedded_date(html_text: str) -> str | None:
    soup = BeautifulSoup(html_text, "lxml")
    meta = soup.find("meta", attrs={"property": "article:published_time"}) or soup.find(
        "meta", attrs={"name": "date"}
    )
    if meta and meta.get("content"):
        return str(meta["content"])[:10]
    return None


def scrape_year(year: int, output_dir: Path) -> list[Path]:
    settings = get_settings()
    output_dir.mkdir(parents=True, exist_ok=True)
    stored_files: list[Path] = []

    logger.info(f"Scraper El Dia | year={year} | output_dir={output_dir}")
    candidate_urls = _iter_article_urls(year)
    logger.info(f"URLs candidatas finales: {len(candidate_urls)}")

    with _http_client() as client:
        for index, article_url in enumerate(candidate_urls, start=1):
            target_path = _target_path(output_dir, article_url)
            metadata_path = target_path.with_suffix(".json")
            if target_path.exists() and metadata_path.exists():
                logger.info(f"[{index}/{len(candidate_urls)}] Ya existe: {target_path}")
                stored_files.append(target_path)
                continue

            logger.info(f"[{index}/{len(candidate_urls)}] Descargando articulo: {article_url}")
            target_path.parent.mkdir(parents=True, exist_ok=True)
            html_bytes = _fetch_bytes(client, article_url)
            html_text = html_bytes.decode("utf-8", errors="ignore")
            target_path.write_text(html_text, encoding="utf-8")
            metadata_path.write_text(
                json.dumps(
                    {
                        "source_url": article_url,
                        "publication_date": _extract_embedded_date(html_text) or _date_from_url(article_url),
                        "newspaper": "el_dia",
                    },
                    ensure_ascii=True,
                    indent=2,
                ),
                encoding="utf-8",
            )
            logger.info(f"[{index}/{len(candidate_urls)}] Guardado: {target_path}")
            stored_files.append(target_path)
            time.sleep(settings.scraper_rate_limit_seconds)

    logger.info(f"Scraper El Dia terminado | archivos={len(stored_files)}")
    return stored_files
