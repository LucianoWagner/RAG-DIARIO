"""
Discover Pagina 12 article URLs and download article HTML for Phase 1.
"""

import argparse
import json
import logging
import re
import time
import warnings
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from tenacity import retry, stop_after_attempt, wait_exponential
from tenacity import retry_if_not_exception_type

LOGGER_NAME = "scrapers.pagina12"
USER_AGENT = "HemerotecaLaPlataAcademic/1.0 (proyecto-universitario)"
SEARCH_URL = "https://www.pagina12.com.ar/buscador/index.php"
ROBOTS_URL = "https://www.pagina12.com.ar/robots.txt"
BASE_URL = "https://www.pagina12.com.ar"
REQUEST_TIMEOUT_SECONDS = 30
RATE_LIMIT_SECONDS = 2
TARGET_PHRASE = "la plata"
ARCHIVE_URL_DATE_RE = re.compile(r"-(\d{4})-(\d{2})-(\d{2})\.html$")
SAFE_FILENAME_RE = re.compile(r"[^a-zA-Z0-9._-]+")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger(LOGGER_NAME)
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)


class RobotsDisallowedError(RuntimeError):
    """Raised when robots.txt explicitly disallows required scraper paths."""


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def parse_date_arg(raw_date: str) -> date:
    try:
        return datetime.strptime(raw_date, "%d-%m-%Y").date()
    except ValueError as exc:
        raise ValueError(f"Fecha invalida: {raw_date}. Usar formato DD-MM-YYYY.") from exc


def build_output_path(raw_date: str, output_root: Path | None = None) -> Path:
    parsed_date = parse_date_arg(raw_date)
    base_dir = output_root or (_project_root() / "data" / "raw" / "pagina12")
    return (
        base_dir
        / str(parsed_date.year)
        / f"{parsed_date.month:02d}"
        / f"urls_{raw_date}.json"
    )


def build_articles_output_dir(raw_date: str, output_root: Path | None = None) -> Path:
    parsed_date = parse_date_arg(raw_date)
    base_dir = output_root or (_project_root() / "backend" / "data" / "raw" / "pagina12")
    return base_dir / str(parsed_date.year) / f"{parsed_date.month:02d}"


def _edition_url(parsed_date: date) -> str:
    return f"{BASE_URL}/diario/secciones/index-{parsed_date:%Y-%m-%d}.html"


def _edition_url_candidates(parsed_date: date) -> list[str]:
    date_text = parsed_date.strftime("%d-%m-%Y")
    month_year = parsed_date.strftime("%m-%Y")
    return [
        f"{BASE_URL}/diario/secciones/index-{parsed_date:%Y-%m-%d}.html",
        f"{BASE_URL}/diario/principal/index-{parsed_date:%Y-%m-%d}.html",
        f"{BASE_URL}/{parsed_date.year}/{month_year}/dia/{date_text}.html",
    ]


def _http_client() -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT},
        timeout=REQUEST_TIMEOUT_SECONDS,
        follow_redirects=True,
    )


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=8),
    retry=retry_if_not_exception_type(httpx.HTTPStatusError),
)
def _get_text(client: httpx.Client, url: str, params: dict[str, str] | None = None) -> str:
    response = client.get(url, params=params)
    response.raise_for_status()
    logger.info("GET final_url=%s status=%s bytes=%s", response.url, response.status_code, len(response.text))
    return response.text


def _path_disallowed(robots_text: str, user_agent: str, path: str) -> bool:
    current_applies = False
    any_group_seen = False

    for raw_line in robots_text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue

        key, value = [part.strip() for part in line.split(":", 1)]
        key = key.lower()

        if key == "user-agent":
            any_group_seen = True
            value_lower = value.lower()
            current_applies = value_lower == "*" or value_lower in user_agent.lower()
            continue

        if key == "disallow" and current_applies and value:
            if path.startswith(value):
                return True

    return False if any_group_seen else False


def verify_robots_allowed(
    client: httpx.Client,
    parsed_date: date,
    extra_paths: list[str] | None = None,
) -> None:
    logger.info("Verificando robots.txt: %s", ROBOTS_URL)
    try:
        robots_text = _get_text(client, ROBOTS_URL)
    except Exception as exc:
        logger.warning("No se pudo verificar robots.txt. Continuando con cautela: %s", exc)
        return

    paths_to_check = [
        urlparse(SEARCH_URL).path,
        urlparse(_edition_url(parsed_date)).path,
    ]
    paths_to_check.extend(extra_paths or [])
    for path in paths_to_check:
        if _path_disallowed(robots_text, USER_AGENT, path):
            raise RobotsDisallowedError(f"robots.txt prohibe acceder a {path}")
    logger.info("robots.txt no prohibe las rutas requeridas")


def _contains_target_phrase(text: str | None) -> bool:
    return bool(text and TARGET_PHRASE in " ".join(text.lower().split()))


def _is_article_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.netloc and parsed.netloc not in {"www.pagina12.com.ar", "pagina12.com.ar"}:
        return False

    path = parsed.path
    if not path or path == "/":
        return False

    blocked_parts = (
        "/buscador",
        "/secciones",
        "/tags",
        "/usuarios",
        "/edicion-impresa",
        "/rss",
    )
    return not any(part in path for part in blocked_parts)


def _archive_article_date(url: str) -> date | None:
    path = urlparse(url).path
    filename = Path(path).name
    if filename.startswith("index-"):
        return None

    match = ARCHIVE_URL_DATE_RE.search(filename)
    if not match:
        return None

    year, month, day = (int(part) for part in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _is_archive_article_url(url: str, expected_date: date | None = None) -> bool:
    parsed = urlparse(url)
    path = parsed.path
    if not path.startswith("/diario/") or path.startswith(
        ("/diario/secciones/", "/diario/principal/")
    ):
        return False

    article_date = _archive_article_date(url)
    if article_date is None:
        return False

    return expected_date is None or article_date == expected_date


def _snippet_for_anchor(anchor) -> str | None:
    parent = anchor.find_parent(["article", "li", "div"]) or anchor.parent
    if parent is None:
        return None
    text = " ".join(parent.get_text(" ", strip=True).split())
    return text or None


def _nearby_archive_text(anchor) -> str:
    parts = [" ".join(anchor.get_text(" ", strip=True).split())]
    sibling = anchor.find_next_sibling()
    while sibling is not None and getattr(sibling, "name", None) not in {"a", "h1", "h2", "h3"}:
        if getattr(sibling, "get_text", None):
            text = " ".join(sibling.get_text(" ", strip=True).split())
            if text:
                parts.append(text)
        sibling = sibling.find_next_sibling()
    return " ".join(part for part in parts if part)


def _extract_candidate_urls(html_text: str, base_url: str, require_phrase: bool) -> list[dict]:
    soup = BeautifulSoup(html_text, "lxml")
    discovered: list[dict] = []
    seen_urls: set[str] = set()

    for anchor in soup.find_all("a", href=True):
        url = urljoin(base_url, str(anchor["href"])).split("#", 1)[0]
        if not _is_article_url(url) or url in seen_urls:
            continue

        title = " ".join(anchor.get_text(" ", strip=True).split()) or None
        snippet = _snippet_for_anchor(anchor)
        combined_text = " ".join(part for part in (title, snippet) if part)
        if require_phrase and not _contains_target_phrase(combined_text):
            continue

        seen_urls.add(url)
        discovered.append(
            {
                "url": url,
                "title": title,
                "snippet": snippet,
            }
        )

    return discovered


def _extract_archive_article_urls(html_text: str, base_url: str, expected_date: date) -> list[dict]:
    soup = BeautifulSoup(html_text, "lxml")
    discovered: list[dict] = []
    seen_urls: set[str] = set()

    for anchor in soup.find_all("a", href=True):
        url = urljoin(base_url, str(anchor["href"])).split("#", 1)[0]
        if not _is_archive_article_url(url, expected_date) or url in seen_urls:
            continue

        title = " ".join(anchor.get_text(" ", strip=True).split()) or None
        snippet = _nearby_archive_text(anchor) or None
        combined_text = snippet or title or ""
        if not _contains_target_phrase(combined_text):
            continue

        seen_urls.add(url)
        discovered.append({"url": url, "title": title, "snippet": snippet})

    return discovered


def _extract_all_archive_article_urls(html_text: str, base_url: str, expected_date: date) -> list[dict]:
    soup = BeautifulSoup(html_text, "lxml")
    discovered: list[dict] = []
    seen_urls: set[str] = set()

    for anchor in soup.find_all("a", href=True):
        url = urljoin(base_url, str(anchor["href"])).split("#", 1)[0]
        if not _is_archive_article_url(url, expected_date) or url in seen_urls:
            continue

        title = " ".join(anchor.get_text(" ", strip=True).split()) or None
        snippet = _nearby_archive_text(anchor) or _snippet_for_anchor(anchor)
        seen_urls.add(url)
        discovered.append({"url": url, "title": title, "snippet": snippet})

    return discovered


def discover_with_search(client: httpx.Client, raw_date: str) -> list[dict]:
    logger.info("Intentando mecanismo: buscador")
    parameter_sets = [
        {"q": "La Plata"},
        {"q": "La Plata", "fecha": raw_date},
        {"q": '"La Plata"', "fecha": raw_date},
        {"q": "La Plata", "date": raw_date},
        {"q": "La Plata", "desde": raw_date, "hasta": raw_date},
    ]

    for params in parameter_sets:
        try:
            html_text = _get_text(client, SEARCH_URL, params=params)
        except Exception as exc:
            logger.warning("Buscador fallo con params=%s: %s", params, exc)
            continue

        logger.info("HTML buscador recibido | chars=%s | params=%s", len(html_text), params)
        urls = _extract_candidate_urls(html_text, SEARCH_URL, require_phrase=False)
        if urls:
            logger.info("Se encontraron %s URLs con mencion de 'La Plata'", len(urls))
            return urls

        time.sleep(RATE_LIMIT_SECONDS)

    return []


def discover_with_daily_edition(client: httpx.Client, parsed_date: date) -> list[dict]:
    logger.info("Intentando mecanismo: edicion_del_dia")
    unfiltered_urls: list[dict] = []
    for edition_url in _edition_url_candidates(parsed_date):
        try:
            html_text = _get_text(client, edition_url)
        except httpx.HTTPStatusError as exc:
            logger.warning("Edicion no disponible url=%s status=%s", edition_url, exc.response.status_code)
            continue

        logger.info("HTML edicion recibido | chars=%s | url=%s", len(html_text), edition_url)
        urls = _extract_archive_article_urls(html_text, edition_url, parsed_date)
        logger.info("Se encontraron %s URLs con mencion de 'La Plata'", len(urls))
        if urls:
            return urls

        all_urls = _extract_all_archive_article_urls(html_text, edition_url, parsed_date)
        logger.info("URLs de notas sin filtro en esta edicion: %s", len(all_urls))
        if all_urls and not unfiltered_urls:
            unfiltered_urls = all_urls

    if unfiltered_urls:
        logger.warning(
            "No se encontraron menciones cercanas de 'La Plata'; "
            "se guardan URLs sin filtro para no bloquear la fase."
        )
        return unfiltered_urls

    logger.warning("No se encontraron URLs para la fecha en las ediciones candidatas")
    return []


def save_output(
    output_path: Path,
    raw_date: str,
    mechanism_used: str,
    urls: list[dict],
    scraped_at: datetime | None = None,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "date": raw_date,
        "source": "pagina12",
        "mechanism_used": mechanism_used,
        "total_urls": len(urls),
        "scraped_at": (scraped_at or datetime.now()).isoformat(timespec="seconds"),
        "urls": urls,
    }

    tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(output_path)
    logger.info("Output guardado en %s", output_path)


def _safe_article_filename(article_url: str) -> str:
    filename = Path(urlparse(article_url).path).name
    if not filename:
        filename = SAFE_FILENAME_RE.sub("-", article_url).strip("-")
    if not filename.endswith(".html"):
        filename = f"{filename}.html"
    return SAFE_FILENAME_RE.sub("-", filename)


def _article_section(article_url: str) -> str | None:
    parts = [part for part in urlparse(article_url).path.split("/") if part]
    if len(parts) >= 2 and parts[0] == "diario":
        return parts[1]
    return None


def _article_output_path(output_dir: Path, article_url: str) -> Path:
    return output_dir / _safe_article_filename(article_url)


def _write_text_atomic(output_path: Path, content: str) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    tmp_path.write_text(content, encoding="utf-8")
    tmp_path.replace(output_path)


def _write_json_atomic(output_path: Path, payload: dict) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(output_path)


def _load_urls_payload(urls_path: Path) -> dict:
    payload = json.loads(urls_path.read_text(encoding="utf-8"))
    if payload.get("source") != "pagina12":
        raise ValueError(f"Archivo de URLs no corresponde a pagina12: {urls_path}")
    if not isinstance(payload.get("urls"), list):
        raise ValueError(f"Archivo de URLs invalido, falta lista 'urls': {urls_path}")
    return payload


def download_articles_from_url_file(
    urls_path: Path,
    output_root: Path | None = None,
    force: bool = False,
    max_articles: int | None = None,
) -> list[Path]:
    urls_path = Path(urls_path)
    payload = _load_urls_payload(urls_path)
    raw_date = str(payload["date"])
    parsed_date = parse_date_arg(raw_date)
    output_dir = build_articles_output_dir(raw_date, output_root=output_root)
    url_items = payload["urls"][:max_articles] if max_articles is not None else payload["urls"]
    stored_files: list[Path] = []

    logger.info(
        "Descargando HTML de notas Pagina 12 | fecha=%s | urls=%s | output_dir=%s",
        raw_date,
        len(url_items),
        output_dir,
    )
    if not url_items:
        return []

    first_url = str(url_items[0].get("url", ""))
    with _http_client() as client:
        verify_robots_allowed(client, parsed_date, extra_paths=[urlparse(first_url).path])
        for index, item in enumerate(url_items, start=1):
            article_url = str(item.get("url", "")).strip()
            if not article_url:
                logger.warning("[%s/%s] URL vacia, se omite", index, len(url_items))
                continue
            if not _is_archive_article_url(article_url, parsed_date):
                logger.warning("[%s/%s] URL fuera de fecha o no es nota: %s", index, len(url_items), article_url)
                continue

            html_path = _article_output_path(output_dir, article_url)
            sidecar_path = html_path.with_suffix(".json")
            if html_path.exists() and sidecar_path.exists() and not force:
                logger.info("[%s/%s] Ya existe HTML: %s", index, len(url_items), html_path)
                stored_files.append(html_path)
                continue

            try:
                logger.info("[%s/%s] Descargando articulo: %s", index, len(url_items), article_url)
                html_text = _get_text(client, article_url)
            except Exception as exc:
                logger.warning("[%s/%s] No se pudo descargar %s: %s", index, len(url_items), article_url, exc)
                continue

            _write_text_atomic(html_path, html_text)
            _write_json_atomic(
                sidecar_path,
                {
                    "source_url": article_url,
                    "publication_date": parsed_date.isoformat(),
                    "newspaper": "pagina12",
                    "article_title": item.get("title"),
                    "section": _article_section(article_url),
                    "snippet": item.get("snippet"),
                },
            )
            stored_files.append(html_path)
            logger.info("[%s/%s] Guardado: %s", index, len(url_items), html_path)
            time.sleep(RATE_LIMIT_SECONDS)

    logger.info("Descarga HTML Pagina 12 terminada | archivos=%s", len(stored_files))
    return stored_files


def discover_urls_for_date(raw_date: str, output_root: Path | None = None) -> Path:
    parsed_date = parse_date_arg(raw_date)
    output_path = build_output_path(raw_date, output_root=output_root)

    logger.info("Iniciando descubrimiento de URLs para fecha: %s", raw_date)
    if output_path.exists():
        logger.info("Ya existe %s, salteando.", output_path)
        return output_path

    try:
        with _http_client() as client:
            verify_robots_allowed(client, parsed_date)
            urls = discover_with_search(client, raw_date)
            mechanism_used = "buscador"

            if not urls:
                time.sleep(RATE_LIMIT_SECONDS)
                urls = discover_with_daily_edition(client, parsed_date)
                mechanism_used = "edicion_del_dia"

        save_output(output_path, raw_date, mechanism_used, urls)
        logger.info(
            "Resumen: fecha=%s mecanismo=%s total_urls=%s output=%s",
            raw_date,
            mechanism_used,
            len(urls),
            output_path,
        )
        return output_path
    except Exception as exc:
        logger.error("Error al descubrir URLs: %s", exc)
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="Fecha en formato DD-MM-YYYY")
    parser.add_argument(
        "--download",
        action="store_true",
        help="Descarga HTML de notas desde el JSON de URLs de la fecha.",
    )
    parser.add_argument(
        "--urls-path",
        type=Path,
        default=None,
        help="Path opcional al urls_DD-MM-YYYY.json. Si no se indica, usa data/raw/pagina12/YYYY/MM/.",
    )
    parser.add_argument("--force", action="store_true", help="Redescarga HTML aunque ya exista.")
    parser.add_argument("--max-articles", type=int, default=None, help="Limite opcional de notas a descargar.")
    args = parser.parse_args()
    urls_path = args.urls_path or discover_urls_for_date(args.date)
    if args.download:
        download_articles_from_url_file(
            urls_path=urls_path,
            force=args.force,
            max_articles=args.max_articles,
        )


if __name__ == "__main__":
    main()
