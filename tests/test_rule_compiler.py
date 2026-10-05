# =============================================================================
# Semantic Rule Compiler — pruebas cross-domain
# =============================================================================
# El compilador es domain-agnostic: los casos usan códigos de producto,
# políticas de RRHH, envíos, precios, fechas y catálogos. ATPCO aparece SOLO
# como regresión, con la redacción real disponible en las fuentes del repo.
#
# Invariantes:
#   - mención != política
#   - asimetría preservada
#   - UNKNOWN conservado
#   - excepciones y conflictos explícitos
#   - evidencia distribuida unida con provenance por propiedad
#   - ejemplos nunca son reglas
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest

from src.core.domain.rule_semantics import (
    LengthPolicy,
    VerificationState,
)
from src.knowledge.compiler.model import (
    EvidenceRef,
    SemanticUnit,
    SourceLocator,
)
from src.knowledge.rule_compiler import CanonicalRule, SemanticRuleCompiler
from src.knowledge.rule_compiler.evaluate import (
    RuleEvaluationStatus,
    evaluate_rule,
)

DOC = uuid4()


def unit(
    kind: str,
    text: str,
    *,
    page: int = 1,
    section: tuple[str, ...] = ("General",),
    label: str = "",
) -> SemanticUnit:
    return SemanticUnit(
        kind=kind,
        key=f"{kind}:{label or text[:30]}",
        label=label or text[:30],
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


def compile_units(*units: SemanticUnit):
    return SemanticRuleCompiler().compile(
        document_id=str(DOC),
        document_title="Manual",
        organization_id=str(uuid4()),
        units=list(units),
    )


def rules_matching(result, needle: str) -> list[CanonicalRule]:
    return [rule for rule in result.canonical_rules if needle in rule.statement]


def single_rule(result, needle: str) -> CanonicalRule:
    found = rules_matching(result, needle)
    assert found, f"no rule containing {needle!r}: {[r.statement for r in result.canonical_rules]}"
    return found[0]


class TestCrossDomain:
    def test_wildcard_product_code(self) -> None:
        result = compile_units(
            unit("definition", "A represents one letter.", page=1, section=("Codes",)),
            unit("definition", "# represents one digit.", page=1, section=("Codes",)),
            unit(
                "reference",
                "Matching is positional. The pattern and the value must have the same length.",
                page=2,
                section=("Codes",),
            ),
        )
        rule = single_rule(result, "Matching is positional")
        assert rule.executable
        assert evaluate_rule(rule, {"value": "ABC-123", "pattern": "AAA-###"}).status == (
            RuleEvaluationStatus.MATCH.value
        )
        assert evaluate_rule(rule, {"value": "ABC-12X", "pattern": "AAA-###"}).status == (
            RuleEvaluationStatus.NO_MATCH.value
        )

    def test_asymmetric_length_rule(self) -> None:
        result = compile_units(
            unit(
                "definition",
                "The value may contain more characters than the pattern.",
                page=1,
                section=("Matching",),
            ),
            unit(
                "definition",
                "& represents one alphanumeric position.",
                page=2,
                section=("Matching",),
            ),
            unit("reference", "Matching is positional.", page=2, section=("Matching",)),
        )
        rule = single_rule(result, "may contain more characters")
        policy = rule.properties["length.policy"].value
        assert policy == LengthPolicy.VALUE_MAY_BE_LONGER.value
        assert policy != LengthPolicy.EXACT.value
        longer = evaluate_rule(rule, {"value": "ABCDEFG", "pattern": "&&&"})
        assert longer.status == RuleEvaluationStatus.MATCH.value
        shorter = evaluate_rule(rule, {"value": "AB", "pattern": "&&&"})
        assert shorter.status == RuleEvaluationStatus.NO_MATCH.value

    def test_exact_length_rule(self) -> None:
        result = compile_units(
            unit(
                "rule",
                "The value must have exactly 4 characters.",
                page=1,
                section=("Codes",),
            ),
            unit("reference", "Matching is positional.", page=1, section=("Codes",)),
        )
        rule = single_rule(result, "exactly 4 characters")
        assert rule.properties["length.policy"].value == LengthPolicy.EXACT.value
        assert evaluate_rule(rule, {"value": "ABCD"}).status == RuleEvaluationStatus.MATCH.value
        assert evaluate_rule(rule, {"value": "ABCDE"}).status == RuleEvaluationStatus.NO_MATCH.value

    def test_inclusive_numeric_range(self) -> None:
        result = compile_units(
            unit(
                "rule",
                "The volume must be between 10 and 20 kg inclusive.",
                page=1,
                section=("Shipment",),
            )
        )
        rule = single_rule(result, "between 10 and 20")
        assert evaluate_rule(rule, {"value": 20}).status == RuleEvaluationStatus.MATCH.value
        assert evaluate_rule(rule, {"value": 21}).status == RuleEvaluationStatus.NO_MATCH.value

    def test_exclusive_numeric_range(self) -> None:
        result = compile_units(
            unit(
                "rule",
                "The volume must be greater than 10 and less than 20.",
                page=1,
                section=("Shipment",),
            )
        )
        rule = single_rule(result, "greater than 10")
        assert evaluate_rule(rule, {"value": 15}).status == RuleEvaluationStatus.MATCH.value
        assert evaluate_rule(rule, {"value": 10}).status == RuleEvaluationStatus.NO_MATCH.value
        assert evaluate_rule(rule, {"value": 20}).status == RuleEvaluationStatus.NO_MATCH.value

    def test_minimum_quantity(self) -> None:
        result = compile_units(
            unit(
                "rule",
                "Applicants must be at least 18 years old.",
                page=1,
                section=("HR",),
            )
        )
        rule = single_rule(result, "at least 18")
        assert evaluate_rule(rule, {"value": 18}).status == RuleEvaluationStatus.MATCH.value
        assert evaluate_rule(rule, {"value": 17}).status == RuleEvaluationStatus.NO_MATCH.value

    def test_date_before(self) -> None:
        result = compile_units(
            unit(
                "rule",
                "The request must be submitted before 15/03/2026.",
                page=1,
                section=("Dates",),
            )
        )
        rule = single_rule(result, "before 15/03/2026")
        assert evaluate_rule(rule, {"value": "2026-03-01"}).status == (
            RuleEvaluationStatus.MATCH.value
        )
        assert evaluate_rule(rule, {"value": "2026-04-01"}).status == (
            RuleEvaluationStatus.NO_MATCH.value
        )

    def test_date_until_including(self) -> None:
        result = compile_units(
            unit(
                "rule",
                "The promotion is valid until 31/12/2026 inclusive.",
                page=1,
                section=("Dates",),
            )
        )
        rule = single_rule(result, "until 31/12/2026")
        assert evaluate_rule(rule, {"value": "2026-12-31"}).status == (
            RuleEvaluationStatus.MATCH.value
        )
        assert evaluate_rule(rule, {"value": "2027-01-01"}).status == (
            RuleEvaluationStatus.NO_MATCH.value
        )

    def test_unless_exception_preserved(self) -> None:
        result = compile_units(
            unit(
                "rule",
                "The carrier must not change the fare basis code on reissue, "
                "unless the ticket is reissued.",
                page=1,
                section=("Changes",),
            )
        )
        rule = single_rule(result, "must not change")
        assert rule.exceptions
        assert any("unless" in exception.lower() for exception in rule.exceptions)
        assert rule.properties["polarity"].value == "NEGATIVE"

    def test_only_if_not_bidirectional(self) -> None:
        result = compile_units(
            unit(
                "rule",
                "The override applies only if the carrier agrees.",
                page=1,
                section=("Overrides",),
            )
        )
        rule = single_rule(result, "only if")
        operators = rule.properties["logic.operators"].value
        assert "ONLY_IF" in operators
        assert "IF_AND_ONLY_IF" not in operators

    def test_allowed_enum(self) -> None:
        result = compile_units(
            unit(
                "rule",
                "Allowed values: RED, GREEN, BLUE.",
                page=1,
                section=("Colors",),
            )
        )
        rule = single_rule(result, "Allowed values")
        assert rule.enumeration.allowed == ["RED", "GREEN", "BLUE"]
        assert evaluate_rule(rule, {"value": "RED"}).status == RuleEvaluationStatus.MATCH.value
        assert evaluate_rule(rule, {"value": "YELLOW"}).status == (
            RuleEvaluationStatus.NO_MATCH.value
        )

    def test_prohibited_enum(self) -> None:
        result = compile_units(
            unit(
                "rule",
                "Prohibited values: X, Y.",
                page=1,
                section=("Codes",),
            )
        )
        rule = single_rule(result, "Prohibited values")
        assert rule.enumeration.prohibited == ["X", "Y"]
        assert evaluate_rule(rule, {"value": "X"}).status == RuleEvaluationStatus.NO_MATCH.value
        assert evaluate_rule(rule, {"value": "Z"}).status == RuleEvaluationStatus.MATCH.value

    def test_formula_with_unit(self) -> None:
        result = compile_units(
            unit(
                "rule",
                "total = price * quantity in USD.",
                page=1,
                section=("Pricing",),
            )
        )
        rule = single_rule(result, "total = price")
        assert rule.kind == "FORMULA"
        assert rule.formula.expression == "price * quantity"
        assert rule.formula.unit == "USD"
        evaluation = evaluate_rule(rule, {"price": 10, "quantity": 3})
        assert evaluation.status == RuleEvaluationStatus.MATCH.value
        assert evaluation.result == 30

    def test_rule_split_between_two_pages(self) -> None:
        result = compile_units(
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
        rule = single_rule(result, "Matching is positional")
        assert rule.executable
        assert rule.properties["length.policy"].value == (
            LengthPolicy.VALUE_MAY_BE_LONGER.value
        )
        pages = {
            item.locator.get("page")
            for item in rule.provenance
            if item.locator.get("page") is not None
        }
        assert {1, 2, 7}.issubset(pages)
        assert evaluate_rule(rule, {"value": "ASDFGRE", "pattern": "&&&F"}).status == (
            RuleEvaluationStatus.MATCH.value
        )

    def test_definition_page_and_condition_page(self) -> None:
        result = compile_units(
            unit(
                "definition",
                "The symbol & represents one alphanumeric position.",
                page=1,
                section=("Kinds of characters",),
            ),
            unit(
                "rule",
                "The code must match the mask &&&F.",
                page=5,
                section=("Field usage",),
            ),
        )
        rule = single_rule(result, "must match the mask")
        assert rule.relations.get("USES_SYMBOL")
        eval_pages = {
            item.locator.get("page")
            for item in rule.provenance
            if item.locator.get("page") is not None
        }
        assert {1, 5}.issubset(eval_pages)
        assert evaluate_rule(rule, {"value": "ASDF", "pattern": "&&&F"}).status == (
            RuleEvaluationStatus.MATCH.value
        )

    def test_distant_exception_attached(self) -> None:
        result = compile_units(
            unit(
                "rule",
                "The carrier must not change the fare basis code on reissue.",
                page=2,
                section=("Changes",),
            ),
            unit(
                "note",
                "This does not apply when the carrier reissues the ticket.",
                page=9,
                section=("Exceptions",),
            ),
        )
        rule = single_rule(result, "must not change")
        assert rule.exceptions
        assert any("does not apply" in exception.lower() for exception in rule.exceptions)

    def test_two_contradictory_rules(self) -> None:
        result = compile_units(
            unit(
                "definition",
                "The value must have exactly 8 characters.",
                page=1,
                section=("Length policy",),
            ),
            unit(
                "definition",
                "The value may contain more characters than the pattern.",
                page=1,
                section=("Length policy",),
            ),
        )
        assert result.conflicts, "dos políticas de longitud distintas deben conflictuar"
        conflict = result.conflicts[0]
        assert conflict.property_name == "length.policy"
        assert conflict.resolution is None
        conflicting = [
            rule
            for rule in result.canonical_rules
            if rule.verification_state == VerificationState.CONFLICTING.value
        ]
        assert len(conflicting) == 2
        assert all(not rule.executable for rule in conflicting)

    def test_example_never_becomes_rule(self) -> None:
        result = compile_units(
            unit(
                "example",
                "For example the product code ABC-123 is valid for this family.",
                page=3,
                section=("Examples",),
            )
        )
        assert result.canonical_rules == []
        assert result.executable_rules == []

    def test_length_mention_without_policy_stays_unknown(self) -> None:
        result = compile_units(
            unit(
                "rule",
                "The code must comply with the length described in the annex.",
                page=1,
                section=("Codes",),
            )
        )
        rule = single_rule(result, "length described")
        assert rule.properties["length.policy"].value == LengthPolicy.UNKNOWN.value
        assert "length_policy" in rule.missing_premises
        assert not rule.executable

    def test_undetermined_answer_keeps_missing_premise(self) -> None:
        result = compile_units(
            unit(
                "rule",
                "The code must comply with the length described in the annex.",
                page=1,
                section=("Codes",),
            )
        )
        rule = single_rule(result, "length described")
        evaluation = evaluate_rule(rule, {"value": "ABCDEFGH"})
        assert evaluation.status == RuleEvaluationStatus.UNDETERMINED.value
        assert "length_policy" in evaluation.missing_premises

    def test_property_level_provenance(self) -> None:
        result = compile_units(
            unit(
                "definition",
                "The value may contain more characters than the pattern.",
                page=1,
                section=("Matching",),
            ),
            unit("reference", "Matching is positional.", page=2, section=("Matching",)),
        )
        rule = single_rule(result, "may contain more characters")
        assert rule.property_evidence("length.policy")
        assert rule.property_evidence("matching.operator")
        for evidence_id in rule.property_evidence("length.policy"):
            assert any(item.evidence_id == evidence_id for item in rule.provenance)

    def test_roundtrip_for_retrieval_metadata(self) -> None:
        result = compile_units(
            unit(
                "rule",
                "Applicants must be at least 18 years old.",
                page=1,
                section=("HR",),
            )
        )
        rule = single_rule(result, "at least 18")
        payload = rule.to_dict()
        rehydrated = CanonicalRule.from_dict(payload)
        assert rehydrated.rule_id == rule.rule_id
        assert rehydrated.properties["quantity.minimum"].value == 18.0
        assert rehydrated.executable is True


class TestAtpcoRegression:
    """Regresión ATPCO con la redacción REAL disponible en las fuentes.

    La lógica de producción no contiene ninguna condición ATPCO: el motor
    deriva la semántica del lenguaje usado en los documentos de prueba.
    """

    def test_real_record4_negative_rule(self) -> None:
        result = compile_units(
            unit(
                "rule",
                "The carrier must not change the fare basis code on reissue.",
                page=1,
                section=("Record 4",),
            )
        )
        rule = single_rule(result, "must not change")
        assert rule.modality == "MUST_NOT"
        assert rule.properties["polarity"].value == "NEGATIVE"
        assert rule.kind == "NORMATIVE_RULE"

    def test_real_pattern_grammar_wording(self) -> None:
        result = compile_units(
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
        rule = single_rule(result, "Matching is positional")
        assert rule.properties["matching.operator"].value == "POSITIONAL"
        assert rule.properties["matching.symbol.&"].value
        assert rule.properties["length.policy"].value == (
            LengthPolicy.VALUE_MAY_BE_LONGER.value
        )
        assert evaluate_rule(rule, {"value": "QNNF0SME", "pattern": "&&&F"}).status == (
            RuleEvaluationStatus.MATCH.value
        )
        assert evaluate_rule(rule, {"value": "QNNG0SME", "pattern": "&&&F"}).status == (
            RuleEvaluationStatus.NO_MATCH.value
        )

    def test_same_engine_on_non_atpco_domain(self) -> None:
        # Misma gramática, otro dominio: sin hardcode la conducta es idéntica.
        result = compile_units(
            unit(
                "definition",
                "A represents one letter. # represents one digit. Matching is positional. "
                "The pattern and the value must have the same length.",
                page=1,
                section=("Product codes",),
            )
        )
        rule = single_rule(result, "Matching is positional")
        assert evaluate_rule(rule, {"value": "XYZ-789", "pattern": "AAA-###"}).status == (
            RuleEvaluationStatus.MATCH.value
        )
        assert evaluate_rule(rule, {"value": "XYZ-78X", "pattern": "AAA-###"}).status == (
            RuleEvaluationStatus.NO_MATCH.value
        )


@pytest.mark.parametrize(
    "text,needle,expected_policy",
    [
        ("The pattern and the value must have the same length.", "same length", LengthPolicy.EXACT.value),
        ("The value may contain more characters than the pattern.", "more characters", LengthPolicy.VALUE_MAY_BE_LONGER.value),
        ("The pattern may contain more characters than the value.", "pattern may contain", LengthPolicy.PATTERN_MAY_BE_LONGER.value),
        ("At least 3 characters are required.", "At least 3", LengthPolicy.MIN_LENGTH.value),
        ("No more than 12 characters are allowed.", "No more than 12", LengthPolicy.MAX_LENGTH.value),
    ],
)
def test_length_policies_from_language(text: str, needle: str, expected_policy: str) -> None:
    result = compile_units(
        unit("definition", text, page=1, section=("Length",)),
        unit("reference", "Matching is positional.", page=1, section=("Length",)),
    )
    rule = single_rule(result, needle)
    assert rule.properties["length.policy"].value == expected_policy


class TestFabricProjection:
    def test_projection_connects_rule_evidence_and_exceptions(self) -> None:
        from src.knowledge.rule_compiler import project_rules_to_fabric

        result = compile_units(
            unit(
                "rule",
                "The carrier must not change the fare basis code on reissue, "
                "unless the ticket is reissued.",
                page=1,
                section=("Changes",),
            )
        )
        projection = project_rules_to_fabric(
            result.canonical_rules, document_id=str(DOC)
        )
        node_types = {node["node_type"] for node in projection["nodes"]}
        assert "Rule" in node_types
        assert "Evidence" in node_types
        assert "Exception" in node_types
        relations = {edge["relation_type"] for edge in projection["edges"]}
        assert {"SUPPORTED_BY", "HAS_EXCEPTION"}.issubset(relations)

    def test_projection_marks_conflicts(self) -> None:
        from src.knowledge.rule_compiler import project_rules_to_fabric

        result = compile_units(
            unit(
                "definition",
                "The value must have exactly 8 characters.",
                page=1,
                section=("Length policy",),
            ),
            unit(
                "definition",
                "The value may contain more characters than the pattern.",
                page=1,
                section=("Length policy",),
            ),
        )
        projection = project_rules_to_fabric(
            result.canonical_rules, document_id=str(DOC)
        )
        relations = {edge["relation_type"] for edge in projection["edges"]}
        assert "CONFLICTS_WITH" in relations


class TestLlmProposal:
    def test_llm_proposal_is_proposed_never_canonical(self) -> None:
        from src.knowledge.rule_compiler import SemanticRuleCompiler
        from src.knowledge.rule_compiler.verify import verify_candidate

        candidate = SemanticRuleCompiler.propose_candidate(
            {
                "rule_type": "CONSTRAINT",
                "subject": "fare basis",
                "statement": "The fare basis must match the pattern.",
                "confidence": 0.9,
                "semantics": {"length.policy": "EXACT"},
                "reason": "el modelo propone igualdad",
            },
            document_id=str(DOC),
        )
        assert candidate.extraction_method == "llm_proposed"
        assert candidate.properties["length.policy"].state == "PROPOSED"
        rule = verify_candidate(candidate)
        assert rule.executable is False
        assert rule.verification_state in {
            VerificationState.UNSUPPORTED.value,
            VerificationState.PARTIALLY_SUPPORTED.value,
            VerificationState.UNKNOWN.value,
        }
        assert not rule.supported
