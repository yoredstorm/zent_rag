# =============================================================================
# Derived Guard + estados de respuesta — el generador no decide
# =============================================================================
# El LLM puede explicar; no puede invertir MATCH/NO_MATCH ni convertir un fallo
# de retrieval en "no existe información".
# =============================================================================
from __future__ import annotations

import pytest

from src.intelligence.reasoning.operations import (
    OperationStatus,
    OperationType,
    run_date_range,
    run_numeric_compare,
    run_set_relation,
    run_string_compare,
)
from src.runtime.answer_gate import (
    ANSWER_STATE_CONFLICTING,
    ANSWER_STATE_DERIVED,
    ANSWER_STATE_INSUFFICIENT,
    ANSWER_STATE_RETRIEVAL_UNAVAILABLE,
    ANSWER_STATE_UNDETERMINED,
    INSUFFICIENT_ANSWER,
    RETRIEVAL_UNAVAILABLE_ANSWER,
    resolve_answer_state,
)
from src.runtime.derived_guard import deterministic_claims, enforce_derived_result


def _claim(
    *,
    result="MATCH",
    deterministic=True,
    status="SUPPORTED",
    statement="«ASDFGRE» cumple el patrón «&&&F»",
    inputs=("value=ASDFGRE", "pattern=&&&F"),
    conflicts=(),
):
    return {
        "statement": statement,
        "result": result,
        "operation": "POSITIONAL_MATCH",
        "deterministic": deterministic,
        "verification_status": status,
        "user_inputs": list(inputs),
        "evidence_refs": ["ev_1"],
        "canonical_rule_ids": ["rule:abc"],
        "conflicts": list(conflicts),
    }


class TestDerivedGuard:
    def test_llm_cannot_invert_match(self) -> None:
        # FakeLLM contradice el resultado determinista: gana MATCH.
        verdict = enforce_derived_result(
            "El valor ASDFGRE no cumple el patrón &&&F.", [_claim()]
        )
        assert verdict.action == "override"
        assert verdict.overridden
        assert "Resultado: MATCH" in verdict.answer
        assert "no cumple" not in verdict.answer.lower()

    def test_llm_cannot_invert_no_match(self) -> None:
        verdict = enforce_derived_result(
            "Sí, el código es válido y coincide.", [_claim(result="NO_MATCH")]
        )
        assert verdict.action == "override"
        assert "NO_MATCH" in verdict.answer
    def test_agreeing_answer_is_untouched(self) -> None:
        answer = "El valor ASDFGRE cumple el patrón &&&F según la regla documentada."
        verdict = enforce_derived_result(answer, [_claim()])
        assert verdict.action == "ok"
        assert verdict.answer == answer
        assert verdict.claims_checked == 1

    def test_non_deterministic_claim_is_ignored(self) -> None:
        verdict = enforce_derived_result(
            "El valor ASDFGRE no cumple.", [_claim(deterministic=False)]
        )
        assert verdict.action == "ok"

    def test_conflicting_claim_marks_internal_conflict(self) -> None:
        verdict = enforce_derived_result(
            "El valor no cumple.", [_claim(conflicts=("rule_conflict:other",))]
        )
        assert verdict.action == "internal_conflict"
        assert "INTERNAL_GROUNDING_CONFLICT" in verdict.answer

    def test_public_claims_filter(self) -> None:
        claims = [_claim(), _claim(deterministic=False)]
        assert len(deterministic_claims(claims)) == 1


class TestAnswerStates:
    def test_retrieval_timeout_zero_evidence(self) -> None:
        state, message = resolve_answer_state(
            is_knowledge_question=True,
            retrieval_failed=True,
            retrieval_reason="embedding provider timeout",
            evidence_count=0,
        )
        assert state == ANSWER_STATE_RETRIEVAL_UNAVAILABLE
        assert "no llegó a ejecutarse" in message
        assert message == RETRIEVAL_UNAVAILABLE_ANSWER or "Causa:" in message
        assert message != INSUFFICIENT_ANSWER

    def test_success_with_missing_premise(self) -> None:
        state, message = resolve_answer_state(
            is_knowledge_question=True,
            retrieval_failed=False,
            evidence_count=2,
            missing_premises=("length_policy",),
        )
        assert state == ANSWER_STATE_UNDETERMINED
        assert "length_policy" in message

    def test_contradictory_rules(self) -> None:
        state, message = resolve_answer_state(
            is_knowledge_question=True,
            retrieval_failed=False,
            evidence_count=3,
            conflicts=("rule_conflict:abc",),
        )
        assert state == ANSWER_STATE_CONFLICTING
        assert "contradicen" in message

    def test_zero_evidence_without_failure_is_insufficient(self) -> None:
        state, message = resolve_answer_state(
            is_knowledge_question=True,
            retrieval_failed=False,
            evidence_count=0,
        )
        assert state == ANSWER_STATE_INSUFFICIENT
        assert message == INSUFFICIENT_ANSWER

    def test_deterministic_result_wins_over_states(self) -> None:
        state, _ = resolve_answer_state(
            is_knowledge_question=True,
            retrieval_failed=True,
            evidence_count=0,
            has_deterministic_result=True,
        )
        assert state == ANSWER_STATE_DERIVED

    def test_conversational_turn_is_not_applicable(self) -> None:
        state, message = resolve_answer_state(
            is_knowledge_question=False, retrieval_failed=True, evidence_count=0
        )
        assert state == ""
        assert message == ""


class TestExtendedOperations:
    def test_string_compare_ordered_and_case(self) -> None:
        assert run_string_compare("Alpha", "alpha", op="eq").value is True
        assert run_string_compare("A", "B", op="lt").value is True
        assert run_string_compare("A", "a", op="eq", case_sensitive=True).value is False

    def test_numeric_compare_rejects_strings(self) -> None:
        assert run_numeric_compare(5, 3, op="gt").value is True
        assert run_numeric_compare("not-a-number", 3).status == OperationStatus.ERROR.value

    def test_date_range(self) -> None:
        result = run_date_range(
            "2026-06-15", start="2026-01-01", end="2026-12-31"
        )
        assert result.value is True
        assert result.operation == OperationType.DATE_RANGE.value
        outside = run_date_range(
            "2027-01-01", start="2026-01-01", end="2026-12-31"
        )
        assert outside.value is False

    def test_set_relation(self) -> None:
        assert run_set_relation("A,B", "A,B,C", relation="subset").value is True
        assert run_set_relation("A,B", "C,D", relation="disjoint").value is True
        assert run_set_relation(["A"], ["A", "B"], relation="intersects").value is True

    def test_set_relation_rejects_non_iterable(self) -> None:
        assert run_set_relation(5, ["A"]).status == OperationStatus.ERROR.value


class TestTimeoutStageReporting:
    @pytest.mark.asyncio
    async def test_timeout_reports_dominant_stage(self) -> None:
        import asyncio
        from uuid import uuid4

        from src.agents.tools.base import Tool, ToolContext, ToolResult
        from src.agents.tools.guards import execute_tool_guarded

        class SlowSearch(Tool):
            name = "search_knowledge"
            input_schema = {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            }
            timeout_seconds = 0.05

            def __init__(self) -> None:
                self.last_stage_ms = {
                    "query_embedding_ms": 3.0,
                    "vector_ms": 150.0,
                }

            async def execute(self, ctx: ToolContext, arguments: dict) -> ToolResult:
                await asyncio.sleep(0.5)
                return ToolResult(output="late")

        result = await execute_tool_guarded(
            SlowSearch(), ToolContext(tenant_id=uuid4()), {"query": "x"}
        )
        assert result.error
        assert "timed out" in result.error
        assert "dominant stage: vector_ms" in result.error
        assert result.meta.get("dominant_stage") == "vector_ms"
        assert result.meta.get("stage_ms", {}).get("vector_ms") == 150.0
