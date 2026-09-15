# =============================================================================
# Decision Result — decisión de negocio tipada producida por un agente
# (Cognitive Workflows, Fase 4).
#
# Se construye desde el JSON validado contra `output_schema`/preset y viaja en
# la contribución `decisions` del WorkflowContext. No reemplaza al output
# crudo: lo tipa para lógica posterior (condition, approval, business_result).
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

AGENT_STATUSES: tuple[str, ...] = (
    "ok",
    "low_confidence",
    "insufficient_context",
    "tool_error",
    "budget_exceeded",
    "permission_denied",
    "invalid_output",
)

_DECISION_FIELDS = ("decision", "risk", "label", "summary")


@dataclass(frozen=True, kw_only=True)
class DecisionResult:
    """Decisión estructurada, auditables y ramificables aguas abajo."""

    decision: str = ""
    status: str = "ok"
    confidence: float | None = None
    reasons: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    claim_refs: tuple[str, ...] = ()
    requires_review: bool = False
    reason_codes: tuple[str, ...] = ()
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "status": self.status,
            "confidence": self.confidence,
            "reasons": list(self.reasons),
            "evidence_refs": list(self.evidence_refs),
            "claim_refs": list(self.claim_refs),
            "requires_review": self.requires_review,
            "reason_codes": list(self.reason_codes),
        }

    @classmethod
    def from_agent_output(
        cls,
        data: dict[str, Any],
        *,
        status: str = "ok",
        reason_codes: tuple[str, ...] | list[str] = (),
        evidence_refs: tuple[str, ...] | list[str] = (),
        claim_refs: tuple[str, ...] | list[str] = (),
    ) -> "DecisionResult":
        decision = ""
        for key in _DECISION_FIELDS:
            value = data.get(key)
            if value:
                decision = str(value)[:200]
                break
        confidence_raw = data.get("confidence")
        confidence = (
            float(confidence_raw)
            if isinstance(confidence_raw, (int, float)) and not isinstance(confidence_raw, bool)
            else None
        )
        reasons: list[str] = []
        for key in ("reason", "recommendation"):
            value = data.get(key)
            if value and str(value) not in reasons:
                reasons.append(str(value)[:400])
        return cls(
            decision=decision,
            status=status,
            confidence=confidence,
            reasons=tuple(reasons),
            evidence_refs=tuple(str(item) for item in evidence_refs),
            claim_refs=tuple(str(item) for item in claim_refs),
            requires_review=bool(data.get("requires_review", False)),
            reason_codes=tuple(str(item) for item in reason_codes),
        )


__all__ = ["AGENT_STATUSES", "DecisionResult"]
