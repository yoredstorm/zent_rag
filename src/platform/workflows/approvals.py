# =============================================================================
# Verified approvals — una aprobación solo autoriza si el servidor puede
# resolverla, vincularla al workflow/instancia/versión/acción y consumirla.
#
# `node.config.approval_ref` NO es autoridad: es una referencia. Un string
# arbitrario ("approved", "ok", etc.) no encuentra fila y se deniega.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

STATUS_APPROVED = "approved"
TERMINAL_FAILURES = frozenset(
    {"pending", "rejected", "expired", "revoked", "cancelled", "canceled"}
)


class ApprovalInvalid(RuntimeError):
    """Aprobación ausente o no verificable para esta operación."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class VerifiedApproval:
    approval_id: str
    run_id: str
    instance_id: str | None
    workflow_id: str
    node_id: str
    capability_ref: str | None
    target_node_id: str | None
    scope: dict[str, Any]
    decided_by: str | None
    expires_at: datetime | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "run_id": self.run_id,
            "instance_id": self.instance_id,
            "workflow_id": self.workflow_id,
            "node_id": self.node_id,
            "capability_ref": self.capability_ref,
            "target_node_id": self.target_node_id,
            "scope": dict(self.scope),
            "decided_by": self.decided_by,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }


def _as_uuid(value: Any) -> UUID | None:
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _approval_ref_value(rctx: Any, node: Any) -> str | None:
    raw = (getattr(node, "config", None) or {}).get("approval_ref")
    if raw is None or raw == "":
        return None
    from src.platform.workflows.nodes import _resolve_ref

    try:
        resolved = _resolve_ref(raw, rctx)
    except Exception:  # noqa: BLE001 — referencia rota == no verificable
        resolved = raw
    text_value = str(resolved or "").strip()
    return text_value or None


async def _load_row(
    organization_id: UUID,
    *,
    approval_id: UUID | None = None,
    instance_id: UUID | None = None,
    run_id: UUID | None = None,
) -> dict[str, Any] | None:
    session = await get_async_session()
    try:
        base = (
            "SELECT a.id, a.run_id, a.instance_id, a.workflow_id, a.organization_id, "
            "       a.workspace_id, a.node_id, a.action, a.summary, a.status, "
            "       a.requested_by, a.decided_by, a.requested_at, a.decided_at, "
            "       a.expires_at, a.workflow_version, a.graph_hash, a.capability_ref, "
            "       a.target_node_id, a.approval_scope, "
            "       COALESCE(a.instance_id, r.instance_id) AS effective_instance_id "
            "FROM workflow_approvals a "
            "LEFT JOIN workflow_runs r ON r.id = a.run_id "
            "WHERE a.organization_id = :oid "
        )
        params: dict[str, Any] = {"oid": str(organization_id)}
        if approval_id is not None:
            base += "AND a.id = :aid "
            params["aid"] = str(approval_id)
        elif instance_id is not None:
            base += "AND (a.instance_id = :iid OR r.instance_id = :iid) "
            params["iid"] = str(instance_id)
        elif run_id is not None:
            base += "AND a.run_id = :rid "
            params["rid"] = str(run_id)
        else:
            return None
        base += "ORDER BY a.decided_at DESC NULLS LAST, a.requested_at DESC LIMIT 1"
        row = (await session.execute(text(base), params)).fetchone()
    finally:
        await session.close()
    return dict(row._mapping) if row is not None else None


def _binding_matches(
    row: dict[str, Any],
    *,
    execution: Any,
    node_id: str,
    capability_ref: str,
) -> tuple[bool, str]:
    scope = dict(row.get("approval_scope") or {})
    target_node = str(row.get("target_node_id") or "")
    bound_capability = str(row.get("capability_ref") or "")
    scope_type = str(scope.get("scope_type") or "")

    if target_node and target_node != str(node_id):
        return False, "approval_scope_mismatch"
    if bound_capability and bound_capability != str(capability_ref):
        return False, "approval_scope_mismatch"
    if scope_type == "node" and target_node != str(node_id):
        return False, "approval_scope_mismatch"
    if scope_type == "capability" and bound_capability != str(capability_ref):
        return False, "approval_scope_mismatch"
    if scope_type not in ("run", "node", "capability"):
        # Aprobaciones sin vínculo explícito (legacy) no autorizan efectos:
        # se requiere volver a pedirlas con el esquema nuevo.
        return False, "approval_scope_mismatch"

    execution_instance = getattr(execution, "instance_id", None)
    effective_instance = row.get("effective_instance_id") or row.get("instance_id")
    if execution_instance is not None:
        if not effective_instance or str(effective_instance) != str(execution_instance):
            return False, "approval_scope_mismatch"
    else:
        # Run standalone: la aprobación debe pertenecer al mismo run.
        if str(row.get("run_id")) != str(getattr(execution, "run_id", "")):
            return False, "approval_scope_mismatch"

    workflow_version = row.get("workflow_version")
    execution_version = getattr(execution, "workflow_version", None)
    if workflow_version is not None and execution_version is not None:
        if int(workflow_version) != int(execution_version):
            return False, "approval_version_mismatch"
    graph_hash = str(row.get("graph_hash") or "")
    execution_hash = str(getattr(execution, "graph_hash", "") or "")
    if graph_hash and execution_hash and graph_hash != execution_hash:
        return False, "approval_version_mismatch"
    return True, ""


def _validate_row(
    row: dict[str, Any], *, execution: Any, node_id: str, capability_ref: str
) -> VerifiedApproval:
    status = str(row.get("status") or "")
    if status != STATUS_APPROVED:
        raise ApprovalInvalid(
            "approval_invalid" if status in TERMINAL_FAILURES else "approval_invalid",
            f"la aprobación está en estado {status or 'desconocido'}",
        )
    if not row.get("decided_by"):
        raise ApprovalInvalid("approval_invalid", "la aprobación no tiene aprobador")
    expires = _parse_dt(row.get("expires_at"))
    if expires is not None and expires <= datetime.now(timezone.utc):
        raise ApprovalInvalid("approval_expired", "la aprobación expiró")
    if str(row.get("workflow_id")) != str(getattr(execution, "workflow_id", "")):
        raise ApprovalInvalid("approval_scope_mismatch", "aprobación de otro workflow")
    approval_ws = row.get("workspace_id")
    execution_ws = getattr(execution, "workspace_id", None)
    if approval_ws and execution_ws and str(approval_ws) != str(execution_ws):
        raise ApprovalInvalid("approval_scope_mismatch", "aprobación de otro workspace")
    if approval_ws and execution_ws is None:
        raise ApprovalInvalid("approval_scope_mismatch", "aprobación de otro workspace")
    matched, code = _binding_matches(
        row, execution=execution, node_id=node_id, capability_ref=capability_ref
    )
    if not matched:
        raise ApprovalInvalid(code, "la aprobación no cubre esta operación")
    return VerifiedApproval(
        approval_id=str(row.get("id")),
        run_id=str(row.get("run_id")),
        instance_id=(
            str(row.get("effective_instance_id"))
            if row.get("effective_instance_id")
            else None
        ),
        workflow_id=str(row.get("workflow_id")),
        node_id=str(row.get("node_id") or ""),
        capability_ref=str(row.get("capability_ref") or "") or None,
        target_node_id=str(row.get("target_node_id") or "") or None,
        scope=dict(row.get("approval_scope") or {}),
        decided_by=str(row.get("decided_by") or "") or None,
        expires_at=expires,
    )


async def _consume(
    organization_id: UUID,
    approval: VerifiedApproval,
    *,
    run_id: UUID,
    node_id: str,
    operation_id: str | None,
) -> None:
    """At-most-once por (aprobación, run, nodo). Cerca del efecto."""
    session = await get_async_session()
    try:
        inserted = (
            await session.execute(
                text(
                    "INSERT INTO workflow_approval_consumptions "
                    "(approval_id, organization_id, run_id, node_id, operation_id) "
                    "VALUES (:aid, :oid, :rid, :nid, :opid) "
                    "ON CONFLICT (approval_id, run_id, node_id) DO NOTHING "
                    "RETURNING id"
                ),
                {
                    "aid": approval.approval_id,
                    "oid": str(organization_id),
                    "rid": str(run_id),
                    "nid": str(node_id)[:120],
                    "opid": (operation_id or "")[:200] or None,
                },
            )
        ).fetchone()
        await session.commit()
    finally:
        await session.close()
    if inserted is None:
        raise ApprovalInvalid(
            "approval_already_consumed",
            "esta aprobación ya autorizó este nodo en este run",
        )


async def resolve_verified_approval(
    rctx: Any,
    node: Any,
    *,
    capability_ref: str,
    consume: bool = True,
) -> VerifiedApproval:
    """Resuelve una aprobación verificable o lanza ApprovalInvalid."""
    execution = rctx.execution
    node_id = str(getattr(node, "id", "") or "")
    ref = _approval_ref_value(rctx, node)
    approval: VerifiedApproval | None = None
    if ref:
        approval_id = _as_uuid(ref)
        if approval_id is None:
            raise ApprovalInvalid(
                "approval_invalid", "approval_ref no es un identificador verificable"
            )
        row = await _load_row(execution.organization_id, approval_id=approval_id)
        if row is None:
            raise ApprovalInvalid("approval_invalid", "la aprobación no existe")
        approval = _validate_row(
            row, execution=execution, node_id=node_id, capability_ref=capability_ref
        )
    else:
        rows = await _load_approved_rows(
            execution.organization_id,
            instance_id=getattr(execution, "instance_id", None),
            run_id=getattr(execution, "run_id", None),
        )
        last_error: ApprovalInvalid | None = None
        for row in rows:
            try:
                approval = _validate_row(
                    row,
                    execution=execution,
                    node_id=node_id,
                    capability_ref=capability_ref,
                )
                break
            except ApprovalInvalid as exc:
                last_error = exc
                continue
        if approval is None:
            raise last_error or ApprovalInvalid(
                "approval_required", "no hay aprobación verificada para esta acción"
            )
    if consume:
        await _consume(
            execution.organization_id,
            approval,
            run_id=execution.run_id,
            node_id=node_id,
            operation_id=str(getattr(rctx, "idempotency_key", "") or ""),
        )
    try:
        logger.info(
            "approval.verified",
            organization_id=str(execution.organization_id),
            workspace_id=str(getattr(execution, "workspace_id", "") or ""),
            approval_id=approval.approval_id,
            run_id=str(execution.run_id),
            instance_id=str(getattr(execution, "instance_id", "") or ""),
            node_id=node_id,
            capability_ref=capability_ref,
            decided_by=approval.decided_by,
        )
    except Exception:  # noqa: BLE001
        pass
    return approval


async def _load_approved_rows(
    organization_id: UUID,
    *,
    instance_id: UUID | None,
    run_id: UUID | None,
) -> list[dict[str, Any]]:
    session = await get_async_session()
    try:
        sql = (
            "SELECT a.id, a.run_id, a.instance_id, a.workflow_id, a.organization_id, "
            "       a.workspace_id, a.node_id, a.action, a.summary, a.status, "
            "       a.requested_by, a.decided_by, a.requested_at, a.decided_at, "
            "       a.expires_at, a.workflow_version, a.graph_hash, a.capability_ref, "
            "       a.target_node_id, a.approval_scope, "
            "       COALESCE(a.instance_id, r.instance_id) AS effective_instance_id "
            "FROM workflow_approvals a "
            "LEFT JOIN workflow_runs r ON r.id = a.run_id "
            "WHERE a.organization_id = :oid AND a.status = 'approved' "
        )
        params: dict[str, Any] = {"oid": str(organization_id)}
        if instance_id is not None:
            sql += "AND (a.instance_id = :iid OR r.instance_id = :iid) "
            params["iid"] = str(instance_id)
        elif run_id is not None:
            sql += "AND a.run_id = :rid "
            params["rid"] = str(run_id)
        else:
            return []
        sql += "ORDER BY a.decided_at DESC NULLS LAST LIMIT 20"
        rows = (await session.execute(text(sql), params)).fetchall()
    finally:
        await session.close()
    return [dict(row._mapping) for row in rows]


__all__ = [
    "ApprovalInvalid",
    "VerifiedApproval",
    "resolve_verified_approval",
]
