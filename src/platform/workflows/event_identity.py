# =============================================================================
# Event identity — una sola regla para decidir si dos entregas son el mismo
# evento. El payload NO es identidad por defecto.
# =============================================================================
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

Source = Literal[
    "webhook",
    "client",
    "provider",
    "schedule",
    "event",
    "manual",
    "conversation",
    "legacy",
]
DedupeMode = Literal[
    "provider_event_id",
    "client_key",
    "schedule_occurrence",
    "producer_event_id",
    "independent",
    "payload_hash",
    "legacy",
]

MAX_KEY_LENGTH = 220


class IngressEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_id: UUID
    workspace_id: UUID | None = None
    workflow_id: UUID
    source: Source = "webhook"
    event_type: str | None = Field(default=None, max_length=120)
    provider_event_id: str | None = Field(default=None, max_length=200)
    occurred_at: datetime | None = None
    received_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    correlation_id: str | None = Field(default=None, max_length=160)
    payload: dict[str, Any] = Field(default_factory=dict)
    business_key: str | None = Field(default=None, max_length=200)
    idempotency_key: str | None = Field(default=None, max_length=240)
    attempt: int = 0
    signature_verified: bool = False
    dedupe_mode: DedupeMode | None = None


@dataclass(frozen=True)
class EventIdentity:
    dedupe_key: str
    dedupe_mode: DedupeMode
    source: Source
    payload_hash: str


def payload_hash(payload: dict[str, Any] | None) -> str:
    blob = json.dumps(payload or {}, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _short(value: str, limit: int = 80) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _clip(value: str) -> str:
    return value[:MAX_KEY_LENGTH]


def resolve_identity(envelope: IngressEnvelope) -> EventIdentity:
    """Resuelve la clave de dedupe por fuente, nunca por payload por defecto."""
    workflow = str(envelope.workflow_id)
    source = envelope.source
    digest = payload_hash(envelope.payload)

    if envelope.dedupe_mode == "payload_hash":
        return EventIdentity(
            _clip(f"payload:{workflow}:{digest}"),
            "payload_hash",
            source,
            digest,
        )

    provider_id = (envelope.provider_event_id or "").strip()
    if provider_id:
        return EventIdentity(
            _clip(f"provider:{source}:{workflow}:{_short(provider_id)}"),
            "provider_event_id",
            source,
            digest,
        )

    explicit = (envelope.idempotency_key or "").strip()
    if explicit:
        if explicit.startswith("sched:"):
            return EventIdentity(_clip(explicit), "schedule_occurrence", "schedule", digest)
        if explicit.startswith("evt:"):
            return EventIdentity(_clip(explicit), "producer_event_id", "event", digest)
        # La clave explícita ya queda aislada por (organization, workflow) en
        # el índice único; no se reescribe para no romper clientes existentes.
        return EventIdentity(_clip(explicit), "client_key", "client", digest)

    if source == "schedule":
        occurrence = (
            envelope.occurred_at.isoformat()
            if envelope.occurred_at is not None
            else envelope.received_at.isoformat()
        )
        return EventIdentity(
            _clip(f"schedule:{workflow}:{occurrence}"),
            "schedule_occurrence",
            "schedule",
            digest,
        )

    if source == "event":
        return EventIdentity(
            _clip(f"event:{workflow}:{uuid4().hex}"),
            "independent",
            "event",
            digest,
        )

    if source in ("webhook", "provider"):
        return EventIdentity(
            _clip(f"webhook:{workflow}:{uuid4().hex}"),
            "independent",
            "webhook",
            digest,
        )

    return EventIdentity(
        _clip(f"{source}:{workflow}:{uuid4().hex}"),
        "independent",
        source,
        digest,
    )


def normalize_ingress_key(
    trigger: str,
    *,
    explicit: str | None,
    workflow_id: UUID,
    payload: dict[str, Any] | None,
    conversation_id: UUID | None = None,
) -> str | None:
    """Compatibilidad: delega la decisión en `resolve_identity`.

    Se conserva la firma para llamadores antiguos; las claves nuevas ya llevan
    namespace de fuente y no derivan del payload salvo opt-in explícito.
    """
    if conversation_id is not None and not explicit:
        digest = payload_hash(payload)
        return _clip(f"conversation:{conversation_id}:{digest}")
    envelope = IngressEnvelope(
        organization_id=UUID("00000000-0000-0000-0000-000000000000"),
        workflow_id=workflow_id,
        source="event" if trigger == "event" else "webhook" if trigger == "webhook" else "manual",
        payload=payload or {},
        idempotency_key=explicit,
    )
    identity = resolve_identity(envelope)
    if identity.dedupe_mode == "independent":
        return None
    return identity.dedupe_key


__all__ = [
    "DedupeMode",
    "EventIdentity",
    "IngressEnvelope",
    "Source",
    "normalize_ingress_key",
    "payload_hash",
    "resolve_identity",
]
