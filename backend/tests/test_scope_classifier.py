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
        institutions=["Banco Central", "H.I.J.O.S."],
        ambiguous_institutions=["Senado", "Congreso", "Diputados"],
        political_organizations=["UCR", "PO", "Union Civica Radical"],
        clubs=["River"],
        keywords=["estado argentino", "argentina"],
        contextual_terms=["gobierno nacional", "derechos humanos"],
        direct_argentina_sections=["elpais", "economia", "sociedad", "universidad", "suplementos/cash"],
        non_direct_sections=["elmundo", "espectaculos", "contratapa", "cultura", "psicologia", "plastica"],
    )


class FakeEmbedder:
    def __init__(self, chunk_vector: list[float]):
        self.chunk_vector = chunk_vector
        self.calls: list[str] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.calls.extend(texts)
        embeddings = []
        for text in texts:
            if text in ANCLAS_ARGENTINA:
                embeddings.append([1.0, 0.0, 0.0])
            elif text in ANCLAS_INTERNACIONAL:
                embeddings.append([0.0, 1.0, 0.0])
            elif text in ANCLAS_UNKNOWN:
                embeddings.append([0.0, 0.0, 1.0])
            else:
                embeddings.append(self.chunk_vector)
        return embeddings


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
        _long_text("El estado argentino anuncio nuevas medidas."),
        {"section": "cultura", "organizations": [], "location_mentions": []},
    )

    assert scope == "argentina"
    assert "term:estado argentino" in signals


def test_capa1_termino_contextual_solo_no_clasifica_argentina():
    classifier = ScopeClassifier(embedder=None, llm_client=None, gazetteer=_gazetteer())

    scope, signals = classifier.classify(
        _long_text("El gobierno nacional anuncio medidas sobre derechos humanos."),
        {"section": "elmundo", "organizations": [], "location_mentions": []},
    )

    assert scope == "unknown"
    assert "contextual_term:gobierno nacional" in signals
    assert "contextual_term:derechos humanos" in signals


def test_capa1_termino_contextual_con_senal_fuerte_clasifica_argentina():
    classifier = ScopeClassifier(embedder=None, llm_client=None, gazetteer=_gazetteer())

    scope, signals = classifier.classify(
        _long_text("Argentina debate una agenda de derechos humanos."),
        {"section": "cultura", "organizations": [], "location_mentions": ["Argentina"]},
    )

    assert scope == "argentina"
    assert "gazetteer:Argentina" in signals
    assert "contextual_term:derechos humanos" in signals


def test_capa1_org_argentina():
    classifier = ScopeClassifier(embedder=None, llm_client=None, gazetteer=_gazetteer())

    scope, signals = classifier.classify(
        _long_text("Partido decisivo en el campeonato."),
        {"section": "deportes", "organizations": ["River"], "location_mentions": []},
    )

    assert scope == "argentina"
    assert "club:River" in signals


def test_capa1_political_org_argentina():
    classifier = ScopeClassifier(embedder=None, llm_client=None, gazetteer=_gazetteer())

    scope, signals = classifier.classify(
        _long_text("La interna radical suma nuevos capitulos."),
        {"section": "cultura", "organizations": ["UCR"], "location_mentions": []},
    )

    assert scope == "argentina"
    assert "political_org:UCR" in signals


def test_capa1_location_mentions_revalida_gazetteer():
    classifier = ScopeClassifier(embedder=None, llm_client=None, gazetteer=_gazetteer())

    scope, signals = classifier.classify(
        _long_text("Una cronica sin senales locales claras."),
        {"section": "cultura", "organizations": [], "location_mentions": ["Montevideo"]},
    )

    assert scope == "unknown"
    assert "gazetteer:Montevideo" not in signals


def test_capa1_institution_en_texto_sin_ner():
    classifier = ScopeClassifier(embedder=None, llm_client=None, gazetteer=_gazetteer())

    scope, signals = classifier.classify(
        _long_text("El Banco Central anuncio nuevas medidas monetarias."),
        {"section": "cultura", "organizations": [], "location_mentions": []},
    )

    assert scope == "argentina"
    assert "institution:Banco Central" in signals


def test_capa1_hijos_comun_no_matchea_organizacion():
    classifier = ScopeClassifier(embedder=None, llm_client=None, gazetteer=_gazetteer())

    scope, signals = classifier.classify(
        _long_text("La cronica habla de padres e hijos sin organizaciones argentinas."),
        {"section": "contratapa", "organizations": [], "location_mentions": []},
    )

    assert scope == "unknown"
    assert "institution:HIJOS" not in signals
    assert "institution:H.I.J.O.S." not in signals


def test_capa1_hijos_punteado_es_senal_fuerte():
    classifier = ScopeClassifier(embedder=None, llm_client=None, gazetteer=_gazetteer())

    scope, signals = classifier.classify(
        _long_text("El comunicado de H.I.J.O.S. cuestiono la medida."),
        {"section": "contratapa", "organizations": [], "location_mentions": []},
    )

    assert scope == "argentina"
    assert "institution:H.I.J.O.S." in signals


def test_capa1_institution_ambigua_sola_no_clasifica_argentina():
    classifier = ScopeClassifier(embedder=None, llm_client=None, gazetteer=_gazetteer())

    scope, signals = classifier.classify(
        _long_text("El Senado critico el plan del gobierno de Estados Unidos."),
        {"section": "elmundo", "organizations": ["Senado"], "location_mentions": []},
    )

    assert scope == "unknown"
    assert "weak_institution:Senado" in signals


def test_capa1_articulo_bush_no_es_argentina_por_senado_congreso():
    classifier = ScopeClassifier(embedder=None, llm_client=None, gazetteer=_gazetteer())
    text = (
        "Bush ahora quiere presos de por vida sin proceso. "
        "El gobierno de Estados Unidos estudia modificar el estatuto de detencion. "
        "El Pentagono y la CIA pidieron a la Casa Blanca un nuevo estatuto. "
        "Influyentes lideres del Senado criticaron el plan. "
        "El Congreso norteamericano debatira fondos y grupos de derechos humanos repudiaron la medida."
    )

    scope, signals = classifier.classify(
        _long_text(text),
        {"section": "elmundo", "organizations": ["CIA", "Senado", "Congreso"], "location_mentions": []},
    )

    assert scope == "unknown"
    assert "weak_institution:Senado" in signals
    assert "weak_institution:Congreso" in signals
    assert "contextual_term:derechos humanos" in signals


def test_capa1_club_no_matchea_directo_en_texto():
    classifier = ScopeClassifier(embedder=None, llm_client=None, gazetteer=_gazetteer())

    scope, signals = classifier.classify(
        _long_text("La novela describe un river oscuro y una ciudad imaginaria."),
        {"section": "cultura", "organizations": [], "location_mentions": []},
    )

    assert scope == "unknown"
    assert "club:River" not in signals


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
    embedder = FakeEmbedder([1.0, 0.0, 0.0])
    classifier = ScopeClassifier(embedder=embedder, llm_client=None, embedding_threshold=0.15)
    metadata = {"section": "contratapa", "organizations": [], "location_mentions": []}

    scope, signals = classifier.classify(
        _long_text("Una nota ambigua sin senales lexicas."),
        metadata,
    )

    assert scope == "argentina"
    assert "emb_arg:1.000" in signals
    assert "emb_margin:1.000" in signals
    assert metadata["_index_vector"] == [1.0, 0.0, 0.0]
    assert not hasattr(embedder, "embed_query")


def test_capa2_usa_embed_documents_para_anclas_y_chunk():
    embedder = FakeEmbedder([0.0, 0.0, 1.0])
    classifier = ScopeClassifier(embedder=embedder, llm_client=None, embedding_threshold=0.15)
    metadata = {"section": "contratapa", "organizations": [], "location_mentions": []}

    classifier.classify(_long_text("Una nota conceptual."), metadata)

    assert set(ANCLAS_ARGENTINA).issubset(set(embedder.calls))
    assert set(ANCLAS_INTERNACIONAL).issubset(set(embedder.calls))
    assert set(ANCLAS_UNKNOWN).issubset(set(embedder.calls))
    assert any("Una nota conceptual" in call for call in embedder.calls)


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
