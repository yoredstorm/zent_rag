# =============================================================================
# Knowledge Retrieval Planner — el retrieval deja de ser solo vector search
# =============================================================================
from __future__ import annotations

from src.rag.retrieval.planner import (
    KnowledgeRetrievalPlanner,
    Representation,
    build_retrieval_plan,
)


def test_consulta_semantica_usa_vector() -> None:
    plan = build_retrieval_plan("¿cómo se reemite un ticket?")
    assert plan.includes(Representation.VECTOR.value)
    assert plan.primary == Representation.VECTOR.value
    assert plan.reasons[Representation.VECTOR.value]


def test_literal_tecnico_activa_exact() -> None:
    plan = build_retrieval_plan("¿qué significa Byte 105?")
    assert plan.includes(Representation.EXACT.value)
    assert any("Byte 105" == needle for needle in plan.exact_needles)
    assert plan.includes(Representation.GRAPH.value)
    assert "Byte" in " ".join(plan.entity_mentions)


def test_consulta_temporal_activa_temporal() -> None:
    plan = build_retrieval_plan("¿qué valor tenía X antes del cambio de septiembre?")
    assert plan.includes(Representation.TEMPORAL.value)
    assert plan.temporal_intent is not None


def test_consulta_de_datos_exactos_activa_structured() -> None:
    plan = build_retrieval_plan("¿cuántos carriers hay en la tabla?")
    assert plan.includes(Representation.STRUCTURED.value)
    assert plan.structured_intent is not None
    assert plan.primary == Representation.STRUCTURED.value


def test_plan_es_explicable() -> None:
    plan = build_retrieval_plan("Record 4 antes de 2025 en la tabla")
    payload = plan.to_dict()
    assert payload["representations"]
    assert set(payload["reasons"]) == set(payload["representations"])
    assert payload["primary"] in payload["representations"]


def test_fachada_del_planner() -> None:
    planner = KnowledgeRetrievalPlanner()
    plan = planner.plan("Cat 31")
    assert plan.normalized == "cat 31"
