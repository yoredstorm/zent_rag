# =============================================================================
# Adversarial generalization benchmark — cross-domain
# =============================================================================
# Objetivo: intentar DEMOSTRAR que el motor NO generaliza. Cada dominio usa
# vocabulario distinto y mezcla paráfrasis, negación, límites, excepciones y
# evidencia distribuida. ASDFGRE vs &&&F es UNA prueba entre muchas.
# =============================================================================
from __future__ import annotations

import pytest

from src.core.domain.rule_semantics import (
    BoundaryKind,
    LengthPolicy,
    ModalityKind,
)
from src.intelligence.reasoning.grounded_engine import (
    ANSWERABLE_DERIVED,
    RETRIEVAL_UNAVAILABLE,
    reason_over_evidence,
    retrieval_unavailable_result,
)
from src.knowledge.rule_compiler import RuleEvaluationStatus, evaluate_rule
from src.runtime.answer_gate import resolve_answer_state
from src.runtime.derived_guard import enforce_derived_result
from tests.adversarial_support import (
    any_executable,
    compile_units,
    rule_with,
    unit,
)

# -----------------------------------------------------------------------------
# DOMINIO A — PRODUCT CODES
# -----------------------------------------------------------------------------


class TestDomainAProductCodes:
    def _rules(self):
        return compile_units(
            unit("definition", "Each ? represents one digit.", page=1, section=("Codes",)),
            unit(
                "reference",
                "The mask is evaluated from the beginning of the product code.",
                page=1,
                section=("Codes",),
            ),
            unit(
                "definition",
                "The product code may contain additional characters beyond those "
                "represented by the mask.",
                page=1,
                section=("Codes",),
            ),
        )

    def test_longer_value_matches(self) -> None:
        rule = any_executable(self._rules())[0]
        assert evaluate_rule(rule, {"value": "123ABC", "pattern": "???"}).status == (
            RuleEvaluationStatus.MATCH.value
        )

    def test_shorter_value_fails(self) -> None:
        rule = any_executable(self._rules())[0]
        assert evaluate_rule(rule, {"value": "12ABC", "pattern": "???"}).status == (
            RuleEvaluationStatus.NO_MATCH.value
        )

    def test_bad_position_fails(self) -> None:
        rule = any_executable(self._rules())[0]
        assert evaluate_rule(rule, {"value": "12XABC", "pattern": "???"}).status == (
            RuleEvaluationStatus.NO_MATCH.value
        )


# -----------------------------------------------------------------------------
# DOMINIO B — EXACT LENGTH
# -----------------------------------------------------------------------------


class TestDomainBExactLength:
    def _rule(self):
        result = compile_units(
            unit(
                "rule",
                "A serial identifier must contain exactly six characters.",
                page=1,
                section=("Serial",),
            )
        )
        return any_executable(result)[0]

    def test_exact_match(self) -> None:
        assert evaluate_rule(self._rule(), {"value": "ABC123"}).status == (
            RuleEvaluationStatus.MATCH.value
        )

    def test_longer_fails(self) -> None:
        assert evaluate_rule(self._rule(), {"value": "ABC1234"}).status == (
            RuleEvaluationStatus.NO_MATCH.value
        )

    def test_shorter_fails(self) -> None:
        assert evaluate_rule(self._rule(), {"value": "ABC12"}).status == (
            RuleEvaluationStatus.NO_MATCH.value
        )


# -----------------------------------------------------------------------------
# DOMINIO C — MINIMUM LENGTH
# -----------------------------------------------------------------------------


class TestDomainCMinimumLength:
    def _rule(self):
        result = compile_units(
            unit(
                "rule",
                "Passwords must contain at least 12 characters.",
                page=1,
                section=("Security",),
            )
        )
        return any_executable(result)[0]

    def test_eleven_fails(self) -> None:
        assert evaluate_rule(self._rule(), {"value": "x" * 11}).status == (
            RuleEvaluationStatus.NO_MATCH.value
        )

    def test_twelve_passes(self) -> None:
        assert evaluate_rule(self._rule(), {"value": "x" * 12}).status == (
            RuleEvaluationStatus.MATCH.value
        )

    def test_fifteen_passes(self) -> None:
        assert evaluate_rule(self._rule(), {"value": "x" * 15}).status == (
            RuleEvaluationStatus.MATCH.value
        )


# -----------------------------------------------------------------------------
# DOMINIO D — NUMERIC RANGE
# -----------------------------------------------------------------------------


class TestDomainDNumericRange:
    def _rule(self):
        result = compile_units(
            unit(
                "rule",
                "Eligible values are greater than 10 and less than or equal to 20.",
                page=1,
                section=("Eligibility",),
            )
        )
        return any_executable(result)[0]

    def test_ten_fails(self) -> None:
        assert evaluate_rule(self._rule(), {"value": 10}).status == (
            RuleEvaluationStatus.NO_MATCH.value
        )

    def test_ten_one_passes(self) -> None:
        assert evaluate_rule(self._rule(), {"value": 10.1}).status == (
            RuleEvaluationStatus.MATCH.value
        )

    def test_twenty_passes(self) -> None:
        assert evaluate_rule(self._rule(), {"value": 20}).status == (
            RuleEvaluationStatus.MATCH.value
        )

    def test_twenty_one_fails(self) -> None:
        assert evaluate_rule(self._rule(), {"value": 20.1}).status == (
            RuleEvaluationStatus.NO_MATCH.value
        )


# -----------------------------------------------------------------------------
# DOMINIO E — DATE
# -----------------------------------------------------------------------------


class TestDomainEDate:
    def _rule(self):
        result = compile_units(
            unit(
                "rule",
                "Applications received before 1 July are processed under Rule A.",
                page=1,
                section=("Applications",),
            )
        )
        return any_executable(result)[0]

    def test_june_is_rule_a(self) -> None:
        assert evaluate_rule(self._rule(), {"value": "2026-06-30"}).status == (
            RuleEvaluationStatus.MATCH.value
        )

    def test_july_first_is_not_rule_a(self) -> None:
        assert evaluate_rule(self._rule(), {"value": "2026-07-01"}).status == (
            RuleEvaluationStatus.NO_MATCH.value
        )


# -----------------------------------------------------------------------------
# DOMINIO F — EXCEPTION
# -----------------------------------------------------------------------------


class TestDomainFException:
    def _rules(self):
        return compile_units(
            unit(
                "rule",
                "Orders above 500 require approval unless the customer is "
                "classified as VIP.",
                page=1,
                section=("Orders",),
            )
        )

    def test_non_vip_over_threshold_requires_approval(self) -> None:
        rule = rule_with(self._rules(), "require approval")
        assert rule is not None
        assert evaluate_rule(rule, {"value": 600, "vip": False}).status == (
            RuleEvaluationStatus.MATCH.value
        )

    def test_vip_over_threshold_excepted(self) -> None:
        rule = rule_with(self._rules(), "require approval")
        assert rule is not None
        assert evaluate_rule(rule, {"value": 600, "vip": True}).status == (
            RuleEvaluationStatus.NOT_APPLICABLE.value
        )

    def test_below_threshold_does_not_require(self) -> None:
        rule = rule_with(self._rules(), "require approval")
        assert rule is not None
        assert evaluate_rule(rule, {"value": 400, "vip": False}).status == (
            RuleEvaluationStatus.NO_MATCH.value
        )


# -----------------------------------------------------------------------------
# DOMINIO G — ONLY IF
# -----------------------------------------------------------------------------


class TestDomainGOnlyIf:
    def _rule(self):
        result = compile_units(
            unit(
                "rule",
                "Feature X may be enabled only if both A and B are active.",
                page=1,
                section=("Features",),
            )
        )
        return any_executable(result)[0]

    def test_both_active_allows(self) -> None:
        assert evaluate_rule(self._rule(), {"a": True, "b": True}).status == (
            RuleEvaluationStatus.MATCH.value
        )

    def test_only_a_does_not_allow(self) -> None:
        assert evaluate_rule(self._rule(), {"a": True, "b": False}).status == (
            RuleEvaluationStatus.NO_MATCH.value
        )

    def test_only_b_does_not_allow(self) -> None:
        assert evaluate_rule(self._rule(), {"a": False, "b": True}).status == (
            RuleEvaluationStatus.NO_MATCH.value
        )


# -----------------------------------------------------------------------------
# DOMINIO H — ENUM
# -----------------------------------------------------------------------------


class TestDomainHEnum:
    def _rule(self):
        result = compile_units(
            unit(
                "rule",
                "Supported statuses are OPEN, CLOSED and PENDING.",
                page=1,
                section=("Statuses",),
            )
        )
        return any_executable(result)[0]

    def test_open_valid(self) -> None:
        assert evaluate_rule(self._rule(), {"value": "OPEN"}).status == (
            RuleEvaluationStatus.MATCH.value
        )

    def test_unknown_invalid(self) -> None:
        assert evaluate_rule(self._rule(), {"value": "UNKNOWN"}).status == (
            RuleEvaluationStatus.NO_MATCH.value
        )


# -----------------------------------------------------------------------------
# DOMINIO I — OVERRIDE
# -----------------------------------------------------------------------------


class TestDomainIOverride:
    def test_final_product_no_refund(self) -> None:
        result = compile_units(
            unit(
                "rule",
                "The general refund window is 30 days.",
                page=1,
                section=("Refunds",),
            ),
            unit(
                "rule",
                "For products marked FINAL, refunds are not allowed.",
                page=1,
                section=("Refunds",),
            ),
        )
        rule = rule_with(result, "not allowed")
        assert rule is not None, "la regla específica debe compilar"
        outcome = evaluate_rule(rule, {"value": "FINAL"})
        assert outcome.status == RuleEvaluationStatus.MATCH.value
        general = rule_with(result, "30 days")
        if general is not None:
            assert evaluate_rule(general, {"value": "STANDARD"}).status in (
                RuleEvaluationStatus.MATCH.value,
                RuleEvaluationStatus.NOT_APPLICABLE.value,
            )


# -----------------------------------------------------------------------------
# DOMINIO J — DISTRIBUTED RULE
# -----------------------------------------------------------------------------


class TestDomainJDistributed:
    def _rules(self):
        return compile_units(
            unit("definition", "# is a numeric position.", page=1, section=("Grammar",)),
            unit(
                "reference",
                "Pattern comparisons begin at the left-most character.",
                page=4,
                section=("Grammar",),
            ),
            unit(
                "definition",
                "The input may contain additional characters after all pattern "
                "positions have been evaluated.",
                page=9,
                section=("Grammar",),
            ),
        )

    def test_distributed_match(self) -> None:
        rule = any_executable(self._rules())[0]
        assert evaluate_rule(rule, {"value": "123ABC", "pattern": "###"}).status == (
            RuleEvaluationStatus.MATCH.value
        )

    def test_distributed_provenance_requires_three_pages(self) -> None:
        rule = any_executable(self._rules())[0]
        pages = {
            item.locator.get("page")
            for item in rule.provenance
            if item.locator.get("page") is not None
        }
        assert {1, 4, 9}.issubset(pages), f"provenance incompleta: {pages}"


# -----------------------------------------------------------------------------
# 2 — NO-INFERENCE
# -----------------------------------------------------------------------------


class TestNoInference:
    def test_length_recorded_is_not_exact(self) -> None:
        result = compile_units(
            unit("note", "The length is recorded in field X.", section=("Notes",))
        )
        for rule in result.canonical_rules:
            prop = rule.properties.get("length.policy")
            if prop is not None:
                assert prop.value != LengthPolicy.EXACT.value

    def test_pattern_length_information_shown_is_unknown(self) -> None:
        result = compile_units(
            unit(
                "note",
                "Pattern length information is shown below.",
                section=("Notes",),
            )
        )
        for rule in result.canonical_rules:
            prop = rule.properties.get("length.policy")
            if prop is not None:
                assert prop.value == LengthPolicy.UNKNOWN.value

    def test_values_compared_is_not_literal_equality(self) -> None:
        result = compile_units(
            unit("note", "Values are compared.", section=("Notes",))
        )
        for rule in result.canonical_rules:
            prop = rule.properties.get("matching.operator")
            assert prop is None or prop.value != "LITERAL"

    def test_maximum_field_stores_value_is_not_a_bound(self) -> None:
        result = compile_units(
            unit("note", "The maximum field stores a value.", section=("Notes",))
        )
        for rule in result.canonical_rules:
            assert not any(
                name.endswith(".maximum") for name in rule.properties
            ), "un 'maximum field' no establece un límite"

    def test_example_is_not_enum(self) -> None:
        result = compile_units(
            unit(
                "note",
                "Examples include ABCD.",
                section=("Notes",),
            )
        )
        for rule in result.canonical_rules:
            assert "ABCD" not in rule.enumeration.allowed


# -----------------------------------------------------------------------------
# 3 — DIRECTIONALITY
# -----------------------------------------------------------------------------


class TestDirectionality:
    def test_longer_than_direction(self) -> None:
        from src.core.domain.rule_semantics import analyze_language

        signals = analyze_language("A may be longer than B.")
        length = signals.length
        assert length.left_operand.strip().lower().startswith("a")
        assert length.right_operand.strip().lower().startswith("b")
        assert length.left_operand.strip().lower() != length.right_operand.strip().lower()

    def test_date_order_not_inverted(self) -> None:
        from src.core.domain.rule_semantics import analyze_language

        signals = analyze_language(
            "The request date must be earlier than the departure date."
        )
        comparisons = signals.comparisons
        assert comparisons, "la comparación temporal debe preservar operandos"
        left = comparisons[0].left_operand.lower()
        right = comparisons[0].right_operand.lower()
        assert "request" in left or "request" in left
        assert "departure" in right
        assert comparisons[0].operator in ("LT", "BEFORE")

    def test_must_not_exceed_is_le(self) -> None:
        from src.core.domain.rule_semantics import analyze_language

        signals = analyze_language("X must not exceed Y.")
        operators = {item.operator for item in signals.comparisons}
        assert "LTE" in operators, f"negación perdida: {operators}"


# -----------------------------------------------------------------------------
# 4 — NEGATIONS
# -----------------------------------------------------------------------------


class TestNegations:
    @pytest.mark.parametrize(
        "text,expected_modality",
        [
            ("The value must be present.", ModalityKind.MUST.value),
            ("The value must not be present.", ModalityKind.MUST_NOT.value),
            ("The value may be present.", ModalityKind.MAY.value),
            ("The value may not be present.", ModalityKind.MUST_NOT.value),
            ("The value cannot be present.", ModalityKind.MUST_NOT.value),
        ],
    )
    def test_modality_matrix(self, text: str, expected_modality: str) -> None:
        from src.core.domain.rule_semantics import analyze_language

        assert analyze_language(text).modality.modality == expected_modality

    def test_except_unless_does_not_apply_keep_negation(self) -> None:
        from src.core.domain.rule_semantics import analyze_language

        for text in (
            "Applies except when the value is zero.",
            "Applies unless the value is zero.",
            "This does not apply when the value is zero.",
            "The field is not required.",
        ):
            signals = analyze_language(text)
            assert signals.negation.negated, f"negación perdida: {text}"
            operators = {item.operator for item in signals.logic}
            assert "NOT" in operators or signals.negation.negated


# -----------------------------------------------------------------------------
# 5 — BOUNDARIES
# -----------------------------------------------------------------------------


class TestBoundaries:
    @pytest.mark.parametrize(
        "text,operator,boundary",
        [
            ("at least 10", "GTE", BoundaryKind.INCLUSIVE.value),
            ("greater than 10", "GT", None),
            ("greater than or equal to 10", "GTE", BoundaryKind.INCLUSIVE.value),
            ("up to 10", "LTE", BoundaryKind.UNKNOWN.value),
            ("up to and including 10", "LTE", BoundaryKind.INCLUSIVE.value),
            ("on or before 10", "LTE", BoundaryKind.INCLUSIVE.value),
            ("on or after 10", "GTE", BoundaryKind.INCLUSIVE.value),
        ],
    )
    def test_comparison_boundaries(self, text, operator, boundary) -> None:
        from src.core.domain.rule_semantics import analyze_language

        comparisons = analyze_language(text).comparisons
        assert comparisons, f"sin comparación: {text}"
        if operator == "BEFORE":
            operators = {item.operator for item in comparisons}
            assert operator in operators
            return
        operators = {item.operator for item in comparisons}
        assert operator in operators, f"{operators} != {operator}"
        if boundary is not None:
            match = next(item for item in comparisons if item.operator == operator)
            assert match.boundary == boundary


# -----------------------------------------------------------------------------
# 6 — MULTI-SENTENCE (una sola oración no alcanza)
# -----------------------------------------------------------------------------


class TestMultiSentence:
    def _rules(self):
        return compile_units(
            unit(
                "note",
                "The field identifies an item mask.",
                page=1,
                section=("Mask",),
            ),
            unit(
                "definition",
                "Each # represents one numeric position.",
                page=2,
                section=("Mask",),
            ),
            unit(
                "reference",
                "Comparison starts from the right.",
                page=3,
                section=("Mask",),
            ),
            unit(
                "reference",
                "Extra leading characters are permitted.",
                page=4,
                section=("Mask",),
            ),
        )

    def test_single_sentence_is_not_enough(self) -> None:
        partial = compile_units(
            unit(
                "definition",
                "Each # represents one numeric position.",
                page=2,
                section=("Mask",),
            )
        )
        assert not any_executable(partial), (
            "una definición aislada no puede resolver la consulta completa"
        )

    def test_full_grammar_matches(self) -> None:
        rule = any_executable(self._rules())[0]
        assert evaluate_rule(rule, {"value": "AB123", "pattern": "###"}).status == (
            RuleEvaluationStatus.MATCH.value
        )
        assert evaluate_rule(rule, {"value": "12X", "pattern": "###"}).status == (
            RuleEvaluationStatus.NO_MATCH.value
        )


# -----------------------------------------------------------------------------
# 7 — CROSS-PAGE EXCEPTIONS
# -----------------------------------------------------------------------------


class TestCrossPageException:
    def test_exception_from_page15_attached(self) -> None:
        result = compile_units(
            unit(
                "rule",
                "Orders above 500 require approval.",
                page=2,
                section=("Orders",),
            ),
            unit(
                "note",
                "This does not apply when the customer is classified as VIP.",
                page=15,
                section=("Exceptions",),
            ),
        )
        rule = rule_with(result, "require approval")
        assert rule is not None
        assert rule.exceptions, "la excepción de la página 15 debe adjuntarse"

    def test_only_rule_page_leaves_coverage_incomplete(self) -> None:
        result = compile_units(
            unit(
                "rule",
                "Orders above 500 require approval.",
                page=2,
                section=("Orders",),
            )
        )
        rule = rule_with(result, "require approval")
        assert rule is not None
        item = type("Item", (), {})()
        item.content = "Orders above 500 require approval."
        item.evidence_id = "ev_rule"
        item.metadata = {"exception_ids": ["fabric-exc-1"]}
        grounded = reason_over_evidence(
            question="¿600 requiere aprobación?",
            evidence_items=[item],
            canonical_rules=result.canonical_rules,
        )
        assert any(
            "exception" in str(missing).lower()
            for missing in grounded.missing_premises
        ), "sin la excepción recuperada, la cobertura debe quedar incompleta"


# -----------------------------------------------------------------------------
# 8 — CONFLICT + TEMPORALITY
# -----------------------------------------------------------------------------


class TestTemporalConflict:
    def _result(self):
        return compile_units(
            unit(
                "rule",
                "Minimum quantity is 10.",
                page=1,
                section=("Quantity",),
            ),
            unit(
                "rule",
                "Effective January 2027, minimum quantity is 20.",
                page=2,
                section=("Quantity",),
            ),
        )

    def test_conflict_is_recorded(self) -> None:
        result = self._result()
        assert result.conflicts, "las dos fuentes deben conflictuar"

    def test_with_date_picks_correct_version(self) -> None:
        result = self._result()
        older = rule_with(result, "quantity is 10")
        newer = rule_with(result, "quantity is 20")
        assert older is not None and newer is not None
        # 2026: rige la versión sin ventana.
        assert evaluate_rule(
            older, {"value": 15, "reference_date": "2026-06-01"}
        ).status == RuleEvaluationStatus.MATCH.value
        # 2027: rige la versión vigente desde enero 2027.
        assert evaluate_rule(
            newer, {"value": 25, "reference_date": "2027-06-01"}
        ).status == RuleEvaluationStatus.MATCH.value
        # La versión nueva no aplica antes de su vigencia (no se elige sola).
        assert evaluate_rule(
            newer, {"value": 25, "reference_date": "2026-06-01"}
        ).status == RuleEvaluationStatus.NOT_APPLICABLE.value

    def test_without_date_does_not_choose(self) -> None:
        result = self._result()
        older = rule_with(result, "quantity is 10")
        newer = rule_with(result, "quantity is 20")
        assert older is not None and newer is not None
        older_outcome = evaluate_rule(older, {"value": 15})
        newer_outcome = evaluate_rule(newer, {"value": 15})
        assert older_outcome.status == RuleEvaluationStatus.UNDETERMINED.value
        assert newer_outcome.status == RuleEvaluationStatus.UNDETERMINED.value


# -----------------------------------------------------------------------------
# 9 — EXAMPLE VS RULE
# -----------------------------------------------------------------------------


class TestExampleVsRule:
    def _result(self):
        return compile_units(
            unit(
                "rule",
                "Allowed prefixes are A and B.",
                page=1,
                section=("Prefixes",),
            ),
            unit(
                "example",
                "For example, A123 is valid.",
                page=2,
                section=("Examples",),
            ),
        )

    def test_allowed_set_is_exactly_declared(self) -> None:
        result = self._result()
        allowed = [
            rule.enumeration.allowed
            for rule in result.canonical_rules
            if rule.enumeration.allowed
        ]
        assert allowed, "el set permitido debe compilarse"
        assert sorted(allowed[0]) == ["A", "B"]

    def test_example_value_not_a_rule(self) -> None:
        result = self._result()
        for rule in result.canonical_rules:
            assert "1234" not in rule.statement.lower()
            assert "A123" not in rule.enumeration.allowed


# -----------------------------------------------------------------------------
# 10 — TABLE SEMANTICS
# -----------------------------------------------------------------------------


class TestTableSemantics:
    def test_table_rows_do_not_invert_allowed(self) -> None:
        result = compile_units(
            unit("column", "Status", page=1, section=("Table",)),
            unit("column", "Meaning", page=1, section=("Table",)),
            unit("column", "Allowed", page=1, section=("Table",)),
            unit("table", "A | Active | Yes", page=1, section=("Table",)),
            unit("table", "I | Inactive | No", page=1, section=("Table",)),
        )
        for rule in result.canonical_rules:
            assert "I" not in rule.enumeration.allowed or "No" not in (
                rule.enumeration.allowed
            )


# -----------------------------------------------------------------------------
# 11 — FORMULA
# -----------------------------------------------------------------------------


class TestFormulaAdversarial:
    def _rule(self):
        result = compile_units(
            unit(
                "rule",
                "Total = subtotal + tax - discount.",
                page=1,
                section=("Pricing",),
            )
        )
        return any_executable(result)[0]

    def test_operands_and_signs(self) -> None:
        rule = self._rule()
        expression = rule.formula.expression.replace(" ", "")
        assert expression == "subtotal+tax-discount"

    def test_deterministic_result(self) -> None:
        outcome = evaluate_rule(
            self._rule(), {"subtotal": 100, "tax": 20, "discount": 5}
        )
        assert outcome.status == RuleEvaluationStatus.MATCH.value
        assert outcome.result == 115

    def test_generator_cannot_recompute(self) -> None:
        outcome = evaluate_rule(
            self._rule(), {"subtotal": 100, "tax": 20, "discount": 5}
        )
        verdict = enforce_derived_result(
            "Total = 130.", [outcome_to_claim(outcome, self._rule())]
        )
        assert verdict.action == "override"
        assert "115" in verdict.answer


def outcome_to_claim(outcome, rule):
    return {
        "statement": rule.statement,
        "result": outcome.result,
        "operation": outcome.operation,
        "deterministic": True,
        "verification_status": "SUPPORTED",
        "user_inputs": ["subtotal=100", "tax=20", "discount=5"],
        "evidence_refs": ["ev_1"],
        "canonical_rule_ids": [rule.rule_id],
        "conflicts": [],
    }


# -----------------------------------------------------------------------------
# 12 — RETRIEVAL FAILURE
# -----------------------------------------------------------------------------


class TestRetrievalFailureAdversarial:
    def test_timeout_with_zero_evidence(self) -> None:
        state, message = resolve_answer_state(
            is_knowledge_question=True,
            retrieval_failed=True,
            retrieval_reason="TimeoutError: embedding stage",
            evidence_count=0,
        )
        assert state == "RETRIEVAL_UNAVAILABLE"
        assert "no llegó a ejecutarse" in message

    def test_engine_state_is_distinct(self) -> None:
        result = retrieval_unavailable_result(
            "¿cuál es la política?", reason="provider down"
        )
        assert result.answerability == RETRIEVAL_UNAVAILABLE
        assert result.answerability != ANSWERABLE_DERIVED


# -----------------------------------------------------------------------------
# 13 — PARTIAL EVIDENCE
# -----------------------------------------------------------------------------


class TestPartialEvidence:
    def test_only_symbol_definition_is_undetermined(self) -> None:
        result = compile_units(
            unit("definition", "# is a digit.", page=1, section=("Grammar",))
        )
        if any_executable(result):
            rule = any_executable(result)[0]
            outcome = evaluate_rule(rule, {"value": "123", "pattern": "###"})
            assert outcome.status == RuleEvaluationStatus.UNDETERMINED.value
        else:
            # Sin regla ejecutable tampoco puede afirmarse MATCH/NO_MATCH.
            assert all(
                not rule.executable for rule in result.canonical_rules
            )


# -----------------------------------------------------------------------------
# 14 — ADVERSARIAL GENERATOR
# -----------------------------------------------------------------------------


class TestAdversarialGenerator:
    def test_true_cannot_become_false(self) -> None:
        claim = {
            "statement": "la regla se cumple",
            "result": True,
            "operation": "BOOLEAN",
            "deterministic": True,
            "verification_status": "SUPPORTED",
            "user_inputs": ["value=600"],
            "evidence_refs": ["ev_1"],
            "canonical_rule_ids": ["rule:x"],
            "conflicts": [],
        }
        verdict = enforce_derived_result("The answer is FALSE.", [claim])
        assert verdict.action == "override"
        assert "cumple" in verdict.answer
        assert "FALSE" not in verdict.answer


# -----------------------------------------------------------------------------
# 15 — PARAPHRASES
# -----------------------------------------------------------------------------


PARAPHRASES = (
    "The value may contain additional characters beyond those represented by the mask.",
    "The value can be longer than the pattern.",
    "Additional trailing characters are permitted after the pattern.",
    "Extra characters after the matched portion are allowed.",
)


class TestParaphrases:
    @pytest.mark.parametrize("sentence", PARAPHRASES)
    def test_same_canonical_length_policy(self, sentence: str) -> None:
        result = compile_units(
            unit("definition", sentence, page=1, section=("Matching",)),
            unit("reference", "Matching is positional.", page=1, section=("Matching",)),
        )
        rule = rule_with(result, sentence[:24])
        assert rule is not None, f"no compiló: {sentence}"
        prop = rule.properties.get("length.policy")
        assert prop is not None and prop.value == (
            LengthPolicy.VALUE_MAY_BE_LONGER.value
        ), f"paráfrasis no reconocida: {sentence} -> {prop.value if prop else None}"


# -----------------------------------------------------------------------------
# 16 — UNKNOWN DOCUMENT (dominio inventado)
# -----------------------------------------------------------------------------


class TestUnknownDocument:
    def _rules(self):
        return compile_units(
            unit("definition", "Each § represents one letter.", page=1, section=("Tessera",)),
            unit(
                "reference",
                "Tiles are matched from the right edge.",
                page=1,
                section=("Tessera",),
            ),
            unit(
                "definition",
                "A value may carry filler characters in front of the matched tile.",
                page=1,
                section=("Tessera",),
            ),
        )

    def test_grammar_reconstructed(self) -> None:
        rule = any_executable(self._rules())[0]
        assert evaluate_rule(rule, {"value": "ABCDEF", "pattern": "§§"}).status == (
            RuleEvaluationStatus.MATCH.value
        )

    def test_filler_before_tile_allowed(self) -> None:
        rule = any_executable(self._rules())[0]
        assert evaluate_rule(rule, {"value": "XYZAB", "pattern": "§§"}).status == (
            RuleEvaluationStatus.MATCH.value
        )

    def test_wrong_symbol_type_fails(self) -> None:
        rule = any_executable(self._rules())[0]
        assert evaluate_rule(rule, {"value": "ABC12", "pattern": "§§"}).status == (
            RuleEvaluationStatus.NO_MATCH.value
        )


# -----------------------------------------------------------------------------
# 17 — ATPCO REAL WORDING (solo frases reales disponibles en el repo)
# -----------------------------------------------------------------------------


class TestAtpcoRealWording:
    def _rules(self):
        return compile_units(
            unit(
                "definition",
                "& represents one alphanumeric position. Matching is positional, "
                "left to right. Literal characters must match exactly at their position.",
                page=1,
                section=("Kinds of characters",),
            ),
            unit(
                "reference",
                "The value may contain more characters than the pattern.",
                page=2,
                section=("Matching rules",),
            ),
        )

    def test_symbol_direction_literal(self) -> None:
        rule = any_executable(self._rules())[0]
        assert rule.properties["matching.operator"].value == "POSITIONAL"
        assert rule.properties["matching.literal"].value is True
        assert evaluate_rule(rule, {"value": "QNNF0SME", "pattern": "&&&F"}).status == (
            RuleEvaluationStatus.MATCH.value
        )

    def test_intermediate_mismatch(self) -> None:
        rule = any_executable(self._rules())[0]
        assert evaluate_rule(rule, {"value": "QNNG0SME", "pattern": "&&&F"}).status == (
            RuleEvaluationStatus.NO_MATCH.value
        )
        assert evaluate_rule(rule, {"value": "QNN-0SME", "pattern": "&&&F"}).status == (
            RuleEvaluationStatus.NO_MATCH.value
        )

    def test_real_negative_rule(self) -> None:
        result = compile_units(
            unit(
                "rule",
                "The carrier must not change the fare basis code on reissue.",
                page=1,
                section=("Record 4",),
            )
        )
        rule = rule_with(result, "must not change")
        assert rule is not None
        assert rule.modality == "MUST_NOT"
        assert rule.properties["polarity"].value == "NEGATIVE"


# -----------------------------------------------------------------------------
# 19 — MUTATION TESTING
# -----------------------------------------------------------------------------


class TestMutationSemantics:
    def _status(self, text: str, values: dict) -> str:
        result = compile_units(
            unit("rule", text, page=1, section=("Mutation",))
        )
        rules = any_executable(result)
        if not rules:
            return "NO_EXECUTABLE"
        return evaluate_rule(rules[0], values).status

    def test_at_least_to_greater_than_changes_boundary(self) -> None:
        inclusive = self._status(
            "The value must be at least 10.", {"value": 10}
        )
        exclusive = self._status(
            "The value must be greater than 10.", {"value": 10}
        )
        assert inclusive == RuleEvaluationStatus.MATCH.value
        assert exclusive == RuleEvaluationStatus.NO_MATCH.value

    def test_may_to_must_changes_modality(self) -> None:
        from src.core.domain.rule_semantics import analyze_language

        assert analyze_language("The value may be enabled.").modality.modality == (
            ModalityKind.MAY.value
        )
        assert analyze_language("The value must be enabled.").modality.modality == (
            ModalityKind.MUST.value
        )

    def test_before_to_on_or_before_changes_boundary(self) -> None:
        before = self._status(
            "Applications received before 1 July 2026.", {"value": "2026-07-01"}
        )
        on_or_before = self._status(
            "Applications received on or before 1 July 2026.",
            {"value": "2026-07-01"},
        )
        assert before == RuleEvaluationStatus.NO_MATCH.value
        assert on_or_before == RuleEvaluationStatus.MATCH.value

    def test_may_contain_more_to_exact_changes_policy(self) -> None:
        longer = self._status(
            "The value may contain more characters than the pattern.",
            {"value": "ABCDEF", "pattern": "&&&"},
        )
        exact = self._status(
            "The value must contain exactly 3 characters.",
            {"value": "ABCDEF"},
        )
        assert longer == RuleEvaluationStatus.MATCH.value
        assert exact == RuleEvaluationStatus.NO_MATCH.value
