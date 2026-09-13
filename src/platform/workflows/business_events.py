# =============================================================================
# BusinessEvent — contrato normalizado de eventos empresariales (Fase A).
#
# Los eventos del bus actual (`rag:events`) son dicts sueltos; este módulo los
# formaliza sin romperlos: `normalize_legacy_event()` convierte el payload
# existente y `to_dispatch_payload()` vuelve al shape que ya consume
# `dispatch_event_to_workflows()`.
#
# El payload de evento es UNTRUSTED INPUT: nunca se interpreta como instrucción.
# =============================================================================
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

DeliveryGuarantee = Literal["best_effort", "at_least_once", "at_most_once"]
Transition = Literal["false_to_true", "true_to_true", "true_to_false", "false_to_false"]
Operation = Literal["created", "updated", "deleted", "transition", "detected", "custom"]

MODEL_CONFIG = ConfigDict(extra="forbid")

_VERSION_RE = re.compile(r"^(?P<type>[a-zA-Z0-9_.-]+?)(?:@v(?P<version>\d+))?$")


def split_event_type(raw: str) -> tuple[str, int]:
    """`inventory.stock.changed@v1` → ("inventory.stock.changed", 1)."""
    match = _VERSION_RE.match(str(raw or "").strip())
    if not match:
        return str(raw or "").strip(), 1
    return match.group("type"), int(match.group("version") or 1)


def transition_of(before_result: bool | None, after_result: bool | None) -> Transition:
    """Diferencia STATE de TRANSITION (misión §13)."""
    before = bool(before_result)
    after = bool(after_result)
    if before is None:
        return "true_to_true" if after else "false_to_false"
    if not before and after:
        return "false_to_true"
    if before and after:
        return "true_to_true"
    if before and not after:
        return "true_to_false"
    return "false_to_false"


def changed_fields(before: dict[str, Any] | None, after: dict[str, Any] | None) -> list[str]:
    before_data = before if isinstance(before, dict) else {}
    after_data = after if isinstance(after, dict) else {}
    keys = set(before_data) | set(after_data)
    return sorted(key for key in keys if before_data.get(key) != after_data.get(key))


def compute_dedupe_key(
    *,
    organization_id: UUID | str,
    event_type: str,
    event_version: int,
    entity_type: str | None,
    entity_id: str | None,
    operation: str | None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    extra: str | None = None,
) -> str:
    """Idempotency key determinista (misión §17).

    org:event@version:entity:operation:hash(before/after) — sin TTL; el
    dispatcher persistente (fase F) la usará para garantizar exactly-once
    lógico. `extra` permite separar transiciones distintas del mismo valor.
    """
    payload = json.dumps(
        {"before": before or {}, "after": after or {}, "extra": extra or ""},
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
    parts = [
        str(organization_id),
        f"{split_event_type(event_type)[0]}@v{event_version}",
        str(entity_type or ""),
        str(entity_id or ""),
        str(operation or ""),
        digest,
    ]
    return ":".join(parts)


class BusinessEvent(BaseModel):
    """Evento empresarial normalizado (misión §5)."""

    model_config = MODEL_CONFIG

    event_id: str = Field(default_factory=lambda: str(uuid4()))
    event_type: str = Field(min_length=1, max_length=160)
    event_version: int = Field(default=1, ge=1)
    organization_id: UUID
    workspace_id: UUID | None = None
    source: str = Field(default="internal_event", max_length=40)
    source_id: str | None = Field(default=None, max_length=160)
    entity_type: str | None = Field(default=None, max_length=80)
    entity_id: str | None = Field(default=None, max_length=160)
    operation: str = Field(default="custom", max_length=40)
    before: dict[str, Any] = Field(default_factory=dict)
    after: dict[str, Any] = Field(default_factory=dict)
    changed_fields: list[str] = Field(default_factory=list)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    received_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    correlation_id: str | None = Field(default=None, max_length=160)
    dedupe_key: str = Field(default="", max_length=300)
    delivery: DeliveryGuarantee = "at_least_once"
    metadata: dict[str, Any] = Field(default_factory=dict)
    security_context: dict[str, Any] | None = None

    def ensure_dedupe_key(self) -> str:
        if not self.dedupe_key:
            base_type, version = split_event_type(self.event_type)
            self.dedupe_key = compute_dedupe_key(
                organization_id=self.organization_id,
                event_type=base_type,
                event_version=version,
                entity_type=self.entity_type,
                entity_id=self.entity_id,
                operation=self.operation,
                before=self.before,
                after=self.after,
                extra=str(self.metadata.get("transition") or ""),
            )
        return self.dedupe_key

    def to_dispatch_payload(self) -> dict[str, Any]:
        """Shape compatible con `dispatch_event_to_workflows()`.

        Los campos de `after` se exponen en la raíz para que los filtros
        (`total`, `stock`, ...) sigan funcionando igual que hoy.
        """
        base_type, version = split_event_type(self.event_type)
        payload: dict[str, Any] = {
            "event": f"{base_type}@v{version}",
            "organization_id": str(self.organization_id),
            "workspace_id": str(self.workspace_id) if self.workspace_id else None,
            "event_id": self.event_id,
            "event_version": version,
            "source": self.source,
            "source_id": self.source_id,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "operation": self.operation,
            "before": self.before,
            "after": self.after,
            "changed_fields": list(self.changed_fields),
            "occurred_at": self.occurred_at.isoformat(),
            "received_at": self.received_at.isoformat(),
            "correlation_id": self.correlation_id,
            "dedupe_key": self.ensure_dedupe_key(),
            "delivery": self.delivery,
            "metadata": self.metadata,
        }
        # Campos de negocio al nivel raíz (filtros existentes).
        for key, value in (self.after or {}).items():
            payload.setdefault(str(key), value)
        return payload

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def build_business_event(
    *,
    organization_id: UUID,
    event_type: str,
    source: str,
    workspace_id: UUID | None = None,
    source_id: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    operation: str = "custom",
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    occurred_at: datetime | None = None,
    correlation_id: str | None = None,
    delivery: DeliveryGuarantee = "at_least_once",
    metadata: dict[str, Any] | None = None,
    security_context: dict[str, Any] | None = None,
    transition: str | None = None,
) -> BusinessEvent:
    base_type, version = split_event_type(event_type)
    before_data = dict(before or {})
    after_data = dict(after or {})
    extra = transition or str((metadata or {}).get("transition") or "")
    event = BusinessEvent(
        event_type=base_type,
        event_version=version,
        organization_id=organization_id,
        workspace_id=workspace_id,
        source=source,
        source_id=source_id,
        entity_type=entity_type,
        entity_id=entity_id,
        operation=operation,
        before=before_data,
        after=after_data,
        changed_fields=changed_fields(before_data, after_data),
        occurred_at=occurred_at or datetime.now(timezone.utc),
        correlation_id=correlation_id,
        delivery=delivery,
        metadata=dict(metadata or {}),
        security_context=security_context,
    )
    event.dedupe_key = compute_dedupe_key(
        organization_id=organization_id,
        event_type=base_type,
        event_version=version,
        entity_type=entity_type,
        entity_id=entity_id,
        operation=operation,
        before=before_data,
        after=after_data,
        extra=extra,
    )
    return event


def normalize_legacy_event(event_type: str, payload: dict[str, Any] | None) -> BusinessEvent | None:
    """Convierte un payload del bus actual a BusinessEvent. None si no hay org."""
    data = dict(payload or {})
    raw_org = data.get("organization_id")
    if not raw_org:
        return None
    try:
        organization_id = UUID(str(raw_org))
    except ValueError:
        return None
    base_type, version = split_event_type(str(event_type or data.get("event") or ""))
    workspace_raw = data.get("workspace_id")
    workspace_id: UUID | None = None
    if workspace_raw:
        try:
            workspace_id = UUID(str(workspace_raw))
        except ValueError:
            workspace_id = None
    dedupe = str(data.get("dedupe_key") or "") or None
    event = build_business_event(
        organization_id=organization_id,
        event_type=base_type,
        source=str(data.get("source") or "internal_event"),
        workspace_id=workspace_id,
        source_id=str(data["source_id"]) if data.get("source_id") else None,
        entity_type=str(data["entity_type"]) if data.get("entity_type") else None,
        entity_id=str(data.get("entity_id") or data.get("id") or "") or None,
        operation=str(data.get("operation") or "custom"),
        before=data.get("before") if isinstance(data.get("before"), dict) else {},
        after=data.get("after") if isinstance(data.get("after"), dict) else {},
        correlation_id=str(data["correlation_id"]) if data.get("correlation_id") else None,
        metadata=data.get("metadata") if isinstance(data.get("metadata"), dict) else {},
    )
    if version != event.event_version and version > 1:
        event.event_version = version
    if dedupe:
        event.dedupe_key = dedupe
    return event


__all__ = [
    "BusinessEvent",
    "DeliveryGuarantee",
    "Operation",
    "Transition",
    "build_business_event",
    "changed_fields",
    "compute_dedupe_key",
    "normalize_legacy_event",
    "split_event_type",
    "transition_of",
]
