# =============================================================================
# Runtime rule integration — retrieval de reglas + ejecución + no-memoria
# =============================================================================
# End-to-end del contrato:
#   query semantics -> runtime values -> canonical rules + evidence
#   -> requirements -> deterministic execution -> DerivedClaim -> guard
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest

from src.core.domain.grounding import VerificationStatus
from src.intelligence.reasoning.grounded_engine import (
    ANSWERABLE_DERIVED,
    UNANSWERABLE_CONFLICT,
    UNANSWERABLE_MISSING_PREMISE,
    reason_over_evidence,
)
from src.knowledge.compiler.model import EvidenceRef, SemanticUnit, SourceLocator
from src.knowledge.rule_compiler import (
    CanonicalRule,
    RequirementState,
    RuleEvaluationStatus,
    SemanticRuleCompiler,
    evaluate_rule,
)
from src.rag.longcontext.package import render_authoritative_results
from src.runtime.answer_gate import resolve_answer_state
from src.runtime.derived_guard import enforce_derived_result
from src.runtime.rule_retrieval import (
    InMemoryRuleLookup,
    collect_rule_ids,
    load_rules_for_evidence,
)

DOC = uuid4()


def unit(kind: str, text: str, page: int = 1, section: tuple[str, ...] = ("General",)) -> SemanticUnit:
    return SemanticUnit(
        kind=kind,
        key=f"{kind}:{text[:24]}",
        label=text[:24],
        text=text,
        confidence=0.8,
        evidence=EvidenceRef(
            locator=SourceLocator(
                document_id=DOC,
                document_title="Manual",
                page=page,
                section_path=section,
            ),
            excerpt=text,
        ),
    )


def compile_rules(*units: SemanticUnit) -> list[CanonicalRule]:
    return SemanticRuleCompiler().compile(
        document_id=str(DOC),
        document_title="Manual",
        organization_id=str(uuid4()),
        units=list(units),
    ).canonical_rules


class _Item:
    def __init__(self, content: str = "", metadata: dict | None = None) -> None:
        self.content = content
        self.evidence_id = "ev_1"
        self.metadata = metadata or {}


class TestRuleRetrieval:
    def test_collect_rule_ids_from_metadata(self) -> None:
        first, second = uuid4(), uuid4()
        items = [
            _Item(metadata={"canonical_rule_ids": {"k1": str(first)}}),
            _Item(metadata={"canonical_rule_objects": [str(second), "no-uuid"]}),
        ]
        ids = collect_rule_ids(items)
        assert ids == [first, second]

    @pytest.mark.asyncio
    async def test_load_rules_by_id(self) -> None:
        rules = compile_rules(
            unit("rule", "Applicants must be at least 18 years old.", section=("HR",))
        )
        rule = next(rule for rule in rules if rule.executable)
        lookup = InMemoryRuleLookup(
            [
                CanonicalRule.from_dict(
                    {**rule.to_dict(), "rule_id": str(rule_id)}
                )
                for rule, rule_id in [(rule, uuid4())]
            ]
        )
        # El InMemory indexa por el rule_id del payload.
        stored = list(lookup._rules.values())[0]  # type: ignore[attr-defined]
        items = [_Item(metadata={"canonical_rule_ids": {"k": stored.rule_id}})]
        loaded = await load_rules_for_evidence(
            uuid4(), items, lookup=lookup
        )
        assert len(loaded) == 1
        assert loaded[0].executable

    @pytest.mark.asyncio
    async def test_without_ids_returns_empty(self) -> None:
        loaded = await load_rules_for_evidence(uuid4(), [_Item()])
        assert loaded == []


class TestDeterministicEndToEnd:
    def _pattern_rules(self) -> list[CanonicalRule]:
        return compile_rules(
            unit(
                "definition",
                "The value may contain more characters than the pattern.",
                page=1,
                section=("Matching",),
            ),
            unit(
                "definition",
                "The symbol & represents one alphanumeric position.",
                page=7,
                section=("Kinds of characters",),
            ),
            unit(
                "reference",
                "Matching is positional, left to right. "
                "Literal characters must match exactly at their position.",
                page=2,
                section=("Matching",),
            ),
        )

    def test_deterministic_claim_and_guard(self) -> None:
        rules = self._pattern_rules()
        executable = [rule for rule in rules if rule.executable]
        assert executable, "la gramática distribuida debe compilar ejecutable"

        item = _Item("Matching is positional, left to right.")
        result = reason_over_evidence(
            question="¿el valor ASDFGRE cumple el patrón &&&F?",
            evidence_items=[item],
            canonical_rules=rules,
        )
        assert result.answerability == ANSWERABLE_DERIVED
        claims = list(result.derivations.claims)
        assert claims and claims[0].deterministic
        assert claims[0].canonical_rule_ids
        assert claims[0].verification_status == VerificationStatus.SUPPORTED.value

        # FakeLLM intenta contradecir: el guard mantiene MATCH.
        fake_llm_answer = "NO_MATCH: el valor ASDFGRE no cumple el patrón &&&F."
        verdict = enforce_derived_result(
            fake_llm_answer, [claim.to_public_dict() for claim in claims]
        )
        assert verdict.action == "override"
        assert "Resultado: cumple" in verdict.answer

        block = render_authoritative_results(result.to_public_dict())
        assert "AUTHORITATIVE DERIVED RESULTS" in block
        assert "POSITIONAL_MATCH" in block
        assert "DO NOT reinterpret" in block

    def test_missing_premise_is_undetermined_and_named(self) -> None:
        rules = compile_rules(
            unit(
                "rule",
                "The code must comply with the length described in the annex.",
                section=("Codes",),
            )
        )
        result = reason_over_evidence(
            question="¿el código ABCDEFGH es válido?",
            evidence_items=[_Item("length described in the annex")],
            canonical_rules=rules,
        )
        assert result.answerability == UNANSWERABLE_MISSING_PREMISE
        assert any("length_policy" in item for item in result.missing_premises)
        state, message = resolve_answer_state(
            is_knowledge_question=True,
            evidence_count=1,
            missing_premises=result.missing_premises,
        )
        assert state == "UNDETERMINED_RULE"
        assert "length_policy" in message

    def test_conflicting_rules_are_conflicting_evidence(self) -> None:
        rules = compile_rules(
            unit(
                "definition",
                "The value must have exactly 8 characters.",
                section=("Length policy",),
            ),
            unit(
                "definition",
                "The value may contain more characters than the pattern.",
                section=("Length policy",),
            ),
        )
        assert all(not rule.executable for rule in rules)
        result = reason_over_evidence(
            question="¿el valor ABCDEFGH cumple la regla?",
            evidence_items=[_Item("length policy")],
            canonical_rules=rules,
        )
        assert result.answerability == UNANSWERABLE_CONFLICT
        state, _ = resolve_answer_state(
            is_knowledge_question=True,
            evidence_count=2,
            conflicts=result.conflicts,
        )
        assert state == "CONFLICTING_EVIDENCE"
        # Ni siquiera el guard convierte un conflicto en un resultado.
        for evaluation in result.rule_evaluations:
            assert evaluation.status == RuleEvaluationStatus.UNDETERMINED.value

    def test_retrieval_failure_never_generates_domain_memory(self) -> None:
        state, message = resolve_answer_state(
            is_knowledge_question=True,
            retrieval_failed=True,
            retrieval_reason="TimeoutError: vector provider timeout",
            evidence_count=0,
        )
        assert state == "RETRIEVAL_UNAVAILABLE"
        assert "no llegó a ejecutarse" in message
        assert "no existe información" not in message.lower()


class TestCompositeAndConditionalRules:
    def test_or_rule(self) -> None:
        rules = compile_rules(
            unit(
                "rule",
                "The value must be less than 5 or greater than 10.",
                section=("Ranges",),
            )
        )
        rule = next(rule for rule in rules if rule.executable)
        inside = evaluate_rule(rule, {"value": 12})
        assert inside.status == RuleEvaluationStatus.MATCH.value
        assert inside.logic == "OR"
        middle = evaluate_rule(rule, {"value": 7})
        assert middle.status == RuleEvaluationStatus.NO_MATCH.value

    def test_only_if_condition(self) -> None:
        rules = compile_rules(
            unit(
                "rule",
                "The fee must be at least 10 only if the value is greater than 100.",
                section=("Fees",),
            )
        )
        rule = next(rule for rule in rules if rule.executable or rule.conditions)
        blocked = evaluate_rule(rule, {"value": 50})
        assert blocked.status == RuleEvaluationStatus.NOT_APPLICABLE.value
        assert blocked.reason == "condition_not_met"
        applies = evaluate_rule(rule, {"value": 150})
        assert applies.status == RuleEvaluationStatus.MATCH.value

    def test_unless_condition_evaluable(self) -> None:
        rules = compile_rules(
            unit(
                "rule",
                "The fee must be at least 10 unless the value is greater than 100.",
                section=("Fees",),
            )
        )
        rule = next(rule for rule in rules if rule.exceptions)
        excepted = evaluate_rule(rule, {"value": 150})
        assert excepted.status == RuleEvaluationStatus.NOT_APPLICABLE.value
        assert excepted.reason == "exception_applied"
        assert excepted.exceptions_applied
        normal = evaluate_rule(rule, {"value": 50})
        assert normal.status == RuleEvaluationStatus.MATCH.value

    def test_unless_without_structure_is_undetermined(self) -> None:
        rules = compile_rules(
            unit(
                "rule",
                "The carrier must not change the fare basis code on reissue, "
                "unless the ticket is reissued.",
                section=("Changes",),
            )
        )
        rule = next(rule for rule in rules if rule.exceptions)
        outcome = evaluate_rule(rule, {"value": "X"})
        assert outcome.status == RuleEvaluationStatus.UNDETERMINED.value
        assert "exception_condition" in outcome.missing_premises


class TestRequirementCoverage:
    def test_requirements_expose_missing(self) -> None:
        rules = compile_rules(
            unit("rule", "The value must be greater than 10.", section=("Volume",))
        )
        rule = next(rule for rule in rules if rule.executable)
        outcome = evaluate_rule(rule, {})
        missing = [
            item
            for item in outcome.requirements
            if item.state == RequirementState.MISSING.value
        ]
        assert missing
        assert outcome.status == RuleEvaluationStatus.UNDETERMINED.value

    def test_requirements_satisfied(self) -> None:
        rules = compile_rules(
            unit("rule", "The value must be greater than 10.", section=("Volume",))
        )
        rule = next(rule for rule in rules if rule.executable)
        outcome = evaluate_rule(rule, {"value": 15})
        assert outcome.status == RuleEvaluationStatus.MATCH.value
        assert all(
            item.state
            in (RequirementState.SATISFIED.value, RequirementState.NOT_APPLICABLE.value)
            for item in outcome.requirements
        )
        public = outcome.to_public_dict()
        assert public["requirements"]
        assert "condition_results" in public
