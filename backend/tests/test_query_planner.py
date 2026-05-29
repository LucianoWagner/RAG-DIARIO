from unittest.mock import MagicMock
import pytest
from app.generation.query_planner import QueryPlanner, QueryPlan


def test_chitchat_local_heuristic():
    planner = QueryPlanner(llm=MagicMock())
    
    # Saludo simple
    plan1 = planner.plan_query("Hola, buenas tardes")
    assert plan1.intent == "CHITCHAT"
    
    # Agradecimiento
    plan2 = planner.plan_query("muchas gracias!!")
    assert plan2.intent == "CHITCHAT"
    
    # Pregunta de identidad
    plan3 = planner.plan_query("quien sos?")
    assert plan3.intent == "CHITCHAT"


def test_structured_llm_call_success():
    mock_llm = MagicMock()
    mock_structured = MagicMock()
    mock_llm.with_structured_output.return_value = mock_structured
    
    expected_plan = QueryPlan(
        intent="ARCHIVE_SEARCH",
        year=2002,
        section="elpais",
        search_query="conflicto de la unlp con el gobierno"
    )
    mock_structured.invoke.return_value = expected_plan
    
    planner = QueryPlanner(llm=mock_llm)
    plan = planner.plan_query("que conflictos tuvo la unlp con el gobierno nacional en el año 2002 en El País?")
    
    assert plan.intent == "ARCHIVE_SEARCH"
    assert plan.year == 2002
    assert plan.section == "elpais"
    assert plan.search_query == "conflicto de la unlp con el gobierno"
    mock_llm.with_structured_output.assert_called_once_with(QueryPlan)


def test_structured_llm_call_fallback():
    mock_llm = MagicMock()
    mock_structured = MagicMock()
    mock_llm.with_structured_output.return_value = mock_structured
    # Simulamos error de la API
    mock_structured.invoke.side_effect = Exception("API Error")
    
    planner = QueryPlanner(llm=mock_llm)
    # Consulta con año explícito
    plan = planner.plan_query("Que paso con el FMI en 2005?")
    
    assert plan.intent == "ARCHIVE_SEARCH"
    assert plan.year == 2005
    assert plan.search_query == "Que paso con el FMI en 2005?"
