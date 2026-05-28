import json
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from app.ingestion.scrapers import pagina12


class DummyClient:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


def test_output_path_generado_correctamente(tmp_path):
    output_path = pagina12.build_output_path("15-03-2005", output_root=tmp_path)

    assert output_path == tmp_path / "2005" / "03" / "urls_15-03-2005.json"


def test_skip_si_archivo_existe(tmp_path):
    output_path = pagina12.build_output_path("15-03-2005", output_root=tmp_path)
    output_path.parent.mkdir(parents=True)
    output_path.write_text("{}", encoding="utf-8")

    with patch.object(pagina12, "_http_client") as http_client:
        result = pagina12.discover_urls_for_date("15-03-2005", output_root=tmp_path)

    assert result == output_path
    http_client.assert_not_called()


def test_parseo_fecha_invalida():
    with pytest.raises(ValueError):
        pagina12.parse_date_arg("32-13-2005")


def test_formato_json_output(tmp_path):
    output_path = tmp_path / "urls_15-03-2005.json"
    urls = [
        {
            "url": "https://www.pagina12.com.ar/diario/elpais/1-1-2005-03-15.html",
            "title": "Una nota sobre La Plata",
            "snippet": "Bajada disponible",
        }
    ]

    pagina12.save_output(
        output_path=output_path,
        raw_date="15-03-2005",
        mechanism_used="buscador",
        urls=urls,
        scraped_at=datetime(2026, 5, 15, 10, 30, 0),
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert set(payload) == {
        "date",
        "source",
        "mechanism_used",
        "total_urls",
        "scraped_at",
        "urls",
    }
    assert payload["date"] == "15-03-2005"
    assert payload["source"] == "pagina12"
    assert payload["mechanism_used"] == "buscador"
    assert payload["total_urls"] == 1
    assert payload["urls"] == urls


def test_edition_url_usa_estructura_real():
    parsed_date = pagina12.parse_date_arg("15-03-2005")

    assert (
        pagina12._edition_url(parsed_date)
        == "https://www.pagina12.com.ar/diario/secciones/index-2005-03-15.html"
    )


def test_extract_archive_article_urls_no_filtra_por_la_plata_y_agrega_seccion():
    html = """
    <html><body>
      <a href="/diario/universidad/10-1-2005-04-15.html">
        El cupo amparado
      </a>
      <p>CONFLICTO EN MEDICINA DE LA PLATA</p>
      <a href="/diario/deportes/8-2-2005-04-15.html">Otra nota</a>
      <p>Sin mencion geografica</p>
      <a href="/diario/secciones/index-2005-04-15.html">Indice</a>
    </body></html>
    """

    urls = pagina12._extract_archive_article_urls(
        html,
        "https://www.pagina12.com.ar/diario/secciones/index-2005-04-15.html",
        date(2005, 4, 15),
    )

    assert urls == [
        {
            "url": "https://www.pagina12.com.ar/diario/universidad/10-1-2005-04-15.html",
            "title": "El cupo amparado",
            "snippet": "El cupo amparado CONFLICTO EN MEDICINA DE LA PLATA",
            "section": "universidad",
        },
        {
            "url": "https://www.pagina12.com.ar/diario/deportes/8-2-2005-04-15.html",
            "title": "Otra nota",
            "snippet": "Otra nota Sin mencion geografica",
            "section": "deportes",
        }
    ]


def test_extract_all_archive_article_urls_sin_filtro():
    html = """
    <html><body>
      <a href="/diario/universidad/10-1-2005-03-15.html">Nota uno</a>
      <p>Texto cualquiera</p>
      <a href="/diario/deportes/8-2-2005-03-15.html">Nota dos</a>
      <a href="/diario/suplementos/cash/17-1771-2005-03-15.html">Nota cash</a>
      <a href="/diario/suplementos/libero/10-3-2005-03-14.html">Nota anterior</a>
      <a href="/diario/psicologia/index-2005-03-10.html">Indice suplemento anterior</a>
      <a href="/diario/elpais/index-2005-03-15.html">Indice del dia</a>
      <a href="/diario/secciones/index-2005-03-15.html">Indice</a>
    </body></html>
    """

    urls = pagina12._extract_all_archive_article_urls(
        html,
        "https://www.pagina12.com.ar/diario/secciones/index-2005-03-15.html",
        date(2005, 3, 15),
    )

    assert [item["url"] for item in urls] == [
        "https://www.pagina12.com.ar/diario/universidad/10-1-2005-03-15.html",
        "https://www.pagina12.com.ar/diario/deportes/8-2-2005-03-15.html",
        "https://www.pagina12.com.ar/diario/suplementos/cash/17-1771-2005-03-15.html",
    ]
    assert [item["section"] for item in urls] == ["universidad", "deportes", "suplementos/cash"]


def test_archive_article_url_exige_nota_y_fecha_objetivo():
    expected_date = date(2005, 3, 15)

    assert pagina12._is_archive_article_url(
        "https://www.pagina12.com.ar/diario/elpais/1-48483-2005-03-15.html",
        expected_date,
    )
    assert not pagina12._is_archive_article_url(
        "https://www.pagina12.com.ar/diario/elpais/1-48483-2005-03-14.html",
        expected_date,
    )
    assert not pagina12._is_archive_article_url(
        "https://www.pagina12.com.ar/diario/elpais/index-2005-03-15.html",
        expected_date,
    )
    assert not pagina12._is_archive_article_url(
        "https://www.pagina12.com.ar/diario/secciones/index-2005-03-15.html",
        expected_date,
    )


def test_download_articles_from_url_file_guarda_html_y_sidecar(tmp_path, monkeypatch):
    urls_path = tmp_path / "urls_17-03-2005.json"
    urls_path.write_text(
        json.dumps(
            {
                "date": "17-03-2005",
                "source": "pagina12",
                "mechanism_used": "edicion_del_dia",
                "total_urls": 1,
                "scraped_at": "2026-05-15T10:30:00",
                "urls": [
                    {
                        "url": "https://www.pagina12.com.ar/diario/elpais/1-48573-2005-03-17.html",
                        "title": "Llegaron vientos de cambio",
                        "snippet": "Bajada de prueba",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(pagina12, "_http_client", lambda: DummyClient())
    monkeypatch.setattr(pagina12, "verify_robots_allowed", lambda *args, **kwargs: None)
    monkeypatch.setattr(pagina12, "_get_text", lambda *args, **kwargs: "<html><body>Nota real</body></html>")
    monkeypatch.setattr(pagina12.time, "sleep", lambda *_args, **_kwargs: None)

    stored_files = pagina12.download_articles_from_url_file(
        urls_path,
        output_root=tmp_path / "raw" / "pagina12",
    )

    assert stored_files == [tmp_path / "raw" / "pagina12" / "2005" / "03" / "1-48573-2005-03-17.html"]
    assert stored_files[0].read_text(encoding="utf-8") == "<html><body>Nota real</body></html>"
    sidecar = json.loads(stored_files[0].with_suffix(".json").read_text(encoding="utf-8"))
    assert sidecar == {
        "source_url": "https://www.pagina12.com.ar/diario/elpais/1-48573-2005-03-17.html",
        "publication_date": "2005-03-17",
        "newspaper": "pagina12",
        "article_title": "Llegaron vientos de cambio",
        "section": "elpais",
        "snippet": "Bajada de prueba",
    }


def test_download_articles_from_url_file_salteia_existentes(tmp_path, monkeypatch):
    urls_path = tmp_path / "urls_17-03-2005.json"
    urls_path.write_text(
        json.dumps(
            {
                "date": "17-03-2005",
                "source": "pagina12",
                "urls": [
                    {
                        "url": "https://www.pagina12.com.ar/diario/elpais/1-48573-2005-03-17.html",
                        "title": "Llegaron vientos de cambio",
                        "snippet": None,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    output_root = tmp_path / "raw" / "pagina12"
    html_path = output_root / "2005" / "03" / "1-48573-2005-03-17.html"
    html_path.parent.mkdir(parents=True)
    html_path.write_text("existente", encoding="utf-8")
    html_path.with_suffix(".json").write_text("{}", encoding="utf-8")
    fetch = patch.object(pagina12, "_get_text")
    monkeypatch.setattr(pagina12, "_http_client", lambda: DummyClient())
    monkeypatch.setattr(pagina12, "verify_robots_allowed", lambda *args, **kwargs: None)

    with fetch as get_text:
        stored_files = pagina12.download_articles_from_url_file(urls_path, output_root=output_root)

    assert stored_files == [html_path]
    get_text.assert_not_called()


def test_limit_url_items_per_section_balancea_muestra():
    url_items = [
        {"url": "https://www.pagina12.com.ar/diario/elpais/1-1-2005-03-15.html", "section": "elpais"},
        {"url": "https://www.pagina12.com.ar/diario/elpais/1-2-2005-03-15.html", "section": "elpais"},
        {"url": "https://www.pagina12.com.ar/diario/elmundo/4-1-2005-03-15.html", "section": "elmundo"},
        {"url": "https://www.pagina12.com.ar/diario/elmundo/4-2-2005-03-15.html", "section": "elmundo"},
        {"url": "https://www.pagina12.com.ar/diario/espectaculos/6-1-2005-03-15.html", "section": "espectaculos"},
    ]

    limited = pagina12._limit_url_items_per_section(url_items, max_articles_per_section=1)

    assert [item["section"] for item in limited] == ["elpais", "elmundo", "espectaculos"]
