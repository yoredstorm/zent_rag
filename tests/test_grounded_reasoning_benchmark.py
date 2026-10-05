# =============================================================================
# Grounded reasoning benchmark — dataset del módulo de evaluación (§52-§53)
# =============================================================================
# El dataset vive en `src/rag/evaluation/grounded_benchmark.py` (60+ casos) y
# estas pruebas verifican: caso por caso, el contraste contra el baseline
# literal, y que el over-abstention baja sin subir la alucinación.
# =============================================================================
from __future__ import annotations

import pytest

from src.core.domain.grounding import (
    ClaimOrigin,
    DerivedClaim,
    GroundingContract,
    GroundingMode,
    Premise,
    VerificationStatus,
)
from src.intelligence.query_semantics import (
    QueryIntent,
    QuerySemanticRole,
    classify_query_semantics,
)
from src.intelligence.reasoning.derivation import verify_derived_claim
from src.intelligence.reasoning.grounded_engine import (
    ANSWERABLE_DERIVED,
    NOT_APPLICABLE,
    UNANSWERABLE_CONFLICT,
    UNANSWERABLE_MISSING_PREMISE,
    reason_over_evidence,
)
from src.intelligence.reasoning.operations import run_arithmetic
from src.rag.evaluation.grounded_benchmark import (
    BENCHMARK_CASES,
    BenchmarkCase,
    compare_baselines,
    evaluate_runner,
    query_role_accuracy,
    run_grounded,
)


class _Item:
    def __init__(self, content: str, evidence_id: str = "E1") -> None:
        self.content = content
        self.evidence_id = evidence_id


def _run(question: str, docs: list[str]):
    return reason_over_evidence(
        question=question,
        evidence_items=[_Item(doc, f"E{i + 1}") for i, doc in enumerate(docs)],
    )


@pytest.mark.parametrize("case", BENCHMARK_CASES, ids=[c.case_id for c in BENCHMARK_CASES])
def test_benchmark_case(case: BenchmarkCase) -> None:
    outcome = run_grounded(case)
    if case.expectation == "derived":
        assert outcome.answerability == ANSWERABLE_DERIVED, (
            f"{case.case_id}: expected derived, got {outcome.answerability} "
            f"(missing={outcome.missing_premises})"
        )
        assert outcome.result == case.expected_result, (
            f"{case.case_id}: {outcome.result} != {case.expected_result}"
        )
    elif case.expectation == "missing":
        assert outcome.answerability == UNANSWERABLE_MISSING_PREMISE, (
            f"{case.case_id}: expected missing premise, got {outcome.answerability}"
        )
        assert any(
            case.expected_missing in item for item in outcome.missing_premises
        ), f"{case.case_id}: {case.expected_missing} not in {outcome.missing_premises}"
    elif case.expectation == "conflict":
        assert outcome.answerability == UNANSWERABLE_CONFLICT, (
            f"{case.case_id}: expected conflict, got {outcome.answerability}"
        )
    else:
        assert outcome.answerability == NOT_APPLICABLE, (
            f"{case.case_id}: expected direct path, got {outcome.answerability}"
        )


def test_benchmark_has_at_least_50_cases() -> None:
    assert len(BENCHMARK_CASES) >= 50
    categories = {case.category for case in BENCHMARK_CASES}
    assert {
        "runtime_values",
        "alpha_only",
        "numeric",
        "patterns",
        "formulas",
        "range",
        "source_lookup",
        "rule_application",
        "missing_premise",
        "calculation",
        "enum",
        "direct_lookup",
        "general_operation",
    } <= categories
    counts: dict[str, int] = {}
    for case in BENCHMARK_CASES:
        counts[case.category] = counts.get(case.category, 0) + 1
    # P1: cobertura mínima pedida.
    assert counts["runtime_values"] >= 10
    assert counts["alpha_only"] >= 5
    assert counts["numeric"] >= 5
    assert counts["patterns"] >= 5
    assert counts["formulas"] >= 5
    assert counts["range"] >= 5
    assert counts["source_lookup"] >= 5


class TestMetricsAndBaseline:
    def test_grounded_metrics(self) -> None:
        metrics = evaluate_runner(BENCHMARK_CASES, run_grounded)
        assert metrics["correctness"] >= 0.95
        assert metrics["hallucination_rate"] == 0.0
        assert metrics["over_abstention_rate"] <= 0.05
        assert metrics["under_abstention_rate"] == 0.0
        assert metrics["faithfulness"] == 1.0
        assert metrics["citation_support"] >= 0.9
        assert metrics["directness"] >= 0.9
        assert metrics["derived_answer_accuracy"] >= 0.95
        # P1: métrica crítica aproximadamente cero en el golden set.
        assert metrics["runtime_cases"] >= 30
        assert metrics["runtime_input_false_missing_rate"] == 0.0

    def test_over_abstention_drops_without_hallucination_increase(self) -> None:
        comparison = compare_baselines(BENCHMARK_CASES)
        legacy = comparison["legacy_literal"]
        grounded = comparison["grounded_reasoning"]
        # El contrato literal abstiene en la gran mayoría de lo derivable.
        assert legacy["over_abstention_rate"] >= 0.8
        assert grounded["over_abstention_rate"] < legacy["over_abstention_rate"]
        assert grounded["correctness"] > legacy["correctness"]
        assert grounded["hallucination_rate"] <= legacy["hallucination_rate"]
        assert comparison["delta"]["over_abstention_rate"] < 0
        # P1: antes 1.0 (todo dato exigido literal), después ~0.
        assert legacy["runtime_input_false_missing_rate"] == 1.0
        assert grounded["runtime_input_false_missing_rate"] == 0.0
        assert comparison["delta"]["runtime_input_false_missing_rate"] == -1.0

    def test_query_role_accuracy(self) -> None:
        metrics = query_role_accuracy()
        assert metrics["query_role_accuracy"] >= 0.95
        assert metrics["misses"] == []


class TestCanonicalScenario:
    QUESTION = (
        "si tengo un farebasis en el boleto ASDFGRE y en el record 2 me viene "
        "&&&F cumple o no?"
    )

    def test_classification(self) -> None:
        semantics = classify_query_semantics(self.QUESTION)
        roles = {obj.value: obj.semantic_role for obj in semantics.objects}
        assert roles["ASDFGRE"] == QuerySemanticRole.USER_INPUT.value
        assert roles["&&&F"] == QuerySemanticRole.RUNTIME_PATTERN.value

    def test_derived_without_literal_instance_or_value(self) -> None:
        # La evidencia define la gramática y NO menciona ni ASDFGRE ni &&&F.
        docs = [
            "& represents one alphanumeric position. Matching is positional from "
            "the start (prefix)."
        ]
        result = _run(self.QUESTION, docs)
        assert result.answerability == ANSWERABLE_DERIVED
        claim = result.derivations.derived_results[0]
        assert claim.result == "MATCH"
        assert "ASDFGRE" in claim.statement
        assert all("ASDFGRE" not in premise.statement for premise in claim.premises)

    def test_abstains_only_for_missing_premise(self) -> None:
        result = _run(self.QUESTION, ["patterns are supported for the field"])
        assert result.answerability == UNANSWERABLE_MISSING_PREMISE
        assert "definition:symbol:&" in result.missing_premises
        assert "ASDFGRE" not in result.abstention_message
        assert "&&&F" not in result.abstention_message
        assert "símbolo" in result.abstention_message

    def test_literal_instance_without_grammar_does_not_invent_meaning(self) -> None:
        docs = ["La máscara &&&F exige que el fare basis tenga la longitud indicada."]
        result = _run(self.QUESTION, docs)
        assert result.answerability == UNANSWERABLE_MISSING_PREMISE
        assert "definition:symbol:&" in result.missing_premises


class TestSourceLookupStillLiteral:
    def test_source_lookup_classifies_as_requirement(self) -> None:
        semantics = classify_query_semantics(
            "¿ASDFGRE aparece literalmente en el documento?"
        )
        assert semantics.intent == QueryIntent.SOURCE_LOOKUP.value
        assert semantics.objects[0].semantic_role == QuerySemanticRole.SOURCE_REQUIREMENT.value
        assert semantics.objects[0].evidence_required is True

    def test_context_changes_role(self) -> None:
        user = classify_query_semantics("mi código es ASDFGRE, ¿cumple esta regla?")
        source = classify_query_semantics("¿ASDFGRE aparece en el documento?")
        user_role = {obj.value: obj.semantic_role for obj in user.objects}["ASDFGRE"]
        source_role = {obj.value: obj.semantic_role for obj in source.objects}["ASDFGRE"]
        assert user_role == QuerySemanticRole.USER_INPUT.value
        assert source_role == QuerySemanticRole.SOURCE_REQUIREMENT.value


class TestGeneralKnowledgeBoundary:
    def test_general_math_allowed(self) -> None:
        assert run_arithmetic(a=3, b=3, op="add").value == 6

    def test_proprietary_symbol_not_filled_from_model_knowledge(self) -> None:
        # El modo grounded_reasoning prohíbe completar semántica propietaria.
        contract = GroundingContract(mode=GroundingMode.GROUNDED_REASONING.value)
        assert contract.requirement_for("MODEL_GENERAL_KNOWLEDGE").allowed is False

    def test_unsupported_claim_never_asserted(self) -> None:
        claim = DerivedClaim(
            statement="ASDFGRE matches &&&F",
            premises=(
                Premise(
                    statement="& means wildcard", origin=ClaimOrigin.SOURCE.value
                ),
            ),
            user_inputs=("ASDFGRE",),
            operation="POSITIONAL_MATCH",
            result="MATCH",
        )
        verified = verify_derived_claim(claim, GroundingContract())
        assert verified.verification_status == VerificationStatus.INSUFFICIENT_PREMISES.value
        assert verified.supported is False


class TestNoDomainHardcode:
    """P0.19: el motor no conoce ATPCO, fare basis ni `&`."""

    def test_generic_product_code_with_question_grammar(self) -> None:
        # Gramática sintética: «? representa una letra mayúscula».
        docs = [
            "Product code: ? represents one uppercase letter. Matching is "
            "positional. The pattern and the value must have the same length."
        ]
        result = _run("mi valor ABCD contra ????", docs)
        assert result.answerability == ANSWERABLE_DERIVED
        assert result.derivations.derived_results[0].result == "MATCH"

        bad = _run("mi valor AB1D contra ????", docs)
        assert bad.answerability == ANSWERABLE_DERIVED
        assert bad.derivations.derived_results[0].result == "NO_MATCH"

    def test_production_source_has_no_atpco_conditionals(self) -> None:
        import io
        import tokenize
        from pathlib import Path

        def _code_only(text: str) -> str:
            """Código sin comentarios ni strings: los ejemplos no son lógica."""
            try:
                tokens = tokenize.generate_tokens(io.StringIO(text).readline)
                return " ".join(
                    token.string
                    for token in tokens
                    if token.type not in (tokenize.COMMENT, tokenize.STRING)
                )
            except tokenize.TokenError:
                return text

        root = Path(__file__).resolve().parents[1] / "src"
        banned = ("farebasis", "fare_basis", "atpco", "fclas")
        core_prefixes = (
            "intelligence/query_semantics",
            "rag/longcontext/pattern",
            "intelligence/reasoning/grounded_engine",
            "intelligence/reasoning/operations",
            "intelligence/reasoning/derivation",
        )
        offenders: list[str] = []
        for path in root.rglob("*.py"):
            relative = str(path.relative_to(root)).replace("\\", "/")
            if not relative.startswith(core_prefixes):
                continue
            code = _code_only(path.read_text(encoding="utf-8", errors="ignore")).lower()
            if any(term in code for term in banned):
                offenders.append(relative)
        assert offenders == [], offenders


class TestArithmeticRegression:
    """P0.15: 3 + 3 = 6 sin exigir «3 + 3 = 6» en la fuente."""

    def test_arithmetic_without_literal_answer_in_source(self) -> None:
        docs = ["Addition combines two quantities into a single total."]
        result = _run("3 + 3", docs)
        assert result.answerability == ANSWERABLE_DERIVED
        claim = result.derivations.derived_results[0]
        assert claim.result == 6
        assert claim.operation == "ARITHMETIC"
        assert "3 + 3 = 6" not in docs[0]

    def test_arithmetic_does_not_require_source_match(self) -> None:
        result = _run("10 - 4", [])
        assert result.answerability == ANSWERABLE_DERIVED
        assert result.derivations.derived_results[0].result == 6


class TestSourceLookupNumeric:
    """P0.17: preguntar si la fuente menciona 20 lo vuelve requirement literal."""

    def test_age_20_source_lookup(self) -> None:
        semantics = classify_query_semantics("¿el documento menciona age 20?")
        assert semantics.intent == QueryIntent.SOURCE_LOOKUP.value
        roles = {obj.value: obj.semantic_role for obj in semantics.objects}
        assert roles.get("20") == QuerySemanticRole.SOURCE_REQUIREMENT.value
        assert all(
            obj.semantic_role != QuerySemanticRole.RUNTIME_PARAMETER.value
            for obj in semantics.objects
        )

    def test_age_20_runtime_is_not_source_lookup(self) -> None:
        semantics = classify_query_semantics("age 20, ¿cumple la edad mínima?")
        roles = {obj.value: obj.semantic_role for obj in semantics.objects}
        assert roles.get("20") == QuerySemanticRole.RUNTIME_PARAMETER.value


class TestAmbiguity:
    """P1: una sigla suelta no recibe un rol inventado con alta confianza."""

    def test_bare_sigla_is_low_confidence(self) -> None:
        semantics = classify_query_semantics("ASDFGRE?")
        assert semantics.decided_by == "low_confidence"
        assert semantics.intent_confidence < 1.0

    def test_optional_llm_classifier_threshold_exists(self) -> None:
        from src.intelligence.query_semantics import (
            ContextualQueryRoleClassifier,
        )

        assert ContextualQueryRoleClassifier().llm_threshold > 0.0
