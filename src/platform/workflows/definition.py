# =============================================================================
# Definition resolver — una sola autoridad para saber qué grafo ejecutar.
#
# `published` = snapshot inmutable apuntado por workflows.published_version_id.
# `draft`     = fila editable, solo para pruebas/simulación.
# `instance`  = snapshot congelado de una WorkflowInstance.
#
# No se infiere el modo por la ausencia de graph_override.
# =============================================================================
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.postgres.session import get_async_session

DEFINITION_SOURCES = ("published", "draft", "instance")


class PublishedDefinitionError(RuntimeError):
    """Definición publicada ausente, inválida o no autorizada."""

    def __init__(self, code: str, message: str, *, status_code: int = 409):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message}


def trigger_fingerprint(trigger_type: str | None, trigger_config: dict | None) -> str:
    """Hash del comportamiento del trigger. El secret no forma parte del hash."""
    cfg = dict(trigger_config or {})
    cfg.pop("hook_secret_hash", None)
    payload = {
        "trigger_type": str(trigger_type or ""),
        "trigger_config": cfg,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _graph_hash(graph: dict[str, Any] | None) -> str:
    from src.platform.workflows.release_policy import graph_fingerprint

    return graph_fingerprint(graph)


def _adapt_legacy(
    steps: list | None,
    trigger_type: str | None,
    trigger_config: dict | None,
) -> dict[str, Any]:
    from src.platform.workflows.ir import LegacyWorkflowAdapter

    return LegacyWorkflowAdapter.steps_to_graph(
        steps or [], str(trigger_type or "webhook"), dict(trigger_config or {})
    ).to_dict()


def _snapshot_graph(
    snapshot: dict[str, Any],
    *,
    steps: list | None = None,
) -> tuple[dict[str, Any], list]:
    graph = snapshot.get("graph")
    snapshot_steps = list(snapshot.get("steps") or steps or [])
    if not isinstance(graph, dict) or not graph:
        graph = _adapt_legacy(
            snapshot_steps,
            snapshot.get("trigger_type"),
            snapshot.get("trigger_config"),
        )
    return dict(graph), snapshot_steps


def _certificate_problem(cert: dict[str, Any] | None) -> tuple[str, str] | None:
    if cert is None:
        return ("certificate_required", "La versión publicada no tiene certificado.")
    if cert.get("revoked_at"):
        return ("certificate_revoked", "El certificado de la versión publicada fue revocado.")
    expires = cert.get("expires_at")
    if expires:
        try:
            if datetime.fromisoformat(str(expires).replace("Z", "+00:00")) <= datetime.now(
                timezone.utc
            ):
                return ("certificate_expired", "El certificado de la versión publicada venció.")
        except ValueError:
            return ("certificate_invalid", "La fecha del certificado no es válida.")
    return None


async def _certificate_row(
    organization_id: UUID, workflow_id: UUID, certificate_id: UUID | None
) -> dict[str, Any] | None:
    if certificate_id is None:
        return None
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT id, organization_id, workspace_id, workflow_id, level, state, "
                    "graph_hash, trigger_hash, binding_fingerprint, revoked_at, expires_at "
                    "FROM workflow_certificates WHERE id = :cid AND organization_id = :oid "
                    "AND workflow_id = :wid"
                ),
                {"cid": certificate_id, "oid": organization_id, "wid": workflow_id},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None:
        return None
    return {
        "id": str(row.id),
        "organization_id": str(row.organization_id),
        "workspace_id": str(row.workspace_id) if row.workspace_id else None,
        "workflow_id": str(row.workflow_id),
        "level": row.level,
        "state": row.state,
        "graph_hash": row.graph_hash,
        "trigger_hash": row.trigger_hash,
        "binding_fingerprint": row.binding_fingerprint,
        "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
    }


async def load_published_definition(
    organization_id: UUID,
    workflow_id: UUID,
    *,
    workspace_id: UUID | None = None,
    require_active: bool = False,
) -> dict[str, Any]:
    """Resuelve la versión publicada exacta que debe ejecutarse."""
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT w.id, w.organization_id, w.workspace_id, w.status, w.name, "
                    "w.description, w.steps AS live_steps, w.graph AS live_graph, "
                    "w.trigger_type AS live_trigger_type, "
                    "w.trigger_config AS live_trigger_config, "
                    "w.workflow_version AS live_workflow_version, "
                    "w.graph_source AS live_graph_source, "
                    "w.editor_state AS live_editor_state, "
                    "w.published_version_id, w.published_certificate_id, "
                    "w.published_graph_hash, w.published_at, w.deployment_generation, "
                    "w.draft_revision, v.id AS version_id, v.version_number, "
                    "v.config_snapshot, v.graph_hash AS version_graph_hash, "
                    "v.trigger_hash AS version_trigger_hash, "
                    "v.certificate_id AS version_certificate_id, "
                    "v.legacy_baseline, v.policy_version AS version_policy_version, "
                    "v.workspace_id AS version_workspace_id "
                    "FROM workflows w "
                    "LEFT JOIN workflow_versions v ON v.id = w.published_version_id "
                    "WHERE w.id = :wid AND w.organization_id = :oid"
                ),
                {"wid": workflow_id, "oid": organization_id},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None:
        raise PublishedDefinitionError("not_found", "Workflow no encontrado.", status_code=404)
    wf_ws = UUID(str(row.workspace_id)) if row.workspace_id else None
    if wf_ws is not None and workspace_id is not None and wf_ws != workspace_id:
        raise PublishedDefinitionError(
            "workspace_mismatch", "El workflow pertenece a otro workspace.", status_code=403
        )
    if require_active and str(row.status) != "active":
        raise PublishedDefinitionError("inactive", "El workflow no está activo.")
    if row.published_version_id is None or row.version_id is None:
        raise PublishedDefinitionError(
            "published_version_required",
            "El workflow activo no tiene una versión publicada.",
        )
    snapshot = row.config_snapshot if isinstance(row.config_snapshot, dict) else {}
    graph, steps = _snapshot_graph(snapshot, steps=row.live_steps)
    computed_hash = _graph_hash(graph)
    stored_hash = str(row.version_graph_hash or "")
    if stored_hash and stored_hash != computed_hash:
        raise PublishedDefinitionError(
            "published_snapshot_hash_mismatch",
            "El snapshot publicado no coincide con su hash certificado.",
        )
    published_hash = str(row.published_graph_hash or "")
    if published_hash and published_hash != computed_hash:
        raise PublishedDefinitionError(
            "published_snapshot_hash_mismatch",
            "El puntero publicado no coincide con el snapshot.",
        )
    if not stored_hash or not published_hash:
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    "UPDATE workflow_versions SET graph_hash = :hash "
                    "WHERE id = :vid AND organization_id = :oid AND graph_hash = ''"
                ),
                {"hash": computed_hash, "vid": row.version_id, "oid": organization_id},
            )
            await session.execute(
                text(
                    "UPDATE workflows SET published_graph_hash = :hash "
                    "WHERE id = :wid AND organization_id = :oid "
                    "AND published_version_id = :vid AND published_graph_hash IS NULL"
                ),
                {
                    "hash": computed_hash,
                    "wid": workflow_id,
                    "oid": organization_id,
                    "vid": row.version_id,
                },
            )
            await session.commit()
        finally:
            await session.close()

    certificate_id = row.version_certificate_id or row.published_certificate_id
    legacy_baseline = bool(row.legacy_baseline)
    trigger_type = str(snapshot.get("trigger_type") or row.live_trigger_type or "webhook")
    trigger_config = dict(snapshot.get("trigger_config") or {})
    trigger_hash = trigger_fingerprint(trigger_type, trigger_config)
    if not legacy_baseline:
        cert = await _certificate_row(
            organization_id, workflow_id, UUID(str(certificate_id)) if certificate_id else None
        )
        problem = _certificate_problem(cert)
        if problem is not None:
            raise PublishedDefinitionError(problem[0], problem[1])
        if cert and cert.get("graph_hash") and cert["graph_hash"] != computed_hash:
            raise PublishedDefinitionError(
                "certificate_stale", "El certificado no corresponde al snapshot publicado."
            )
        if cert and cert.get("trigger_hash") and cert["trigger_hash"] != trigger_hash:
            raise PublishedDefinitionError(
                "trigger_stale", "El trigger cambió desde la certificación."
            )
    return {
        "workflow_id": str(row.id),
        "organization_id": str(row.organization_id),
        "workspace_id": str(row.workspace_id) if row.workspace_id else None,
        "name": snapshot.get("name") or row.name,
        "description": snapshot.get("description") if snapshot.get("description") is not None else row.description,
        "status": str(row.status),
        "version_id": str(row.version_id),
        "version_number": int(row.version_number or 0),
        "certificate_id": str(certificate_id) if certificate_id else None,
        "definition_source": "published",
        "graph": graph,
        "steps": steps,
        "trigger_type": trigger_type,
        "trigger_config": trigger_config,
        "workflow_version": int(snapshot.get("workflow_version") or row.live_workflow_version or 1),
        "policy_version": str(row.version_policy_version or "v1"),
        "deployment_generation": int(row.deployment_generation or 0),
        "graph_hash": computed_hash,
        "trigger_hash": trigger_hash,
        "legacy_baseline": legacy_baseline,
        "draft_revision": int(row.draft_revision or 0),
    }


async def load_draft_definition(
    organization_id: UUID,
    workflow_id: UUID,
    *,
    workspace_id: UUID | None = None,
) -> dict[str, Any]:
    """Fila editable. Solo para simulación o pruebas explícitas."""
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT id, organization_id, workspace_id, status, name, description, "
                    "steps, graph, trigger_type, trigger_config, workflow_version, "
                    "graph_source, editor_state, published_version_id, published_at, "
                    "deployment_generation, draft_revision "
                    "FROM workflows WHERE id = :wid AND organization_id = :oid"
                ),
                {"wid": workflow_id, "oid": organization_id},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None:
        raise PublishedDefinitionError("not_found", "Workflow no encontrado.", status_code=404)
    wf_ws = UUID(str(row.workspace_id)) if row.workspace_id else None
    if wf_ws is not None and workspace_id is not None and wf_ws != workspace_id:
        raise PublishedDefinitionError(
            "workspace_mismatch", "El workflow pertenece a otro workspace.", status_code=403
        )
    graph = dict(row.graph) if row.graph else _adapt_legacy(
        row.steps, row.trigger_type, row.trigger_config
    )
    return {
        "workflow_id": str(row.id),
        "organization_id": str(row.organization_id),
        "workspace_id": str(row.workspace_id) if row.workspace_id else None,
        "name": row.name,
        "description": row.description,
        "status": str(row.status),
        "version_id": str(row.published_version_id) if row.published_version_id else None,
        "version_number": None,
        "certificate_id": None,
        "definition_source": "draft",
        "graph": graph,
        "steps": list(row.steps or []),
        "trigger_type": str(row.trigger_type or "webhook"),
        "trigger_config": dict(row.trigger_config or {}),
        "workflow_version": int(row.workflow_version or 1),
        "policy_version": "v1",
        "deployment_generation": int(row.deployment_generation or 0),
        "graph_hash": _graph_hash(graph),
        "trigger_hash": trigger_fingerprint(row.trigger_type, row.trigger_config),
        "legacy_baseline": False,
        "draft_revision": int(row.draft_revision or 0),
    }


async def load_instance_definition(instance: dict[str, Any]) -> dict[str, Any]:
    snapshot = instance.get("definition_snapshot") or {}
    graph, steps = _snapshot_graph(snapshot)
    trigger_type = str(snapshot.get("trigger_type") or "manual")
    trigger_config = dict(snapshot.get("trigger_config") or {})
    return {
        "workflow_id": str(instance.get("workflow_id") or ""),
        "organization_id": str(instance.get("organization_id") or ""),
        "workspace_id": str(instance["workspace_id"]) if instance.get("workspace_id") else None,
        "name": snapshot.get("name"),
        "description": snapshot.get("description"),
        "status": str(instance.get("status") or ""),
        "version_id": str(instance.get("workflow_version") or ""),
        "version_number": None,
        "certificate_id": None,
        "definition_source": "instance",
        "graph": graph,
        "steps": steps,
        "trigger_type": trigger_type,
        "trigger_config": trigger_config,
        "workflow_version": int(instance.get("workflow_version") or 1),
        "policy_version": "v1",
        "deployment_generation": 0,
        "graph_hash": _graph_hash(graph),
        "trigger_hash": trigger_fingerprint(trigger_type, trigger_config),
        "legacy_baseline": False,
        "draft_revision": 0,
        "policy_snapshot": snapshot.get("policy_snapshot") or {},
    }


async def resolve_definition(
    organization_id: UUID,
    workflow_id: UUID,
    *,
    source: str,
    workspace_id: UUID | None = None,
    require_active: bool = False,
    instance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if source not in DEFINITION_SOURCES:
        raise PublishedDefinitionError(
            "definition_source_invalid", f"definition_source inválido: {source}", status_code=400
        )
    if source == "published":
        return await load_published_definition(
            organization_id,
            workflow_id,
            workspace_id=workspace_id,
            require_active=require_active,
        )
    if source == "draft":
        return await load_draft_definition(
            organization_id, workflow_id, workspace_id=workspace_id
        )
    if instance is None:
        raise PublishedDefinitionError(
            "instance_required", "definition_source=instance requiere la instancia."
        )
    return await load_instance_definition(instance)


__all__ = [
    "DEFINITION_SOURCES",
    "PublishedDefinitionError",
    "load_draft_definition",
    "load_instance_definition",
    "load_published_definition",
    "resolve_definition",
    "trigger_fingerprint",
]
