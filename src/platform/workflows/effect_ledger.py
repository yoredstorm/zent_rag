# =============================================================================
# Effect ledger — identidad estable de un efecto externo y su confirmación.
# La transacción de negocio no se mantiene abierta durante la llamada externa.
# Pagos/commerce conservan su ledger existente; esto cubre capacidades externas
# no financieras.
# =============================================================================
from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.postgres.session import get_async_session


def effect_id(
    *,
    organization_id: UUID,
    workflow_id: UUID | None,
    instance_id: UUID | None,
    run_id: UUID | None,
    node_id: str | None,
    capability_ref: str,
    inputs: dict[str, Any] | None,
) -> str:
    scope = {
        "organization_id": str(organization_id),
        "workflow_id": str(workflow_id or ""),
        "instance_id": str(instance_id or ""),
        "run_id": str(run_id or ""),
        "node_id": str(node_id or ""),
        "capability_ref": str(capability_ref),
        "inputs": inputs or {},
    }
    blob = json.dumps(scope, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def request_hash(inputs: dict[str, Any] | None) -> str:
    blob = json.dumps(inputs or {}, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


async def begin_effect(
    *,
    organization_id: UUID,
    workspace_id: UUID | None,
    workflow_id: UUID,
    instance_id: UUID | None,
    run_id: UUID | None,
    node_id: str,
    capability_ref: str,
    inputs: dict[str, Any] | None,
) -> tuple[str, dict[str, Any] | None]:
    """Devuelve (effect_id, resultado confirmado si ya existe)."""
    eid = effect_id(
        organization_id=organization_id,
        workflow_id=workflow_id,
        instance_id=instance_id,
        run_id=run_id,
        node_id=node_id,
        capability_ref=capability_ref,
        inputs=inputs,
    )
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO workflow_effect_intents "
                    "(organization_id, workspace_id, workflow_id, instance_id, node_id, "
                    "capability_ref, effect_id, status, request_hash, attempts) "
                    "VALUES (:oid, :ws, :wid, :iid, :nid, :cap, :eid, 'pending', :rhash, 1) "
                    "ON CONFLICT (organization_id, effect_id) DO UPDATE "
                    "SET attempts = workflow_effect_intents.attempts + 1, "
                    "updated_at = NOW() "
                    "RETURNING status, response"
                ),
                {
                    "oid": organization_id,
                    "ws": workspace_id,
                    "wid": workflow_id,
                    "iid": instance_id,
                    "nid": node_id[:80],
                    "cap": capability_ref[:120],
                    "eid": eid,
                    "rhash": request_hash(inputs),
                },
            )
        ).fetchone()
        await session.commit()
    finally:
        await session.close()
    if row is not None and str(row.status) == "confirmed":
        return eid, dict(row.response or {})
    return eid, None


async def confirm_effect(
    *,
    organization_id: UUID,
    eid: str,
    response: dict[str, Any] | None,
    external_id: str | None = None,
) -> None:
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "UPDATE workflow_effect_intents SET status = 'confirmed', "
                "response = CAST(:response AS jsonb), external_id = :external, "
                "updated_at = NOW(), last_error = NULL "
                "WHERE organization_id = :oid AND effect_id = :eid"
            ),
            {
                "response": json.dumps(response or {}, default=str),
                "external": (external_id or "")[:200] or None,
                "oid": organization_id,
                "eid": eid,
            },
        )
        await session.commit()
    finally:
        await session.close()


async def fail_effect(*, organization_id: UUID, eid: str, error: str) -> None:
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "UPDATE workflow_effect_intents SET status = 'failed', "
                "last_error = :error, updated_at = NOW() "
                "WHERE organization_id = :oid AND effect_id = :eid"
            ),
            {"error": error[:400], "oid": organization_id, "eid": eid},
        )
        await session.commit()
    finally:
        await session.close()


__all__ = [
    "begin_effect",
    "confirm_effect",
    "effect_id",
    "fail_effect",
    "request_hash",
]
