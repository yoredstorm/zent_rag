# =============================================================================
# Query Intelligence — Knowledge V2 (Phase F slice 1)
# =============================================================================
from src.rag.query_intelligence import (
    INTENT_ANALYTICAL,
    INTENT_COMPARISON,
    INTENT_DEFINITION,
    INTENT_EXPLANATION,
    INTENT_FACTUAL,
    INTENT_LIST,
    INTENT_NAVIGATION,
    INTENT_SUMMARY,
    INTENT_TEMPORAL,
    classify_intent,
)


def test_classify_intent_covers_brief_cases() -> None:
    assert classify_intent("Resume este contrato") == INTENT_SUMMARY
    assert classify_intent("¿Qué penalización establece la cláusula 8?") == INTENT_FACTUAL
    assert (
        classify_intent("Compara las obligaciones del contrato 2025 y su adenda 2026")
        == INTENT_COMPARISON
    )
    assert classify_intent("¿Cuándo vence el acuerdo?") == INTENT_TEMPORAL
    assert classify_intent("Lista las obligaciones principales") == INTENT_LIST
    assert classify_intent("¿Qué es la comisión?") == INTENT_DEFINITION
    assert classify_intent("¿Por qué cambió la política?") == INTENT_EXPLANATION
    assert classify_intent("¿Cuánto representa el 5% del total?") == INTENT_ANALYTICAL
    assert classify_intent("Dónde está la sección 5.2 del manual") == INTENT_NAVIGATION
    assert classify_intent("hola") == INTENT_FACTUAL


def test_build_query_plan_is_structured() -> None:
    from src.rag.query_intelligence import build_query_plan

    plan = build_query_plan(
        "Compara el contrato 2025 con la adenda 2026 vigente"
    )
    assert plan.intent == INTENT_COMPARISON
    assert plan.normalized_intent == "COMPARISON"
    assert plan.original_query.startswith("Compara")
    assert plan.search_queries == (plan.original_query,)
    assert "2025" in plan.entities or "contrato" in plan.entities
    assert plan.date_filters.get("year") == 2025
    assert "page" in plan.required_evidence
    assert "section_path" in plan.required_evidence


def test_temporal_query_extracts_current_constraint() -> None:
    from src.rag.query_intelligence import build_query_plan

    plan = build_query_plan("¿Cuál es la política vigente?")
    assert plan.intent == INTENT_TEMPORAL
    assert plan.date_filters.get("temporal") == "current"
