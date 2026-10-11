# =============================================================================
# Políticas del runtime — guards de transición, valor JEV y contexto (P3/P4/P6)
# =============================================================================
from __future__ import annotations

from src.runtime.context_envelope import (
    ContextOrigin,
    ContextTrust,
    build_context_envelope,
)
from src.runtime.jev_value import classify_gate_value, summarize_jev_value
from src.runtime.run_guards import RunEvent, evaluate_transition
from src.runtime.run_state import RunPhase


class TestRunGuards:
    def test_terminal_no_transiciona(self) -> None:
        for event in RunEvent:
            verdict = evaluate_transition(RunPhase.FINALIZED, event)
            assert verdict.allowed is False
            assert verdict.reason_code == "TERMINAL_NO_TRANSITIONS"

    def test_tool_sin_autorizacion_no_ejecuta(self) -> None:
        verdict = evaluate_transition(
            RunPhase.REASONING, RunEvent.REQUEST_TOOL, tool_authorized=False
        )
        assert verdict.allowed is False
        assert verdict.to_phase is RunPhase.REASONING
        assert verdict.reason_code == "TOOL_NOT_AUTHORIZED"

    def test_tool_autorizada_transiciona_a_acting(self) -> None:
        verdict = evaluate_transition(
            RunPhase.REASONING, RunEvent.REQUEST_TOOL, tool_authorized=True
        )
        assert verdict.allowed is True
        assert verdict.to_phase is RunPhase.ACTING

    def test_duplicate_tool_call_bloquea_en_run(self) -> None:
        verdict = evaluate_transition(
            RunPhase.REASONING,
            RunEvent.REQUEST_TOOL,
            tool_authorized=True,
            duplicate_tool_call=True,
        )
        assert verdict.allowed is False
        assert verdict.reason_code == "DUPLICATE_TOOL_CALL"

    def test_budget_agotado_no_gasta_mas(self) -> None:
        tool = evaluate_transition(
            RunPhase.REASONING,
            RunEvent.REQUEST_TOOL,
            tool_authorized=True,
            budget_exhausted=True,
        )
        assert tool.allowed is False
        assert tool.reason_code == "BUDGET_EXHAUSTED"
        retrieval = evaluate_transition(
            RunPhase.REASONING, RunEvent.REQUEST_RETRIEVAL, budget_exhausted=True
        )
        assert retrieval.allowed is False
        assert retrieval.to_phase is RunPhase.READY_TO_FINALIZE

    def test_ejecutable_sin_autoridad_no_finaliza_binario(self) -> None:
        verdict = evaluate_transition(
            RunPhase.READY_TO_FINALIZE,
            RunEvent.REQUEST_FINALIZE,
            requires_deterministic=True,
            authority_present=False,
        )
        assert verdict.allowed is True
        assert verdict.to_phase is RunPhase.UNDETERMINED
        assert verdict.reason_code == "AUTHORITY_MISSING_FOR_EXECUTABLE"

    def test_analisis_incompleto_no_finaliza(self) -> None:
        verdict = evaluate_transition(
            RunPhase.READY_TO_FINALIZE,
            RunEvent.REQUEST_FINALIZE,
            analysis_incomplete=True,
        )
        assert verdict.allowed is False
        assert verdict.to_phase is RunPhase.REASONING
        assert verdict.reason_code == "ANALYSIS_INCOMPLETE"

    def test_budget_con_evidencia_finaliza_degradado(self) -> None:
        verdict = evaluate_transition(
            RunPhase.READY_TO_FINALIZE,
            RunEvent.REQUEST_FINALIZE,
            budget_exhausted=True,
            evidence_available=True,
        )
        assert verdict.allowed is True
        assert verdict.reason_code == "BUDGET_EXHAUSTED_WITH_EVIDENCE"

    def test_tool_failure_transitorio_reintenta_definitivo_no(self) -> None:
        transient = evaluate_transition(
            RunPhase.ACTING, RunEvent.OBSERVE_TOOL_RESULT, tool_failure="transient"
        )
        assert transient.allowed is True
        assert transient.reason_code == "TOOL_RETRY_ALLOWED"
        permanent = evaluate_transition(
            RunPhase.ACTING, RunEvent.OBSERVE_TOOL_RESULT, tool_failure="permanent"
        )
        assert permanent.allowed is False
        assert permanent.reason_code == "TOOL_FAILED_PERMANENT_NO_RETRY"


class TestJevValue:
    def test_clasificacion(self) -> None:
        assert classify_gate_value("approve", "approve") == "CONFIRMED"
        assert classify_gate_value("retrieve_more", "approve") == "PREVENTED"
        assert classify_gate_value("abstain", "approve") == "PREVENTED"
        assert classify_gate_value("approve", "retrieve_more") == "CHANGED"
        assert classify_gate_value("", "approve") == "UNCLASSIFIED"

    def test_resumen_desde_steps(self) -> None:
        steps = [
            {
                "type": "evidence_sufficiency",
                "recommended_action": "generate",
            },
            {"type": "answer_gate", "verdict": "approve", "mode": "on"},
            {"type": "answer_gate", "verdict": "retrieve_more", "mode": "on"},
            {"type": "answer_gate", "verdict": "approve", "mode": "passthrough"},
            {"type": "termination_gate", "stop": True, "provider": "jev"},
        ]
        summary = summarize_jev_value(steps)
        assert summary["calls"] == 3
        assert summary["by_phase"]["answer_gate"] == 3
        assert summary["by_phase"]["termination"] == 1
        assert summary["values"]["CONFIRMED"] == 1
        assert summary["values"]["PREVENTED"] == 1
        assert summary["values"]["SKIPPED"] == 1
        assert summary["values"]["UNCLASSIFIED"] == 1
        assert summary["redundant_rate"] == 0.5

    def test_sin_steps(self) -> None:
        summary = summarize_jev_value([])
        assert summary["calls"] == 0
        assert summary["redundant_rate"] is None


class TestContextEnvelope:
    def _envelope(self):
        return build_context_envelope(
            tenant_id="org-1",
            conversation_id="conv-1",
            memory_labels=("prefiere respuestas cortas",),
            company_section_labels=("política de reembolsos",),
            evidence_ids=("E1", "E2"),
            workflow_keys=("approval_id",),
            tool_observation_labels=("search_knowledge",),
        )

    def test_trust_y_scope_por_origen(self) -> None:
        envelope = self._envelope()
        evidence = envelope.of(ContextOrigin.EVIDENCE)
        assert all(item.trust is ContextTrust.AUTHORITATIVE for item in evidence)
        memory = envelope.of(ContextOrigin.MEMORY)
        assert all(item.trust is ContextTrust.SUPPORTING for item in memory)
        tools = envelope.of(ContextOrigin.TOOL_OBSERVATION)
        assert all(item.trust is ContextTrust.UNTRUSTED for item in tools)

    def test_memory_no_es_evidence(self) -> None:
        envelope = self._envelope()
        assert envelope.of(ContextOrigin.MEMORY)
        assert not any(item.is_evidence for item in envelope.of(ContextOrigin.MEMORY))
        assert all(item.is_evidence for item in envelope.of(ContextOrigin.EVIDENCE))

    def test_isolation_key_incluye_conversation(self) -> None:
        envelope = self._envelope()
        payload = envelope.to_public_dict()
        assert payload["isolation_key"] == "org-1:conv-1"
        assert all(
            item.to_public_dict()["isolation_key"] == "org-1:conv-1"
            for item in envelope.items
        )

    def test_company_context_no_es_autoritativo(self) -> None:
        envelope = self._envelope()
        company = envelope.of(ContextOrigin.COMPANY_CONTEXT)
        assert company
        assert all(item.trust is not ContextTrust.AUTHORITATIVE for item in company)

    def test_workflow_es_input_no_instruccion(self) -> None:
        envelope = self._envelope()
        workflow = envelope.of(ContextOrigin.WORKFLOW)
        assert workflow
        assert all(item.scope.value == "RUN" for item in workflow)

    def test_untrusted_lista_tools(self) -> None:
        assert self._envelope().untrusted()
