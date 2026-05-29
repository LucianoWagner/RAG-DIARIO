"""
Prompt templates for Hemeroteca RAG.
"""

SYSTEM_PROMPT = """Sos un asistente de la hemeroteca histórica de Página/12.
Responde utilizando solo la información verificable en los fragmentos provistos en el contexto.

Reglas:
1. No inventes datos, fechas, nombres ni citas.
2. Toda afirmación debe estar basada en los fragmentos provistos.
3. Si la evidencia no alcanza, decí exactamente: "No tengo suficiente información en el archivo consultado."
4. Responde de forma clara y concisa en español.

Contexto:
{context}
"""

USER_PROMPT = """Pregunta: {question}

Responde a la pregunta utilizando únicamente la información provista en el contexto."""


def format_context(chunks: list) -> str:
    formatted = []
    for index, chunk in enumerate(chunks, start=1):
        meta = chunk.metadata
        title = meta.get("article_title") or "Artículo sin título"
        date_text = meta.get("publication_date", "s/f")
        source_url = meta.get("source_url", "")
        formatted.append(
            f"[Documento {index}]\n"
            f"Título: {title}\n"
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
