# =============================================================================
# Answerability Engine — tests unitarios (sin infraestructura)
# =============================================================================
# Cubre: gate determinista y su orden de prioridad, los 10 estados, confianza
# discreta (sin falsa precisión), abstention estructurada (DATA vs CONTEXT
# missing), source conflict, planner, FSM + límites duros, loop prevention.
# =============================================================================
from __future__ import annotations

import time
from uuid import UUID

import pytest

from src.core.domain.intelligence import (
    AnswerabilityDecision,
    AnswerabilityStatus,
    Budget,
    BudgetLimits,
    ConfidenceLevel,
    EvidenceObject,
    EvidenceType,
    PlanStrategy,
    QueryPlan,
    QueryUnderstanding,
    ToolFingerprint,
)
from src.intelligence.abstention import AbstentionBuilder
from src.intelligence.answerability import (
    AnswerabilityGate,
    detect_source_conflicts,
)
from src.intelligence.fsm import (
    FSMViolation,
    IntelligenceState,
    IntelligenceStateMachine,
)
from src.intelligence.loop_guard import LoopGuard, SQLRepairGuard
from src.intelligence.planner import QueryPlanner
from src.intelligence.signals import SignalCollector, SignalSet
from src.intelligence.understanding import QueryUnderstandingService

ORG = UUID("00000000-0000-0000-0000-000000000001")


def _evidence(source: str, value: float, etype: EvidenceType = EvidenceType.SQL_RESULT) -> EvidenceObject:
    return EvidenceObject(
        type=etype,
        source_name=source,
        authority_level="authoritative",
        value=value,
        validation_status="valid",
        access_verified=True,
    )


def _understanding(**kwargs) -> QueryUnderstanding:
    base = dict(
        intent="business_metric",
        concepts=["cliente_rentable"],
        resolved_concepts={"cliente_rentable": True},
        requires_structured_data=True,
    )
    base.update(kwargs)
    return QueryUnderstanding(**base)


class TestAnswerabilityStates:
    def test_ten_formal_states_exist(self) -> None:
        expected = {
            "ANSWERABLE",
            "CLARIFICATION_REQUIRED",
            "CONTEXT_MISSING",
            "DATA_MISSING",
            "DATA_QUALITY_LOW",
            "AMBIGUOUS",
            "ACCESS_BLOCKED",
            "SOURCE_CONFLICT",
            "EXECUTION_FAILED",
            "HUMAN_REVIEW_REQUIRED",
        }
        assert {s.value for s in AnswerabilityStatus} == expected


class TestConfidenceMapping:
    @pytest.mark.parametrize(
        "score,expected",
        [
            (0.95, ConfidenceLevel.HIGH),
            (0.8, ConfidenceLevel.HIGH),
            (0.79, ConfidenceLevel.MEDIUM),
            (0.6, ConfidenceLevel.MEDIUM),
            (0.59, ConfidenceLevel.LOW),
            (0.4, ConfidenceLevel.LOW),
            (0.39, ConfidenceLevel.INSUFFICIENT),
            (0.0, ConfidenceLevel.INSUFFICIENT),
        ],
    )
    def test_discrete_levels_no_false_precision(
        self, score: float, expected: ConfidenceLevel
    ) -> None:
        assert AnswerabilityGate.confidence_level(score) == expected


class TestQueryUnderstandingDeterministic:
    def setup_method(self) -> None:
        self.service = QueryUnderstandingService(concept_llm_enabled=False)

    def test_business_metric_intent(self) -> None:
        u = self.service.understand_deterministic(
            "¿Cuántos clientes corporativos rentables tenemos actualmente?"
        )
        assert u.intent == "business_metric"
        assert u.requires_structured_data is True
        assert u.time_scope == "current"
        assert "clientes" in u.concepts
        assert "rentables" in u.concepts

    def test_document_policy_intent(self) -> None:
        u = self.service.understand_deterministic("¿Cuál es la política de devolución?")
        assert u.intent == "document_policy"
        assert u.requires_documents is True
        assert u.requires_structured_data is False

    def test_operational_status_intent(self) -> None:
        u = self.service.understand_deterministic("¿Cuál es el estado actual del envío?")
        assert u.intent == "operational_status"
        assert u.requires_tools is True

    def test_concept_definition_intent(self) -> None:
        u = self.service.understand_deterministic("¿Qué significa cliente rentable?")
        assert u.intent == "concept_definition"
        assert u.requires_documents is True

    def test_general_intent(self) -> None:
        u = self.service.understand_deterministic("Hola, buenos días")
        assert u.intent == "general"

    def test_concept_types_populated_and_definitional_filtered(self) -> None:
        u = self.service.understand_deterministic(
            "¿Cuántos clientes corporativos rentables tenemos?"
        )
        assert u.concept_types.get("clientes") == "ENTITY"
        assert u.concept_types.get("corporativos") == "SEGMENT"
        assert u.concept_types.get("rentables") == "BUSINESS_RULE"
        assert "clientes" not in u.requires_definition
        assert "corporativos" in u.requires_definition
        assert "rentables" in u.requires_definition
        assert "concept_types" in u.to_dict()

    def test_sales_fact_does_not_require_definition(self) -> None:
        u = self.service.understand_deterministic("¿Cuántas ventas hubo ayer?")
        assert "ventas" in u.concepts
        assert u.concept_types.get("ventas") == "FACT"
        assert u.requires_definition == []

    def test_merge_llm_classifies_instead_of_all_concepts_definitional(self) -> None:
        base = self.service.understand_deterministic("¿Cuántas ventas hubo ayer?")
        merged = QueryUnderstandingService._merge_llm(
            base,
            {
                "intent": "business_metric",
                "entities": ["Aeroméxico"],
                "concepts": ["cliente", "venta", "margen"],
                "time_scope": "past",
                "requires_structured_data": True,
                "requires_documents": False,
                "requires_tools": False,
                "ambiguity": False,
                "clarifying_question": None,
            },
        )
        assert merged.extraction_source == "llm"
        assert merged.entities == ["Aeroméxico"]
        assert merged.concept_types.get("cliente") == "ENTITY"
        assert merged.concept_types.get("venta") == "FACT"
        assert merged.concept_types.get("margen") == "DERIVED_METRIC"
        assert merged.requires_definition == ["margen"]
        assert "cliente" not in merged.requires_definition
        assert "venta" not in merged.requires_definition


class TestQueryPlanner:
    def setup_method(self) -> None:
        self.planner = QueryPlanner()

    def test_metric_with_sql(self) -> None:
        plan = self.planner.plan(
            _understanding(), query="¿Cuánto vendimos en agosto?",
            sql_available=True, router_score=0.8,
        )
        assert plan.strategy == PlanStrategy.SQL

    def test_policy_goes_rag(self) -> None:
        plan = self.planner.plan(
            _understanding(intent="document_policy", requires_structured_data=False),
            query="¿Cuál es la política de devolución?",
            sql_available=True, router_score=0.8,
        )
        assert plan.strategy == PlanStrategy.RAG

    def test_causal_metric_goes_sql_rag(self) -> None:
        plan = self.planner.plan(
            _understanding(), query="¿Por qué cayó la venta de agosto?",
            sql_available=True, router_score=0.8,
        )
        assert plan.strategy == PlanStrategy.SQL_RAG
        assert plan.needs_sql and plan.needs_retrieval

    def test_operational_status_prefers_tool(self) -> None:
        plan = self.planner.plan(
            _understanding(intent="operational_status", requires_structured_data=False),
            query="¿Cuál es el estado actual del envío?",
            sql_available=True, tools_available=True,
        )
        assert plan.strategy == PlanStrategy.API_TOOL

    def test_concept_definition_goes_rag(self) -> None:
        plan = self.planner.plan(
            _understanding(intent="concept_definition", requires_structured_data=False),
            query="¿Qué significa cliente rentable?",
            sql_available=True,
        )
        assert plan.strategy == PlanStrategy.RAG
        assert plan.needs_semantic_resolution

    def test_ambiguous_with_question_goes_clarification(self) -> None:
        plan = self.planner.plan(
            _understanding(
                ambiguity=True, clarifying_question="¿Quieres margen bruto o neto?"
            ),
            query="¿Cuál es el margen del último trimestre?",
            sql_available=True,
        )
        # Con fuentes disponibles se recopila evidencia; el gate decide la
        # aclaración post-evidencia (no frictiona con datos en mano).
        assert plan.strategy != PlanStrategy.CLARIFICATION
        assert plan.needs_sql or plan.needs_retrieval

    def test_ambiguous_without_sources_goes_abstain(self) -> None:
        """Sin fuentes, la abstención (DATA_MISSING) es más informativa que clarificar."""
        plan = self.planner.plan(
            _understanding(
                ambiguity=True, clarifying_question="¿Quieres margen bruto o neto?"
            ),
            query="¿Cuál es el margen del último trimestre?",
            sql_available=False, kb_available=False, tools_available=False,
        )
        assert plan.strategy == PlanStrategy.ABSTAIN

    def test_no_sources_goes_abstain(self) -> None:
        plan = self.planner.plan(
            _understanding(), query="¿Cuánto vendimos en agosto?",
            sql_available=False, kb_available=False, tools_available=False,
        )
        assert plan.strategy == PlanStrategy.ABSTAIN


def _gate_signals(**overrides) -> SignalSet:
    base = dict(
        intent_resolution=1.0,
        concept_resolution=1.0,
        schema_link_quality=1.0,
        retrieval_relevance=0.8,
        retrieval_coverage=0.8,
        sql_validation=1.0,
        sql_execution_success=1.0,
        result_presence=1.0,
        result_relevance=1.0,
        source_freshness=1.0,
        source_authority=1.0,
        source_agreement=1.0,
        business_definition_status=1.0,
        permission_check=1.0,
        data_quality=1.0,
        ambiguity=0.0,
    )
    base.update(overrides)
    return SignalSet(**base)


class TestAnswerabilityGate:
    def setup_method(self) -> None:
        self.gate = AnswerabilityGate(min_score=0.6)

    def _eval(self, signals: SignalSet, understanding=None, plan=None, evidences=None, **kwargs):
        return self.gate.evaluate(
            signals,
            understanding or _understanding(),
            plan or QueryPlan(strategy=PlanStrategy.SQL, needs_sql=True),
            evidences or [],
            **kwargs,
        )

    def test_access_blocked(self) -> None:
        decision = self._eval(
            _gate_signals(permission_check=0.0),
            evidences=[_evidence("ERP", 10.0)],
        )
        assert decision.status == AnswerabilityStatus.ACCESS_BLOCKED
        assert not decision.answerable
        assert "PERMISSION_DENIED" in decision.reason_codes

    def test_access_blocked_from_sql_error_hint(self) -> None:
        decision = self._eval(
            _gate_signals(),
            execution_error="Column 'salary' is blocked for role 'admin'",
        )
        assert decision.status == AnswerabilityStatus.ACCESS_BLOCKED

    def test_execution_failed_without_evidence(self) -> None:
        decision = self._eval(
            _gate_signals(),
            execution_error="cannot generate query for this question",
        )
        assert decision.status == AnswerabilityStatus.EXECUTION_FAILED

    def test_source_conflict_beats_answer(self) -> None:
        decision = self._eval(
            _gate_signals(source_agreement=0.0),
            evidences=[
                _evidence("ERP", 120.0),
                _evidence("Documento", 100.0),
            ],
        )
        assert decision.status == AnswerabilityStatus.SOURCE_CONFLICT
        assert len(decision.conflicting_sources) >= 1

    def test_clarification_required(self) -> None:
        decision = self._eval(
            _gate_signals(result_presence=0.0),
            understanding=_understanding(
                ambiguity=True, clarifying_question="¿Bruto o neto?"
            ),
            evidences=[],
        )
        assert decision.status == AnswerabilityStatus.CLARIFICATION_REQUIRED
        assert decision.clarifying_question == "¿Bruto o neto?"

    def test_clarification_not_asked_when_evidence_exists(self) -> None:
        """Con evidencia contestable NO se pide aclaración (se responde)."""
        decision = self._eval(
            _gate_signals(),
            understanding=_understanding(
                ambiguity=True, clarifying_question="¿Bruto o neto?"
            ),
            evidences=[_evidence("ERP", 10.0)],
        )
        assert decision.status == AnswerabilityStatus.ANSWERABLE

    def test_ambiguous_without_question(self) -> None:
        decision = self._eval(
            _gate_signals(result_presence=0.0),
            understanding=_understanding(ambiguity=True, clarifying_question=None),
            evidences=[],
        )
        assert decision.status == AnswerabilityStatus.AMBIGUOUS

    def test_context_missing_undefined_concept(self) -> None:
        decision = self._eval(
            _gate_signals(concept_resolution=0.0, business_definition_status=0.0),
            understanding=_understanding(
                resolved_concepts={"cliente_activo": False},
                requires_definition=["cliente_activo"],
            ),
            evidences=[_evidence("ERP", 10.0)],
        )
        assert decision.status == AnswerabilityStatus.CONTEXT_MISSING
        assert "Definition of cliente_activo" in decision.missing_context

    def test_non_definitional_concept_does_not_abstain(self) -> None:
        """Un sustantivo genérico sin regla empresarial no dispara CONTEXT_MISSING."""
        decision = self._eval(
            _gate_signals(),
            understanding=_understanding(
                concepts=["devoluciones"],
                requires_definition=[],
                resolved_concepts={"devoluciones": False},
            ),
            evidences=[_evidence("ERP", 10.0)],
        )
        assert decision.status == AnswerabilityStatus.ANSWERABLE

    def test_data_missing_no_data_at_all(self) -> None:
        decision = self._eval(_gate_signals(result_presence=0.0))
        assert decision.status == AnswerabilityStatus.DATA_MISSING
        assert decision.missing_data

    def test_data_quality_low(self) -> None:
        decision = self._eval(
            _gate_signals(
                result_presence=1.0,
                retrieval_coverage=0.05,
                source_freshness=0.2,
                source_authority=0.4,
                sql_validation=0.0,
                sql_execution_success=0.0,
                schema_link_quality=0.5,
            ),
            plan=QueryPlan(strategy=PlanStrategy.RAG, needs_retrieval=True),
            evidences=[_evidence("KB", 10.0, EvidenceType.DOCUMENT_CHUNK)],
        )
        assert decision.status == AnswerabilityStatus.DATA_QUALITY_LOW

    def test_human_review_required_low_score(self) -> None:
        """Evidencia presente, sin flag específico de calidad, pero score < umbral."""
        decision = self._eval(
            _gate_signals(
                result_presence=1.0,
                retrieval_relevance=0.2,
                retrieval_coverage=0.2,
                result_relevance=0.2,
                source_freshness=0.5,
                source_authority=0.6,
                concept_resolution=1.0,
            ),
            plan=QueryPlan(strategy=PlanStrategy.RAG, needs_retrieval=True),
            evidences=[_evidence("KB", 10.0, EvidenceType.DOCUMENT_CHUNK)],
        )
        assert decision.status == AnswerabilityStatus.HUMAN_REVIEW_REQUIRED
        assert not decision.answerable

    def test_answerable_with_strong_signals(self) -> None:
        decision = self._eval(
            _gate_signals(),
            evidences=[_evidence("ERP", 10.0)],
        )
        assert decision.status == AnswerabilityStatus.ANSWERABLE
        assert decision.answerable
        assert decision.confidence_level == ConfidenceLevel.HIGH

    def test_empty_sql_result_is_valid_answer_case8(self) -> None:
        """Case 8: 'resultado = 0' NO es DATA_MISSING si el SQL se ejecutó."""
        decision = self._eval(_gate_signals(), evidences=[])
        assert decision.status == AnswerabilityStatus.ANSWERABLE
        assert decision.answerable

    def test_no_sql_no_chunks_is_data_missing(self) -> None:
        decision = self._eval(_gate_signals(result_presence=0.0), evidences=[])
        assert decision.status == AnswerabilityStatus.DATA_MISSING
        assert not decision.answerable


class TestSourceConflictDetection:
    def test_conflict_detected(self) -> None:
        conflicts = detect_source_conflicts(
            [_evidence("ERP", 120.0), _evidence("Documento", 100.0)]
        )
        assert len(conflicts) == 1
        assert conflicts[0]["source_a"] in ("ERP", "Documento")

    def test_tolerance_respects_small_diffs(self) -> None:
        conflicts = detect_source_conflicts(
            [_evidence("ERP", 100.0), _evidence("Documento", 102.0)],
            tolerance_pct=5.0,
        )
        assert conflicts == []

    def test_authoritative_source_resolves_conflict(self) -> None:
        conflicts = detect_source_conflicts(
            [_evidence("ERP", 120.0), _evidence("Documento", 100.0)],
            authoritative_source="ERP",
        )
        assert conflicts == []

    def test_no_conflict_single_source(self) -> None:
        conflicts = detect_source_conflicts([_evidence("ERP", 120.0)])
        assert conflicts == []


class TestAbstentionBuilder:
    def test_context_missing_explains_what_is_missing(self) -> None:
        decision = AnswerabilityDecision(
            status=AnswerabilityStatus.CONTEXT_MISSING,
            answerable=False,
            confidence_level=ConfidenceLevel.LOW,
            reason_codes=["UNDEFINED_BUSINESS_TERM"],
            missing_context=["Definition of active_customer"],
            found=["CUSTOMER.STATUS_CD", "CUSTOMER.LAST_PURCHASE"],
            message=(
                "Puedo identificar clientes y sus estados, pero no existe una "
                "definición empresarial aprobada de cliente activo."
            ),
        )
        abstention = AbstentionBuilder.build(decision)
        assert abstention.status == "CONTEXT_MISSING"
        assert "active_customer" in abstention.missing_context[0]
        assert abstention.found == ["CUSTOMER.STATUS_CD", "CUSTOMER.LAST_PURCHASE"]
        assert abstention.recommended_next_step is not None

    def test_data_missing_distinct_from_context_missing(self) -> None:
        decision = AnswerabilityDecision(
            status=AnswerabilityStatus.DATA_MISSING,
            answerable=False,
            confidence_level=ConfidenceLevel.INSUFFICIENT,
            missing_data=["costo de producto / COGS"],
            message="No puedo calcular margen porque no tengo costo de producto / COGS.",
        )
        abstention = AbstentionBuilder.build(decision)
        assert abstention.status == "DATA_MISSING"
        assert not abstention.missing_context
        assert "COGS" in abstention.missing_data[0]

    def test_legacy_prefix_preserved_for_cache_guard(self) -> None:
        decision = AnswerabilityDecision(
            status=AnswerabilityStatus.DATA_MISSING,
            answerable=False,
            confidence_level=ConfidenceLevel.INSUFFICIENT,
            missing_data=["ventas"],
        )
        message = AbstentionBuilder.to_llm_response(AbstentionBuilder.build(decision))
        assert "No tengo suficiente información" in message

    def test_clarification_message_is_the_question(self) -> None:
        decision = AnswerabilityDecision(
            status=AnswerabilityStatus.CLARIFICATION_REQUIRED,
            answerable=False,
            confidence_level=ConfidenceLevel.MEDIUM,
            clarifying_question="¿Quieres margen bruto o margen neto?",
            message="¿Quieres margen bruto o margen neto?",
        )
        abstention = AbstentionBuilder.build(decision)
        assert abstention.clarifying_question == "¿Quieres margen bruto o margen neto?"


class TestFSM:
    def test_valid_transition_chain(self) -> None:
        fsm = IntelligenceStateMachine()
        fsm.transition(IntelligenceState.PLAN)
        fsm.transition(IntelligenceState.RETRIEVE)
        fsm.transition(IntelligenceState.EXECUTE)
        fsm.transition(IntelligenceState.VALIDATE)
        fsm.transition(IntelligenceState.ANSWER)
        fsm.transition(IntelligenceState.DONE)
        assert fsm.state == IntelligenceState.DONE
        assert fsm.history[-1] == "DONE"

    def test_invalid_transition_raises(self) -> None:
        fsm = IntelligenceStateMachine()
        with pytest.raises(FSMViolation):
            fsm.transition(IntelligenceState.EXECUTE)  # salta PLAN

    def test_transition_from_done_raises(self) -> None:
        fsm = IntelligenceStateMachine()
        fsm.transition(IntelligenceState.PLAN)
        fsm.transition(IntelligenceState.RETRIEVE)
        fsm.transition(IntelligenceState.VALIDATE)
        fsm.transition(IntelligenceState.ABSTAIN)
        fsm.transition(IntelligenceState.DONE)
        with pytest.raises(FSMViolation):
            fsm.transition(IntelligenceState.PLAN)

    def test_budget_llm_calls_hard_limit(self) -> None:
        budget = Budget(limits=BudgetLimits(max_llm_calls=2))
        budget.record_llm_call()
        budget.record_llm_call()
        assert budget.exceeded is None
        budget.record_llm_call()
        assert budget.exceeded == "max_llm_calls"

    def test_budget_tokens_hard_limit(self) -> None:
        budget = Budget(limits=BudgetLimits(max_total_tokens=100))
        budget.record_llm_call(tokens=101)
        assert budget.exceeded == "max_total_tokens"

    def test_budget_cost_hard_limit(self) -> None:
        budget = Budget(limits=BudgetLimits(max_cost_usd=1.0))
        budget.record_llm_call(cost=1.01)
        assert budget.exceeded == "max_cost_usd"

    def test_budget_execution_seconds_hard_limit(self) -> None:
        budget = Budget(limits=BudgetLimits(max_execution_seconds=0.05))
        time.sleep(0.08)
        assert budget.exceeded == "max_execution_seconds"

    def test_budget_repairs_hard_limit(self) -> None:
        budget = Budget(limits=BudgetLimits(max_sql_repair_attempts=1))
        budget.record_sql_repair()
        budget.record_sql_repair()
        assert budget.exceeded == "max_sql_repair_attempts"


class TestLoopGuard:
    def test_first_call_allowed(self) -> None:
        guard = LoopGuard()
        fp = ToolFingerprint.compute(
            tool="sql", source="erp", arguments={}, query="q", agent_id="a",
            organization_id=str(ORG),
        )
        assert guard.check(fp, observation_context="obs1") is True

    def test_identical_call_without_new_info_blocked(self) -> None:
        guard = LoopGuard()
        fp = ToolFingerprint.compute(
            tool="sql", source="erp", arguments={"a": 1}, query="q",
            agent_id="a", organization_id=str(ORG),
        )
        assert guard.check(fp, observation_context="obs1") is True
        assert guard.check(fp, observation_context="obs1") is False
        assert guard.prevented_count == 1

    def test_changed_observation_allows_retry(self) -> None:
        guard = LoopGuard()
        fp = ToolFingerprint.compute(
            tool="sql", source="erp", arguments={}, query="q", agent_id="a",
            organization_id=str(ORG),
        )
        assert guard.check(fp, observation_context="obs1") is True
        assert guard.check(fp, observation_context="obs2") is True

    def test_new_information_explicitly_allows_retry(self) -> None:
        guard = LoopGuard()
        fp = ToolFingerprint.compute(
            tool="sql", source="erp", arguments={}, query="q", agent_id="a",
            organization_id=str(ORG),
        )
        assert guard.check(fp, observation_context="obs1") is True
        assert guard.check(
            fp,
            observation_context="obs1",
            new_information="Schema TOTAL_AMT discovered",
            retry_reason="schema_inspection",
            modified_plan=True,
        ) is True
        assert guard.retry_records[0].new_information == "Schema TOTAL_AMT discovered"

    def test_identical_call_without_new_info_keeps_blocking(self) -> None:
        guard = LoopGuard()
        fp = ToolFingerprint.compute(
            tool="sql", source="erp", arguments={}, query="q", agent_id="a",
            organization_id=str(ORG),
        )
        guard.check(fp, observation_context="obs")
        guard.check(fp, observation_context="obs")
        guard.check(fp, observation_context="obs")
        assert guard.prevented_count == 2


class TestSQLRepairGuard:
    def test_identical_sql_error_blocked(self) -> None:
        guard = SQLRepairGuard()
        assert guard.allow("SELECT x", "Unknown column TOTAL") is True
        assert guard.allow("SELECT x", "Unknown column TOTAL") is False
        assert guard.prevented == 1

    def test_different_error_allowed(self) -> None:
        guard = SQLRepairGuard()
        assert guard.allow("SELECT x", "Unknown column TOTAL") is True
        assert guard.allow("SELECT x", "Unknown column OTHER") is True
        assert guard.prevented == 0

    def test_valid_retry_sequence_with_new_information(self) -> None:
        guard = SQLRepairGuard()
        assert guard.allow("SELECT TOTAL", "Unknown column TOTAL") is True
        assert guard.allow("SELECT TOTAL_AMT", "Unknown column TOTAL_AMT") is True
        assert guard.prevented == 0


class TestToolFingerprint:
    def test_deterministic(self) -> None:
        fp1 = ToolFingerprint.compute(
            tool="QueryDatabase", source=None, arguments={"query": "x"},
            query="Pregunta", agent_id="a1", organization_id=str(ORG),
        )
        fp2 = ToolFingerprint.compute(
            tool="QueryDatabase", source=None, arguments={"query": "x"},
            query="Pregunta", agent_id="a1", organization_id=str(ORG),
        )
        assert fp1.digest == fp2.digest

    def test_normalized_args_order_insensitive(self) -> None:
        fp1 = ToolFingerprint.compute(
            tool="t", source=None, arguments={"b": 2, "a": 1}, query="q",
            agent_id="a", organization_id=str(ORG),
        )
        fp2 = ToolFingerprint.compute(
            tool="t", source=None, arguments={"a": 1, "b": 2}, query="q",
            agent_id="a", organization_id=str(ORG),
        )
        assert fp1.digest == fp2.digest

    def test_differs_across_org(self) -> None:
        fp1 = ToolFingerprint.compute(
            tool="t", source=None, arguments={}, query="q", agent_id="a",
            organization_id=str(ORG),
        )
        fp2 = ToolFingerprint.compute(
            tool="t", source=None, arguments={}, query="q", agent_id="a",
            organization_id=str(UUID("00000000-0000-0000-0000-000000000002")),
        )
        assert fp1.digest != fp2.digest

    def test_differs_across_arguments(self) -> None:
        fp1 = ToolFingerprint.compute(
            tool="t", source=None, arguments={"a": 1}, query="q", agent_id="a",
            organization_id=str(ORG),
        )
        fp2 = ToolFingerprint.compute(
            tool="t", source=None, arguments={"a": 2}, query="q", agent_id="a",
            organization_id=str(ORG),
        )
        assert fp1.digest != fp2.digest


class TestSignalCollector:
    def test_sql_ran_empty_is_result_present(self) -> None:
        from src.core.ports.sql_expert import SqlQueryResult

        collector = SignalCollector()
        signals = collector.collect(
            _understanding(),
            QueryPlan(strategy=PlanStrategy.SQL, needs_sql=True),
            retrieval_context=None,
            sql_result=SqlQueryResult(sql="SELECT 1", row_count=0),
            evidences=[],
        )
        assert signals.result_presence == 1.0
        assert signals.sql_execution_success == 1.0

    def test_no_sql_no_retrieval_is_not_present(self) -> None:
        collector = SignalCollector()
        signals = collector.collect(
            _understanding(),
            QueryPlan(strategy=PlanStrategy.RAG, needs_retrieval=True),
            retrieval_context=None,
            sql_result=None,
            evidences=[],
        )
        assert signals.result_presence == 0.0

    def test_undefined_concepts_lower_concept_resolution(self) -> None:
        collector = SignalCollector()
        signals = collector.collect(
            _understanding(resolved_concepts={"a": True, "b": False}),
            QueryPlan(strategy=PlanStrategy.SQL_RAG, needs_sql=True, needs_retrieval=True),
            retrieval_context=None,
            sql_result=None,
            evidences=[],
        )
        assert signals.concept_resolution == 0.5
        assert signals.business_definition_status == 0.5
