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


def test_turn_publica_evidence_y_brief(monkeypatch) -> None:
    from src.runtime.evidence_assembly import assemble_evidence
    from src.runtime.knowledge_brief import build_knowledge_brief

    monkeypatch.setattr(get_settings(), "COGNITIVE_OS_ENABLED", "shadow")
    turn = CognitiveTurn(query="q")
    assert turn.to_public_dict()["evidence"] is None
    assert turn.to_public_dict()["brief"] is None
    package = assemble_evidence()
    turn.evidence = package
    turn.brief = build_knowledge_brief(package)
    payload = turn.to_public_dict()
    assert payload["evidence"]["count"] == 0
    assert [section["kind"] for section in payload["brief"]["sections"]][0] == "facts"


def test_turn_publica_verificacion_budget_loop_learning(monkeypatch) -> None:
    from src.runtime.evidence_assembly import EvidencePackage
    from src.runtime.turn_reports import build_budget_report, build_loop_report
    from src.runtime.verification import verify_answer

    monkeypatch.setattr(get_settings(), "COGNITIVE_OS_ENABLED", "shadow")
    turn = CognitiveTurn(query="q")
    turn.verification = verify_answer("", EvidencePackage())
    turn.budget = build_budget_report(complexity="L1", llm_calls=1, tokens=100, elapsed_ms=10)
    turn.loop = build_loop_report({})
    payload = turn.to_public_dict()
    assert payload["verification"]["action"] == "approve"
    assert payload["budget"]["complexity"] == "L1"
    assert payload["loop"]["count"] == 0
    assert payload["learning"] == []


def test_jev_signals_sin_entidades(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "COGNITIVE_OS_ENABLED", "shadow")
    query = "¿Aplica la regla 12?"
    turn = CognitiveTurn(query=query, plan=build_cognitive_plan(query))
    assert turn.jev_signals() == {
        "exact_lookup_declared": False,
        "entity_resolved": None,
    }


def test_jev_signals_entidad_resuelta(monkeypatch) -> None:
    from src.runtime.entity_resolution import (
        EntityMatch,
        EntityResolution,
        MentionResolution,
    )

    monkeypatch.setattr(get_settings(), "COGNITIVE_OS_ENABLED", "shadow")
    query = "¿Qué significa el Byte 105?"
    turn = CognitiveTurn(query=query, plan=build_cognitive_plan(query))
    turn.entities = EntityResolution(
        mentions=(
            MentionResolution(
                mention="Byte 105",
                status="resolved",
                matches=(
                    EntityMatch(
                        mention="Byte 105",
                        canonical_id="c1",
                        name="Byte 105",
                        kind="entity",
                        match="exact_name",
                        confidence=1.0,
                    ),
                ),
            ),
        )
    )
    signals = turn.jev_signals()
    assert signals["exact_lookup_declared"] is True
    assert signals["entity_resolved"] is True
