import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.ingestion.parsers import html_parser


def test_parse_html_file_extrae_texto_y_metadata(tmp_path, monkeypatch):
    html_path = tmp_path / "nota.html"
    html_path.write_text(
        """
        <html>
          <head>
            <meta property="article:section" content="La Ciudad">
            <meta property="article:published_time" content="2005-03-15T10:30:00-03:00">
          </head>
          <body>
            <h1>Titulo desde HTML</h1>
            <article>Texto de una nota sobre La Plata con contenido suficiente.</article>
          </body>
        </html>
        """,
        encoding="utf-8",
    )
    html_path.with_suffix(".json").write_text(
        json.dumps(
            {
                "source_url": "https://www.eldia.com/nota/2005-3-15-ejemplo",
                "publication_date": "2005-03-15",
                "newspaper": "el_dia",
            }
        ),
        encoding="utf-8",
    )
    extracted_text = "La Plata " + ("contenido historico " * 12)
    monkeypatch.setattr(html_parser.trafilatura, "extract", lambda *args, **kwargs: extracted_text)
    monkeypatch.setattr(
        html_parser.trafilatura,
        "extract_metadata",
        lambda *args, **kwargs: SimpleNamespace(title="Titulo desde trafilatura", author="Redaccion"),
    )

    document = html_parser.parse_html_file(html_path)

    assert document is not None
    assert document.page_content == " ".join(extracted_text.split())
    assert document.metadata["publication_date"] == "2005-03-15"
    assert document.metadata["article_title"] == "Titulo desde trafilatura"
    assert document.metadata["section"] == "La Ciudad"
    assert document.metadata["author"] == "Redaccion"
    assert document.metadata["source_url"] == "https://www.eldia.com/nota/2005-3-15-ejemplo"
    assert document.metadata["source_type"] == "html"
    assert document.metadata["granularity"] == "article"


def test_parse_html_file_omite_texto_insuficiente(tmp_path, monkeypatch):
    html_path = tmp_path / "nota.html"
    html_path.write_text("<html><body><h1>Nota corta</h1></body></html>", encoding="utf-8")
    monkeypatch.setattr(html_parser.trafilatura, "extract", lambda *args, **kwargs: "muy corto")

    document = html_parser.parse_html_file(html_path)

    assert document is None


def test_parse_html_directory_solo_devuelve_documentos_validos(tmp_path, monkeypatch):
    valid_path = tmp_path / "valid.html"
    invalid_path = tmp_path / "invalid.html"
    valid_path.write_text("<html><body><h1>Valida</h1></body></html>", encoding="utf-8")
    invalid_path.write_text("<html><body><h1>Invalida</h1></body></html>", encoding="utf-8")

    def fake_extract(html_text, *args, **kwargs):
        if "Valida" in html_text:
            return "La Plata " + ("contenido historico " * 12)
        return "corto"

    monkeypatch.setattr(html_parser.trafilatura, "extract", fake_extract)
    monkeypatch.setattr(
        html_parser.trafilatura,
        "extract_metadata",
        lambda *args, **kwargs: SimpleNamespace(title=None, author=None, date=None),
    )

    documents = html_parser.parse_html_directory(tmp_path)

    assert len(documents) == 1
    assert documents[0].metadata["source_file"] == str(valid_path)


def test_write_parsed_documents_genera_json(tmp_path):
    document = html_parser.Document(
        page_content="Texto parseado de prueba",
        metadata={
            "source_id": "data/raw/pagina12/2005/03/nota.html",
            "source_url": "https://www.pagina12.com.ar/diario/elpais/1-48573-2005-03-17.html",
            "publication_date": "2005-03-17",
            "newspaper": "pagina12",
        },
    )
    output_path = tmp_path / "parsed" / "pagina12" / "2005" / "03" / "documents.json"

    result = html_parser.write_parsed_documents([document], output_path)

    payload = json.loads(result.read_text(encoding="utf-8"))
    assert result == output_path
    assert payload["total_documents"] == 1
    assert payload["documents"][0]["page_content"] == "Texto parseado de prueba"
    assert payload["documents"][0]["metadata"]["publication_date"] == "2005-03-17"


def test_normalize_whitespace_repara_mojibake_comun():
    text = "La CÃ¡mara dijo â€œdelitos de lesa humanidadâ€."

    assert html_parser._normalize_whitespace(text) == 'La Cámara dijo "delitos de lesa humanidad".'


def test_parser_compatible_con_urls_pagina12_17_marzo_2005(tmp_path, monkeypatch):
    fixture_path = (
        Path(__file__).resolve().parents[2]
        / "data"
        / "raw"
        / "pagina12"
        / "2005"
        / "03"
        / "urls_17-03-2005.json"
    )
    if not fixture_path.exists():
        pytest.skip(f"No existe fixture local: {fixture_path}")

    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    urls = payload["urls"]
    assert payload["date"] == "17-03-2005"
    assert payload["source"] == "pagina12"
    assert payload["total_urls"] == len(urls)
    assert urls
    assert not [item["url"] for item in urls if "-2005-03-17.html" not in item["url"]]

    sample = urls[0]
    html_path = tmp_path / "pagina12" / "2005" / "03" / "nota.html"
    html_path.parent.mkdir(parents=True)
    html_path.write_text(
        f"""
        <html>
          <head>
            <meta property="article:section" content="El Pais">
            <meta property="article:published_time" content="2005-03-17T12:00:00-03:00">
          </head>
          <body>
            <h1>{sample["title"]}</h1>
            <article>{sample["snippet"]}. Texto de prueba para validar el parser.</article>
          </body>
        </html>
        """,
        encoding="utf-8",
    )
    html_path.with_suffix(".json").write_text(
        json.dumps(
            {
                "source_url": sample["url"],
                "publication_date": "2005-03-17",
                "newspaper": "pagina12",
                "article_title": sample["title"],
                "section": "El Pais",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    extracted_text = f"{sample['title']}. {sample['snippet']}. " + ("contenido historico " * 12)
    monkeypatch.setattr(html_parser.trafilatura, "extract", lambda *args, **kwargs: extracted_text)
    monkeypatch.setattr(
        html_parser.trafilatura,
        "extract_metadata",
        lambda *args, **kwargs: SimpleNamespace(title=None, author=None, date=None),
    )

    document = html_parser.parse_html_file(html_path)
    assert document is not None
    output_path = tmp_path / "parsed" / "pagina12" / "2005" / "03" / "test_urls_17-03-2005.json"
    html_parser.write_parsed_documents([document], output_path)
    parsed_payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert document.metadata["newspaper"] == "pagina12"
    assert document.metadata["publication_date"] == "2005-03-17"
    assert document.metadata["article_title"] == sample["title"]
    assert document.metadata["section"] == "El Pais"
    assert document.metadata["source_url"] == sample["url"]
    assert document.metadata["source_type"] == "html"
    assert document.metadata["granularity"] == "article"
    assert sample["title"] in document.page_content
    assert parsed_payload["total_documents"] == 1
    assert parsed_payload["documents"][0]["metadata"]["source_url"] == sample["url"]
