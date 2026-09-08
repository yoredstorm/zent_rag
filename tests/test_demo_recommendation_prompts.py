# =============================================================================
# Chat demo — recomendaciones de catálogo no deben abstenerse
# =============================================================================
from src.agents.runtime.orchestrator import (
    RAG_SYSTEM_PROMPT,
    RAG_SYSTEM_PROMPT_CUSTOMER,
    sql_mode_from_result,
)
from src.agents.tools.sql_expert_postgres import _SQL_GENERATION_PROMPT
from src.core.ports.sql_expert import SqlQueryResult
from src.verticals.demo_farmacia.prompts import SYSTEM_PROMPT_ADMIN, SYSTEM_PROMPT_CUSTOMER

_RECOMMEND_HINT = "recomendación"


def test_admin_and_generic_prompts_allow_catalog_recommendation() -> None:
    for prompt in (RAG_SYSTEM_PROMPT, SYSTEM_PROMPT_ADMIN, RAG_SYSTEM_PROMPT_CUSTOMER):
        lowered = prompt.lower()
        assert _RECOMMEND_HINT in lowered
        assert "reseña" in lowered or "reseñas" in lowered


def test_customer_prompt_still_forbids_robotic_abstention() -> None:
    assert "no tengo información suficiente" in SYSTEM_PROMPT_CUSTOMER.lower()


def test_sql_generation_searches_category_not_only_name() -> None:
    lowered = _SQL_GENERATION_PROMPT.lower()
    assert "recommend" in lowered
    assert "tags" in lowered
    assert "description" in lowered


def test_empty_catalog_sql_falls_back_to_rag() -> None:
    empty = SqlQueryResult(sql="SELECT 1", row_count=0)
    assert sql_mode_from_result(empty, "Recomiéndame un analgésico") is False
    assert sql_mode_from_result(empty, "¿Cuánto vendimos este mes?") is True
    filled = SqlQueryResult(sql="SELECT 1", row_count=2)
    assert sql_mode_from_result(filled, "Recomiéndame un analgésico") is True
