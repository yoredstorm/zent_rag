# =============================================================================
# Catálogo único de reason codes — contrato y no-vocabulario-paralelo.
# =============================================================================
from __future__ import annotations

from types import SimpleNamespace

from src.runtime import reason_codes
from src.runtime.finalization_policy import evaluate_finalization
from src.runtime.reason_codes import ALL_REASON_CODES, is_known_reason_code
from src.runtime.run_guards import RunEvent, evaluate_transition
from src.runtime.run_state import AgentRunState, RunIdentity, RunPhase


def _state(
    *,
    evidence: str = "unknown",
    reasoning_incomplete: bool = False,
    authority: str = "none",
    requires_deterministic: bool = False,
    budget_exhausted: bool = False,
) -> AgentRunState:
    state = AgentRunState(identity=RunIdentity(run_id="run-1"))
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
                missing_entities=(),
                missing_anchors=(),
            )
        )
    elif evidence == "failed":
        state.evidence.retrieval_failed = True
    if authority == "positive":
        state.decisions.set_envelope(
            SimpleNamespace(authoritative=True, state="MATCH")
        )
    elif authority == "negative":
        state.decisions.set_envelope(
            SimpleNamespace(authoritative=True, state="NO_MATCH")
        )
    state.decisions.requires_deterministic = requires_deterministic
    if reasoning_incomplete:
        state.reasoning.run = SimpleNamespace(
            enabled=True,
            is_complex=True,
            analysis_complete=False,
            blocks_early_answer=True,
        )
    if budget_exhausted:
        state.budget.ledger = SimpleNamespace(
            remaining_tokens=0, remaining_cost_usd=None
        )
    return state


class TestCatalogo:
    def test_sin_duplicados_ni_valores_rotos(self) -> None:
        values = [
            value
            for name, value in vars(reason_codes).items()
            if name.isupper() and isinstance(value, str)
            and name != "REASON_CODES_VERSION"
        ]
        assert len(values) == len(set(values))
        assert set(values) == set(ALL_REASON_CODES)

    def test_version_estable(self) -> None:
        assert reason_codes.REASON_CODES_VERSION == "reason-codes-1"

    def test_desconocido_no_es_senal(self) -> None:
        assert is_known_reason_code("READY") is True
        assert is_known_reason_code("NOPE_NOT_A_CODE") is False
        assert is_known_reason_code("") is False


class TestFinalizationEmiteSoloCatalogo:
    def test_matriz_completa(self) -> None:
        seen: set[str] = set()
        for evidence in ("unknown", "complete", "insufficient", "failed"):
            for authority in ("none", "positive", "requires"):
                for budget in (False, True):
                    for draft in (False, True):
                        for termination in (False, True):
                            state = _state(
                                evidence=evidence,
                                authority=(
                                    "positive"
                                    if authority == "positive"
                                    else "none"
                                ),
                                requires_deterministic=authority == "requires",
                                budget_exhausted=budget,
                            )
                            decision = evaluate_finalization(
                                state,
                                retrieval_possible=evidence != "failed",
                                termination_requested=termination,
                                draft_available=draft,
                                jev_verdict="uncertain",
                            )
                            assert is_known_reason_code(decision.reason_code), (
                                f"código fuera del catálogo: {decision.reason_code}"
                            )
                            for code in decision.signals_ignored:
                                assert is_known_reason_code(code), code
                            for code in decision.conflicts:
                                assert is_known_reason_code(code), code
                            seen.add(decision.reason_code)
        assert "READY" in seen
        assert "EVIDENCE_INCOMPLETE" in seen
        assert "RETRIEVAL_UNAVAILABLE" in seen
        assert "UNDETERMINED" not in seen  # es acción, no reason code

    def test_tool_solo_catalogo(self) -> None:
        state = _state(evidence="complete")
        for requested, authorized in ((True, False), (True, True), (False, False)):
            decision = evaluate_finalization(
                state,
                tool_requested=requested,
                tool_authorized=authorized,
                draft_available=True,
            )
            assert is_known_reason_code(decision.reason_code)


class TestGuardsEmitenSoloCatalogo:
    def test_matriz_de_transiciones(self) -> None:
        phases = (
            RunPhase.REASONING,
            RunPhase.RETRIEVING,
            RunPhase.ACTING,
            RunPhase.READY_TO_FINALIZE,
            RunPhase.FINALIZED,
            RunPhase.ABSTAINED,
            RunPhase.BLOCKED,
            RunPhase.UNDETERMINED,
        )
        for phase in phases:
            for event in RunEvent:
                for flags in (
                    {},
                    {"tool_authorized": True},
                    {"tool_authorized": True, "duplicate_tool_call": True},
                    {"budget_exhausted": True},
                    {"requires_deterministic": True},
                    {"analysis_incomplete": True},
                    {"tool_failure": "transient"},
                    {"tool_failure": "permanent"},
                    {"tool_authorized": True, "budget_exhausted": True},
                ):
                    verdict = evaluate_transition(phase, event, **flags)
                    assert is_known_reason_code(verdict.reason_code), (
                        f"código fuera del catálogo: {verdict.reason_code}"
                    )
