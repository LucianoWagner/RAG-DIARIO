"""
Intent router for the Hemeroteca assistant.
"""

import re

from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger

_CHITCHAT_PATTERNS: list[re.Pattern] = [
    re.compile(r"^\s*(hola|hello|hi|hey|buenas|buen\s?d[ií]a|buenos?\s?(d[ií]as|tardes|noches))\s*[!.?]*\s*$", re.IGNORECASE),
    re.compile(r"^\s*(gracias|thanks|thank\s*you|thx|ty|muchas\s*gracias)\s*[!.?]*\s*$", re.IGNORECASE),
    re.compile(r"^\s*(chau|adi[oó]s|bye|nos\s*vemos|hasta\s*(luego|pronto|la\s*vista))\s*[!.?]*\s*$", re.IGNORECASE),
    re.compile(r"^\s*(ok|dale|perfecto|genial|bien|entendido|listo|excelente|copado|joya)\s*[!.?]*\s*$", re.IGNORECASE),
    re.compile(r"^\s*(qui[eé]n\s+(sos|eres)|what\s+are\s+you|who\s+are\s+you|c[oó]mo\s+te\s+llam[aá]s)\s*[?!.]*\s*$", re.IGNORECASE),
]

_RAG_KEYWORDS: list[str] = [
    "la plata",
    "berisso",
    "ensenada",
    "hemeroteca",
    "diario",
    "noticia",
    "periodico",
    "archivo",
    "articulo",
    "inundacion",
    "eleccion",
    "policial",
    "cultura",
    "deporte",
    "historia",
    "pagina/12",
    "pagina 12",
    "pagina12",
    "2005",
    "1996",
    "1930",
]

_ROUTER_SYSTEM_PROMPT = """You classify messages for a historical newspaper assistant.
Return exactly one word: RAG or CHITCHAT.

RAG:
- questions about events, people, places, topics, newspapers, years, decades, archives

CHITCHAT:
- greetings, thanks, jokes, personal questions, generic conversation
"""

_FEW_SHOT_EXAMPLES = [
    ("Que paso en La Plata en 2005?", "RAG"),
    ("Cobertura de Maradona en los 90", "RAG"),
    ("Noticias sobre Berisso en 1986", "RAG"),
    ("Hola, como estas?", "CHITCHAT"),
    ("Gracias por la ayuda", "CHITCHAT"),
]


def _heuristic_classify(question: str) -> str | None:
    text = question.strip().lower()
    if any(keyword in text for keyword in _RAG_KEYWORDS):
        return "RAG"
    for pattern in _CHITCHAT_PATTERNS:
        if pattern.match(question):
            return "CHITCHAT"
    return None


def _llm_classify(llm, question: str) -> str:
    examples_text = "\n".join(f'User: "{q}" -> {label}' for q, label in _FEW_SHOT_EXAMPLES)
    messages = [
        SystemMessage(content=f"{_ROUTER_SYSTEM_PROMPT}\nExamples:\n{examples_text}"),
        HumanMessage(content=question),
    ]
    try:
        response = llm.invoke(messages)
        result = str(response.content).strip().upper()
        if result == "CHITCHAT":
            return "CHITCHAT"
        return "RAG"
    except Exception as exc:
        logger.warning(f"Router fallback a RAG por error: {exc}")
        return "RAG"


def route_query(llm, question: str) -> str:
    heuristic_result = _heuristic_classify(question)
    if heuristic_result is not None:
        return heuristic_result
    return _llm_classify(llm, question)


def get_chitchat_response(llm, question: str) -> str:
    messages = [
        SystemMessage(
            content=(
                "You are a friendly historical newspaper assistant. "
                "Respond briefly in the same language as the user. "
                "Mention that you can help search historical newspaper archives."
            )
        ),
        HumanMessage(content=question),
    ]
    try:
        response = llm.invoke(messages)
        return str(response.content).strip()
    except Exception:
        return "Hola. Puedo ayudarte a buscar notas y eventos en la hemeroteca de La Plata."
