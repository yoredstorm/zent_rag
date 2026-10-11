# =============================================================================
# Políticas del runtime — guards de transición, valor JEV y contexto (P3/P4/P6)
# =============================================================================
from __future__ import annotations

import pytest

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


class TestGateAbstentionAdoption:
    @staticmethod
    def _state(*, evidence: str = "unknown", authority: str = "none"):
        from types import SimpleNamespace

        from src.runtime.run_state import AgentRunState, RunIdentity

        state = AgentRunState(identity=RunIdentity(run_id="gate-abstention"))
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
                    missing_entities=("campo_x",),
                    missing_anchors=(),
                )
            )
        elif evidence == "failed":
            state.evidence.retrieval_failed = True
        if authority == "positive":
            state.decisions.set_envelope(
                SimpleNamespace(authoritative=True, state="MATCH")
            )
        return state

    def test_evidencia_alcanza_no_abstiene(self) -> None:
        from src.runtime.finalization_policy import gate_abstention_action

        state = self._state(evidence="complete")
        assert (
            gate_abstention_action(state, draft_available=True)
            == "answer_with_limits"
        )

    def test_evidencia_insuficiente_sin_draft_abstiene(self) -> None:
        from src.runtime.finalization_policy import gate_abstention_action

        state = self._state(evidence="insufficient")
        assert gate_abstention_action(state, draft_available=False) == "abstain"

    def test_evidencia_insuficiente_con_draft_tambien_abstiene(self) -> None:
        from src.runtime.finalization_policy import gate_abstention_action

        state = self._state(evidence="insufficient")
        assert gate_abstention_action(state, draft_available=True) == "abstain"

    def test_retrieval_fallido_abstiene(self) -> None:
        from src.runtime.finalization_policy import gate_abstention_action

        state = self._state(evidence="failed")
        assert gate_abstention_action(state, draft_available=True) == "abstain"

    def test_autoridad_sin_evidencia_no_es_tarea_del_helper(self) -> None:
        """El envelope lo resuelve el runtime antes de llegar a este helper."""
        from src.runtime.finalization_policy import gate_abstention_action

        state = self._state(authority="positive")
        assert gate_abstention_action(state, draft_available=True) == "abstain"


class TestJevAccounting:
    def test_record_judge_call_suma_tokens_y_step(self) -> None:
        from uuid import uuid4

        from src.agents.runtime.agent_runtime import AgentRunResult
        from src.runtime.run_accounting import record_judge_call

        result = AgentRunResult(
            run_id=uuid4(),
            agent_id=uuid4(),
            organization_id=None,
            status="completed",
            answer="x",
        )
        record_judge_call(
            result, purpose="answer_gate", prompt_tokens=120, completion_tokens=30
        )
        assert result.prompt_tokens == 120
        assert result.completion_tokens == 30
        assert result.total_tokens == 150
        assert result.steps[-1]["type"] == "jev_usage"
        assert result.steps[-1]["purpose"] == "answer_gate"
        record_judge_call(result, purpose="agent_step")
        assert len(result.steps) == 1  # sin tokens no ensucia la traza

    @pytest.mark.asyncio
    async def test_answer_gate_expone_tokens_del_juez(self) -> None:
        from src.runtime.answer_gate import judge_answer

        class _UsageEngine:
            def __init__(self) -> None:
                self.answers = {
                    "answer_grounded": {"type": "noul", "noul": 0.95},
                    "answer_complete": {"type": "noul", "noul": 0.9},
                    "answer_quality": {"type": "score", "score": 1.0},
                }

            async def judge(self, *, state, questions, context=None):
                return {
                    "model": "jev-test",
                    "answers": dict(self.answers),
                    "usage": {"input_tokens": 111, "output_tokens": 22},
                }

        gate = await judge_answer(
            engine=_UsageEngine(),
            mode="on",
            user_request="¿cumple?",
            draft="Sí, cumple.",
            settings=object(),
            retrieval_rounds_left=0,
        )
        assert gate.prompt_tokens == 111
        assert gate.completion_tokens == 22
        assert gate.to_step()["jev_tokens"] == {"input": 111, "output": 22}

    @pytest.mark.asyncio
    async def test_termination_expone_tokens_del_pack(self) -> None:
        from src.runtime.termination import original_request_satisfied

        class _UsageEngine:
            async def judge(self, *, state, questions, context=None):
                return {
                    "model": "jev-test",
                    "answers": {"request_satisfied": {"type": "noul", "noul": 0.95}},
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                }

        outcome = await original_request_satisfied(
            engine=_UsageEngine(),
            user_request="q",
            history=["OBSERVATION: algo"],
            tool_calls=1,
        )
        assert outcome["prompt_tokens"] == 10
        assert outcome["completion_tokens"] == 5


class TestStoryView:
    def test_business_normaliza_reason_codes(self) -> None:
        from src.runtime.story_view import build_story

        steps = [
            {
                "type": "evidence_sufficiency",
                "status": "ok",
                "recommended_action": "generate",
                "supporting_chunks": 4,
                "latency_ms": 12,
            },
            {
                "type": "answer_gate",
                "status": "ok",
                "verdict": "answer_with_limits",
                "grounding_verdict": "PARTIAL",
                "latency_ms": 30,
            },
            {"type": "tool_call", "tool": "search_knowledge", "output": "x" * 500},
            {
                "type": "finalization_policy",
                "status": "warn",
                "action": "UNDETERMINED",
                "authority": "DETERMINISTIC",
                "signals_ignored": ["jev_only_negative_signal"],
            },
        ]
        story = build_story(steps, view="business")
        assert story["view"] == "business"
        rows = story["steps"]
        assert rows[0]["type"] == "evidence_evaluation"
        assert rows[0]["reason_code"] == "EVIDENCE_COMPLETE"
        assert rows[0]["facts"]["supporting_chunks"] == 4
        assert rows[1]["reason_code"] == "ANSWER_LIMITED"
        assert rows[2]["reason_code"] == "TOOL_EXECUTED"
        assert rows[3]["reason_code"] == "AUTHORITY_UNDETERMINED"
        assert rows[3]["facts"]["signals_ignored"] == ["jev_only_negative_signal"]
        # Sin campos técnicos en la vista de negocio.
        assert "latency_ms" not in rows[0]
        assert "output" not in rows[2]

    def test_technical_trunca_contenido_pesado(self) -> None:
        from src.runtime.story_view import build_story

        story = build_story(
            [{"type": "tool_call", "output": "x" * 500, "latency_ms": 3}],
            view="technical",
        )
        row = story["steps"][0]
        assert len(row["output"]) == 240
        assert row["output_truncated"] is True
        assert row["latency_ms"] == 3


class TestJevSkips:
    def test_skip_phases_from_settings(self) -> None:
        from types import SimpleNamespace

        from src.runtime.jev_value import skip_phases_from_settings

        assert skip_phases_from_settings(
            SimpleNamespace(RUNTIME_JEV_SKIP_PHASES="answer_gate, agent_step")
        ) == frozenset({"answer_gate", "agent_step"})
        assert skip_phases_from_settings(SimpleNamespace()) == frozenset()
        assert (
            skip_phases_from_settings(SimpleNamespace(RUNTIME_JEV_SKIP_PHASES=" , "))
            == frozenset()
        )

    def test_phase_skipped_default_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from types import SimpleNamespace

        import src.core.config as config_module
        from src.runtime.jev_value import phase_skipped

        monkeypatch.setattr(
            config_module,
            "get_settings",
            lambda: SimpleNamespace(RUNTIME_JEV_SKIP_PHASES=""),
        )
        assert phase_skipped("answer_gate") is False

    def test_phase_skipped_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from types import SimpleNamespace

        import src.core.config as config_module
        from src.runtime.jev_value import phase_skipped

        monkeypatch.setattr(
            config_module,
            "get_settings",
            lambda: SimpleNamespace(RUNTIME_JEV_SKIP_PHASES="answer_gate"),
        )
        assert phase_skipped("answer_gate") is True
        assert phase_skipped("termination") is False

    @pytest.mark.asyncio
    async def test_gate_no_llama_al_engine_si_fase_salteada(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from types import SimpleNamespace

        import src.core.config as config_module
        from src.runtime.answer_gate import judge_answer

        monkeypatch.setattr(
            config_module,
            "get_settings",
            lambda: SimpleNamespace(RUNTIME_JEV_SKIP_PHASES="answer_gate"),
        )

        class _Engine:
            calls = 0

            async def judge(self, *, state, questions, context=None):
                _Engine.calls += 1
                return {"answers": {}}

        gate = await judge_answer(
            engine=_Engine(),
            mode="on",
            user_request="¿cumple?",
            draft="Sí, cumple.",
            settings=object(),
        )
        assert gate.verdict == "skipped"
        assert gate.provider == "skip_config"
        assert _Engine.calls == 0

    @pytest.mark.asyncio
    async def test_termination_no_llama_si_fase_salteada(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from types import SimpleNamespace

        import src.core.config as config_module
        from src.runtime.termination import original_request_satisfied

        monkeypatch.setattr(
            config_module,
            "get_settings",
            lambda: SimpleNamespace(RUNTIME_JEV_SKIP_PHASES="termination"),
        )

        class _Engine:
            calls = 0

            async def judge(self, *, state, questions, context=None):
                _Engine.calls += 1
                return {"answers": {}}

        outcome = await original_request_satisfied(
            engine=_Engine(),
            user_request="q",
            history=["OBSERVATION: x"],
            tool_calls=1,
        )
        assert outcome["provider"] == "skip_config"
        assert outcome["stop"] is False
        assert _Engine.calls == 0
