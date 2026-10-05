# =============================================================================
# Rule evaluation — operaciones deterministas + integración grounded
# =============================================================================
# El LLM no decide un cálculo determinista: premisas grounded + datos runtime
# + operación -> DerivedClaim. Falta de premisa -> UNDETERMINED con nombre.
# Fallo operativo de retrieval -> RETRIEVAL_UNAVAILABLE (no es "no hay
# evidencia" ni NO_MATCH/FALSE).
# =============================================================================
from __future__ import annotations

from uuid import uuid4

from src.core.domain.rule_semantics import (
    VerificationState,
)
from src.intelligence.reasoning.grounded_engine import (
    ANSWERABLE_DERIVED,
    RETRIEVAL_UNAVAILABLE,
    UNANSWERABLE_CONFLICT,
    UNANSWERABLE_MISSING_PREMISE,
    reason_over_evidence,
    retrieval_unavailable_result,
)
from src.knowledge.compiler.model import EvidenceRef, SemanticUnit, SourceLocator
from src.knowledge.rule_compiler import CanonicalRule, SemanticRuleCompiler
from src.knowledge.rule_compiler.evaluate import (
    RuleEvaluationStatus,
    evaluate_rule,
    evaluate_rules,
    rule_premises,
)
from src.runtime.answer_gate import INSUFFICIENT_ANSWER, RETRIEVAL_UNAVAILABLE_ANSWER

DOC = uuid4()


def unit(kind: str, text: str, page: int = 1, section: tuple[str, ...] = ("General",)) -> SemanticUnit:
    return SemanticUnit(
        kind=kind,
        key=f"{kind}:{text[:30]}",
        label=text[:30],
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
    def __init__(self, content: str, metadata: dict | None = None) -> None:
        self.content = content
        self.evidence_id = "ev_doc_1"
        self.metadata = metadata or {}


class TestDeterministicEvaluation:
    def test_comparison_direction_preserved(self) -> None:
        rules = compile_rules(unit("rule", "The volume must be greater than 10."))
        rule = next(r for r in rules if r.executable)
        assert evaluate_rule(rule, {"value": 11}).status == RuleEvaluationStatus.MATCH.value
        assert evaluate_rule(rule, {"value": 10}).status == RuleEvaluationStatus.NO_MATCH.value

    def test_boundary_unknown_is_undetermined(self) -> None:
        rules = compile_rules(unit("rule", "The volume must be between 10 and 20."))
        rule = next(r for r in rules if "between" in r.statement)
        assert not rule.executable or not rule.properties.get("comparison.boundary")
        evaluation = evaluate_rule(rule, {"value": 15})
        if evaluation.status == RuleEvaluationStatus.UNDETERMINED.value:
            assert "boundary" in evaluation.missing_premises

    def test_enum_allowed_and_prohibited(self) -> None:
        allowed = compile_rules(unit("rule", "Allowed values: RED, GREEN."))
        rule = next(r for r in allowed if r.enumeration.allowed)
        assert evaluate_rule(rule, {"value": "GREEN"}).status == RuleEvaluationStatus.MATCH.value
        assert evaluate_rule(rule, {"value": "BLUE"}).status == RuleEvaluationStatus.NO_MATCH.value
        prohibited = compile_rules(unit("rule", "Prohibited values: X, Y."))
        rule = next(r for r in prohibited if r.enumeration.prohibited)
        assert evaluate_rule(rule, {"value": "X"}).status == RuleEvaluationStatus.NO_MATCH.value

    def test_length_unknown_blocks_execution(self) -> None:
        rules = compile_rules(
            unit(
                "rule",
                "The code must comply with the length described in the annex.",
                section=("Codes",),
            )
        )
        rule = next(r for r in rules if "length described" in r.statement)
        evaluation = evaluate_rule(rule, {"value": "ABCD"})
        assert evaluation.status == RuleEvaluationStatus.UNDETERMINED.value
        assert "length_policy" in evaluation.missing_premises

    def test_not_supported_rule_is_undetermined(self) -> None:
        rules = compile_rules(
            unit("rule", "The carrier must not change the fare basis code on reissue.")
        )
        rule = rules[0]
        rule.verification_state = VerificationState.PARTIALLY_SUPPORTED.value
        rule.executable = False
        evaluation = evaluate_rule(rule, {})
        assert evaluation.status == RuleEvaluationStatus.UNDETERMINED.value
        assert "regla no ejecutable" in evaluation.reason

    def test_evaluate_rules_merges_distributed_fragments(self) -> None:
        rules = compile_rules(
            unit(
                "definition",
                "The value may contain more characters than the pattern.",
                page=1,
                section=("Matching",),
            ),
            unit(
                "definition",
                "The symbol & represents one alphanumeric position.",
                page=5,
                section=("Characters",),
            ),
            unit(
                "reference",
                "Matching is positional. Literal characters must match exactly.",
                page=2,
                section=("Matching",),
            ),
        )
        evaluations = evaluate_rules(rules, {"value": "ASDFGRE", "pattern": "&&&F"})
        assert any(
            evaluation.status == RuleEvaluationStatus.MATCH.value
            for evaluation in evaluations
        )

    def test_rule_premises_have_evidence(self) -> None:
        rules = compile_rules(unit("rule", "Applicants must be at least 18 years old."))
        rule = next(r for r in rules if r.executable)
        premises = rule_premises(rule)
        assert premises
        assert all(premise.grounded for premise in premises)


class TestGroundedIntegration:
    def test_reason_over_evidence_consumes_canonical_rule(self) -> None:
        rules = compile_rules(
            unit(
                "definition",
                "The value may contain more characters than the pattern.",
                page=1,
                section=("Matching",),
            ),
            unit(
                "definition",
                "The symbol & represents one alphanumeric position.",
                page=5,
                section=("Characters",),
            ),
            unit(
                "reference",
                "Matching is positional.",
                page=2,
                section=("Matching",),
            ),
        )
        item = _Item(
            "Matching is positional.",
            metadata={"canonical_rules": [rule.to_dict() for rule in rules]},
        )
        result = reason_over_evidence(
            question="¿el valor ASDFGRE cumple el patrón &&&F?",
            evidence_items=[item],
        )
        assert result.answerability == ANSWERABLE_DERIVED
        derived = result.derivations.derived_results
        assert derived
        assert result.rule_evaluations
        public = result.to_public_dict()
        assert "canonical_rule_flow" in public
        assert public["canonical_rule_flow"][0]["rule_id"]

    def test_conflicting_rules_do_not_execute(self) -> None:
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
        item = _Item(
            "length policy",
            metadata={"canonical_rules": [rule.to_dict() for rule in rules]},
        )
        result = reason_over_evidence(
            question="¿el valor ABCDEFGH cumple?", evidence_items=[item]
        )
        assert result.answerability == UNANSWERABLE_CONFLICT

    def test_missing_premise_is_named_not_invented(self) -> None:
        rules = compile_rules(
            unit(
                "rule",
                "The code must comply with the length described in the annex.",
                section=("Codes",),
            )
        )
        item = _Item(
            "length described in the annex",
            metadata={"canonical_rules": [rule.to_dict() for rule in rules]},
        )
        result = reason_over_evidence(
            question="¿el código ABCDEFGH es válido?",
            evidence_items=[item],
        )
        assert result.answerability == UNANSWERABLE_MISSING_PREMISE
        assert any("length_policy" in item for item in result.missing_premises)

    def test_retrieval_unavailable_is_distinct(self) -> None:
        result = retrieval_unavailable_result(
            "¿cuál es la política de devoluciones?",
            reason="embedding provider timeout",
        )
        assert result.answerability == RETRIEVAL_UNAVAILABLE
        assert result.answerability not in (
            "INSUFFICIENT_EVIDENCE",
            ANSWERABLE_DERIVED,
            UNANSWERABLE_MISSING_PREMISE,
        )
        public = result.to_public_dict()
        assert public["answerability"] == RETRIEVAL_UNAVAILABLE
        assert public["decided_by"] == "operational"
        # El mensaje de abstención operativa no es el de evidencia insuficiente.
        assert RETRIEVAL_UNAVAILABLE_ANSWER != INSUFFICIENT_ANSWER
        assert "no llegó a ejecutarse" in RETRIEVAL_UNAVAILABLE_ANSWER
