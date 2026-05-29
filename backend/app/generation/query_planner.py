"""
Query Planner for Hemeroteca RAG.
Clasifica la intención del usuario y extrae filtros estructurados opcionales de la consulta.
"""

import re
import unicodedata
from typing import Literal
from pydantic import BaseModel, Field
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_groq import ChatGroq
from loguru import logger

# Expresiones regulares para interceptar chitchat de forma local rápida
_CHITCHAT_PATTERNS: list[re.Pattern] = [
    re.compile(r"^\s*(hola|hello|hi|hey|buenas|buen\s?d[ií]a|buen(o|a)s?\s?(d[ií]as|tardes|noches))(\s*,\s*(hola|hello|hi|hey|buenas|buen\s?d[ií]a|buen(o|a)s?\s?(d[ií]as|tardes|noches)))?\s*[!.?]*\s*$", re.IGNORECASE),
    re.compile(r"^\s*(gracias|thanks|thank\s*you|thx|ty|muchas\s*gracias)\s*[!.?]*\s*$", re.IGNORECASE),
    re.compile(r"^\s*(chau|adi[oó]s|bye|nos\s*vemos|hasta\s*(luego|pronto|la\s*vista))\s*[!.?]*\s*$", re.IGNORECASE),
    re.compile(r"^\s*(ok|dale|perfecto|genial|bien|entendido|listo|excelente|copado|joya)\s*[!.?]*\s*$", re.IGNORECASE),
    re.compile(r"^\s*(qui[eé]n\s+(sos|eres)|what\s+are\s+you|who\s+are\s+you|c[oó]mo\s+te\s+llam[aá]s)\s*[?!.]*\s*$", re.IGNORECASE),
]


class QueryPlan(BaseModel):
    intent: Literal["CHITCHAT", "ARCHIVE_SEARCH", "OUT_OF_SCOPE"] = Field(
        description="Clasificación de la intención. CHITCHAT para saludos/gracias. ARCHIVE_SEARCH para buscar noticias, personas, temas o hechos históricos del diario. OUT_OF_SCOPE para consultas no periodísticas (ej. código, recetas, ecuaciones)."
    )
    year: int | None = Field(
        default=None,
        description="Año de 4 dígitos mencionado explícita o implícitamente en la consulta (ej. '2005', '1996'). Si no hay año, null."
    )
    decade: int | None = Field(
        default=None,
        description="Década de 4 dígitos mencionada (ej: 'los 90' o 'los noventa' -> 1990, 'los 80' -> 1980). Si no hay década, null."
    )
    publication_date: str | None = Field(
        default=None,
        description="Fecha exacta en formato YYYY-MM-DD si se especifica día, mes y año (ej: '17 de marzo de 2005' -> '2005-03-17'). Si no hay fecha exacta, null."
    )
    section: str | None = Field(
        default=None,
        description="Sección del diario mencionada. Normalizar a minúsculas, sin acentos y sin espacios (ej: 'El País' -> 'elpais', 'Espectáculos' -> 'espectaculos', 'Economía' -> 'economia'). Si no hay sección, null."
    )
    newspaper: str | None = Field(
        default="pagina12",
        description="Nombre del diario. Por defecto 'pagina12'."
    )
    search_query: str | None = Field(
        default=None,
        description="Consulta optimizada y limpia en español para buscar en la base de datos vectorial/léxica, resumiendo el núcleo temático y eliminando ruidos conversacionales o filtros temporales explícitos."
    )


QUERY_PLANNER_SYSTEM_PROMPT = """Eres un planificador de consultas para una hemeroteca de diarios históricos argentinos (principalmente Página/12).
Tu tarea es analizar la consulta del usuario, clasificar su intención y extraer filtros de búsqueda opcionales en formato estructurado.

Intenciones:
- CHITCHAT: Saludos, agradecimientos, despedidas o conversación informal muy básica.
- OUT_OF_SCOPE: Consultas que no tienen ninguna relación con buscar información, noticias o hechos del pasado en un archivo periodístico (por ejemplo: pedir escribir código de programación, dar una receta de cocina, resolver un problema matemático general, etc.).
- ARCHIVE_SEARCH: Cualquier consulta referida a buscar noticias, temas, personas, sucesos o eventos históricos en la hemeroteca.

Filtros (deja en null si no se mencionan):
- year (entero de 4 dígitos).
- decade (entero de 4 dígitos, ej: 1990).
- publication_date (string, YYYY-MM-DD).
- section (string normalizado a minúsculas sin acentos, ej: "espectaculos", "elpais", "economia", "sociedad", "deportes"). IMPORTANTE: No confundas expresiones comunes como 'en el país' (que se refieren a la geografía o política de Argentina) con la sección periodística 'elpais'. Solo extrae la sección 'elpais' si el usuario se refiere de forma explícita a la sección del diario (ej: 'en la sección El País' o 'las notas de El País').
- newspaper (string, por defecto "pagina12").
- search_query (string en español): Consulta de búsqueda limpia sin saludos ni palabras temporales explícitas (ej: "conflicto de la unlp con el gobierno" en vez de "qué conflictos tuvo la unlp con el gobierno nacional en el año 2002").

No asumas ni inventes años o fechas si no están referenciados de alguna forma en la consulta."""


def _normalize_string(text: str) -> str:
    """Normaliza texto para comparación eliminando acentos y dobles espacios."""
    text = "".join(
        c for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    )
    return " ".join(text.split())


class QueryPlanner:
    def __init__(self, llm: ChatGroq):
        self.llm = llm

    def _match_local_chitchat(self, question: str) -> QueryPlan | None:
        """Verifica de forma rápida y local si la consulta es un chitchat básico para no llamar al LLM."""
        normalized = question.strip()
        for pattern in _CHITCHAT_PATTERNS:
            if pattern.match(normalized):
                logger.info("Intercepción heurística de chitchat local.")
                return QueryPlan(
                    intent="CHITCHAT",
                    search_query=question,
                    newspaper="pagina12"
                )
        return None

    def plan_query(self, question: str) -> QueryPlan:
        """Genera un plan de consulta con intención y filtros."""
        # 1. Chequeo local rápido
        local_plan = self._match_local_chitchat(question)
        if local_plan:
            return local_plan

        # 2. Llamada estructurada al LLM
        try:
            structured_llm = self.llm.with_structured_output(QueryPlan)
            messages = [
                SystemMessage(content=QUERY_PLANNER_SYSTEM_PROMPT),
                HumanMessage(content=question),
            ]
            plan = structured_llm.invoke(messages)
            if plan and isinstance(plan, QueryPlan):
                # Normalizar la sección si fue extraída
                if plan.section:
                    plan.section = _normalize_string(plan.section).lower().replace(" ", "")
                
                # Validar y post-procesar la fecha para evitar falsos positivos
                if plan.publication_date:
                    if not re.match(r"^\d{4}-\d{2}-\d{2}$", plan.publication_date):
                        plan.publication_date = None
                    else:
                        # Si es el primer día del mes (ej: YYYY-MM-01), verificar si el usuario realmente especificó el día
                        parts = plan.publication_date.split("-")
                        if parts[2] == "01":
                            q_clean = _normalize_string(question).lower()
                            if not re.search(r"\b(1|uno|primero|1ro)\b", q_clean):
                                plan.publication_date = None

                logger.info(f"Query plan exitoso: intent={plan.intent}, filters={plan.model_dump(exclude={'search_query', 'intent'})}")
                return plan
            raise ValueError("No se pudo obtener una instancia válida de QueryPlan.")
        except Exception as exc:
            logger.warning(f"Error en QueryPlanner estructurado, ejecutando fallback: {exc}")
            
            # Fallback simple: intentar extraer año con regex
            year_match = re.search(r"\b(19\d{2}|20\d{2})\b", question)
            detected_year = int(year_match.group(1)) if year_match else None
            
            return QueryPlan(
                intent="ARCHIVE_SEARCH",
                year=detected_year,
                search_query=question,
                newspaper="pagina12"
            )
