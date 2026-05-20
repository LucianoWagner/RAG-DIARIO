from langchain_core.documents import Document

from app.ingestion import metadata
from app.ingestion.enrichers.scope_classifier import ScopeClassifier
from app.ingestion.enrichers.gazetteer import Gazetteer


class SequenceScopeClassifier:
    def __init__(self, results):
        self.results = list(results)
        self.index = 0

    def classify(self, _text, _metadata):
        result = self.results[self.index]
        self.index += 1
        return result


def test_enrich_metadata_argentina_por_seccion_sin_location_mentions(monkeypatch):
    monkeypatch.setattr(
        metadata,
        "extract_entities",
        lambda _text: {"persons": ["Alfonsin"], "organizations": ["UCR"]},
    )
    gazetteer = Gazetteer(
        city="Argentina",
        aliases=["Argentina", "Catamarca"],
        institutions=["UCR"],
        keywords=["argentina"],
        direct_argentina_sections=["elpais"],
    )
    chunk = Document(
        page_content=("Nota sobre Alfonsin y la interna radical. " * 8).strip(),
        metadata={
            "source_id": "nota",
            "publication_date": "2005-03-06",
            "section": "elpais",
            "newspaper": "pagina12",
        },
    )

    enriched = metadata.enrich_metadata(
        [chunk],
        gazetteer=gazetteer,
        scope_classifier=ScopeClassifier(embedder=None, llm_client=None, gazetteer=gazetteer),
    )[0]

    assert enriched.metadata["location_mentions"] == []
    assert enriched.metadata["primary_location"] is None
    assert enriched.metadata["country_scope"] == "argentina"
    assert enriched.metadata["scope_signals"] == ["seccion:elpais"]
    assert enriched.metadata["article_country_scope"] == "argentina"
    assert enriched.metadata["article_scope_signals"]


def test_enrich_metadata_elmundo_sin_senales_unknown(monkeypatch):
    monkeypatch.setattr(
        metadata,
        "extract_entities",
        lambda _text: {"persons": [], "organizations": []},
    )
    gazetteer = Gazetteer(
        city="Argentina",
        aliases=["Argentina"],
        institutions=["UCR"],
        keywords=["argentina"],
        direct_argentina_sections=["elpais"],
    )
    chunk = Document(
        page_content="Siria se retira en varias etapas.",
        metadata={
            "source_id": "nota",
            "publication_date": "2005-03-06",
            "section": "elmundo",
            "newspaper": "pagina12",
        },
    )

    enriched = metadata.enrich_metadata(
        [chunk],
        gazetteer=gazetteer,
        scope_classifier=ScopeClassifier(embedder=None, llm_client=None, gazetteer=gazetteer),
    )[0]

    assert enriched.metadata["country_scope"] == "unknown"
    assert enriched.metadata["scope_signals"] == []
    assert enriched.metadata["article_country_scope"] == "unknown"
    assert enriched.metadata["article_scope_signals"] == []


def test_article_scope_argentina_se_propaga_a_chunks_unknown(monkeypatch):
    monkeypatch.setattr(
        metadata,
        "extract_entities",
        lambda _text: {"persons": [], "organizations": []},
    )
    gazetteer = Gazetteer(
        city="Argentina",
        aliases=[],
        institutions=[],
        keywords=[],
        direct_argentina_sections=[],
    )
    chunks = [
        Document(
            page_content=("Texto con evidencia argentina. " * 8).strip(),
            metadata={"source_id": "nota-a", "publication_date": "2005-03-06", "chunk_index": 0},
        ),
        Document(
            page_content=("Texto conceptual sin evidencia propia. " * 8).strip(),
            metadata={"source_id": "nota-a", "publication_date": "2005-03-06", "chunk_index": 1},
        ),
    ]

    enriched = metadata.enrich_metadata(
        chunks,
        gazetteer=gazetteer,
        scope_classifier=SequenceScopeClassifier(
            [
                ("argentina", ["term:gobierno argentino"]),
                ("unknown", []),
            ]
        ),
    )

    assert enriched[0].metadata["country_scope"] == "argentina"
    assert enriched[1].metadata["country_scope"] == "unknown"
    assert enriched[0].metadata["article_country_scope"] == "argentina"
    assert enriched[1].metadata["article_country_scope"] == "argentina"


def test_article_scope_no_se_eleva_por_un_solo_llm_argentina(monkeypatch):
    monkeypatch.setattr(
        metadata,
        "extract_entities",
        lambda _text: {"persons": [], "organizations": []},
    )
    gazetteer = Gazetteer(
        city="Argentina",
        aliases=[],
        institutions=[],
        keywords=[],
        direct_argentina_sections=[],
    )
    chunks = [
        Document(
            page_content=("Texto ambiguo clasificado por LLM. " * 8).strip(),
            metadata={"source_id": "nota-b", "publication_date": "2005-03-06", "chunk_index": 0},
        ),
        Document(
            page_content=("Texto conceptual sin evidencia propia. " * 8).strip(),
            metadata={"source_id": "nota-b", "publication_date": "2005-03-06", "chunk_index": 1},
        ),
    ]

    enriched = metadata.enrich_metadata(
        chunks,
        gazetteer=gazetteer,
        scope_classifier=SequenceScopeClassifier(
            [
                ("argentina", ["llm_local:fake"]),
                ("unknown", []),
            ]
        ),
    )

    assert enriched[0].metadata["country_scope"] == "argentina"
    assert enriched[0].metadata["article_country_scope"] == "unknown"
    assert enriched[1].metadata["article_country_scope"] == "unknown"


def test_article_scope_international_si_no_hay_argentina(monkeypatch):
    monkeypatch.setattr(
        metadata,
        "extract_entities",
        lambda _text: {"persons": [], "organizations": []},
    )
    gazetteer = Gazetteer(
        city="Argentina",
        aliases=[],
        institutions=[],
        keywords=[],
        direct_argentina_sections=[],
    )
    chunks = [
        Document(
            page_content=("Texto sobre Austria y literatura europea. " * 8).strip(),
            metadata={"source_id": "nota-c", "publication_date": "2005-03-06", "chunk_index": 0},
        ),
        Document(
            page_content=("Texto conceptual sin evidencia propia. " * 8).strip(),
            metadata={"source_id": "nota-c", "publication_date": "2005-03-06", "chunk_index": 1},
        ),
    ]

    enriched = metadata.enrich_metadata(
        chunks,
        gazetteer=gazetteer,
        scope_classifier=SequenceScopeClassifier(
            [
                ("international", ["emb_int:0.900", "emb_margin:0.300"]),
                ("unknown", []),
            ]
        ),
    )

    assert enriched[0].metadata["article_country_scope"] == "international"
    assert enriched[1].metadata["article_country_scope"] == "international"
