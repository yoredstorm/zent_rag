# =============================================================================
# Pattern grammar — instancia vs gramática documentada
# =============================================================================
# La instancia concreta («&&&F», «AAA-###») NO exige presencia literal en las
# fuentes. Sus SEMÁNTICAS sí: definición del símbolo, matching posicional,
# literalidad, longitud y prefijo/sufijo. Si falta una premisa, el resultado es
# UNDETERMINED y la premisa se nombra; jamás se inventa el significado.
# =============================================================================
from __future__ import annotations

import pytest

from src.rag.longcontext.pattern import (
    MatchStatus,
    analyze_pattern_instance,
    extract_pattern_semantics,
    missing_pattern_premises,
    positional_match,
)


class _Item:
    def __init__(self, content: str, evidence_id: str = "E1") -> None:
        self.content = content
        self.evidence_id = evidence_id


GRAMMAR_ES = (
    "El símbolo & representa una posición alfanumérica. El matching es "
    "posicional, de izquierda a derecha."
)
GRAMMAR_EN = (
    "& represents one alphanumeric position. Matching is positional, left to "
    "right. Literal characters must match exactly at their position."
)


class TestPatternInstance:
    def test_tokens_and_symbols(self) -> None:
        instance = analyze_pattern_instance("&&&F")
        assert instance.length == 4
        assert instance.symbols == ("&",)
        assert instance.literal_positions == ((3, "F"),)
        assert instance.user_supplied is True
        assert "definition:symbol:&" in instance.requires_semantics

    def test_generic_product_pattern(self) -> None:
        instance = analyze_pattern_instance("AAA-###")
        assert instance.symbols == ("#",)
        assert instance.length == 7

    def test_public_dict_has_no_chain_of_thought(self) -> None:
        payload = analyze_pattern_instance("&&&F").to_public_dict()
        assert "tokens" in payload
        assert "reasoning" not in payload
        assert "thoughts" not in payload


class TestGrammarExtraction:
    def test_symbol_definition_es(self) -> None:
        semantics = extract_pattern_semantics([_Item(GRAMMAR_ES)])
        definition = semantics.definition_for("&")
        assert definition is not None
        assert definition.meaning == "alphanumeric_position"
        assert semantics.positional is True

    def test_symbol_definition_en(self) -> None:
        semantics = extract_pattern_semantics([_Item(GRAMMAR_EN)])
        definition = semantics.definition_for("&")
        assert definition is not None
        assert definition.meaning == "alphanumeric_position"
        assert semantics.literal is True

    def test_no_definition_no_grammar(self) -> None:
        semantics = extract_pattern_semantics(
            [_Item("patterns are supported for the field")]
        )
        assert semantics.definition_for("&") is None
        assert semantics.matching_policy_known() is False

    def test_length_policy_detected(self) -> None:
        semantics = extract_pattern_semantics(
            [_Item("& represents one alphanumeric position. The pattern and the "
                   "value must have the same length. Matching is positional.")]
        )
        assert semantics.length_sensitive is True

    def test_suffix_policy_detected(self) -> None:
        semantics = extract_pattern_semantics(
            [_Item("& represents one alphanumeric position. Matching is "
                   "positional from the end (suffix).")]
        )
        assert semantics.anchor_side == "end"


class TestMissingPremises:
    def test_missing_symbol_definition_is_named(self) -> None:
        semantics = extract_pattern_semantics([_Item("patterns are supported")])
        missing = missing_pattern_premises(
            analyze_pattern_instance("&&&F"), semantics, value_length=7
        )
        assert "definition:symbol:&" in missing
        assert "matching_policy" in missing

    def test_complete_grammar_has_no_missing(self) -> None:
        semantics = extract_pattern_semantics([_Item(GRAMMAR_EN)])
        missing = missing_pattern_premises(
            analyze_pattern_instance("&&&F"), semantics, value_length=4
        )
        assert missing == ()

    def test_length_only_missing_when_lengths_differ(self) -> None:
        semantics = extract_pattern_semantics(
            [_Item("& represents one alphanumeric position. Matching is positional.")]
        )
        same = missing_pattern_premises(
            analyze_pattern_instance("&&&F"), semantics, value_length=4
        )
        different = missing_pattern_premises(
            analyze_pattern_instance("&&&F"), semantics, value_length=7
        )
        assert "length_semantics" not in same
        assert "length_semantics" in different


class TestPositionalMatch:
    def test_match_with_documented_grammar(self) -> None:
        semantics = extract_pattern_semantics([_Item(GRAMMAR_EN)])
        result = positional_match("ASDF", "&&&F", semantics)
        assert result.status == MatchStatus.MATCH.value
        assert result.derived is True

    def test_no_match_literal_position(self) -> None:
        semantics = extract_pattern_semantics([_Item(GRAMMAR_EN)])
        result = positional_match("ASDG", "&&&F", semantics)
        assert result.status == MatchStatus.NO_MATCH.value
        assert result.mismatches[0]["position"] == 4

    def test_no_match_wildcard_rejects(self) -> None:
        semantics = extract_pattern_semantics([_Item(GRAMMAR_EN)])
        result = positional_match("AS-F", "&&&F", semantics)
        assert result.status == MatchStatus.NO_MATCH.value

    def test_undetermined_without_symbol_definition(self) -> None:
        semantics = extract_pattern_semantics([_Item("patterns are supported")])
        result = positional_match("ASDFGRE", "&&&F", semantics)
        assert result.status == MatchStatus.UNDETERMINED.value
        assert "definition:symbol:&" in result.missing_premises

    def test_undetermined_length_without_policy(self) -> None:
        semantics = extract_pattern_semantics(
            [_Item("& represents one alphanumeric position. Matching is positional.")]
        )
        result = positional_match("ASDFGRE", "&&&F", semantics)
        assert result.status == MatchStatus.UNDETERMINED.value
        assert "length_semantics" in result.missing_premises

    def test_length_enforced(self) -> None:
        semantics = extract_pattern_semantics(
            [_Item("& represents one alphanumeric position. Matching is positional. "
                   "The pattern and the value must have the same length.")]
        )
        result = positional_match("ASDFGRE", "&&&F", semantics)
        assert result.status == MatchStatus.NO_MATCH.value
        assert result.mismatches[0]["reason"] == "length_mismatch"

    def test_prefix_policy_allows_longer_value(self) -> None:
        semantics = extract_pattern_semantics(
            [_Item("& represents one alphanumeric position. Matching is positional "
                   "from the start (prefix).")]
        )
        result = positional_match("ASDFGRE", "&&&F", semantics)
        assert result.status == MatchStatus.MATCH.value
        assert result.checked_positions == 4

    def test_suffix_policy_checks_tail(self) -> None:
        semantics = extract_pattern_semantics(
            [_Item("& represents one alphanumeric position. Matching is positional "
                   "from the end (suffix).")]
        )
        result = positional_match("GREASDF", "&&&F", semantics)
        assert result.status == MatchStatus.MATCH.value

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("ABCFXYZ", MatchStatus.MATCH.value),
            ("123FABC", MatchStatus.MATCH.value),
            ("ABCX", MatchStatus.NO_MATCH.value),
            ("ABCDX", MatchStatus.NO_MATCH.value),
        ],
    )
    def test_pattern_instance_values(self, value: str, expected: str) -> None:
        # Gramática con prefijo: el 4º carácter debe ser F; el resto del valor
        # del usuario no está restringido por el patrón.
        semantics = extract_pattern_semantics(
            [_Item("& represents one alphanumeric position. Matching is positional "
                   "from the start (prefix).")]
        )
        result = positional_match(value, "&&&F", semantics)
        assert result.status == expected

    def test_generic_product_pattern(self) -> None:
        semantics = extract_pattern_semantics(
            [_Item("A represents one letter. # represents one digit. "
                   "Matching is positional. The pattern and the value must have "
                   "the same length.")]
        )
        assert positional_match("ABC-123", "AAA-###", semantics).status == MatchStatus.MATCH.value
        assert positional_match("ABC-12X", "AAA-###", semantics).status == MatchStatus.NO_MATCH.value

    def test_premises_used_are_statements_not_copies(self) -> None:
        semantics = extract_pattern_semantics([_Item(GRAMMAR_EN)])
        result = positional_match("ASDF", "&&&F", semantics)
        assert any("alphanumeric" in statement for statement in result.premises_used)
        assert "ASDF" not in " ".join(result.premises_used)


class TestLengthPolicyMigration:
    """Mencionar longitud NO fija política; length_sensitive solo con igualdad."""

    def test_mere_length_mention_is_unknown(self) -> None:
        semantics = extract_pattern_semantics(
            [
                _Item(
                    "& represents one alphanumeric position. Matching is positional. "
                    "The field length is described in the annex."
                )
            ]
        )
        assert semantics.length_policy == "UNKNOWN"
        assert semantics.length_sensitive is False
        result = positional_match("ASDFGRE", "&&&F", semantics)
        assert result.status == MatchStatus.UNDETERMINED.value
        assert "length_semantics" in result.missing_premises

    def test_same_length_is_exact_only_with_evidence(self) -> None:
        semantics = extract_pattern_semantics(
            [
                _Item(
                    "& represents one alphanumeric position. Matching is positional. "
                    "The pattern and the value must have the same length."
                )
            ]
        )
        assert semantics.length_policy == "EXACT"
        assert semantics.length_sensitive is True

    def test_value_may_be_longer_is_asymmetric(self) -> None:
        semantics = extract_pattern_semantics(
            [
                _Item(
                    "& represents one alphanumeric position. Matching is positional. "
                    "The value may contain more characters than the pattern."
                )
            ]
        )
        assert semantics.length_policy == "VALUE_MAY_BE_LONGER"
        assert semantics.length_sensitive is False
        longer = positional_match("ASDFGRE", "&&&F", semantics)
        assert longer.status == MatchStatus.MATCH.value
        shorter = positional_match("ASD", "&&&F", semantics)
        assert shorter.status == MatchStatus.NO_MATCH.value

    def test_pattern_may_be_longer_is_asymmetric(self) -> None:
        semantics = extract_pattern_semantics(
            [
                _Item(
                    "& represents one alphanumeric position. Matching is positional. "
                    "The pattern may contain more characters than the value."
                )
            ]
        )
        assert semantics.length_policy == "PATTERN_MAY_BE_LONGER"
        result = positional_match("AS", "&&&F", semantics)
        # El valor corto solo exige las posiciones presentes.
        assert result.status == MatchStatus.MATCH.value

    def test_numeric_length_policy_from_language(self) -> None:
        semantics = extract_pattern_semantics(
            [
                _Item(
                    "& represents one alphanumeric position. Matching is positional. "
                    "At least 3 characters are required."
                )
            ]
        )
        assert semantics.length_policy == "MIN_LENGTH"
        assert semantics.length_value == 3
        assert positional_match("AS", "&&&F", semantics).status == (
            MatchStatus.NO_MATCH.value
        )
        assert positional_match("ASDF", "&&&F", semantics).status == (
            MatchStatus.MATCH.value
        )
