# =============================================================================
# Context Envelope — procedencia, scope y confianza de cada dato del prompt.
# =============================================================================
# Envuelve lo que YA existe (turno del usuario, historial, memorias, company
# context, evidencia, workflow, observaciones de tools) con una etiqueta clara:
# de dónde viene, a qué scope pertenece, cuánta confianza tiene y su clave de
# aislamiento (tenant + conversación). NO crea un sistema de memoria nuevo.
#
# Reglas que habilita:
#   - Memory no es evidence.
#   - El escenario del usuario no es evidencia documental.
#   - Company Context no tiene prioridad sobre una regla documental sin política.
#   - Workflow es input del run, no instrucción del sistema.
#   - Observaciones de tools son untrusted.
#   - conversation_id es parte de la isolation key.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

CONTEXT_ENVELOPE_VERSION = "context-envelope-1"


class ContextOrigin(StrEnum):
    USER_TURN = "USER_TURN"
    CONVERSATION = "CONVERSATION"
    MEMORY = "MEMORY"
    COMPANY_CONTEXT = "COMPANY_CONTEXT"
    EVIDENCE = "EVIDENCE"
    WORKFLOW = "WORKFLOW"
    TOOL_OBSERVATION = "TOOL_OBSERVATION"


class ContextScope(StrEnum):
    RUN = "RUN"
    CONVERSATION = "CONVERSATION"
    USER = "USER"
    TENANT = "TENANT"


class ContextTrust(StrEnum):
    AUTHORITATIVE = "AUTHORITATIVE"
    SUPPORTING = "SUPPORTING"
    UNTRUSTED = "UNTRUSTED"


#: Política por origen: (scope, trust). Una sola definición.
_ORIGIN_POLICY: dict[ContextOrigin, tuple[ContextScope, ContextTrust]] = {
    ContextOrigin.USER_TURN: (ContextScope.RUN, ContextTrust.SUPPORTING),
    ContextOrigin.CONVERSATION: (ContextScope.CONVERSATION, ContextTrust.SUPPORTING),
    ContextOrigin.MEMORY: (ContextScope.USER, ContextTrust.SUPPORTING),
    ContextOrigin.COMPANY_CONTEXT: (ContextScope.TENANT, ContextTrust.SUPPORTING),
    ContextOrigin.EVIDENCE: (ContextScope.RUN, ContextTrust.AUTHORITATIVE),
    ContextOrigin.WORKFLOW: (ContextScope.RUN, ContextTrust.SUPPORTING),
    ContextOrigin.TOOL_OBSERVATION: (ContextScope.RUN, ContextTrust.UNTRUSTED),
}


@dataclass(frozen=True, kw_only=True)
class ContextItem:
    origin: ContextOrigin
    scope: ContextScope
    trust: ContextTrust
    tenant_id: str
    conversation_id: str | None = None
    source: str = ""
    ttl_seconds: int | None = None
    label: str = ""

    @property
    def is_evidence(self) -> bool:
        return self.origin is ContextOrigin.EVIDENCE

    def isolation_key(self) -> str:
        """Aislamiento real: tenant + conversación (nunca solo el run)."""
        return f"{self.tenant_id}:{self.conversation_id or '-'}"

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "origin": str(self.origin),
            "scope": str(self.scope),
            "trust": str(self.trust),
            "source": self.source,
            "label": self.label,
            "ttl_seconds": self.ttl_seconds,
            "isolation_key": self.isolation_key(),
        }


@dataclass(frozen=True)
class ContextEnvelope:
    tenant_id: str
    conversation_id: str | None
    items: tuple[ContextItem, ...] = field(default_factory=tuple)

    def of(self, origin: ContextOrigin) -> tuple[ContextItem, ...]:
        return tuple(item for item in self.items if item.origin is origin)

    def authoritative(self) -> tuple[ContextItem, ...]:
        return tuple(
            item for item in self.items if item.trust is ContextTrust.AUTHORITATIVE
        )

    def untrusted(self) -> tuple[ContextItem, ...]:
        return tuple(
            item for item in self.items if item.trust is ContextTrust.UNTRUSTED
        )

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "version": CONTEXT_ENVELOPE_VERSION,
            "isolation_key": f"{self.tenant_id}:{self.conversation_id or '-'}",
            "counts": {
                str(origin): len(self.of(origin))
                for origin in ContextOrigin
                if self.of(origin)
            },
            "items": [item.to_public_dict() for item in self.items],
        }


def _item(
    origin: ContextOrigin,
    *,
    tenant_id: str,
    conversation_id: str | None,
    source: str,
    label: str = "",
    ttl_seconds: int | None = None,
) -> ContextItem:
    scope, trust = _ORIGIN_POLICY[origin]
    return ContextItem(
        origin=origin,
        scope=scope,
        trust=trust,
        tenant_id=str(tenant_id),
        conversation_id=str(conversation_id) if conversation_id else None,
        source=source,
        label=label,
        ttl_seconds=ttl_seconds,
    )


def build_context_envelope(
    *,
    tenant_id: Any,
    conversation_id: Any = None,
    user_turn: bool = True,
    memory_labels: tuple[str, ...] = (),
    company_section_labels: tuple[str, ...] = (),
    evidence_ids: tuple[str, ...] = (),
    workflow_keys: tuple[str, ...] = (),
    tool_observation_labels: tuple[str, ...] = (),
) -> ContextEnvelope:
    """Arma el sobre de contexto del run sin copiar contenido (solo procedencia)."""
    items: list[ContextItem] = []
    if user_turn:
        items.append(
            _item(
                ContextOrigin.USER_TURN,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                source="request.message",
            )
        )
    if conversation_id:
        items.append(
            _item(
                ContextOrigin.CONVERSATION,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                source="conversation_history",
            )
        )
    for label in memory_labels:
        items.append(
            _item(
                ContextOrigin.MEMORY,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                source="memory",
                label=label,
            )
        )
    for label in company_section_labels:
        items.append(
            _item(
                ContextOrigin.COMPANY_CONTEXT,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                source="company_context",
                label=label,
            )
        )
    for evidence_id in evidence_ids:
        items.append(
            _item(
                ContextOrigin.EVIDENCE,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                source="evidence_registry",
                label=str(evidence_id),
            )
        )
    for key in workflow_keys:
        items.append(
            _item(
                ContextOrigin.WORKFLOW,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                source="workflow_context",
                label=str(key),
            )
        )
    for label in tool_observation_labels:
        items.append(
            _item(
                ContextOrigin.TOOL_OBSERVATION,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                source="tool_observation",
                label=str(label),
            )
        )
    return ContextEnvelope(
        tenant_id=str(tenant_id or ""),
        conversation_id=str(conversation_id) if conversation_id else None,
        items=tuple(items),
    )


__all__ = [
    "CONTEXT_ENVELOPE_VERSION",
    "ContextEnvelope",
    "ContextItem",
    "ContextOrigin",
    "ContextScope",
    "ContextTrust",
    "build_context_envelope",
]
