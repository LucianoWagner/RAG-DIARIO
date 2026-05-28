from datetime import date
from unittest.mock import patch

from langchain_core.documents import Document

from app.ingestion.run import _filter_chunks_for_index, _first_chunk_with_signal, run_ingestion_range


def test_filter_chunks_for_index_usa_article_country_scope():
    chunks = [
        Document(page_content="a", metadata={"article_country_scope": "argentina"}),
        Document(page_content="b", metadata={"article_country_scope": "unknown"}),
        Document(page_content="c", metadata={"article_country_scope": "international"}),
    ]

    filtered = _filter_chunks_for_index(chunks, "argentina")

    assert [chunk.page_content for chunk in filtered] == ["a"]


def test_filter_chunks_for_index_permite_unknown_o_all():
    chunks = [
        Document(page_content="a", metadata={"article_country_scope": "argentina"}),
        Document(page_content="b", metadata={"article_country_scope": "unknown"}),
        Document(page_content="c", metadata={"article_country_scope": "international"}),
    ]

    filtered = _filter_chunks_for_index(chunks, "argentina,unknown")
    all_chunks = _filter_chunks_for_index(chunks, "all")

    assert [chunk.page_content for chunk in filtered] == ["a", "b"]
    assert all_chunks == chunks


def test_first_chunk_with_signal_devuelve_primer_match():
    chunks = [
        Document(page_content="a", metadata={"scope_signals": ["seccion:elpais"]}),
        Document(page_content="b", metadata={"scope_signals": ["emb_arg:0.9"]}),
    ]

    assert _first_chunk_with_signal(chunks, ("emb_",)).page_content == "b"
    assert _first_chunk_with_signal(chunks, ("llm_",)) is None


@patch("app.ingestion.run.run_ingestion")
def test_run_ingestion_range_resetea_indice_solo_el_primer_dia(mock_run_ingestion):
    mock_run_ingestion.return_value = []

    run_ingestion_range(
        start_date=date(2005, 1, 1),
        end_date=date(2005, 1, 3),
        reset_index=True,
        stage="all",
    )

    reset_values = [call.kwargs["reset_index"] for call in mock_run_ingestion.call_args_list]
    assert reset_values == [True, False, False]


@patch("app.ingestion.run.run_ingestion")
def test_run_ingestion_range_pasa_config_preview(mock_run_ingestion):
    mock_run_ingestion.return_value = []

    run_ingestion_range(
        start_date=date(2005, 1, 1),
        end_date=date(2005, 1, 1),
        stage="preview",
        preview_limit=40,
        preview_chars=700,
    )

    assert mock_run_ingestion.call_args.kwargs["preview_limit"] == 40
    assert mock_run_ingestion.call_args.kwargs["preview_chars"] == 700


@patch("app.ingestion.run.run_ingestion")
def test_run_ingestion_range_pasa_max_articles_per_section(mock_run_ingestion):
    mock_run_ingestion.return_value = []

    run_ingestion_range(
        start_date=date(2005, 1, 1),
        end_date=date(2005, 1, 1),
        max_articles_per_section=2,
    )

    assert mock_run_ingestion.call_args.kwargs["max_articles_per_section"] == 2
