# =============================================================================
# Context Assembly Service — política de memoria por rol.
#
# Usa MemoryRecord y MemoryFoundationService existentes. No crea otro store,
# otro recall ni otro índice. La política del rol decide qué scopes puede leer;
# el tenant, workspace, sujeto, conversación y consentimiento se verifican
# siempre antes de incluir un recuerdo.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from src.platform.studio.contracts import MemoryPolicy, RoleProfileV1, role_from_legacy_payload

#: Scope del rol → scopes de MemoryRecord que puede leer.
_ALLOWED_RECORD_SCOPES: dict[str, frozenset[str]] = {
    "none": frozenset(),
    "session": frozenset({"session"}),
    "participant": frozenset({"participant", "workspace"}),
    "workspace": frozenset({"workspace", "durable_business_state", "tenant"}),
    "durable_business_state": frozenset({"durable_business_state", "workspace"}),
    "long_term": frozenset({"tenant", "workspace", "long_term_consent"}),
    "long_term_consent": frozenset({"long_term_consent"}),
}


@dataclass(frozen=True)
class MemoryContextResult:
    policy: str
    items: tuple[dict[str, Any], ...] = ()
    omitted: tuple[dict[str, str], ...] = ()
    inspected: int = 0

    @property
    def payload(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self.items]

    def summary(self) -> dict[str, Any]:
        return {
            "policy": self.policy,
            "included": len(self.items),
            "omitted": len(self.omitted),
            "inspected": self.inspected,
        }


def memory_policy(role: RoleProfileV1 | dict[str, Any] | None) -> MemoryPolicy:
    if role is None:
        return MemoryPolicy(scope="none")
    profile = role if isinstance(role, RoleProfileV1) else role_from_legacy_payload(role)
    return profile.memory_policy


def _conversation_matches(record: Any, conversation_id: UUID | None) -> bool:
    if conversation_id is None:
        return False
    if record.created_from_conversation_id is not None:
        return str(record.created_from_conversation_id) == str(conversation_id)
    metadata = record.metadata if isinstance(record.metadata, dict) else {}
    return str(metadata.get("conversation_id") or "") == str(conversation_id)


def _expired(record: Any, now: datetime) -> bool:
    if record.deleted_at is not None:
        return True
    expires_at = getattr(record, "expires_at", None)
    if expires_at is None:
        return False
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at <= now


def _record_item(record: Any, *, mask_pii: bool) -> dict[str, Any]:
    item = {
        "memory_id": str(record.id),
        "memory_type": record.memory_type.value,
        "title": record.title,
        "scope": record.scope,
        "confidence": round(float(record.confidence or 0.0), 4),
        "source_component": record.source_component,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }
    if not mask_pii:
        item["description"] = record.description
    return item


async def assemble_memory_context(
    *,
    organization_id: UUID,
    workspace_id: UUID | None,
    role: RoleProfileV1 | dict[str, Any] | None,
    agent_id: UUID | None = None,
    run_id: UUID | None = None,
    workflow_id: UUID | None = None,
    conversation_id: UUID | None = None,
    subject_id: str | None = None,
    limit: int = 8,
    record_usage: bool = False,
    service: Any | None = None,
) -> MemoryContextResult:
    """Ensambla solo memoria autorizada. Fail-closed ante datos incompletos."""
    policy = memory_policy(role)
    scope = policy.scope
    allowed = _ALLOWED_RECORD_SCOPES[scope]
    if not allowed:
        return MemoryContextResult(policy=scope)
    if scope == "session" and conversation_id is None:
        return MemoryContextResult(
            policy=scope,
            omitted=({"reason": "session_without_conversation"},),
        )
    if scope == "participant" and not subject_id:
        return MemoryContextResult(
            policy=scope,
            omitted=({"reason": "participant_without_subject"},),
        )

    if service is None:
        from src.memory.wiring import memory_foundation_service

        service = memory_foundation_service()
    rows = await service.list_memories(
        organization_id,
        status="active",
        limit=200,
        offset=0,
    )
    now = datetime.now(timezone.utc)
    kept: list[dict[str, Any]] = []
    omitted: list[dict[str, str]] = []
    for record in rows:
        reason = None
        if record.deleted_at is not None or _expired(record, now):
            reason = "expired_or_deleted"
        elif record.scope not in allowed:
            reason = "scope_not_allowed"
        elif record.workspace_id is not None and (
            workspace_id is None or str(record.workspace_id) != str(workspace_id)
        ):
            reason = "workspace_mismatch"
        elif scope == "session" and not _conversation_matches(record, conversation_id):
            reason = "conversation_mismatch"
        elif scope in ("participant", "long_term_consent"):
            if not subject_id or str(record.subject_id or "") != str(subject_id):
                reason = "subject_mismatch"
        if reason is None and record.scope == "long_term_consent":
            if record.consent_at is None:
                reason = "missing_consent"
        if reason is not None:
            omitted.append({"memory_id": str(record.id), "reason": reason})
            continue
        kept.append(_record_item(record, mask_pii=policy.pii_masking))
        if len(kept) >= max(1, min(int(limit or 8), 20)):
            break

    result = MemoryContextResult(
        policy=scope,
        items=tuple(kept),
        omitted=tuple(omitted),
        inspected=len(rows),
    )
    if record_usage and run_id is not None:
        for item in result.items:
            try:
                await service.record_use(
                    organization_id=organization_id,
                    memory_id=UUID(str(item["memory_id"])),
                    source_component="workflow.context",
                    phase="assemble",
                    outcome="included",
                    conversation_id=conversation_id,
                    run_id=run_id,
                    agent_id=agent_id,
                    workflow_id=workflow_id,
                    idempotency_key=f"context:{run_id}:{item['memory_id']}",
                    metadata={
                        "policy": scope,
                        "workspace_id": str(workspace_id) if workspace_id else None,
                    },
                )
            except Exception:  # noqa: BLE001 — la observabilidad no tumba el run
                pass
    return result


__all__ = [
    "MemoryContextResult",
    "assemble_memory_context",
    "memory_policy",
]
