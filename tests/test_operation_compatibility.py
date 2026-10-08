# =============================================================================
# Operation compatibility — EL RANKING NO DECIDE QUÉ OPERACIÓN ES CORRECTA
# =============================================================================
# Contratos que estos tests fijan:
#   1. QueryOperationRequirements se derivan de QuerySemantics (sin dominio):
#      runtime pattern => familia MATCHING + capacidades MASK_MATCH /
#      POSITIONAL_SYMBOL_SEMANTICS.
#   2. symbol_mentioned != symbol_defined != symbol_executable (pesos distintos).
#   3. La matriz de operaciones excluye COMPARISON/RANGE/DATE/FORMULA para una
#      consulta de máscara (OPERATION_INCOMPATIBLE) y MISSING_RUNTIME_SYMBOL_
#      SEMANTICS cuando la regla declara matching de OTRO símbolo.
#   4. OperationInputValidator: `ABCFGEGE >= &&&F` falla OPERAND_TYPE_
#      INCOMPATIBLE — nunca comparación lexical.
#   5. El gate produce telemetría determinista (score ANTES/después, rechazos).
# =============================================================================
from __future__ import annotations

import pytest

from src.core.domain.rule_semantics import (
    BoundaryKind,
    ComparisonOperator,
    MatchOperator,
    TemporalRelation,
    VerificationState,
)
from src.knowledge.rule_compiler.index import (
    SYMBOL_DEFINED,
    SYMBOL_EXECUTABLE,
    SYMBOL_MENTIONED,
    rank_rule,
    rule_symbol_usage,
)
from src.knowledge.rule_compiler.model import (
    CanonicalRule,
    RuleEnumerationSpec,
    RuleFormulaSpec,
    RuleProperty,
    RuleTemporalSpec,
)
from src.runtime.operation_compatibility import (
    CAP_MASK_MATCH,
    CAP_POSITIONAL_SYMBOL_SEMANTICS,
    ELIGIBLE,
    FAMILY_ANY,
    FAMILY_COMPARISON,
    FAMILY_FORMULA,
    FAMILY_MATCHING,
    FAMILY_RANGE,
    MISSING_RUNTIME_SYMBOL_SEMANTICS,
    OPERAND_TYPE_INCOMPATIBLE,
    OPERATION_INCOMPATIBLE,
    derive_query_operation_requirements,
    envelope_operation_compatible,
    evaluate_operation_compatibility,
    gate_rules_for_requirements,
    is_runtime_mask,
    question_mask_token,
    rule_capability_profile,
    validate_operation_inputs,
)

PROP = "supported"

PATTERN_QUESTION = "¿ABCFGEGE cumple el patrón &&&F?"
PRODUCTION_QUESTION = (
    "yo tengo en el record 2 &&&F y en el farebasis me viene ABCFGEGE "
    "cumple o no cumple"
)


def _prop(name: str, value, *, state: str = PROP) -> RuleProperty:
    return RuleProperty(
        name=name,
        value=value,
        state=state,
        evidence=[f"ev:{name}"],
    )


def matching_rule(
    rule_id: str = "rule:matching",
    *,
    symbol: str = "&",
    statement: str = "The symbol & matches one alphanumeric position.",
    with_operator: bool = True,
) -> CanonicalRule:
    properties = {
        f"matching.symbol.{symbol}": _prop(
            f"matching.symbol.{symbol}", "one alphanumeric position"
        ),
    }
    if with_operator:
        properties["matching.operator"] = _prop(
            "matching.operator", MatchOperator.POSITIONAL.value
        )
    return CanonicalRule(
        rule_id=rule_id,
        statement=statement,
        properties=properties,
        verification_state=VerificationState.SUPPORTED.value,
        executable=True,
    )


def comparison_rule(
    rule_id: str = "rule:comparison",
    *,
    statement: str = "The value must be at least 10.",
    left: str = "The value",
    right: str = "10",
    operator: str = ComparisonOperator.GTE.value,
) -> CanonicalRule:
    return CanonicalRule(
        rule_id=rule_id,
        statement=statement,
        operator=operator,
        properties={
            "comparison.operator": _prop("comparison.operator", operator),
            "comparison.left": _prop("comparison.left", left),
            "comparison.right": _prop("comparison.right", right),
            "comparison.boundary": _prop(
                "comparison.boundary", BoundaryKind.INCLUSIVE.value
            ),
        },
        verification_state=VerificationState.SUPPORTED.value,
        executable=True,
    )


def mention_only_rule(rule_id: str = "rule:mention") -> CanonicalRule:
    """Regla real del fallo: menciona `&` y su operación final es COMPARISON."""
    return comparison_rule(
        rule_id,
        statement=(
            "ATPCO edits require at least one alphanumeric character in the "
            "fare basis (&&&F)."
        ),
    )


def range_rule(rule_id: str = "rule:range") -> CanonicalRule:
    return CanonicalRule(
        rule_id=rule_id,
        statement="The value must be between 10 and 20.",
        operator=ComparisonOperator.BETWEEN.value,
        properties={
            "comparison.operator": _prop(
                "comparison.operator", ComparisonOperator.BETWEEN.value
            ),
            "comparison.left": _prop("comparison.left", "10"),
            "comparison.right": _prop("comparison.right", "20"),
            "quantity.minimum": _prop("quantity.minimum", 10),
            "quantity.maximum": _prop("quantity.maximum", 20),
        },
        verification_state=VerificationState.SUPPORTED.value,
        executable=True,
    )


def date_rule(rule_id: str = "rule:date") -> CanonicalRule:
    return CanonicalRule(
        rule_id=rule_id,
        statement="Applications must be received before 1 July 2026.",
        properties={
            "temporal.relation": _prop(
                "temporal.relation", TemporalRelation.BEFORE.value
            ),
        },
        temporal=RuleTemporalSpec(relation=TemporalRelation.BEFORE.value, value="2026-07-01"),
        verification_state=VerificationState.SUPPORTED.value,
        executable=True,
    )


def enum_rule(rule_id: str = "rule:enum") -> CanonicalRule:
    return CanonicalRule(
        rule_id=rule_id,
        statement="The status must be one of ACTIVE, PENDING.",
        enumeration=RuleEnumerationSpec(allowed=["ACTIVE", "PENDING"]),
        verification_state=VerificationState.SUPPORTED.value,
        executable=True,
    )


def formula_rule(rule_id: str = "rule:formula") -> CanonicalRule:
    return CanonicalRule(
        rule_id=rule_id,
        statement="Total = subtotal + tax.",
        formula=RuleFormulaSpec(target="total", expression="subtotal + tax"),
        verification_state=VerificationState.SUPPORTED.value,
        executable=True,
    )


def boolean_rule(rule_id: str = "rule:boolean") -> CanonicalRule:
    return CanonicalRule(
        rule_id=rule_id,
        statement="Eligible when active and verified.",
        properties={"logic.operators": _prop("logic.operators", ["AND"])},
        verification_state=VerificationState.SUPPORTED.value,
        executable=True,
    )


# -----------------------------------------------------------------------------
# 1 — QueryOperationRequirements
# -----------------------------------------------------------------------------


class TestQueryOperationRequirements:
    def test_production_question_requires_matching(self) -> None:
        requirements = derive_query_operation_requirements(
            question=PRODUCTION_QUESTION
        )
        assert requirements.operation_family == FAMILY_MATCHING
        assert requirements.enforced is True
        assert requirements.runtime_patterns == ("&&&F",)
        assert requirements.symbols == ("&",)
        assert requirements.positional is True
        assert CAP_MASK_MATCH in requirements.required_capabilities
        assert CAP_POSITIONAL_SYMBOL_SEMANTICS in requirements.required_capabilities

    def test_runtime_pattern_from_semantics_object(self) -> None:
        from src.intelligence.query_semantics import classify_query_semantics

        semantics = classify_query_semantics(PRODUCTION_QUESTION)
        requirements = derive_query_operation_requirements(
            question=PRODUCTION_QUESTION, semantics=semantics
        )
        assert requirements.operation_family == FAMILY_MATCHING
        assert requirements.symbols == ("&",)

    def test_numeric_compare_requires_comparison_or_range(self) -> None:
        requirements = derive_query_operation_requirements(
            question="¿120 es mayor o igual que el mínimo 100?"
        )
        assert requirements.operation_family in (FAMILY_COMPARISON, FAMILY_RANGE)
        assert requirements.runtime_patterns == ()

    def test_formula_question(self) -> None:
        requirements = derive_query_operation_requirements(
            question="calcula el total con subtotal=100 aplicando la fórmula"
        )
        assert requirements.operation_family == FAMILY_FORMULA

    def test_unknown_question_is_permissive(self) -> None:
        requirements = derive_query_operation_requirements(question="hola, ¿cómo estás?")
        assert requirements.operation_family == FAMILY_ANY
        assert requirements.enforced is False

    def test_trailing_question_mark_is_not_a_mask(self) -> None:
        assert question_mask_token("¿el valor ABCD cumple?") == ""
        assert question_mask_token("¿ABCFGEGE cumple &&&F?") == "&&&F"
        assert is_runtime_mask("cumple?") is False
        assert is_runtime_mask("&&&F") is True
        assert is_runtime_mask("W&&2M") is True
        assert is_runtime_mask("ABCFGEGE") is False
        assert is_runtime_mask("120") is False


# -----------------------------------------------------------------------------
# 2 — symbol_mentioned != symbol_defined != symbol_executable
# -----------------------------------------------------------------------------


class TestSymbolLevels:
    def test_executable_requires_operator(self) -> None:
        usage = rule_symbol_usage(matching_rule())
        assert usage["&"] == SYMBOL_EXECUTABLE

    def test_defined_without_operator(self) -> None:
        usage = rule_symbol_usage(matching_rule(with_operator=False))
        assert usage["&"] == SYMBOL_DEFINED

    def test_mention_only(self) -> None:
        usage = rule_symbol_usage(mention_only_rule())
        assert usage["&"] == SYMBOL_MENTIONED

    def test_ranking_separates_levels(self) -> None:
        score_executable, reasons_executable = rank_rule(
            matching_rule(), symbols=("&",), intent="VALIDATE"
        )
        score_defined, _ = rank_rule(
            matching_rule(with_operator=False), symbols=("&",), intent="VALIDATE"
        )
        score_mention, _ = rank_rule(
            mention_only_rule(), symbols=("&",), intent="VALIDATE"
        )
        assert score_executable > score_defined > score_mention
        assert any(
            "symbol:&:executable" in reason for reason in reasons_executable
        )

    def test_profile_capabilities_by_level(self) -> None:
        executable = rule_capability_profile(matching_rule())
        assert CAP_MASK_MATCH in executable.capabilities
        defined = rule_capability_profile(matching_rule(with_operator=False))
        assert CAP_MASK_MATCH in defined.capabilities
        mention = rule_capability_profile(mention_only_rule())
        assert CAP_MASK_MATCH not in mention.capabilities
        assert CAP_POSITIONAL_SYMBOL_SEMANTICS not in mention.capabilities


# -----------------------------------------------------------------------------
# 3 — Matriz de compatibilidad
# -----------------------------------------------------------------------------


class TestCompatibilityMatrix:
    def _requirements(self, question: str = PATTERN_QUESTION):
        return derive_query_operation_requirements(question=question)

    def test_mention_only_comparison_is_operation_incompatible(self) -> None:
        result = evaluate_operation_compatibility(
            mention_only_rule(), self._requirements(), score_before=999.0
        )
        assert result.compatible is False
        assert result.eligibility == OPERATION_INCOMPATIBLE
        assert OPERATION_INCOMPATIBLE in result.hard_reasons
        # Ni con un score altísimo entra al pass decisivo.
        assert result.score_after == result.score_before

    def test_positional_rule_is_eligible_and_boosted(self) -> None:
        result = evaluate_operation_compatibility(
            matching_rule(), self._requirements(), score_before=20.0
        )
        assert result.compatible is True
        assert result.eligibility == ELIGIBLE
        assert result.score_after > result.score_before
        assert result.symbol_executable == ("&",)

    def test_foreign_symbol_needs_semantics(self) -> None:
        foreign = matching_rule(symbol="?", statement="The symbol ? matches one digit.")
        result = evaluate_operation_compatibility(foreign, self._requirements())
        assert result.compatible is False
        assert result.eligibility == MISSING_RUNTIME_SYMBOL_SEMANTICS

    def test_matching_rule_rejected_for_numeric_query(self) -> None:
        requirements = self._requirements("¿120 es mayor o igual que el mínimo 100?")
        result = evaluate_operation_compatibility(matching_rule(), requirements)
        assert result.compatible is False
        assert result.eligibility == OPERATION_INCOMPATIBLE

    def test_comparison_rule_allowed_for_numeric_query(self) -> None:
        requirements = self._requirements("¿120 es mayor o igual que el mínimo 100?")
        result = evaluate_operation_compatibility(comparison_rule(), requirements)
        assert result.compatible is True

    def test_gate_partitions_candidates_with_telemetry(self) -> None:
        rules = [
            mention_only_rule("rule:a-mention"),
            matching_rule("rule:b-matching"),
            matching_rule(
                "rule:c-foreign",
                symbol="?",
                statement="The symbol ? matches one digit.",
            ),
        ]
        gate = gate_rules_for_requirements(
            rules,
            self._requirements(),
            scores={"rule:a-mention": 99.0, "rule:b-matching": 1.0},
        )
        payload = gate.to_public_dict()
        assert payload["applied"] is True
        assert payload["candidates"] == 3
        assert payload["compatible"] == 1
        assert payload["rejected"] == 2
        assert payload["winner_rule_id"] == "rule:b-matching"
        reasons = {item["reason"] for item in payload["top_rejected_reasons"]}
        assert OPERATION_INCOMPATIBLE in reasons
        assert MISSING_RUNTIME_SYMBOL_SEMANTICS in reasons
        scores = {item["rule_id"]: item for item in payload["scores"]}
        # El score antes/después se muestra para TODAS las candidatas.
        assert scores["rule:a-mention"]["score_before"] == 99.0
        assert scores["rule:a-mention"]["score_after"] == 99.0
        assert scores["rule:a-mention"]["eligible"] is False
        assert scores["rule:b-matching"]["score_after"] > scores["rule:b-matching"]["score_before"]

    def test_ranking_scores_after_gate_are_deterministic(self) -> None:
        rules = [
            matching_rule("rule:z"),
            matching_rule("rule:a"),
        ]
        first = gate_rules_for_requirements(rules, self._requirements()).ranked_compatible()
        for _ in range(10):
            again = gate_rules_for_requirements(rules, self._requirements()).ranked_compatible()
            assert [rule.rule_id for rule in again] == [rule.rule_id for rule in first]


# -----------------------------------------------------------------------------
# 4 — OperationInputValidator (tipos antes del registry)
# -----------------------------------------------------------------------------


class TestOperationInputValidator:
    @pytest.mark.parametrize(
        "left,right,op,valid",
        [
            ("ABCFGEGE", "&&&F", "ge", False),
            ("&&&F", "ABCFGEGE", "ge", False),
            ("120", "100", "ge", True),
            (120, 100, "ge", True),
            ("ABCFGEGE", "&&&F", "eq", False),
            ("ACTIVE", "active", "eq", True),
            ("sí", "no", "eq", True),
        ],
    )
    def test_comparison_operands(self, left, right, op, valid) -> None:
        outcome = validate_operation_inputs(
            "COMPARISON", operands={"a": left, "b": right, "op": op}
        )
        assert outcome.valid is valid
        if not valid:
            assert OPERAND_TYPE_INCOMPATIBLE in outcome.reasons

    def test_lexical_order_never_runs(self) -> None:
        from src.intelligence.reasoning.operations import run_comparison

        result = run_comparison("ABCFGEGE", "&&&F", op="ge")
        assert result.ok is False
        assert OPERAND_TYPE_INCOMPATIBLE in (result.error or "")

    def test_range_value_type(self) -> None:
        outcome = validate_operation_inputs(
            "RANGE_CHECK", operands={"value": "ABCFGEGE", "minimum": 10}
        )
        assert outcome.valid is False
        assert OPERAND_TYPE_INCOMPATIBLE in outcome.reasons

    def test_date_operands(self) -> None:
        assert validate_operation_inputs(
            "DATE_COMPARISON", operands={"a": "2026-01-01", "b": "2026-12-31"}
        ).valid
        assert not validate_operation_inputs(
            "DATE_COMPARISON", operands={"a": "ABCFGEGE", "b": "&&&F"}
        ).valid

    def test_envelope_operation_compatible(self) -> None:
        requirements = derive_query_operation_requirements(question=PATTERN_QUESTION)
        compatible, reason = envelope_operation_compatible(
            "POSITIONAL_MATCH", requirements
        )
        assert compatible is True
        compatible, reason = envelope_operation_compatible("COMPARISON", requirements)
        assert compatible is False
        assert reason == OPERATION_INCOMPATIBLE
        permissive = derive_query_operation_requirements(question="hola")
        assert envelope_operation_compatible("COMPARISON", permissive)[0] is True


__all__ = [
    "matching_rule",
    "comparison_rule",
    "mention_only_rule",
    "range_rule",
    "date_rule",
    "enum_rule",
    "formula_rule",
    "boolean_rule",
]
