# =============================================================================
# Cognitive Turn State — modo del runtime + estado compartido del turno.
# =============================================================================
from __future__ import annotations

from src.core.config import get_settings
from src.rag.retrieval.planner import build_retrieval_plan
from src.runtime.cognitive_plan import build_cognitive_plan
from src.runtime.cognitive_state import CognitiveTurn, cognitive_runtime_mode
from src.runtime.knowledge_strategy import build_knowledge_strategy


def test_modo_invalido_cae_a_off(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "COGNITIVE_OS_ENABLED", "banana")
    assert cognitive_runtime_mode() == "off"


def test_modo_shadow_se_lee(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "COGNITIVE_OS_ENABLED", "shadow")
    assert cognitive_runtime_mode() == "shadow"


def test_turn_publica_plan_y_strategy(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "COGNITIVE_OS_ENABLED", "shadow")
    query = "¿Qué dice la regla 12?"
    plan = build_cognitive_plan(query)
    turn = CognitiveTurn(
        query=query,
        plan=plan,
        strategy=build_knowledge_strategy(build_retrieval_plan(query)),
    )
    turn.add_note("plan", "necesidades calculadas")
    payload = turn.to_public_dict()
    assert payload["mode"] == "shadow"
    assert payload["plan"]["needs"]
    assert payload["strategy"]["representations"]
    assert payload["notes"] == [{"stage": "plan", "detail": "necesidades calculadas"}]


def test_turn_sin_plan_es_serializable() -> None:
    payload = CognitiveTurn(query="hola").to_public_dict()
    assert "plan" not in payload
    assert "strategy" not in payload
    assert payload["notes"] == []
