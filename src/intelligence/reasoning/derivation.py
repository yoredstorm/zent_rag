# =============================================================================
# Derivation — conclusiones derivadas con premisas, operación y verificación
# =============================================================================
# El InferenceVerifier viejo responde «¿la fuente contiene la conclusión?».
# Éste responde la pregunta correcta:
#
#   ¿La conclusión C se sigue de premisas grounded P y datos aceptados U?
#
# Guarda premisas + operación + resultado + verificación. NUNCA cadena de
# pensamiento.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from src.core.domain.grounding import (
    ClaimOrigin,
    DerivedClaim,
    GroundedInference,
    GroundingCategory,
    GroundingContract,
    Premise,
    VerificationStatus,
)
from src.intelligence.reasoning.operations import OperationResult

DERIVATION_VERSION = "derivation-1"


def verify_derived_claim(
    claim: DerivedClaim,
    contract: GroundingContract,
    *,
    conflicts: Sequence[str] = (),
) -> DerivedClaim:
    """Marca el claim SUPPORTED sólo si premisas, operación y resultado cierran.

    No busca la conclusión en la fuente: verifica que las premisas del dominio
    estén respaldadas y que la operación sea válida en el modo de grounding.
    """
    if conflicts:
        return _with_status(
            claim,
            VerificationStatus.CONFLICTING.value,
            note="premises conflict; cannot conclude",
        )
    if claim.missing_premises:
        return _with_status(
            claim,
            VerificationStatus.INSUFFICIENT_PREMISES.value,
            note="missing domain premises: " + ", ".join(claim.missing_premises[:4]),
        )
    if claim.operation and not contract.requirement_for(
        GroundingCategory.GENERAL_OPERATION.value
    ).operation_allowed:
        return _with_status(
            claim,
            VerificationStatus.UNSUPPORTED.value,
            note="operation not allowed in grounding mode " + contract.grounding_mode.value,
        )
    source_premises = [
        premise for premise in claim.premises if premise.origin == ClaimOrigin.SOURCE.value
    ]
    ungrounded = [premise for premise in source_premises if not premise.grounded]
    if ungrounded:
        return _with_status(
            claim,
            VerificationStatus.INSUFFICIENT_PREMISES.value,
            note="ungrounded source premises",
        )
    if not claim.premises and not claim.user_inputs:
        return _with_status(
            claim,
            VerificationStatus.UNVERIFIABLE.value,
            note="no premises and no user inputs",
        )
    return _with_status(
        claim,
        VerificationStatus.SUPPORTED.value,
        note="premises grounded and derivation valid",
    )


def _with_status(claim: DerivedClaim, status: str, *, note: str) -> DerivedClaim:
    return DerivedClaim(
        statement=claim.statement,
        claim_type=claim.claim_type,
        premises=claim.premises,
        user_inputs=claim.user_inputs,
        operation=claim.operation,
        result=claim.result,
        evidence_refs=claim.evidence_refs,
        confidence=claim.confidence,
        verification_status=status,
        origin=claim.origin,
        missing_premises=claim.missing_premises,
        verification_note=note,
        canonical_rule_ids=claim.canonical_rule_ids,
        deterministic=claim.deterministic,
        unresolved_requirements=claim.unresolved_requirements,
        conflicts=claim.conflicts,
    )


def verify_grounded_inference(
    inference: GroundedInference,
    contract: GroundingContract,
    *,
    conflicts: Sequence[str] = (),
) -> GroundedInference:
    """Verifica una inferencia no ejecutable contra premisas grounded."""
    if conflicts:
        return GroundedInference(
            candidate=inference.candidate,
            premises=inference.premises,
            user_inputs=inference.user_inputs,
            supporting_evidence=inference.supporting_evidence,
            verification_status=VerificationStatus.CONFLICTING.value,
            verification_note="premises conflict",
        )
    source_premises = [
        premise for premise in inference.premises if premise.origin == ClaimOrigin.SOURCE.value
    ]
    if any(not premise.grounded for premise in source_premises):
        return GroundedInference(
            candidate=inference.candidate,
            premises=inference.premises,
            user_inputs=inference.user_inputs,
            supporting_evidence=inference.supporting_evidence,
            verification_status=VerificationStatus.INSUFFICIENT_PREMISES.value,
            verification_note="ungrounded source premises",
        )
    if not inference.premises and not inference.supporting_evidence:
        return GroundedInference(
            candidate=inference.candidate,
            premises=inference.premises,
            user_inputs=inference.user_inputs,
            supporting_evidence=inference.supporting_evidence,
            verification_status=VerificationStatus.UNVERIFIABLE.value,
            verification_note="no supporting premises",
        )
    return GroundedInference(
        candidate=inference.candidate,
        premises=inference.premises,
        user_inputs=inference.user_inputs,
        supporting_evidence=inference.supporting_evidence,
        verification_status=VerificationStatus.SUPPORTED.value,
        verification_note="inference follows from grounded premises",
    )


def claim_from_operation(
    *,
    statement: str,
    operation: OperationResult,
    premises: Iterable[Premise] = (),
    user_inputs: Iterable[str] = (),
    evidence_refs: Iterable[str] = (),
    contract: GroundingContract,
    claim_type: str = GroundingCategory.DERIVED_CLAIM.value,
    confidence: float = 0.85,
    missing_premises: Iterable[str] = (),
    conflicts: Iterable[str] = (),
    canonical_rule_ids: Iterable[str] = (),
    deterministic: bool = False,
    unresolved_requirements: Iterable[str] = (),
) -> DerivedClaim:
    """Compone un DerivedClaim a partir de una operación determinista."""
    claim = DerivedClaim(
        statement=statement,
        claim_type=claim_type,
        premises=tuple(premises),
        user_inputs=tuple(user_inputs),
        operation=str(operation.operation or ""),
        result=operation.value,
        evidence_refs=tuple(dict.fromkeys(str(ref) for ref in evidence_refs if ref)),
        confidence=float(confidence),
        missing_premises=tuple(dict.fromkeys(str(item) for item in missing_premises if item)),
        canonical_rule_ids=tuple(
            dict.fromkeys(str(item) for item in canonical_rule_ids if item)
        ),
        deterministic=bool(deterministic),
        unresolved_requirements=tuple(
            dict.fromkeys(str(item) for item in unresolved_requirements if item)
        ),
        conflicts=tuple(dict.fromkeys(str(item) for item in conflicts if item)),
    )
    return verify_derived_claim(claim, contract, conflicts=tuple(conflicts))


@dataclass(kw_only=True)
class DerivationGraph:
    """Grafo de derivaciones del run: claims + premisas faltantes + conflictos."""

    claims: tuple[DerivedClaim, ...] = ()
    inferences: tuple[GroundedInference, ...] = ()
    missing_premises: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    operations_used: tuple[str, ...] = ()
    version: str = DERIVATION_VERSION

    @property
    def derived_results(self) -> tuple[DerivedClaim, ...]:
        return tuple(claim for claim in self.claims if claim.supported)

    @property
    def has_supported_result(self) -> bool:
        return bool(self.derived_results)

    def result_for(self, operation: str) -> Any:
        for claim in self.claims:
            if claim.operation == operation and claim.supported:
                return claim.result
        return None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "claims": [claim.to_public_dict() for claim in self.claims[:8]],
            "inferences": [item.to_public_dict() for item in self.inferences[:4]],
            "missing_premises": list(self.missing_premises[:12]),
            "conflicts": list(self.conflicts[:8]),
            "operations_used": list(self.operations_used[:12]),
            "derived_results": len(self.derived_results),
        }


class InferenceVerifier:
    """Verificador conceptual reutilizable (premisas + inputs → conclusión)."""

    def __init__(self, contract: GroundingContract | None = None) -> None:
        self._contract = contract or GroundingContract()

    @property
    def contract(self) -> GroundingContract:
        return self._contract

    def verify_claim(
        self, claim: DerivedClaim, *, conflicts: Sequence[str] = ()
    ) -> DerivedClaim:
        return verify_derived_claim(claim, self._contract, conflicts=conflicts)

    def verify_inference(
        self, inference: GroundedInference, *, conflicts: Sequence[str] = ()
    ) -> GroundedInference:
        return verify_grounded_inference(inference, self._contract, conflicts=conflicts)


__all__ = [
    "DERIVATION_VERSION",
    "DerivationGraph",
    "InferenceVerifier",
    "claim_from_operation",
    "verify_derived_claim",
    "verify_grounded_inference",
]
