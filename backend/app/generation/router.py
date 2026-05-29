"""
Intent router for the Hemeroteca assistant.
"""

from langchain_core.messages import HumanMessage, SystemMessage
from app.generation.query_planner import QueryPlanner


def route_query(llm, question: str) -> str:
    """Clasifica la intención de la query usando QueryPlanner."""
    planner = QueryPlanner(llm)
    plan = planner.plan_query(question)
    return plan.intent


def get_chitchat_response(llm, question: str) -> str:
    """Genera respuesta breve de chitchat."""
    messages = [
        SystemMessage(
            content=(
                "You are a friendly historical newspaper assistant for Página/12 archive. "
                "Respond briefly in the same language as the user. "
                "Mention that you can help search historical newspaper archives of Página/12."
            )
        ),
        HumanMessage(content=question),
    ]
    try:
        response = llm.invoke(messages)
        return str(response.content).strip()
    except Exception:
        return "Hola. Puedo ayudarte a buscar notas y eventos en la hemeroteca de Página/12."
