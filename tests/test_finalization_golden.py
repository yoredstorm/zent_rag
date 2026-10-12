# =============================================================================
# Corpus dorado de la FinalizationPolicy (gate de promoción por etapas).
# =============================================================================
# La matriz cubre query/evidence/authority/budget/draft/termination/tool/JEV.
# Cada caso fija la resolución EXACTA (acción, reason_code, autoridad, límites):
# una regresión de autoridad rompe CI. El gate de adopción por etapa exige cero
# divergencias no justificadas sobre este corpus antes de convertir una señal
# en autoridad (`zent_finalization_divergence_total`).
#
# La regeneración es deliberada: si un cambio de política altera una resolución,
# el caso se actualiza en el mismo commit y se documenta el porqué.
# =============================================================================
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from src.runtime.finalization_policy import (
    FinalizationAction,
    decision_matches_terminal,
    evaluate_finalization,
)
from src.runtime.reason_codes import is_known_reason_code
from src.runtime.run_state import AgentRunState, RunIdentity, RunPhase

GOLDEN = Path(__file__).resolve().parent / "golden" / "finalization_cases.json"
GOLDEN_VERSION = "finalization-golden-1"

_PHASE_BY_ACTION = {
    "FINALIZE": RunPhase.FINALIZED,
    "ABSTAIN": RunPhase.ABSTAINED,
    "BLOCK": RunPhase.BLOCKED,
    "UNDETERMINED": RunPhase.UNDETERMINED,
}


def _load() -> dict:
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def _state(case: dict) -> AgentRunState:
    state = AgentRunState(identity=RunIdentity(run_id=f"golden-{case['id']}"))
    evidence = case["evidence"]
    if evidence == "complete":
        state.evidence.observe(
            sufficiency=SimpleNamespace(
                evidence_complete=True,
                recommended_action="generate",
                missing_entities=(),
                missing_anchors=(),
            )
        )
    elif evidence == "insufficient":
        state.evidence.observe(
            sufficiency=SimpleNamespace(
                evidence_complete=False,
                recommended_action="retrieve_more",
                missing_entities=("efectividad",),
                missing_anchors=(),
            )
        )
    elif evidence == "failed":
        state.evidence.retrieval_failed = True
    authority = case["authority"]
    if authority == "positive":
        state.decisions.set_envelope(
            SimpleNamespace(authoritative=True, state="MATCH")
        )
    elif authority == "negative":
        state.decisions.set_envelope(
            SimpleNamespace(authoritative=True, state="NO_MATCH")
        )
    state.decisions.requires_deterministic = authority == "requires"
    if case["reasoning_incomplete"]:
        state.reasoning.run = SimpleNamespace(
            enabled=True,
            is_complex=True,
            analysis_complete=False,
            blocks_early_answer=True,
        )
    if case["budget_exhausted"]:
        state.budget.ledger = SimpleNamespace(
            remaining_tokens=0, remaining_cost_usd=None
        )
    if case["tool_outside_allowlist"]:
        state.tools.allowed = frozenset({"search_knowledge"})
        state.tools.used = frozenset({"query_database"})
    return state


def _resolve(case: dict):
    return evaluate_finalization(
        _state(case),
        tool_requested=case["tool_requested"],
        tool_authorized=case["tool_authorized"],
        retrieval_possible=case["retrieval_possible"],
        termination_requested=case["termination_requested"],
        draft_available=case["draft_available"],
        jev_verdict=case["jev"],
    )


def test_corpus_versionado_y_ids_unicos() -> None:
    data = _load()
    assert data["version"] == GOLDEN_VERSION
    ids = [case["id"] for case in data["cases"]]
    assert len(ids) == len(set(ids))
    assert len(ids) >= 20  # matriz representativa, no un smoke suelto


def test_resoluciones_del_corpus() -> None:
    data = _load()
    for case in data["cases"]:
        decision = _resolve(case)
        expected = case["expected"]
        assert str(decision.action) == expected["action"], case["id"]
        assert decision.reason_code == expected["reason_code"], case["id"]
        assert str(decision.authority) == expected["authority"], case["id"]
        assert decision.limited is expected["limited"], case["id"]
        assert list(decision.signals_ignored) == expected["signals_ignored"], case
        assert list(decision.conflicts) == expected["conflicts"], case


def test_reason_codes_del_corpus_pertenecen_al_catalogo() -> None:
    data = _load()
    for case in data["cases"]:
        assert is_known_reason_code(case["expected"]["reason_code"]), case["id"]
        for code in case["expected"]["signals_ignored"]:
            assert is_known_reason_code(code), case["id"]
        for code in case["expected"]["conflicts"]:
            assert is_known_reason_code(code), case["id"]


def test_fases_terminales_del_corpus_acompanan_a_la_resolucion() -> None:
    """Enforcement por etapa: la fase que la política implica no diverge."""
    for case in _load()["cases"]:
        expected = case["expected"]
        action = FinalizationAction(expected["action"])
        phase = _PHASE_BY_ACTION.get(str(action))
        if phase is None:
            continue
        assert decision_matches_terminal(_resolve(case), phase), case["id"]


def test_estabilidad_cien_runs_por_caso() -> None:
    """Misma entrada ×100 ⇒ misma resolución semántica (Parte XXVII)."""
    for case in _load()["cases"]:
        first = _resolve(case)
        for _ in range(100):
            again = _resolve(case)
            assert str(again.action) == str(first.action), case["id"]
            assert again.reason_code == first.reason_code, case["id"]
            assert str(again.authority) == str(first.authority), case["id"]
