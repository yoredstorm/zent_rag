# =============================================================================
# Domain — Grounding contract (GROUNDING != LITERAL COPY)
# =============================================================================
# Categorías formales de afirmación y qué exige cada una:
#
#   SOURCE_FACT / SOURCE_RULE      -> evidencia documental obligatoria
#   USER_INPUT / USER_EXAMPLE      -> dato del escenario; NO se busca en fuentes
#   RUNTIME_PATTERN                -> la instancia no exige match literal; su
#                                     semántica (gramática documentada) sí
#   RUNTIME_PARAMETER              -> parámetro aportado por el usuario
#   GENERAL_OPERATION              -> matemática/lógica/transformación permitida
#   DERIVED_CLAIM                  -> premisas respaldadas + derivación válida
#   MODEL_GENERAL_KNOWLEDGE        -> gobernado por el modo de grounding
#   UNSUPPORTED_CLAIM              -> nunca se afirma
#
# Modos:
#   STRICT_SOURCE      compliance/legal/auditoría
#   GROUNDED_REASONING recomendado para ZENT
#   HYBRID_KNOWLEDGE   fuente + usuario + operaciones + conocimiento general
#                      (diferenciado internamente, nunca mezclado en silencio)
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

GROUNDING_VERSION = "grounding-contract-1"


class GroundingCategory(StrEnum):
    SOURCE_FACT = "SOURCE_FACT"
    SOURCE_RULE = "SOURCE_RULE"
    USER_INPUT = "USER_INPUT"
    USER_EXAMPLE = "USER_EXAMPLE"
    RUNTIME_PATTERN = "RUNTIME_PATTERN"
    RUNTIME_PARAMETER = "RUNTIME_PARAMETER"
    GENERAL_OPERATION = "GENERAL_OPERATION"
    DERIVED_CLAIM = "DERIVED_CLAIM"
    MODEL_GENERAL_KNOWLEDGE = "MODEL_GENERAL_KNOWLEDGE"
    UNSUPPORTED_CLAIM = "UNSUPPORTED_CLAIM"


class GroundingMode(StrEnum):
    STRICT_SOURCE = "strict_source"
    GROUNDED_REASONING = "grounded_reasoning"
    HYBRID_KNOWLEDGE = "hybrid_knowledge"

    @classmethod
    def parse(cls, value: Any) -> "GroundingMode":
        text = str(value or "").strip().lower()
        for mode in cls:
            if mode.value == text:
                return mode
        if text in ("strict", "source", "strict_source_mode"):
            return cls.STRICT_SOURCE
        if text in ("grounded", "reasoning", "on", "active", "true"):
            return cls.GROUNDED_REASONING
        if text in ("hybrid", "knowledge"):
            return cls.HYBRID_KNOWLEDGE
        return cls.GROUNDED_REASONING


class ClaimOrigin(StrEnum):
    SOURCE = "SOURCE"
    USER = "USER"
    DERIVED = "DERIVED"
    GENERAL_KNOWLEDGE = "GENERAL_KNOWLEDGE"


class VerificationStatus(StrEnum):
    SUPPORTED = "SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    INSUFFICIENT_PREMISES = "INSUFFICIENT_PREMISES"
    CONFLICTING = "CONFLICTING"
    UNVERIFIABLE = "UNVERIFIABLE"


@dataclass(frozen=True, kw_only=True)
class GroundingRequirement:
    """Qué respaldo exige una categoría, según el modo."""

    category: str
    source_evidence_required: bool = False
    semantics_required: bool = False
    user_data_allowed: bool = False
    operation_allowed: bool = False
    model_knowledge_allowed: bool = False
    allowed: bool = True
    reason: str = ""

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "source_evidence_required": self.source_evidence_required,
            "semantics_required": self.semantics_required,
            "user_data_allowed": self.user_data_allowed,
            "operation_allowed": self.operation_allowed,
            "model_knowledge_allowed": self.model_knowledge_allowed,
            "allowed": self.allowed,
            "reason": self.reason,
        }


@dataclass(frozen=True, kw_only=True)
class Premise:
    """Premisa de un claim derivado. Nunca guarda cadena de pensamiento."""

    statement: str
    origin: str = ClaimOrigin.SOURCE.value
    evidence_refs: tuple[str, ...] = ()
    key: str = ""

    @property
    def grounded(self) -> bool:
        if self.origin == ClaimOrigin.SOURCE.value:
            return bool(self.statement) and (bool(self.evidence_refs) or bool(self.key))
        return self.origin in (
            ClaimOrigin.USER.value,
            ClaimOrigin.GENERAL_KNOWLEDGE.value,
            ClaimOrigin.DERIVED.value,
        )

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "statement": self.statement[:240],
            "origin": self.origin,
            "evidence_refs": list(self.evidence_refs[:6]),
            "key": self.key[:80],
        }


@dataclass(kw_only=True)
class DerivedClaim:
    """Conclusión derivada: premisas + operación + resultado + verificación."""

    statement: str
    claim_type: str = GroundingCategory.DERIVED_CLAIM.value
    premises: tuple[Premise, ...] = ()
    user_inputs: tuple[str, ...] = ()
    operation: str = ""
    result: Any = None
    evidence_refs: tuple[str, ...] = ()
    confidence: float = 0.0
    verification_status: str = VerificationStatus.UNVERIFIABLE.value
    origin: str = ClaimOrigin.DERIVED.value
    missing_premises: tuple[str, ...] = ()
    verification_note: str = ""
    version: str = GROUNDING_VERSION

    @property
    def supported(self) -> bool:
        return self.verification_status == VerificationStatus.SUPPORTED.value

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "statement": self.statement[:300],
            "claim_type": self.claim_type,
            "origin": self.origin,
            "operation": self.operation,
            "result": self.result,
            "premises": [premise.to_public_dict() for premise in self.premises[:8]],
            "user_inputs": list(self.user_inputs[:8]),
            "evidence_refs": list(self.evidence_refs[:8]),
            "confidence": round(float(self.confidence), 4),
            "verification_status": self.verification_status,
            "missing_premises": list(self.missing_premises[:8]),
            "verification_note": self.verification_note[:240],
        }


@dataclass(frozen=True, kw_only=True)
class GroundedInference:
    """Inferencia no ejecutable: premisas + conclusión candidata + verificación.

    La conclusión puede NO existir textualmente en las fuentes; lo que debe
    existir es el respaldo de las premisas y la validez de la derivación.
    """

    candidate: str
    premises: tuple[Premise, ...] = ()
    user_inputs: tuple[str, ...] = ()
    supporting_evidence: tuple[str, ...] = ()
    verification_status: str = VerificationStatus.UNVERIFIABLE.value
    verification_note: str = ""

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate[:300],
            "premises": [premise.to_public_dict() for premise in self.premises[:8]],
            "user_inputs": list(self.user_inputs[:8]),
            "supporting_evidence": list(self.supporting_evidence[:8]),
            "verification_status": self.verification_status,
            "verification_note": self.verification_note[:240],
        }


@dataclass(frozen=True, kw_only=True)
class GroundingContract:
    """Contrato explícito: qué tipo de afirmación requiere qué respaldo."""

    mode: str = GroundingMode.GROUNDED_REASONING.value
    allowed_operations: tuple[str, ...] = ()
    version: str = GROUNDING_VERSION

    @property
    def grounding_mode(self) -> GroundingMode:
        return GroundingMode.parse(self.mode)

    def requirement_for(self, category: str) -> GroundingRequirement:
        mode = self.grounding_mode
        normalized = str(category or "").upper()
        if normalized in (
            GroundingCategory.SOURCE_FACT.value,
            GroundingCategory.SOURCE_RULE.value,
        ):
            return GroundingRequirement(
                category=normalized,
                source_evidence_required=True,
                reason="domain fact/rule must be supported by retrieved evidence",
            )
        if normalized in (
            GroundingCategory.USER_INPUT.value,
            GroundingCategory.USER_EXAMPLE.value,
            GroundingCategory.RUNTIME_PARAMETER.value,
        ):
            return GroundingRequirement(
                category=normalized,
                user_data_allowed=True,
                reason="user-provided value is scenario data; source match not required",
            )
        if normalized == GroundingCategory.RUNTIME_PATTERN.value:
            return GroundingRequirement(
                category=normalized,
                source_evidence_required=False,
                semantics_required=True,
                user_data_allowed=True,
                operation_allowed=True,
                reason="pattern instance does not require literal source match; its documented semantics do",
            )
        if normalized == GroundingCategory.GENERAL_OPERATION.value:
            allowed = mode != GroundingMode.STRICT_SOURCE
            return GroundingRequirement(
                category=normalized,
                operation_allowed=allowed,
                allowed=allowed,
                reason=(
                    "deterministic operation allowed on grounded premises"
                    if allowed
                    else "strict source mode restricts general operations"
                ),
            )
        if normalized == GroundingCategory.DERIVED_CLAIM.value:
            return GroundingRequirement(
                category=normalized,
                source_evidence_required=True,
                semantics_required=True,
                user_data_allowed=True,
                operation_allowed=mode != GroundingMode.STRICT_SOURCE,
                allowed=True,
                reason="derived conclusion requires grounded premises and a valid derivation",
            )
        if normalized == GroundingCategory.MODEL_GENERAL_KNOWLEDGE.value:
            allowed = mode == GroundingMode.HYBRID_KNOWLEDGE
            return GroundingRequirement(
                category=normalized,
                model_knowledge_allowed=allowed,
                allowed=allowed,
                reason=(
                    "general model knowledge allowed in hybrid mode, never silently"
                    if allowed
                    else "model knowledge cannot fill missing domain semantics in this mode"
                ),
            )
        return GroundingRequirement(
            category=normalized or GroundingCategory.UNSUPPORTED_CLAIM.value,
            allowed=False,
            reason="unsupported claim: never asserted",
        )

    def allows_category(self, category: str) -> bool:
        return self.requirement_for(category).allowed

    def to_public_dict(self) -> dict[str, Any]:
        categories = [
            GroundingCategory.SOURCE_FACT.value,
            GroundingCategory.SOURCE_RULE.value,
            GroundingCategory.USER_INPUT.value,
            GroundingCategory.RUNTIME_PATTERN.value,
            GroundingCategory.RUNTIME_PARAMETER.value,
            GroundingCategory.GENERAL_OPERATION.value,
            GroundingCategory.DERIVED_CLAIM.value,
            GroundingCategory.MODEL_GENERAL_KNOWLEDGE.value,
        ]
        return {
            "version": self.version,
            "mode": self.grounding_mode.value,
            "allowed_operations": list(self.allowed_operations),
            "requirements": [
                self.requirement_for(category).to_public_dict()
                for category in categories
            ],
        }


def resolve_grounding_mode(settings: Any | None = None) -> str:
    """Modo de grounding desde settings si existe; GROUNDED_REASONING default."""
    if settings is None:
        try:
            from src.core.config import get_settings

            settings = get_settings()
        except Exception:  # noqa: BLE001 — sin settings, default documentado
            settings = None
    raw = getattr(settings, "RAG_GROUNDING_MODE", "") if settings is not None else ""
    return GroundingMode.parse(raw).value


__all__ = [
    "ClaimOrigin",
    "DerivedClaim",
    "GROUNDING_VERSION",
    "GroundedInference",
    "GroundingCategory",
    "GroundingContract",
    "GroundingMode",
    "GroundingRequirement",
    "Premise",
    "VerificationStatus",
    "resolve_grounding_mode",
]
