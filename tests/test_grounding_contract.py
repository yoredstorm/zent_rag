# =============================================================================
# Grounding contract — GROUNDING != LITERAL COPY
# =============================================================================
# Cada categoría de afirmación exige un respaldo distinto; los tres modos
# (strict_source / grounded_reasoning / hybrid_knowledge) cambian lo permitido.
# La verificación de un claim derivado pregunta «¿se sigue de las premisas?»,
# nunca «¿la fuente contiene la conclusión?».
# =============================================================================
from __future__ import annotations

from src.core.domain.grounding import (
    ClaimOrigin,
    DerivedClaim,
    GroundedInference,
    GroundingCategory,
    GroundingContract,
    GroundingMode,
    Premise,
    VerificationStatus,
)
from src.intelligence.reasoning.derivation import (
    DerivationGraph,
    InferenceVerifier,
    verify_derived_claim,
    verify_grounded_inference,
)


class TestCategories:
    def test_source_fact_and_rule_require_evidence(self) -> None:
        contract = GroundingContract()
        for category in (GroundingCategory.SOURCE_FACT, GroundingCategory.SOURCE_RULE):
            requirement = contract.requirement_for(category.value)
            assert requirement.source_evidence_required is True
            assert requirement.allowed is True

    def test_user_input_does_not_require_evidence(self) -> None:
        contract = GroundingContract()
        requirement = contract.requirement_for(GroundingCategory.USER_INPUT.value)
        assert requirement.source_evidence_required is False
        assert requirement.user_data_allowed is True

    def test_runtime_pattern_requires_semantics_not_literal(self) -> None:
        contract = GroundingContract()
        requirement = contract.requirement_for(GroundingCategory.RUNTIME_PATTERN.value)
        assert requirement.source_evidence_required is False
        assert requirement.semantics_required is True

    def test_derived_claim_requires_premises(self) -> None:
        contract = GroundingContract()
        requirement = contract.requirement_for(GroundingCategory.DERIVED_CLAIM.value)
        assert requirement.source_evidence_required is True
        assert requirement.operation_allowed is True

    def test_unsupported_claim_never_allowed(self) -> None:
        contract = GroundingContract()
        assert contract.allows_category(GroundingCategory.UNSUPPORTED_CLAIM.value) is False


class TestModes:
    def test_strict_source_restricts_general_operations(self) -> None:
        contract = GroundingContract(mode=GroundingMode.STRICT_SOURCE.value)
        assert contract.requirement_for(GroundingCategory.GENERAL_OPERATION.value).allowed is False
        assert contract.requirement_for(GroundingCategory.MODEL_GENERAL_KNOWLEDGE.value).allowed is False

    def test_grounded_reasoning_allows_operations_blocks_model_knowledge(self) -> None:
        contract = GroundingContract(mode=GroundingMode.GROUNDED_REASONING.value)
        assert contract.requirement_for(GroundingCategory.GENERAL_OPERATION.value).allowed is True
        assert contract.requirement_for(GroundingCategory.MODEL_GENERAL_KNOWLEDGE.value).allowed is False

    def test_hybrid_allows_model_knowledge_differentiated(self) -> None:
        contract = GroundingContract(mode=GroundingMode.HYBRID_KNOWLEDGE.value)
        assert contract.requirement_for(GroundingCategory.MODEL_GENERAL_KNOWLEDGE.value).allowed is True

    def test_mode_parse_aliases(self) -> None:
        assert GroundingMode.parse("strict_source") == GroundingMode.STRICT_SOURCE
        assert GroundingMode.parse("active") == GroundingMode.GROUNDED_REASONING
        assert GroundingMode.parse("") == GroundingMode.GROUNDED_REASONING
        assert GroundingMode.parse("hybrid") == GroundingMode.HYBRID_KNOWLEDGE


class TestDerivedClaimVerification:
    def _premise(self, statement: str, refs: tuple[str, ...] = ("E1",)) -> Premise:
        return Premise(statement=statement, origin=ClaimOrigin.SOURCE.value, evidence_refs=refs)

    def test_supported_when_premises_grounded_and_operation_valid(self) -> None:
        claim = DerivedClaim(
            statement="ASDFGRE matches &&&F",
            premises=(
                self._premise("& represents one alphanumeric position"),
                self._premise("matching is positional"),
            ),
            user_inputs=("ASDFGRE", "&&&F"),
            operation="POSITIONAL_MATCH",
            result="MATCH",
            evidence_refs=("E1",),
            confidence=0.9,
        )
        verified = verify_derived_claim(claim, GroundingContract())
        assert verified.verification_status == VerificationStatus.SUPPORTED.value
        assert verified.supported is True

    def test_insufficient_when_source_premise_ungrounded(self) -> None:
        claim = DerivedClaim(
            statement="result",
            premises=(
                Premise(statement="proprietary symbol meaning", origin=ClaimOrigin.SOURCE.value),
            ),
            user_inputs=("X",),
            operation="POSITIONAL_MATCH",
            result="MATCH",
        )
        verified = verify_derived_claim(claim, GroundingContract())
        assert verified.verification_status == VerificationStatus.INSUFFICIENT_PREMISES.value

    def test_insufficient_when_missing_premises_declared(self) -> None:
        claim = DerivedClaim(
            statement="result",
            premises=(self._premise("pattern supported"),),
            user_inputs=("ASDFGRE",),
            operation="POSITIONAL_MATCH",
            missing_premises=("definition:symbol:&",),
        )
        verified = verify_derived_claim(claim, GroundingContract())
        assert verified.verification_status == VerificationStatus.INSUFFICIENT_PREMISES.value

    def test_conflicting_premises(self) -> None:
        claim = DerivedClaim(statement="x", premises=(self._premise("a"),))
        verified = verify_derived_claim(claim, GroundingContract(), conflicts=("a vs b",))
        assert verified.verification_status == VerificationStatus.CONFLICTING.value

    def test_strict_mode_blocks_operation(self) -> None:
        claim = DerivedClaim(
            statement="x",
            premises=(self._premise("a"),),
            operation="ARITHMETIC",
            result=2,
        )
        verified = verify_derived_claim(
            claim, GroundingContract(mode=GroundingMode.STRICT_SOURCE.value)
        )
        assert verified.verification_status == VerificationStatus.UNSUPPORTED.value

    def test_public_dict_has_no_chain_of_thought(self) -> None:
        claim = DerivedClaim(statement="x", premises=(self._premise("a"),))
        payload = claim.to_public_dict()
        assert "premises" in payload
        assert "operation" in payload
        assert "result" in payload
        assert "verification_status" in payload
        assert "reasoning" not in payload
        assert "chain_of_thought" not in payload


class TestGroundedInference:
    def test_supported_from_grounded_premises(self) -> None:
        inference = GroundedInference(
            candidate="the fare basis is valid for the route",
            premises=(
                Premise(
                    statement="FCLAS defines the fare class",
                    origin=ClaimOrigin.SOURCE.value,
                    evidence_refs=("E1",),
                ),
            ),
            user_inputs=("FCLAS=B",),
            supporting_evidence=("E1",),
        )
        verified = verify_grounded_inference(inference, GroundingContract())
        assert verified.verification_status == VerificationStatus.SUPPORTED.value

    def test_verifier_interface(self) -> None:
        verifier = InferenceVerifier(GroundingContract())
        claim = DerivedClaim(
            statement="x",
            premises=(
                Premise(
                    statement="a",
                    origin=ClaimOrigin.SOURCE.value,
                    evidence_refs=("E1",),
                ),
            ),
            user_inputs=("u",),
        )
        assert verifier.verify_claim(claim).verification_status == VerificationStatus.SUPPORTED.value


class TestDerivationGraph:
    def test_graph_public_shape(self) -> None:
        graph = DerivationGraph(
            claims=(
                DerivedClaim(
                    statement="120",
                    operation="ARITHMETIC",
                    result=120,
                    premises=(
                        Premise(
                            statement="fee = base + surcharge",
                            origin=ClaimOrigin.SOURCE.value,
                            evidence_refs=("E1",),
                        ),
                    ),
                    user_inputs=("base=100", "surcharge=20"),
                    verification_status=VerificationStatus.SUPPORTED.value,
                ),
            ),
            operations_used=("ARITHMETIC",),
        )
        public = graph.to_public_dict()
        assert public["derived_results"] == 1
        assert public["claims"][0]["origin"] == ClaimOrigin.DERIVED.value
        assert public["claims"][0]["result"] == 120
        assert graph.result_for("ARITHMETIC") == 120
