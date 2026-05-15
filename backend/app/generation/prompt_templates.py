"""
Prompt templates for Hemeroteca RAG.
"""

SYSTEM_PROMPT = """Sos un asistente de hemeroteca historica de La Plata.
Responde solo con informacion verificable en los fragmentos provistos.

Reglas:
1. No inventes datos, fechas, nombres ni citas.
2. Toda afirmacion factual debe llevar una cita inline con formato [Fuente N].
3. Si la evidencia no alcanza, deci exactamente: "No tengo suficiente informacion en el archivo consultado."
4. Responde en espanol.

Contexto:
{context}
"""

USER_PROMPT = """Pregunta: {question}

Responde usando solo el contexto y cita cada afirmacion relevante con [Fuente N]."""


def format_context(chunks: list) -> str:
    formatted = []
    for index, chunk in enumerate(chunks, start=1):
        meta = chunk.metadata
        title = meta.get("article_title") or "Articulo sin titulo"
        date_text = meta.get("publication_date", "s/f")
        source_url = meta.get("source_url", "")
        formatted.append(
            f"[Fuente {index}]\n"
            f"Titulo: {title}\n"
            f"Fecha: {date_text}\n"
            f"URL: {source_url}\n"
            f"---\n{chunk.page_content}\n---"
        )
    return "\n\n".join(formatted)


def build_messages(question: str, context: str, system_prompt: str = SYSTEM_PROMPT) -> list[dict]:
    return [
        {"role": "system", "content": system_prompt.format(context=context)},
        {"role": "user", "content": USER_PROMPT.format(question=question)},
    ]
