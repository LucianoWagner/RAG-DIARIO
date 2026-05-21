from datetime import date
from unittest.mock import patch

from langchain_core.documents import Document

from app.ingestion.run import _filter_chunks_for_index, run_ingestion_range


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
