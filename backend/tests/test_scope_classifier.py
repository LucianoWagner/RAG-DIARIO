from app.ingestion.enrichers.gazetteer import Gazetteer
from app.ingestion.enrichers.scope_classifier import (
    ANCLAS_ARGENTINA,
    ANCLAS_INTERNACIONAL,
    ANCLAS_UNKNOWN,
    PROMPT_TEMPLATE,
    ScopeClassifier,
)


def _long_text(text: str) -> str:
    return (text + " ") * 30


def _gazetteer() -> Gazetteer:
    return Gazetteer(
        city="Argentina",
        aliases=["Argentina", "Buenos Aires"],
        institutions=["UCR", "River", "Banco Central", "PO"],
        keywords=["gobierno nacional", "argentina"],
        direct_argentina_sections=["elpais", "economia", "sociedad", "universidad", "suplementos/cash"],
    )


class FakeEmbedder:
    def __init__(self, chunk_vector: list[float]):
        self.chunk_vector = chunk_vector
        self.calls: list[str] = []

    def embed_query(self, query: str) -> list[float]:
        self.calls.append(query)
        if query in ANCLAS_ARGENTINA:
            return [1.0, 0.0, 0.0]
        if query in ANCLAS_INTERNACIONAL:
            return [0.0, 1.0, 0.0]
        if query in ANCLAS_UNKNOWN:
            return [0.0, 0.0, 1.0]
        return self.chunk_vector


class FakeLLM:
    model = "fake-local-llm"

    def __init__(self, response: str):
        self.response = response
        self.calls = 0

    def generate(self, prompt: str) -> str:
        self.calls += 1
        return self.response


def test_capa1_seccion_argentina_directa():
    classifier = ScopeClassifier(
        embedder=FakeEmbedder([0.0, 1.0]),
        llm_client=FakeLLM("international"),
        gazetteer=_gazetteer(),
    )

    scope, signals = classifier.classify(
        _long_text("Nota sobre Alfonsin y la interna radical."),
        {"section": "elpais", "organizations": [], "location_mentions": []},
    )

    assert scope == "argentina"
    assert signals == ["seccion:elpais"]


def test_capa1_termino_en_texto():
    classifier = ScopeClassifier(embedder=None, llm_client=None, gazetteer=_gazetteer())

    scope, signals = classifier.classify(
        _long_text("El gobierno nacional anuncio nuevas medidas."),
        {"section": "cultura", "organizations": [], "location_mentions": []},
    )

    assert scope == "argentina"
    assert "term:gobierno nacional" in signals


def test_capa1_org_argentina():
    classifier = ScopeClassifier(embedder=None, llm_client=None, gazetteer=_gazetteer())

    scope, signals = classifier.classify(
        _long_text("Partido decisivo en el campeonato."),
        {"section": "deportes", "organizations": ["River"], "location_mentions": []},
    )

    assert scope == "argentina"
    assert "institution:River" in signals


def test_capa1_sigla_corta_no_matchea_substring():
    classifier = ScopeClassifier(embedder=None, llm_client=None, gazetteer=_gazetteer())

    scope, signals = classifier.classify(
        _long_text("La nota menciona al Partido Popular europeo sin vinculo local."),
        {"section": "suplementos/libros", "organizations": ["Partido Popular"], "location_mentions": []},
    )

    assert scope == "unknown"
    assert "institution:PO" not in signals


def test_capa1_elmundo_sin_senales():
    classifier = ScopeClassifier(embedder=None, llm_client=None, gazetteer=_gazetteer())

    scope, signals = classifier.classify(
        _long_text("Siria se retira en varias etapas."),
        {"section": "elmundo", "organizations": [], "location_mentions": []},
    )

    assert scope == "unknown"
    assert signals == ["llm_skipped:disabled"]


def test_capa1_chunk_corto():
    classifier = ScopeClassifier(embedder=FakeEmbedder([1.0, 0.0]), llm_client=FakeLLM("argentina"))

    scope, signals = classifier.classify(
        "Texto demasiado corto.",
        {"section": "cultura", "organizations": ["River"], "location_mentions": ["Buenos Aires"]},
    )

    assert scope == "unknown"
    assert signals == []


def test_capa2_argentina_gana_score_ternario():
    classifier = ScopeClassifier(embedder=FakeEmbedder([1.0, 0.0, 0.0]), llm_client=None, embedding_threshold=0.15)

    scope, signals = classifier.classify(
        _long_text("Una nota ambigua sin senales lexicas."),
        {"section": "contratapa", "organizations": [], "location_mentions": []},
    )

    assert scope == "argentina"
    assert "emb_arg:1.000" in signals
    assert "emb_margin:1.000" in signals


def test_capa2_international_gana_score_ternario():
    classifier = ScopeClassifier(embedder=FakeEmbedder([0.0, 1.0, 0.0]), llm_client=None, embedding_threshold=0.15)

    scope, signals = classifier.classify(
        _long_text("Una nota ambigua sin senales lexicas."),
        {"section": "elmundo", "organizations": [], "location_mentions": []},
    )

    assert scope == "international"
    assert "emb_int:1.000" in signals
    assert "emb_margin:1.000" in signals


def test_capa2_unknown_gana_y_no_llama_llm():
    llm = FakeLLM("argentina")
    classifier = ScopeClassifier(embedder=FakeEmbedder([0.0, 0.0, 1.0]), llm_client=llm, embedding_threshold=0.15)

    scope, signals = classifier.classify(
        _long_text("Una nota conceptual sin senales nacionales."),
        {"section": "suplementos/libros", "organizations": [], "location_mentions": []},
    )

    assert scope == "unknown"
    assert "emb_unknown:1.000" in signals
    assert "emb_margin:1.000" in signals
    assert llm.calls == 0


def test_capa2_zona_gris_pasa_a_capa3():
    llm = FakeLLM("international")
    classifier = ScopeClassifier(embedder=FakeEmbedder([1.0, 1.0, 1.0]), llm_client=llm, embedding_threshold=0.15)

    scope, signals = classifier.classify(
        _long_text("Una nota ambigua sin senales lexicas ni contexto claro."),
        {"section": "contratapa", "organizations": [], "location_mentions": []},
    )

    assert scope == "international"
    assert "emb_margin:0.000" in signals
    assert "llm_local:fake-local-llm:international" in signals
    assert llm.calls == 1


def test_capa3_respuesta_valida_argentina():
    llm = FakeLLM("argentina")
    classifier = ScopeClassifier(embedder=FakeEmbedder([1.0, 1.0, 1.0]), llm_client=llm, embedding_threshold=0.15)

    scope, signals = classifier.classify(
        _long_text("Una nota ambigua sin senales lexicas ni contexto claro."),
        {"section": "contratapa", "organizations": [], "location_mentions": []},
    )

    assert scope == "argentina"
    assert "emb_margin:0.000" in signals
    assert "llm_local:fake-local-llm:argentina" in signals


def test_capa3_respuesta_invalida():
    classifier = ScopeClassifier(
        embedder=FakeEmbedder([1.0, 1.0, 1.0]),
        llm_client=FakeLLM("quizas"),
        embedding_threshold=0.15,
    )

    scope, signals = classifier.classify(
        _long_text("Una nota ambigua sin senales lexicas ni contexto claro."),
        {"section": "contratapa", "organizations": [], "location_mentions": []},
    )

    assert scope == "unknown"
    assert "emb_margin:0.000" in signals
    assert "llm_local:fake-local-llm:unknown" in signals


def test_capa3_deshabilitado_devuelve_unknown():
    classifier = ScopeClassifier(embedder=FakeEmbedder([1.0, 1.0, 1.0]), llm_client=None, embedding_threshold=0.15)

    scope, signals = classifier.classify(
        _long_text("Una nota ambigua sin senales lexicas ni contexto claro."),
        {"section": "contratapa", "organizations": [], "location_mentions": []},
    )

    assert scope == "unknown"
    assert "emb_margin:0.000" in signals
    assert "llm_skipped:disabled" in signals


def test_cache_llm_no_repite_llamada():
    llm = FakeLLM("argentina")
    classifier = ScopeClassifier(embedder=FakeEmbedder([1.0, 1.0, 1.0]), llm_client=llm, embedding_threshold=0.15)
    text = _long_text("Una nota ambigua sin senales lexicas ni contexto claro.")
    metadata = {"section": "contratapa", "organizations": [], "location_mentions": []}

    assert classifier.classify(text, metadata)[0] == "argentina"
    assert classifier.classify(text, metadata)[0] == "argentina"
    assert llm.calls == 1


def test_prompt_few_shot_contiene_casos_estrictos():
    assert "Elfriede Jelinek" in PROMPT_TEMPLATE
    assert "Respuesta: international" in PROMPT_TEMPLATE
    assert "sexualidad" in PROMPT_TEMPLATE
    assert "Respuesta: unknown" in PROMPT_TEMPLATE
    assert "Alfonsin" in PROMPT_TEMPLATE
    assert "Respuesta: argentina" in PROMPT_TEMPLATE
