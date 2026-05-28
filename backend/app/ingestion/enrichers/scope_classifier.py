"""
Country-scope classifier for Pagina/12 chunks.

The classifier uses a three-layer cascade:
1. Auditable heuristic rules.
2. Semantic similarity against Argentina/international anchors.
3. Optional local Ollama LLM only for gray-zone chunks.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
import unicodedata
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.config import get_settings
from app.ingestion.enrichers.gazetteer import Gazetteer

logger = logging.getLogger("enrichers.scope_classifier")

ANCLAS_ARGENTINA = [
    "noticias de Argentina",
    "politica argentina",
    "economia argentina",
    "sociedad argentina",
    "gobierno de Argentina",
    "Buenos Aires Argentina",
    "noticias argentinas",
]

ANCLAS_INTERNACIONAL = [
    "noticias internacionales",
    "politica exterior mundial",
    "conflicto internacional",
    "elecciones en otro pais",
    "economia mundial",
    "guerra en el exterior",
]

ANCLAS_UNKNOWN = [
    "fragmento ambiguo sin contexto nacional",
    "ensayo literario conceptual",
    "critica cultural sin referencia geografica",
    "reflexion sobre sexualidad y capitalismo",
    "resena de libro sin pais definido",
    "texto conceptual sin evidencia nacional",
]

PROMPT_TEMPLATE = """Sos un clasificador estricto de alcance nacional para una hemeroteca argentina.
Responde SOLO con una de estas tres palabras exactas: argentina / international / unknown

Pregunta: Este fragmento de noticia esta vinculado con Argentina?

Usa SOLO la evidencia del fragmento. No infieras Argentina porque el texto este en
espanol, porque fue publicado por Pagina/12, porque la seccion sea cultural, ni
porque mencione capitalismo, fabrica, violencia, sexualidad, literatura o politica
en terminos generales.

Responde "argentina" SOLO si el fragmento menciona explicitamente alguna evidencia
argentina: Argentina/argentinos, provincias o ciudades argentinas, instituciones
argentinas, partidos/sindicatos/clubes argentinos, figuras publicas argentinas,
obras o eventos argentinos, o argentinos en el exterior.

Responde "international" si el fragmento trata claramente sobre otro pais, autores,
instituciones o eventos extranjeros sin vinculo explicito con Argentina.

Responde "unknown" si el fragmento es conceptual, literario, ambiguo o no contiene
evidencia suficiente para decidir.

Ejemplos few-shot:

Fragmento:
Elfriede Jelinek, escritora austriaca, obtuvo el Premio Nobel y polemizo con la
politica cultural de Austria.
Respuesta: international

Fragmento:
La novela revisa la idea de revolucion sexual y usa la violencia para retratar
relaciones de dominacion propias del capitalismo.
Respuesta: unknown

Fragmento:
Alfonsin se reunio con dirigentes de la UCR en Buenos Aires antes del debate en
el Congreso.
Respuesta: argentina

Fragmento:
La Cancilleria argentina asistio a ciudadanos argentinos afectados por el
conflicto en el exterior.
Respuesta: argentina

Fragmento:
\"\"\"
{text}
\"\"\"

Responde solo con una palabra:"""


class Embedder(Protocol):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        ...


class ScopeLLMClient(Protocol):
    model: str

    def generate(self, prompt: str) -> str:
        ...


@dataclass(frozen=True)
class ScopeResult:
    country_scope: str
    scope_signals: list[str]


@dataclass(frozen=True)
class EmbeddingDecision:
    result: ScopeResult
    final: bool


class OllamaScopeLLM:
    def __init__(self, base_url: str, model: str, timeout_seconds: float = 20.0):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds

    def generate(self, prompt: str) -> str:
        response = httpx.post(
            f"{self.base_url}/api/generate",
            json={
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0,
                    "num_predict": 5,
                },
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        return str(response.json().get("response", ""))


class ScopeClassifier:
    def __init__(
        self,
        embedder: Embedder | None,
        llm_client: ScopeLLMClient | None = None,
        gazetteer: Gazetteer | None = None,
        *,
        embedding_threshold: float | None = None,
    ):
        settings = get_settings()
        self.embedder = embedder
        self.llm_client = llm_client
        self.gazetteer = gazetteer
        self.embedding_threshold = (
            settings.scope_embedding_threshold
            if embedding_threshold is None
            else embedding_threshold
        )
        self._llm_cache: dict[str, ScopeResult] = {}
        self._arg_anchor_embeddings: list[list[float]] = []
        self._int_anchor_embeddings: list[list[float]] = []
        self._unknown_anchor_embeddings: list[list[float]] = []
        self._direct_argentina_sections = _normalized_set(
            self.gazetteer.direct_argentina_sections if self.gazetteer else []
        )
        self._direct_institution_terms = _direct_text_terms(
            self.gazetteer.institutions if self.gazetteer else []
        )
        self._direct_political_org_terms = _direct_text_terms(
            self.gazetteer.political_organizations if self.gazetteer else []
        )
        self._direct_ambiguous_institution_terms = _direct_text_terms(
            self.gazetteer.ambiguous_institutions if self.gazetteer else []
        )

        if self.embedder is not None:
            self._arg_anchor_embeddings = self._embed_many(ANCLAS_ARGENTINA)
            self._int_anchor_embeddings = self._embed_many(ANCLAS_INTERNACIONAL)
            self._unknown_anchor_embeddings = self._embed_many(ANCLAS_UNKNOWN)
            logger.info(
                "Anclas de embeddings precalculadas (%s argentina, %s internacional, %s unknown)",
                len(self._arg_anchor_embeddings),
                len(self._int_anchor_embeddings),
                len(self._unknown_anchor_embeddings),
            )

        logger.info(
            "ScopeClassifier inicializado. LLM capa 3: %s",
            "habilitado" if llm_client else "deshabilitado",
        )

    def classify(self, chunk_text: str, metadata: dict) -> tuple[str, list[str]]:
        if len(chunk_text.strip()) < 100:
            logger.debug("[Capa1] scope=unknown signals=[]")
            return "unknown", []

        heuristic = self._classify_heuristic(chunk_text, metadata)
        if heuristic.country_scope != "unknown":
            logger.debug("[Capa1] scope=%s signals=%s", heuristic.country_scope, heuristic.scope_signals)
            return heuristic.country_scope, heuristic.scope_signals

        logger.debug("[Capa1] scope=unknown signals=%s", heuristic.scope_signals)
        heuristic_signals = heuristic.scope_signals
        embedding_decision = self._classify_embeddings(chunk_text, metadata)
        embedding_result = embedding_decision.result
        if embedding_decision.final:
            return embedding_result.country_scope, heuristic_signals + embedding_result.scope_signals

        llm_result = self._classify_llm(chunk_text)
        base_signals = heuristic_signals + embedding_result.scope_signals
        if llm_result.scope_signals:
            return llm_result.country_scope, base_signals + llm_result.scope_signals
        return llm_result.country_scope, base_signals

    def _classify_heuristic(self, text: str, metadata: dict) -> ScopeResult:
        section = _normalize_section(metadata.get("section"))
        if section in self._direct_argentina_sections:
            return ScopeResult("argentina", [f"seccion:{section}"])

        strong_signals: list[str] = []
        weak_signals: list[str] = []
        location_mentions = _as_list(metadata.get("location_mentions"))
        organizations = _as_list(metadata.get("organizations"))
        haystack = " ".join(
            part
            for part in (
                text,
                str(metadata.get("article_title") or ""),
                " ".join(organizations),
                " ".join(location_mentions),
            )
            if part
        )

        for location in location_mentions:
            if self.gazetteer is not None and not self.gazetteer.is_known_location(location):
                continue
            _append_signal(strong_signals, f"gazetteer:{location}")

        organization_text = " ".join(organizations)
        gazetteer_institutions = self.gazetteer.institutions if self.gazetteer else []
        gazetteer_political_orgs = self.gazetteer.political_organizations if self.gazetteer else []
        gazetteer_clubs = self.gazetteer.clubs if self.gazetteer else []
        gazetteer_ambiguous_institutions = self.gazetteer.ambiguous_institutions if self.gazetteer else []
        gazetteer_contextual_terms = self.gazetteer.contextual_terms if self.gazetteer else []
        for org in _contains_any(organization_text, gazetteer_institutions):
            _append_signal(strong_signals, f"institution:{org}")
        for org in _contains_any(organization_text, gazetteer_political_orgs):
            _append_signal(strong_signals, f"political_org:{org}")
        for club in _contains_any(organization_text, gazetteer_clubs):
            _append_signal(strong_signals, f"club:{club}")
        for org in _contains_any(organization_text, gazetteer_ambiguous_institutions):
            _append_signal(weak_signals, f"weak_institution:{org}")

        for org in _contains_any(haystack, self._direct_institution_terms):
            _append_signal(strong_signals, f"institution:{org}")
        for org in _contains_any(haystack, self._direct_political_org_terms):
            _append_signal(strong_signals, f"political_org:{org}")
        for org in _contains_any(haystack, self._direct_ambiguous_institution_terms):
            _append_signal(weak_signals, f"weak_institution:{org}")

        gazetteer_keywords = self.gazetteer.keywords if self.gazetteer else []
        for term in _contains_any(haystack, gazetteer_keywords):
            _append_signal(strong_signals, f"term:{term}")
        for term in _contains_any(haystack, gazetteer_contextual_terms):
            _append_signal(weak_signals, f"contextual_term:{term}")

        if strong_signals:
            return ScopeResult("argentina", strong_signals + weak_signals)
        return ScopeResult("unknown", weak_signals)

    def _classify_embeddings(self, text: str, metadata: dict) -> EmbeddingDecision:
        if (
            self.embedder is None
            or not self._arg_anchor_embeddings
            or not self._int_anchor_embeddings
            or not self._unknown_anchor_embeddings
        ):
            return EmbeddingDecision(ScopeResult("unknown", []), final=False)

        chunk_embedding = self._embed_many([text])[0]
        metadata["_index_vector"] = chunk_embedding
        score_arg = max(_cosine_similarity(chunk_embedding, anchor) for anchor in self._arg_anchor_embeddings)
        score_int = max(_cosine_similarity(chunk_embedding, anchor) for anchor in self._int_anchor_embeddings)
        score_unknown = max(
            _cosine_similarity(chunk_embedding, anchor) for anchor in self._unknown_anchor_embeddings
        )
        scores = {
            "argentina": score_arg,
            "international": score_int,
            "unknown": score_unknown,
        }
        ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        winner, winner_score = ordered[0]
        runner_up_score = ordered[1][1]
        margin = winner_score - runner_up_score
        signals = [
            f"emb_arg:{score_arg:.3f}",
            f"emb_int:{score_int:.3f}",
            f"emb_unknown:{score_unknown:.3f}",
            f"emb_margin:{margin:.3f}",
        ]

        if margin > self.embedding_threshold:
            logger.debug("[Capa2] margin=%.3f scope=%s", margin, winner)
            return EmbeddingDecision(ScopeResult(winner, signals), final=True)

        logger.debug("[Capa2] margin=%.3f scope=unknown", margin)
        return EmbeddingDecision(ScopeResult("unknown", signals), final=False)

    def _classify_llm(self, text: str) -> ScopeResult:
        if len(text.strip()) < 150:
            return ScopeResult("unknown", ["llm_skipped:short_text"])
        if self.llm_client is None:
            return ScopeResult("unknown", ["llm_skipped:disabled"])

        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        cached = self._llm_cache.get(digest)
        if cached is not None:
            return cached

        logger.debug("[Capa3] enviando chunk (%s chars) a LLM", len(text))
        try:
            raw_response = self.llm_client.generate(PROMPT_TEMPLATE.format(text=text[:3500]))
        except Exception as exc:  # pragma: no cover - defensive runtime guard
            logger.warning("[Capa3] fallo LLM local: %s", exc)
            result = ScopeResult("unknown", [f"llm_error:{self.llm_client.model}"])
            self._llm_cache[digest] = result
            return result

        scope = _parse_llm_scope(raw_response)
        logger.debug("[Capa3] LLM respondio: %s -> %s", raw_response, scope)
        signals = [f"llm_local:{self.llm_client.model}:{scope}"]
        result = ScopeResult(scope, signals)
        self._llm_cache[digest] = result
        return result

    def _embed_many(self, texts: list[str]) -> list[list[float]]:
        return [list(vector) for vector in self.embedder.embed_documents(texts)] if self.embedder else []


def build_default_llm_client() -> ScopeLLMClient | None:
    settings = get_settings()
    if not settings.scope_llm_enabled:
        return None
    return OllamaScopeLLM(
        base_url=settings.ollama_base_url,
        model=settings.scope_llm_model,
        timeout_seconds=settings.request_timeout_seconds,
    )


def classify_country_scope(
    text: str,
    metadata: dict,
    gazetteer: Gazetteer,
    organizations: list[str],
    locations: list[str],
) -> ScopeResult:
    enriched_metadata = dict(metadata)
    enriched_metadata["organizations"] = organizations
    enriched_metadata["location_mentions"] = locations
    classifier = ScopeClassifier(embedder=None, llm_client=None, gazetteer=gazetteer)
    scope, signals = classifier.classify(text, enriched_metadata)
    return ScopeResult(scope, signals)


def _normalize_section(section: str | None) -> str:
    return (section or "").strip().lower()


def _normalized_set(values: list[str]) -> set[str]:
    return {_normalize_section(value) for value in values}


def _as_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if isinstance(value, (tuple, set)):
        return [str(item) for item in value if item]
    return []


def _strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _contains_any(text: str, values: list[str] | set[str]) -> list[str]:
    normalized_text = _strip_accents(text).lower()
    found: list[str] = []
    for value in values:
        normalized = _strip_accents(value).lower().strip()
        if normalized and _contains_term(normalized_text, normalized) and value not in found:
            found.append(value)
    return found


def _contains_term(normalized_text: str, normalized_term: str) -> bool:
    escaped = re.escape(normalized_term).replace(r"\ ", r"\s+")
    pattern = rf"(?<!\w){escaped}(?!\w)"
    return re.search(pattern, normalized_text, flags=re.IGNORECASE) is not None


def _direct_text_terms(values: list[str]) -> list[str]:
    terms: list[str] = []
    for value in values:
        normalized = _strip_accents(value).strip()
        if " " in normalized or len(normalized) > 4:
            terms.append(value)
    return terms


def _append_signal(signals: list[str], signal: str) -> None:
    if signal and signal not in signals:
        signals.append(signal)


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def _parse_llm_scope(raw_response: str) -> str:
    first = raw_response.strip().lower().split()
    if not first:
        return "unknown"
    value = first[0].strip(".,;:!?")
    if value in {"argentina", "international", "unknown"}:
        return value
    return "unknown"
