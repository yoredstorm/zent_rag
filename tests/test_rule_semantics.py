# =============================================================================
# Rule semantics — lenguaje -> políticas (domain-agnostic)
# =============================================================================
# Principio: MENCIONAR no establece política. "may" != "must". "unless" se
# conserva. La dirección (izquierda/derecha) no se pierde. Sin marcador de
# inclusividad, el límite queda UNKNOWN.
# =============================================================================
from __future__ import annotations

import pytest

from src.core.domain.rule_semantics import (
    BoundaryKind,
    ComparisonOperator,
    LengthPolicy,
    MatchOperator,
    ModalityKind,
    TemporalRelation,
    analyze_language,
    classify_boundary,
    classify_comparison,
    classify_length_policy,
    classify_modality,
    is_example,
    is_normative,
)


class TestMentionVsPolicy:
    def test_mere_length_mention_is_unknown(self) -> None:
        observation = classify_length_policy("Field length is described below.")
        assert observation.policy == LengthPolicy.UNKNOWN.value
        assert observation.mention_only is True
        assert "length_policy" in observation.missing_premises

    def test_same_length_is_explicit_exact(self) -> None:
        observation = classify_length_policy(
            "The pattern and the value must have the same length."
        )
        assert observation.policy == LengthPolicy.EXACT.value
        assert observation.explicit is True
        assert observation.mention_only is False

    def test_value_may_be_longer_preserves_direction(self) -> None:
        observation = classify_length_policy(
            "The value may contain more characters than the pattern."
        )
        assert observation.policy == LengthPolicy.VALUE_MAY_BE_LONGER.value
        assert "value" in observation.left_operand.lower()
        assert "pattern" in observation.right_operand.lower()

    def test_pattern_may_be_longer_preserves_direction(self) -> None:
        observation = classify_length_policy(
            "The pattern may contain more characters than the value."
        )
        assert observation.policy == LengthPolicy.PATTERN_MAY_BE_LONGER.value

    def test_unidentified_operands_do_not_invent_direction(self) -> None:
        observation = classify_length_policy("X may be longer than Y")
        assert observation.policy == LengthPolicy.UNKNOWN.value
        assert "length_operand_role" in observation.missing_premises

    def test_quantity_is_not_length_policy(self) -> None:
        observation = classify_length_policy(
            "The value may not exceed the maximum of 5 days."
        )
        assert observation.policy == LengthPolicy.UNKNOWN.value
        assert observation.mention_only is False

    def test_numeric_length_requires_length_context(self) -> None:
        observation = classify_length_policy("At least 3 characters are required.")
        assert observation.policy == LengthPolicy.MIN_LENGTH.value
        assert observation.value == 3
        # "at least 5 units" sin contexto de longitud no es política de largo.
        assert classify_length_policy("At least 5 units are required.").policy == (
            LengthPolicy.UNKNOWN.value
        )

    def test_exact_numeric_length(self) -> None:
        observation = classify_length_policy("The code must have a length of 8.")
        assert observation.policy == LengthPolicy.EXACT.value
        assert observation.value == 8


class TestModality:
    def test_may_is_not_must(self) -> None:
        assert classify_modality("The value may contain letters.").modality == (
            ModalityKind.MAY.value
        )
        assert classify_modality("The value must contain letters.").modality == (
            ModalityKind.MUST.value
        )

    def test_must_not_keeps_negation(self) -> None:
        observation = classify_modality("The carrier must not change the code.")
        assert observation.modality == ModalityKind.MUST_NOT.value
        assert observation.matched_text

    def test_spanish_normative(self) -> None:
        signals = analyze_language("El código debe tener 8 caracteres.")
        assert signals.modality.modality == ModalityKind.MUST.value
        assert signals.length.policy == LengthPolicy.EXACT.value


class TestComparisonAsymmetry:
    def test_greater_than_preserves_left_right(self) -> None:
        comparisons = classify_comparison("The maximum weight is greater than 20 kg.")
        assert comparisons[0].operator == ComparisonOperator.GT.value

    def test_not_between_is_outside_range(self) -> None:
        comparisons = classify_comparison("The value must be outside 10 and 20.")
        assert comparisons[0].operator == ComparisonOperator.OUTSIDE_RANGE.value
        assert comparisons[0].boundary == BoundaryKind.UNKNOWN.value

    def test_inclusive_boundary_declared(self) -> None:
        comparisons = classify_comparison("The value is between 1 and 5 inclusive.")
        assert comparisons[0].operator == ComparisonOperator.BETWEEN.value
        assert comparisons[0].boundary == BoundaryKind.INCLUSIVE.value

    def test_exclusive_boundary_declared(self) -> None:
        comparisons = classify_comparison("Between 1 and 5 exclusive.")
        assert comparisons[0].boundary == BoundaryKind.EXCLUSIVE.value


class TestLogicNegation:
    def test_unless_is_preserved(self) -> None:
        signals = analyze_language(
            "The carrier must not change the code unless the ticket is reissued."
        )
        operators = {item.operator for item in signals.logic}
        assert "UNLESS" in operators
        assert signals.negation.negated is True

    def test_only_if_is_not_bidirectional(self) -> None:
        signals = analyze_language("The change applies only if the ticket is reissued.")
        operators = {item.operator for item in signals.logic}
        assert "ONLY_IF" in operators
        assert "IF_AND_ONLY_IF" not in operators

    def test_if_and_only_if_is_explicit(self) -> None:
        signals = analyze_language("It applies if and only if the ticket is reissued.")
        operators = {item.operator for item in signals.logic}
        assert "IF_AND_ONLY_IF" in operators


class TestClassification:
    def test_example_is_not_rule(self) -> None:
        text = "For example the fare basis YQYR applies."
        assert is_example(text) is True
        assert is_normative(text) is False

    def test_only_if_without_modality_is_normative(self) -> None:
        assert is_normative("The override applies only if the carrier agrees.") is True


class TestTemporal:
    def test_before(self) -> None:
        observation = analyze_language(
            "The request must be submitted before 15/03/2026."
        )
        assert observation.temporal.relation == TemporalRelation.BEFORE.value

    def test_until_is_expiration(self) -> None:
        observation = analyze_language("The fare is valid until 31/12/2026 inclusive.")
        assert observation.temporal.relation in {
            TemporalRelation.EXPIRES.value,
            TemporalRelation.FROM_TO.value,
        }


class TestMatchOperators:
    def test_positional_match_detected(self) -> None:
        observation = analyze_language("Matching is positional, left to right.")
        assert observation.match.operator == MatchOperator.POSITIONAL.value

    def test_mere_position_noun_is_not_policy(self) -> None:
        observation = analyze_language("& represents one alphanumeric position.")
        assert observation.match.operator != MatchOperator.POSITIONAL.value

    def test_literal_is_flagged(self) -> None:
        observation = analyze_language("Literal characters must match exactly.")
        assert observation.match.literal is True

    def test_prohibited_alphabet_only_with_alphabet_object(self) -> None:
        good = analyze_language("The code must not contain spaces.")
        assert good.match.prohibited_alphabet
        bad = analyze_language(
            "The carrier must not change the fare basis code on reissue."
        )
        assert bad.match.prohibited_alphabet == ""


class TestBoundary:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("up to and including 5", BoundaryKind.INCLUSIVE.value),
            ("less than 5", BoundaryKind.UNKNOWN.value),
            ("5 exclusive", BoundaryKind.EXCLUSIVE.value),
            ("hasta e incluyendo 5", BoundaryKind.INCLUSIVE.value),
        ],
    )
    def test_boundary(self, text: str, expected: str) -> None:
        assert classify_boundary(text) == expected
