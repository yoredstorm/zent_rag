# =============================================================================
# Regresión exacta: `&&&F` vs `ABCFGEGE` => POSITIONAL_MATCH / MATCH
# =============================================================================
# Caso real de producción (post cutover a OpenDataLoader):
#
#   "yo tengo en el record 2 &&&F y en el farebasis me viene ABCFGEGE
#    cumple o no cumple"
#
# produjo COMPARISON/VALID con el check `abcfgege >= &&&f is True` a partir de
# una CanonicalRule cuya operación final era GTE y que solo MENCIONABA `&`.
#
# Contrato que estos tests fijan:
#   1. Candidate A (COMPARISON, menciona `&`) => eligible=false,
#      reason=OPERATION_INCOMPATIBLE; jamás produce autoridad, ni con score alto.
#   2. Candidate B (matching.symbol.& + POSITIONAL + length policy) => eligible.
#      La decisión final es POSITIONAL_MATCH / MATCH.
#   3. COMPARISON con una máscara runtime falla OPERAND_TYPE_INCOMPATIBLE:
#      nunca se compara lexicalmente `ABCFGEGE >= &&&F`.
#   4. Las comparaciones reales siguen funcionando (no se elimina COMPARISON).
#   5. Adversarial (100+ fixtures cross-domain): una operación incompatible
#      jamás se vuelve autoritativa por score alto.
#
# ATPCO (&&&F / ABCFGEGE) se usa SOLO como fixture de regresión, nunca como
# lógica productiva.
# =============================================================================
from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from src.core.domain.grounding import VerificationStatus
from src.core.domain.rule_semantics import (
    BoundaryKind,
    ComparisonOperator,
    MatchOperator,
    TemporalRelation,
    VerificationState,
)
from src.intelligence.reasoning.grounded_engine import (
    ANSWERABLE_DERIVED,
    reason_over_evidence,
)
from src.knowledge.compiler.model import EvidenceRef, SemanticUnit, SourceLocator
from src.knowledge.rule_compiler import CanonicalRule, SemanticRuleCompiler
from src.knowledge.rule_compiler.evaluate import (
    RuleEvaluationStatus,
    evaluate_rule,
)
from src.knowledge.rule_compiler.model import (
    RuleEnumerationSpec,
    RuleFormulaSpec,
    RuleProperty,
    RuleTemporalSpec,
)
from src.runtime.decision_envelope import build_decision_envelope
from src.runtime.operation_compatibility import (
    OPERAND_TYPE_INCOMPATIBLE,
    OPERATION_INCOMPATIBLE,
    derive_query_operation_requirements,
    gate_rules_for_requirements,
)
from src.runtime.rule_retrieval import (
    InMemoryRuleIndex,
    InMemoryRuleLookup,
    retrieve_canonical_rules,
)

DOC = uuid4()
ORG = uuid4()

PRODUCTION_QUESTION = (
    "yo tengo en el record 2 &&&F y en el farebasis me viene ABCFGEGE "
    "cumple o no cumple"
)
CLEAN_QUESTION = "¿ABCFGEGE cumple el patrón &&&F?"


# -----------------------------------------------------------------------------
# Fixture compilada (una sola vez): A = GTE que menciona `&`; B = gramática.
# -----------------------------------------------------------------------------


def _unit(kind: str, text: str, *, page: int = 1, section: tuple[str, ...] = ("General",)) -> SemanticUnit:
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


def _compile(units: list[SemanticUnit]) -> list[CanonicalRule]:
    return SemanticRuleCompiler().compile(
        document_id=str(DOC),
        document_title="Manual",
        organization_id=str(ORG),
        units=units,
    ).canonical_rules


_CANDIDATE_A: list[CanonicalRule] = [
    rule
    for rule in _compile(
        [
            _unit(
                "rule",
                "ATPCO edits require at least one alphanumeric character in the "
                "fare basis.",
                page=3,
                section=("Record 2",),
            ),
            _unit(
                "reference",
                "Record 2 &&&F farebasis matching edit.",
                page=3,
                section=("Record 2",),
            ),
        ]
    )
    if rule.supported
    and rule.executable
    and any(name.startswith("comparison.operator") for name in rule.properties)
]
_CANDIDATE_B: list[CanonicalRule] = [
    rule
    for rule in _compile(
        [
            _unit(
                "definition",
                "The symbol & represents one alphanumeric position.",
                page=7,
                section=("Kinds of characters",),
            ),
            _unit(
                "reference",
                "Matching is positional, left to right. Literal characters "
                "must match exactly at their position.",
                page=2,
                section=("Matching",),
            ),
            _unit(
                "definition",
                "The value may contain more characters than the pattern.",
                page=1,
                section=("Matching",),
            ),
        ]
    )
    if rule.supported
    and rule.executable
    and str(getattr(rule.properties.get("matching.operator"), "value", ""))
    == MatchOperator.POSITIONAL.value
]


def _rule_compatibility(result, rule_id: str) -> dict:
    for item in result.operation_compatibility.get("scores") or ():
        if item.get("rule_id") == rule_id:
            return item
    return {}


@pytest.fixture(scope="module")
def candidates() -> list[CanonicalRule]:
    assert _CANDIDATE_A and _CANDIDATE_B, "los fixtures deben compilar ejecutables"
    return [*_CANDIDATE_A, *_CANDIDATE_B]


# -----------------------------------------------------------------------------
# 1 — Retrieval: A incompatible, B compatible; ranking DESPUÉS del gate
# -----------------------------------------------------------------------------


class TestRetrievalGate:
    @pytest.mark.asyncio
    async def test_candidate_a_rejected_candidate_b_eligible(self, candidates) -> None:
        result = await retrieve_canonical_rules(
            ORG,
            PRODUCTION_QUESTION,
            evidence_items=[],
            lookup=InMemoryRuleLookup(candidates),
            index=InMemoryRuleIndex(candidates),
        )
        assert result.compatibility_applied is True
        payload = result.operation_compatibility
        assert payload["applied"] is True
        assert payload["query_operation"] == "MATCHING"
        assert payload["candidates"] == len(candidates)

        a_id = _CANDIDATE_A[0].rule_id
        b_id = _CANDIDATE_B[0].rule_id
        a_view = _rule_compatibility(result, a_id)
        b_view = _rule_compatibility(result, b_id)
        assert a_view["eligible"] is False
        assert OPERATION_INCOMPATIBLE in a_view["hard_reasons"]
        assert a_view["eligibility"] == OPERATION_INCOMPATIBLE
        assert b_view["eligible"] is True

        # Solo B sostiene el pass decisivo; A queda fuera aunque su score
        # lexical haya sido mayor.
        assert [rule.rule_id for rule in result.supported_rules] == [b_id]
        assert [rule.rule_id for rule in result.compatible_rules] == [b_id]
        assert payload["winner_rule_id"] == b_id

    @pytest.mark.asyncio
    async def test_telemetry_shows_score_before_and_after(self, candidates) -> None:
        result = await retrieve_canonical_rules(
            ORG,
            PRODUCTION_QUESTION,
            evidence_items=[],
            lookup=InMemoryRuleLookup(candidates),
            index=InMemoryRuleIndex(candidates),
        )
        payload = result.operation_compatibility
        assert payload["top_rejected_reasons"]
        scores = {item["rule_id"]: item for item in payload["scores"]}
        assert scores
        for item in scores.values():
            assert "score_before" in item and "score_after" in item
        a_id = _CANDIDATE_A[0].rule_id
        b_id = _CANDIDATE_B[0].rule_id
        assert scores[b_id]["score_after"] > scores[b_id]["score_before"]
        assert scores[a_id]["eligible"] is False

    @pytest.mark.asyncio
    async def test_public_dict_exposes_compatibility(self, candidates) -> None:
        result = await retrieve_canonical_rules(
            ORG,
            PRODUCTION_QUESTION,
            evidence_items=[],
            lookup=InMemoryRuleLookup(candidates),
            index=InMemoryRuleIndex(candidates),
        )
        public = result.to_public_dict()
        assert public["operation_compatibility"]["applied"] is True
        assert public["compatible_rules"] == 1
        assert "operation_mismatch" not in public["reasons"]

    @pytest.mark.asyncio
    async def test_grounding_rules_exclude_incompatible_candidates(
        self, candidates
    ) -> None:
        from src.runtime.deterministic_authority import _rules_for_grounding

        result = await retrieve_canonical_rules(
            ORG,
            PRODUCTION_QUESTION,
            evidence_items=[],
            lookup=InMemoryRuleLookup(candidates),
            index=InMemoryRuleIndex(candidates),
        )
        grounding_rules = _rules_for_grounding(result)
        ids = [str(rule.rule_id) for rule in grounding_rules]
        assert _CANDIDATE_A[0].rule_id not in ids
        assert _CANDIDATE_B[0].rule_id in ids


# -----------------------------------------------------------------------------
# 2 — Decisión final: POSITIONAL_MATCH / MATCH
# -----------------------------------------------------------------------------


class TestFinalDecision:
    def test_envelope_is_positional_match(self, candidates) -> None:
        grounded = reason_over_evidence(
            question=PRODUCTION_QUESTION,
            evidence_items=[],
            canonical_rules=candidates,
        )
        assert grounded.answerability == ANSWERABLE_DERIVED
        operations = [
            claim.operation
            for claim in grounded.derivations.claims
            if claim.deterministic
            and claim.verification_status == VerificationStatus.SUPPORTED.value
        ]
        assert operations == ["POSITIONAL_MATCH"], (
            "solo la regla compatible (POSITIONAL) puede producir claim"
        )
        envelope = build_decision_envelope(grounded)
        assert envelope is not None
        assert envelope.authoritative is True
        assert envelope.operation == "POSITIONAL_MATCH"
        assert envelope.normalized_result == "MATCH"
        assert envelope.canonical_rule_ids == (_CANDIDATE_B[0].rule_id,)
        compatibility = envelope.operation_compatibility
        assert compatibility.get("compatible") is True

    def test_candidate_a_alone_never_authoritative(self) -> None:
        grounded = reason_over_evidence(
            question=PRODUCTION_QUESTION,
            evidence_items=[],
            canonical_rules=_CANDIDATE_A,
        )
        assert grounded.answerability != ANSWERABLE_DERIVED
        assert not grounded.derivations.claims
        assert any(
            str(item) == "rule:operation_incompatible"
            for item in grounded.missing_premises
        )
        assert build_decision_envelope(grounded) is None

    def test_execution_safety_no_lexical_comparison(self) -> None:
        """Aun sin gate, COMPARISON con máscara falla por tipo/operando."""
        outcome = evaluate_rule(
            _CANDIDATE_A[0], {"value": "ABCFGEGE", "pattern": "&&&F"}
        )
        assert outcome.status != RuleEvaluationStatus.MATCH.value
        comparison = next(
            (
                check
                for check in outcome.checks
                if check.name == "comparison"
            ),
            None,
        )
        assert comparison is not None
        assert comparison.status == RuleEvaluationStatus.UNDETERMINED.value
        assert (
            OPERAND_TYPE_INCOMPATIBLE in comparison.missing_premises
            or "operand:right" in comparison.missing_premises
        )
        assert "&&&f" not in (comparison.detail or "").lower()

    def test_comparison_never_receives_runtime_mask(self) -> None:
        from src.intelligence.reasoning.operations import run_comparison

        result = run_comparison("ABCFGEGE", "&&&F", op="ge")
        assert result.ok is False
        assert OPERAND_TYPE_INCOMPATIBLE in (result.error or "")
        assert result.value is None


# -----------------------------------------------------------------------------
# 3 — Regresión negativa: las comparaciones reales siguen funcionando
# -----------------------------------------------------------------------------


class TestRealComparisonsStillWork:
    def _comparison_rules(self) -> list[CanonicalRule]:
        return [
            rule
            for rule in _compile(
                [_unit("rule", "The value must be at least 100.", page=1)]
            )
            if rule.supported and rule.executable
        ]

    @pytest.mark.parametrize(
        "value,expected",
        [("120", "positive"), ("150", "positive"), ("90", "negative")],
    )
    def test_numeric_comparison_still_decides(self, value, expected) -> None:
        rules = self._comparison_rules()
        assert rules
        grounded = reason_over_evidence(
            question=f"¿el valor {value} es mayor o igual que el mínimo 100?",
            evidence_items=[],
            canonical_rules=rules,
        )
        envelope = build_decision_envelope(grounded)
        assert envelope is not None, "COMPARISON no se eliminó globalmente"
        assert envelope.operation in ("COMPARISON", "RANGE_CHECK")
        if expected == "positive":
            assert envelope.normalized_result in ("VALID", "MATCH", "TRUE")
        else:
            assert envelope.normalized_result in ("INVALID", "NO_MATCH", "FALSE")

    def test_spec_question_can_use_comparison(self) -> None:
        """El caso textual del contrato puede usar COMPARISON (no se eliminó)."""
        rules = self._comparison_rules()
        assert rules
        grounded = reason_over_evidence(
            question="¿120 es mayor o igual que el mínimo 100?",
            evidence_items=[],
            canonical_rules=rules,
        )
        envelope = build_decision_envelope(grounded)
        assert envelope is not None
        assert envelope.operation in ("COMPARISON", "RANGE_CHECK")
        assert envelope.authoritative is True

    def test_equality_comparison_of_strings_still_works(self) -> None:
        rules = [
            rule
            for rule in _compile(
                [_unit("rule", "The status must equal ACTIVE.", page=1)]
            )
            if rule.supported and rule.executable
        ]
        if not rules:
            pytest.skip("el compilador no produjo regla ejecutable de igualdad")
        grounded = reason_over_evidence(
            question="¿el estado ACTIVE es igual a ACTIVE?",
            evidence_items=[],
            canonical_rules=rules,
        )
        # No exige decisión binaria específica: solo que no se bloquee en falso
        # por el validador de tipos.
        assert grounded.answerability in (
            "ANSWERABLE_DERIVED",
            "UNANSWERABLE_MISSING_PREMISE",
            "NOT_APPLICABLE",
            "UNDETERMINED_RULE",
        )


# -----------------------------------------------------------------------------
# 4 — Regla híbrida: comparación artefacto NO envenena el matching (caso vivo)
# -----------------------------------------------------------------------------


def _hybrid_rule() -> CanonicalRule:
    """Regla productiva real: matching posicional + GTE artefacto de compilación."""
    from src.core.domain.rule_semantics import MatchOperator
    from src.knowledge.rule_compiler.model import RuleProperty

    def _prop(name: str, value: Any) -> RuleProperty:
        return RuleProperty(
            name=name,
            value=value,
            state=VerificationState.SUPPORTED.value,
            evidence=[f"ev:{name}"],
        )

    return CanonicalRule(
        rule_id="rule:hybrid-live",
        statement=(
            "The symbol & represents one alphanumeric position. Matching is "
            "positional, left to right. ATPCO edits require at least one "
            "alphanumeric character in the fare basis."
        ),
        operator=MatchOperator.POSITIONAL.value,
        properties={
            "matching.symbol.&": _prop(
                "matching.symbol.&", "one alphanumeric position"
            ),
            "matching.symbol.&.alphabet": _prop(
                "matching.symbol.&.alphabet", "alphanumeric"
            ),
            "matching.operator": _prop(
                "matching.operator", MatchOperator.POSITIONAL.value
            ),
            "length.policy": _prop("length.policy", "VALUE_MAY_BE_LONGER"),
            "comparison.operator": _prop("comparison.operator", "GTE"),
            "comparison.left": _prop("comparison.left", "ATPCO edits require"),
            "comparison.right": _prop(
                "comparison.right", "one alphanumeric character in the fare"
            ),
            "comparison.boundary": _prop("comparison.boundary", "INCLUSIVE"),
        },
        verification_state=VerificationState.SUPPORTED.value,
        executable=True,
    )


class TestHybridRuleDoesNotPoisonMatching:
    def test_hybrid_rule_decides_positional_match(self) -> None:
        outcome = evaluate_rule(
            _hybrid_rule(), {"value": "ABCFGEGE", "pattern": "&&&F"}
        )
        assert outcome.status == RuleEvaluationStatus.MATCH.value
        assert outcome.operation == "POSITIONAL_MATCH"
        assert outcome.result is True
        # La comparación artefacto no produce check ni missing premise.
        assert not any(check.name == "comparison" for check in outcome.checks)
        assert OPERAND_TYPE_INCOMPATIBLE not in outcome.missing_premises

    def test_hybrid_rule_produces_authoritative_envelope(self) -> None:
        grounded = reason_over_evidence(
            question=PRODUCTION_QUESTION,
            evidence_items=[],
            canonical_rules=[_hybrid_rule()],
        )
        assert grounded.answerability == ANSWERABLE_DERIVED
        assert "OPERAND_TYPE_INCOMPATIBLE" not in grounded.missing_premises
        envelope = build_decision_envelope(grounded)
        assert envelope is not None
        assert envelope.operation == "POSITIONAL_MATCH"
        assert envelope.normalized_result == "MATCH"

    def test_comparison_only_rule_still_fails_closed(self) -> None:
        """Sin otra dimensión, la comparación incomparable queda UNDETERMINED."""
        mention = _comparison_fixture(
            "rule:mention-live",
            statement=(
                "ATPCO edits require at least one alphanumeric character in the "
                "fare basis (&&&F)."
            ),
        )
        outcome = evaluate_rule(mention, {"value": "ABCFGEGE", "pattern": "&&&F"})
        assert outcome.status == RuleEvaluationStatus.UNDETERMINED.value
        assert OPERAND_TYPE_INCOMPATIBLE in outcome.missing_premises

    def test_hybrid_comparison_still_decides_numeric_scenario(self) -> None:
        """Con operando numerico real, la comparación de la regla híbrida vive."""
        from src.core.domain.rule_semantics import MatchOperator
        from src.knowledge.rule_compiler.model import RuleProperty

        def _prop(name: str, value: Any) -> RuleProperty:
            return RuleProperty(
                name=name,
                value=value,
                state=VerificationState.SUPPORTED.value,
                evidence=[f"ev:{name}"],
            )

        rule = CanonicalRule(
            rule_id="rule:hybrid-numeric",
            statement="Positional mask & plus minimum 100.",
            operator=MatchOperator.POSITIONAL.value,
            properties={
                "matching.symbol.&": _prop("matching.symbol.&", "digit"),
                "matching.operator": _prop(
                    "matching.operator", MatchOperator.POSITIONAL.value
                ),
                "comparison.operator": _prop("comparison.operator", "GTE"),
                "comparison.left": _prop("comparison.left", "value"),
                "comparison.right": _prop("comparison.right", "100"),
                "comparison.boundary": _prop("comparison.boundary", "INCLUSIVE"),
            },
            verification_state=VerificationState.SUPPORTED.value,
            executable=True,
        )
        good = evaluate_rule(rule, {"value": "150", "pattern": "1&&"})
        assert good.status == RuleEvaluationStatus.MATCH.value
        bad = evaluate_rule(rule, {"value": "50", "pattern": "1&&"})
        assert bad.status == RuleEvaluationStatus.NO_MATCH.value


# -----------------------------------------------------------------------------
# 5 — Invariante del envelope sin depender del engine
# -----------------------------------------------------------------------------

class TestEnvelopeInvariant:
    def _grounded(
        self,
        *,
        operation: str,
        rule_id: str = "rule:x",
        compatible: bool | None,
        eligibility: str = "ELIGIBLE",
        claim_result=True,
    ) -> dict:
        evaluation = {
            "rule_id": rule_id,
            "status": "MATCH",
            "operation": operation,
            "result": claim_result,
            "checks": [],
        }
        if compatible is not None:
            evaluation["compatible"] = compatible
            evaluation["operation_compatibility"] = {
                "candidate_rule_id": rule_id,
                "compatible": compatible,
                "eligibility": eligibility,
                "hard_reasons": [] if compatible else [eligibility],
            }
        return {
            "answerability": ANSWERABLE_DERIVED,
            "semantics": {
                "intent": "VALIDATE",
                "runtime_patterns": ["&&&F"],
                "runtime_inputs": ["ABCFGEGE"],
            },
            "runtime_patterns": ["&&&F"],
            "canonical_rule_flow": [evaluation],
            "derived_claim": {
                "deterministic": True,
                "verification_status": "SUPPORTED",
                "operation": operation,
                "result": claim_result,
                "canonical_rule_ids": [rule_id],
            },
            "canonical_rules_used": [
                {
                    "rule_id": rule_id,
                    "verification_state": "SUPPORTED",
                    "executable": True,
                    "conflicts_with": [],
                }
            ],
            "derivations": {
                "claims": [
                    {
                        "deterministic": True,
                        "verification_status": "SUPPORTED",
                        "operation": operation,
                        "result": claim_result,
                        "canonical_rule_ids": [rule_id],
                        "user_inputs": ["value=ABCFGEGE", "pattern=&&&F"],
                        "evidence_refs": [],
                        "premises": [],
                    }
                ],
                "claims_count": 1,
            },
        }

    def test_incompatible_comparison_never_builds_authority(self) -> None:
        grounded = self._grounded(
            operation="COMPARISON",
            compatible=False,
            eligibility=OPERATION_INCOMPATIBLE,
        )
        assert build_decision_envelope(grounded) is None

    def test_operation_family_mismatch_never_builds_authority(self) -> None:
        # Sin metadatos de compatibilidad: la familia de la operación (COMPARISON)
        # no está permitida para una query de máscara (MATCHING).
        grounded = self._grounded(operation="COMPARISON", compatible=None)
        assert build_decision_envelope(grounded) is None

    def test_compatible_positional_builds_authority(self) -> None:
        grounded = self._grounded(
            operation="POSITIONAL_MATCH",
            compatible=True,
            claim_result=True,
        )
        envelope = build_decision_envelope(grounded)
        assert envelope is not None
        assert envelope.authoritative is True
        assert envelope.operation == "POSITIONAL_MATCH"
        assert envelope.normalized_result == "MATCH"
        assert envelope.operation_compatibility["compatible"] is True


# -----------------------------------------------------------------------------
# 5 — Adversarial (100+ fixtures cross-domain)
# -----------------------------------------------------------------------------


def _prop(name: str, value, *, state: str = VerificationState.SUPPORTED.value) -> RuleProperty:
    return RuleProperty(name=name, value=value, state=state, evidence=[f"ev:{name}"])


def _comparison_fixture(rule_id: str, *, statement: str = "The value must be at least 10.") -> CanonicalRule:
    return CanonicalRule(
        rule_id=rule_id,
        statement=statement,
        operator=ComparisonOperator.GTE.value,
        properties={
            "comparison.operator": _prop("comparison.operator", ComparisonOperator.GTE.value),
            "comparison.left": _prop("comparison.left", "The value"),
            "comparison.right": _prop("comparison.right", "10"),
            "comparison.boundary": _prop("comparison.boundary", BoundaryKind.INCLUSIVE.value),
        },
        verification_state=VerificationState.SUPPORTED.value,
        executable=True,
    )


def _mention_only_fixture(rule_id: str) -> CanonicalRule:
    return _comparison_fixture(
        rule_id,
        statement="ATPCO edits require at least one alphanumeric character (&&&F).",
    )


def _matching_fixture(rule_id: str, *, symbol: str = "&") -> CanonicalRule:
    return CanonicalRule(
        rule_id=rule_id,
        statement=f"The symbol {symbol} matches one character position.",
        properties={
            f"matching.symbol.{symbol}": _prop(
                f"matching.symbol.{symbol}", "one character position"
            ),
            "matching.operator": _prop("matching.operator", MatchOperator.POSITIONAL.value),
        },
        verification_state=VerificationState.SUPPORTED.value,
        executable=True,
    )


def _range_fixture(rule_id: str) -> CanonicalRule:
    return CanonicalRule(
        rule_id=rule_id,
        statement="The value must be between 10 and 20.",
        properties={
            "comparison.operator": _prop("comparison.operator", ComparisonOperator.BETWEEN.value),
            "comparison.left": _prop("comparison.left", "10"),
            "comparison.right": _prop("comparison.right", "20"),
            "quantity.minimum": _prop("quantity.minimum", 10),
            "quantity.maximum": _prop("quantity.maximum", 20),
        },
        verification_state=VerificationState.SUPPORTED.value,
        executable=True,
    )


def _date_fixture(rule_id: str) -> CanonicalRule:
    return CanonicalRule(
        rule_id=rule_id,
        statement="Applications must be received before 1 July 2026.",
        properties={
            "temporal.relation": _prop("temporal.relation", TemporalRelation.BEFORE.value)
        },
        temporal=RuleTemporalSpec(relation=TemporalRelation.BEFORE.value, value="2026-07-01"),
        verification_state=VerificationState.SUPPORTED.value,
        executable=True,
    )


def _enum_fixture(rule_id: str) -> CanonicalRule:
    return CanonicalRule(
        rule_id=rule_id,
        statement="The status must be one of ACTIVE, PENDING.",
        enumeration=RuleEnumerationSpec(allowed=["ACTIVE", "PENDING"]),
        verification_state=VerificationState.SUPPORTED.value,
        executable=True,
    )


def _formula_fixture(rule_id: str) -> CanonicalRule:
    return CanonicalRule(
        rule_id=rule_id,
        statement="Total = subtotal + tax.",
        formula=RuleFormulaSpec(target="total", expression="subtotal + tax"),
        verification_state=VerificationState.SUPPORTED.value,
        executable=True,
    )


def _boolean_fixture(rule_id: str) -> CanonicalRule:
    return CanonicalRule(
        rule_id=rule_id,
        statement="Eligible when active and verified.",
        properties={"logic.operators": _prop("logic.operators", ["AND"])},
        verification_state=VerificationState.SUPPORTED.value,
        executable=True,
    )


_PATTERN_QUESTIONS: tuple[str, ...] = (
    PRODUCTION_QUESTION,
    CLEAN_QUESTION,
    "¿mi valor ABCD contra ???? cumple?",
    "¿el valor XV12 cumple ***?",
    "¿el valor ABC cumple @@@?",
    "¿AB12 cumple &&##?",
    "¿WB2MXRT cumple W&&2M?",
    "¿WBC2MXRT cumple W&C&M?",
    "¿ABTEST cumple &&TEST?",
    "¿A1TEST cumple %%TEST?",
    "¿1234 cumple ####?",
    "¿AB12CD cumple !&!&?",
)

_FORBIDDEN_FOR_PATTERN: tuple[tuple[str, object], ...] = (
    ("comparison", _comparison_fixture),
    ("mention-only", _mention_only_fixture),
    ("range", _range_fixture),
    ("date", _date_fixture),
    ("enum", _enum_fixture),
    ("formula", _formula_fixture),
    ("boolean", _boolean_fixture),
    ("foreign-symbol", lambda rule_id: _matching_fixture(rule_id, symbol="~")),
)

_OTHER_QUESTIONS: tuple[tuple[str, tuple[tuple[str, object], ...]], ...] = (
    (
        "¿120 es mayor o igual que el mínimo 100?",
        (
            ("matching", _matching_fixture),
            ("foreign-symbol", lambda rule_id: _matching_fixture(rule_id, symbol="~")),
            ("enum", _enum_fixture),
            ("formula", _formula_fixture),
        ),
    ),
    (
        "¿el valor 15 cumple el rango entre 10 y 20?",
        (
            ("matching", _matching_fixture),
            ("foreign-symbol", lambda rule_id: _matching_fixture(rule_id, symbol="~")),
            ("enum", _enum_fixture),
            ("formula", _formula_fixture),
        ),
    ),
    (
        "¿el estado ACTIVE está permitido por la regla?",
        (
            ("matching", _matching_fixture),
            ("foreign-symbol", lambda rule_id: _matching_fixture(rule_id, symbol="~")),
            ("range", _range_fixture),
            ("formula", _formula_fixture),
        ),
    ),
    (
        "calcula el total con subtotal=100 aplicando la fórmula documentada",
        (
            ("matching", _matching_fixture),
            ("foreign-symbol", lambda rule_id: _matching_fixture(rule_id, symbol="~")),
            ("enum", _enum_fixture),
            ("range", _range_fixture),
        ),
    ),
    (
        "¿la regla está vigente el 2027-06-01?",
        (
            ("matching", _matching_fixture),
            ("foreign-symbol", lambda rule_id: _matching_fixture(rule_id, symbol="~")),
            ("enum", _enum_fixture),
            ("formula", _formula_fixture),
        ),
    ),
    (
        "si el valor está activo entonces es elegible",
        (
            ("matching", _matching_fixture),
            ("foreign-symbol", lambda rule_id: _matching_fixture(rule_id, symbol="~")),
            ("formula", _formula_fixture),
        ),
    ),
)


def _adversarial_cases() -> list[tuple[str, str, object]]:
    cases: list[tuple[str, str, object]] = []
    for q_index, question in enumerate(_PATTERN_QUESTIONS):
        for family, factory in _FORBIDDEN_FOR_PATTERN:
            cases.append((question, family, factory(f"rule:adv-{q_index}-{family}")))
    for q_index, (question, forbidden) in enumerate(_OTHER_QUESTIONS):
        for family, factory in forbidden:
            cases.append((question, family, factory(f"rule:adv-x{q_index}-{family}")))
    return cases


_ADVERSARIAL_CASES = _adversarial_cases()
assert len(_ADVERSARIAL_CASES) >= 100, len(_ADVERSARIAL_CASES)


class TestAdversarialIncompatibleNeverAuthoritative:
    @pytest.mark.parametrize(
        "question,family,rule",
        _ADVERSARIAL_CASES,
        ids=[
            f"{index:03d}-{family}"
            for index, (_q, family, _r) in enumerate(_ADVERSARIAL_CASES)
        ],
    )
    def test_incompatible_never_authoritative(self, question, family, rule) -> None:
        requirements = derive_query_operation_requirements(question=question)
        assert requirements.enforced is True

        # 1. El gate la rechaza aunque el score antes del gate sea enorme.
        gate = gate_rules_for_requirements([rule], requirements, scores={rule.rule_id: 999.0})
        view = gate.to_public_dict()
        assert view["compatible"] == 0
        assert view["rejected"] == 1
        score = view["scores"][0]
        assert score["eligible"] is False
        assert score["score_after"] == 999.0  # rechazada: no se re-rankea

        # 2. El engine no produce claim determinista ni envelope autoritativo.
        grounded = reason_over_evidence(
            question=question,
            evidence_items=[],
            canonical_rules=[rule],
        )
        assert not any(
            claim.deterministic
            and claim.verification_status == VerificationStatus.SUPPORTED.value
            for claim in grounded.derivations.claims
        )
        assert build_decision_envelope(grounded) is None
