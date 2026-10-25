# =============================================================================
# Workflow Versions — snapshot inmutable del workflow (grafo + trigger)
# =============================================================================
# El hook y /run siempre ejecutan la fila viva `workflows`. Una versión es una
# copia congelada de lo publicable: nombre, trigger, steps y grafo. Restaurar
# escribe el snapshot de vuelta en la fila viva (rollback). El secret del
# webhook NUNCA entra al snapshot (`get_workflow` lo filtra).
# =============================================================================
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

VERSION_STATUSES = ("draft", "ready", "production", "archived")

# Transiciones permitidas del ciclo de vida de una versión de workflow.
_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"ready", "archived"},
    "ready": {"production", "archived"},
    "production": {"ready", "archived"},
    "archived": set(),
}

# Campos de `get_workflow` que forman el snapshot ejecutable.
_SNAPSHOT_KEYS = (
    "name",
    "description",
    "trigger_type",
    "trigger_config",
    "steps",
    "graph",
    "workflow_version",
    "graph_source",
    "editor_state",
)

_TABLE = """
CREATE TABLE IF NOT EXISTS workflow_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    workflow_id UUID NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'ready', 'production', 'archived')),
    config_snapshot JSONB NOT NULL DEFAULT '{}',
    notes TEXT,
    created_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (workflow_id, version_number)
)
"""

_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_workflow_versions_wf "
    "ON workflow_versions(workflow_id, version_number DESC)"
)


def validate_transition(current: str, target: str) -> bool:
    return target in _TRANSITIONS.get(current, set())


def snapshot_workflow(workflow: dict) -> dict:
    """Congela la configuración publicable de un workflow.

    `workflow` es la salida de `get_workflow` (trigger_config ya viene sin
    `hook_secret_hash`).
    """
    snapshot = {key: workflow.get(key) for key in _SNAPSHOT_KEYS}
    snapshot["schema_version"] = 1
    return json.loads(json.dumps(snapshot, default=str))


async def ensure_workflow_versions_table() -> None:
    """Crea la tabla si la base es anterior a la migración 109 (fail-silent)."""
    session = await get_async_session()
    try:
        await session.execute(text(_TABLE))
        await session.execute(text(_INDEX))
        await session.commit()
    except Exception:  # noqa: BLE001
        await session.rollback()
        logger.warning("Failed to ensure workflow_versions table")
    finally:
        await session.close()


def _version_response(row) -> dict:
    return {
        "id": str(row.id),
        "workflow_id": str(row.workflow_id),
        "version_number": int(row.version_number),
        "status": row.status,
        "config_snapshot": row.config_snapshot or {},
        "notes": row.notes,
        "created_by": str(row.created_by) if row.created_by else None,
        "created_at": row.created_at.isoformat(),
        "workspace_id": (
            str(getattr(row, "workspace_id", None))
            if getattr(row, "workspace_id", None)
            else None
        ),
        "graph_hash": str(getattr(row, "graph_hash", "") or ""),
        "trigger_hash": str(getattr(row, "trigger_hash", "") or ""),
        "certificate_id": (
            str(getattr(row, "certificate_id", None))
            if getattr(row, "certificate_id", None)
            else None
        ),
        "legacy_baseline": bool(getattr(row, "legacy_baseline", False)),
        "published_at": (
            row.published_at.isoformat()
            if getattr(row, "published_at", None)
            else None
        ),
    }


async def list_versions(organization_id: UUID, workflow_id: UUID) -> dict:
    await ensure_workflow_versions_table()
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT id, workflow_id, version_number, status, config_snapshot, "
                    "notes, created_by, created_at, workspace_id, graph_hash, trigger_hash, "
                    "certificate_id, legacy_baseline, published_at FROM workflow_versions "
                    "WHERE organization_id = :oid AND workflow_id = :wid "
                    "ORDER BY version_number DESC"
                ),
                {"oid": organization_id, "wid": workflow_id},
            )
        ).fetchall()
    finally:
        await session.close()
    versions = [_version_response(r) for r in rows]
    return {"versions": versions, "count": len(versions)}


async def _demote_other_productions(
    session, organization_id: UUID, workflow_id: UUID, keep_id: UUID
) -> None:
    """Solo una versión en production por workflow: el resto vuelve a ready."""
    await session.execute(
        text(
            "UPDATE workflow_versions SET status = 'ready' "
            "WHERE organization_id = :oid AND workflow_id = :wid "
            "AND status = 'production' AND id <> :vid"
        ),
        {"oid": organization_id, "wid": workflow_id, "vid": keep_id},
    )


async def _lock_live_workflow(session, organization_id: UUID, workflow_id: UUID) -> dict | None:
    row = (
        await session.execute(
            text(
                "SELECT id, organization_id, workspace_id, name, description, "
                "trigger_type, trigger_config, steps, graph, workflow_version, "
                "graph_source, editor_state, status, solution_id FROM workflows "
                "WHERE id = :wid AND organization_id = :oid FOR UPDATE"
            ),
            {"wid": workflow_id, "oid": organization_id},
        )
    ).fetchone()
    if row is None:
        return None
    tcfg = dict(row.trigger_config or {})
    tcfg.pop("hook_secret_hash", None)
    return {
        "id": row.id,
        "organization_id": str(row.organization_id),
        "workspace_id": str(row.workspace_id) if row.workspace_id else None,
        "name": row.name,
        "description": row.description,
        "trigger_type": row.trigger_type,
        "trigger_config": tcfg,
        "steps": row.steps,
        "graph": row.graph,
        "workflow_version": int(row.workflow_version or 1),
        "graph_source": row.graph_source,
        "editor_state": row.editor_state or {},
        "status": row.status,
        "solution_id": str(row.solution_id) if getattr(row, "solution_id", None) else None,
    }


def _snapshot_hashes(snapshot: dict) -> tuple[str, str]:
    from src.platform.workflows.definition import trigger_fingerprint
    from src.platform.workflows.release_policy import graph_fingerprint

    graph = snapshot.get("graph")
    if not graph:
        from src.platform.workflows.ir import LegacyWorkflowAdapter

        graph = LegacyWorkflowAdapter.steps_to_graph(
            snapshot.get("steps") or [],
            snapshot.get("trigger_type") or "webhook",
            snapshot.get("trigger_config") or {},
        ).to_dict()
    return (
        graph_fingerprint(graph),
        trigger_fingerprint(snapshot.get("trigger_type"), snapshot.get("trigger_config")),
    )


async def create_version(
    organization_id: UUID,
    workflow_id: UUID,
    *,
    notes: str | None = None,
    created_by: UUID | None = None,
    status: str = "draft",
) -> dict | None:
    """Snapshot del estado vivo del workflow. None = workflow inexistente."""
    if status not in VERSION_STATUSES:
        raise ValueError(f"status debe ser uno de {VERSION_STATUSES}")
    await ensure_workflow_versions_table()
    session = await get_async_session()
    try:
        workflow = await _lock_live_workflow(session, organization_id, workflow_id)
        if workflow is None:
            await session.rollback()
            return None
        snapshot = snapshot_workflow(workflow)
        graph_hash, trigger_hash = _snapshot_hashes(snapshot)
        row = (
            await session.execute(
                text(
                    "INSERT INTO workflow_versions (organization_id, workflow_id, "
                    "workspace_id, version_number, status, config_snapshot, notes, "
                    "created_by, graph_hash, trigger_hash, policy_version) "
                    "SELECT :oid, :wid, CAST(:ws AS uuid), COALESCE(MAX(version_number), 0) + 1, "
                    "CASE WHEN :status = 'production' THEN 'ready' ELSE :status END, "
                    "CAST(:snapshot AS jsonb), :notes, :by, :ghash, :thash, 'v1' "
                    "FROM workflow_versions WHERE workflow_id = :wid "
                    "RETURNING id, workflow_id, version_number, status, "
                    "config_snapshot, notes, created_by, created_at, workspace_id, "
                    "graph_hash, trigger_hash, certificate_id, legacy_baseline, published_at"
                ),
                {
                    "oid": organization_id,
                    "wid": workflow_id,
                    "ws": workflow.get("workspace_id"),
                    "status": status,
                    "snapshot": json.dumps(snapshot),
                    "notes": notes,
                    "by": created_by,
                    "ghash": graph_hash,
                    "thash": trigger_hash,
                },
            )
        ).fetchone()
        if status == "production":
            await _demote_other_productions(
                session, organization_id, workflow_id, row.id
            )
            row = (
                await session.execute(
                    text(
                        "UPDATE workflow_versions SET status = 'production' "
                        "WHERE id = :vid RETURNING id, workflow_id, version_number, status, "
                        "config_snapshot, notes, created_by, created_at, workspace_id, "
                        "graph_hash, trigger_hash, certificate_id, legacy_baseline, published_at"
                    ),
                    {"vid": row.id},
                )
            ).fetchone()
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
    return _version_response(row)


async def promote_version(
    organization_id: UUID,
    workflow_id: UUID,
    version_id: UUID,
    status: str,
    *,
    workspace_id: UUID | None = None,
    permissions: frozenset[str] | None = None,
) -> dict | None:
    """Mueve una versión en el ciclo de vida. None = versión inexistente."""
    if status not in VERSION_STATUSES:
        raise ValueError(f"status debe ser uno de {VERSION_STATUSES}")
    await ensure_workflow_versions_table()
    session = await get_async_session()
    try:
        workflow = (
            await session.execute(
                text(
                    "SELECT id, organization_id, workspace_id FROM workflows "
                    "WHERE id = :wid AND organization_id = :oid FOR UPDATE"
                ),
                {"wid": workflow_id, "oid": organization_id},
            )
        ).fetchone()
        if workflow is None:
            await session.rollback()
            return None
        current = (
            await session.execute(
                text(
                    "SELECT id, status, config_snapshot, certificate_id, workspace_id, "
                    "legacy_baseline FROM workflow_versions WHERE id = :vid "
                    "AND workflow_id = :wid AND organization_id = :oid FOR UPDATE"
                ),
                {"vid": version_id, "wid": workflow_id, "oid": organization_id},
            )
        ).fetchone()
        if current is None:
            await session.rollback()
            return None
        if not validate_transition(current.status, status):
            raise ValueError(
                f"transición inválida: {current.status} → {status}"
            )
        snapshot = current.config_snapshot if isinstance(current.config_snapshot, dict) else {}
        graph = snapshot.get("graph")
        if not graph:
            from src.platform.workflows.ir import LegacyWorkflowAdapter

            graph = LegacyWorkflowAdapter.steps_to_graph(
                snapshot.get("steps") or [],
                snapshot.get("trigger_type") or "webhook",
                snapshot.get("trigger_config") or {},
            ).to_dict()
        if status == "production":
            from src.platform.workflows.release_policy import (
                ReleaseDenied,
                ensure_release_tables,
                target_graph_decision,
            )

            await ensure_release_tables()
            decision = await target_graph_decision(
                organization_id,
                workflow_id,
                graph,
                action="promote",
                workspace_id=workspace_id,
                permissions=permissions,
                trigger_type=snapshot.get("trigger_type"),
                trigger_config=snapshot.get("trigger_config") or {},
            )
            if not decision.allowed:
                raise ReleaseDenied(decision.to_dict())
        if status == "production":
            await _demote_other_productions(
                session, organization_id, workflow_id, version_id
            )
        row = (
            await session.execute(
                text(
                    "UPDATE workflow_versions SET status = :status WHERE id = :vid "
                    "RETURNING id, workflow_id, version_number, status, "
                    "config_snapshot, notes, created_by, created_at, workspace_id, "
                    "graph_hash, trigger_hash, certificate_id, legacy_baseline, published_at"
                ),
                {"status": status, "vid": version_id},
            )
        ).fetchone()
        if status == "production":
            graph_hash, _trigger_hash = _snapshot_hashes(snapshot)
            generation = (
                await session.execute(
                    text(
                        "UPDATE workflows SET published_version_id = :vid, "
                        "published_certificate_id = :cert, published_graph_hash = :ghash, "
                        "published_at = NOW(), deployment_generation = deployment_generation + 1 "
                        "WHERE id = :wid AND organization_id = :oid "
                        "RETURNING deployment_generation"
                    ),
                    {
                        "vid": version_id,
                        "cert": current.certificate_id,
                        "ghash": graph_hash,
                        "wid": workflow_id,
                        "oid": organization_id,
                    },
                )
            ).fetchone()
            await session.execute(
                text(
                    "INSERT INTO workflow_deployments "
                    "(organization_id, workspace_id, workflow_id, version_id, certificate_id, "
                    "graph_hash, deployment_generation, action, actor_type, reason) "
                    "VALUES (:oid, :ws, :wid, :vid, :cert, :ghash, :dgen, 'promote', "
                    "'user', 'promote_version')"
                ),
                {
                    "oid": organization_id,
                    "ws": workflow.workspace_id,
                    "wid": workflow_id,
                    "vid": version_id,
                    "cert": current.certificate_id,
                    "ghash": graph_hash,
                    "dgen": int(generation.deployment_generation) if generation else 0,
                },
            )
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
    return _version_response(row)


async def restore_version(
    organization_id: UUID,
    workflow_id: UUID,
    version_id: UUID,
    *,
    workspace_id: UUID | None = None,
    permissions: frozenset[str] | None = None,
) -> dict | None:
    """Rollback atómico. En activo cambia el puntero; nunca deja estado mixto."""
    await ensure_workflow_versions_table()
    session = await get_async_session()
    try:
        live = (
            await session.execute(
                text(
                    "SELECT id, organization_id, workspace_id, status, trigger_type, "
                    "trigger_config FROM workflows "
                    "WHERE id = :wid AND organization_id = :oid FOR UPDATE"
                ),
                {"wid": workflow_id, "oid": organization_id},
            )
        ).fetchone()
        if live is None:
            await session.rollback()
            return None
        row = (
            await session.execute(
                text(
                    "SELECT version_number, config_snapshot, certificate_id, status, "
                    "workspace_id, legacy_baseline FROM workflow_versions "
                    "WHERE id = :vid AND workflow_id = :wid AND organization_id = :oid "
                    "FOR UPDATE"
                ),
                {"vid": version_id, "wid": workflow_id, "oid": organization_id},
            )
        ).fetchone()
        if row is None:
            await session.rollback()
            return None
        snapshot = row.config_snapshot if isinstance(row.config_snapshot, dict) else {}
        if str(live.status) == "active":
            from src.platform.workflows.release_policy import (
                ReleaseDenied,
                ensure_release_tables,
                target_graph_decision,
            )

            await ensure_release_tables()
            target_graph = snapshot.get("graph")
            if not target_graph:
                from src.platform.workflows.ir import LegacyWorkflowAdapter

                target_graph = LegacyWorkflowAdapter.steps_to_graph(
                    snapshot.get("steps") or [],
                    snapshot.get("trigger_type") or "webhook",
                    snapshot.get("trigger_config") or {},
                ).to_dict()
            decision = await target_graph_decision(
                organization_id,
                workflow_id,
                target_graph,
                action="restore",
                workspace_id=workspace_id,
                permissions=permissions,
                trigger_type=snapshot.get("trigger_type"),
                trigger_config=snapshot.get("trigger_config") or {},
            )
            if not decision.allowed:
                raise ReleaseDenied(decision.to_dict())

            graph_hash, _trigger_hash = _snapshot_hashes(snapshot)
            restore_trigger_config = dict(snapshot.get("trigger_config") or {})
            live_trigger_config = dict(live.trigger_config or {})
            if live_trigger_config.get("hook_secret_hash"):
                restore_trigger_config["hook_secret_hash"] = live_trigger_config[
                    "hook_secret_hash"
                ]
            await _demote_other_productions(
                session, organization_id, workflow_id, version_id
            )
            await session.execute(
                text(
                    "UPDATE workflow_versions SET status = 'production', "
                    "published_at = COALESCE(published_at, NOW()) WHERE id = :vid"
                ),
                {"vid": version_id},
            )
            updated_row = (
                await session.execute(
                    text(
                        "UPDATE workflows SET name = :name, description = :description, "
                        "trigger_type = :ttype, trigger_config = CAST(:tcfg AS jsonb), "
                        "steps = CAST(:steps AS jsonb), editor_state = CAST(:estate AS jsonb), "
                        "graph = CAST(:graph AS jsonb), graph_source = :gsource, "
                        "workflow_version = :wver, status = 'active', "
                        "published_version_id = :vid, published_certificate_id = :cert, "
                        "published_graph_hash = :ghash, published_at = NOW(), "
                        "deployment_generation = deployment_generation + 1, "
                        "draft_revision = draft_revision + 1, updated_at = NOW() "
                        "WHERE id = :wid AND organization_id = :oid "
                        "RETURNING deployment_generation"
                    ),
                    {
                        "name": snapshot.get("name"),
                        "description": snapshot.get("description"),
                        "ttype": snapshot.get("trigger_type") or "webhook",
                        "tcfg": json.dumps(restore_trigger_config),
                        "steps": json.dumps(snapshot.get("steps") or []),
                        "estate": json.dumps(snapshot.get("editor_state") or {}),
                        "graph": json.dumps(snapshot.get("graph") or {}),
                        "gsource": snapshot.get("graph_source") or "graph",
                        "wver": int(snapshot.get("workflow_version") or 2),
                        "vid": version_id,
                        "cert": row.certificate_id,
                        "ghash": graph_hash,
                        "wid": workflow_id,
                        "oid": organization_id,
                    },
                )
            ).fetchone()
            await session.execute(
                text(
                    "INSERT INTO workflow_deployments "
                    "(organization_id, workspace_id, workflow_id, version_id, certificate_id, "
                    "graph_hash, deployment_generation, action, actor_type, reason) "
                    "VALUES (:oid, :ws, :wid, :vid, :cert, :ghash, :dgen, 'restore', "
                    "'user', 'restore_version')"
                ),
                {
                    "oid": organization_id,
                    "ws": live.workspace_id,
                    "wid": workflow_id,
                    "vid": version_id,
                    "cert": row.certificate_id,
                    "ghash": graph_hash,
                    "dgen": int(updated_row.deployment_generation) if updated_row else 0,
                },
            )
            await session.commit()
            return {
                "restored": True,
                "workflow_id": str(workflow_id),
                "version_id": str(version_id),
                "version_number": int(row.version_number),
                "deployment_generation": (
                    int(updated_row.deployment_generation) if updated_row else 0
                ),
            }
        await session.rollback()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()

    # Workflow no activo: se conserva el comportamiento de copia a borrador.
    from src.platform.workflows.engine import update_workflow

    legacy = str(snapshot.get("graph_source") or "graph") == "legacy"
    updated = await update_workflow(
        organization_id,
        workflow_id,
        snapshot.get("name"),
        snapshot.get("description"),
        snapshot.get("trigger_config") or {},
        snapshot.get("steps") or [],
        snapshot.get("editor_state") or {},
        graph=None if legacy else (snapshot.get("graph") or None),
        workflow_version=snapshot.get("workflow_version"),
        trigger_type=snapshot.get("trigger_type"),
    )
    if updated is None:
        return None
    return {
        "restored": True,
        "workflow_id": str(workflow_id),
        "version_id": str(version_id),
        "version_number": int(row.version_number),
    }


async def _architect_publication_problems(
    organization_id: UUID,
    workflow_id: UUID,
    *,
    permissions: frozenset[str] | None = None,
) -> list[str]:
    """Re-valida un workflow nacido del Architect antes de publicarlo.

    El estado guardado es la señal de revisión humana (fallback/clarificaciones);
    las dependencias se recalculan SIEMPRE contra las capacidades actuales.
    """
    from src.platform.workflows.ir import (
        LegacyWorkflowAdapter,
        WorkflowGraph,
        WorkflowGraphError,
        validate_graph,
    )
    from src.platform.workflows.plan_compiler import load_capabilities
    from src.platform.workflows.readiness import readiness_checks

    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT graph, steps, trigger_type, trigger_config, workspace_id "
                    "FROM workflows WHERE id = :wid AND organization_id = :oid"
                ),
                {"wid": str(workflow_id), "oid": str(organization_id)},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None:
        return ["workflow inexistente"]

    graph = dict(row.graph) if row.graph else None
    if graph is None:
        graph = LegacyWorkflowAdapter.steps_to_graph(
            row.steps or [],
            str(row.trigger_type or "webhook"),
            dict(row.trigger_config or {}),
        ).to_dict()
    metadata = graph.get("metadata") or {}
    if not metadata.get("architect"):
        return []  # workflows manuales/legacy: comportamiento existente

    problems: list[str] = []
    workspace_id = UUID(str(row.workspace_id)) if row.workspace_id else None
    state = str(metadata.get("architect_state") or "")
    if state == "BLOCKED":
        problems.append("el diseño quedó bloqueado; corrígelo antes de publicar")
    try:
        validate_graph(WorkflowGraph.from_dict(graph))
    except (WorkflowGraphError, KeyError, TypeError, ValueError) as exc:
        problems.append(f"grafo inválido: {str(exc)[:160]}")

    for node in graph.get("nodes") or []:
        if str(node.get("type")) == "llm" and not str(
            (node.get("config") or {}).get("agent_id") or ""
        ).strip():
            problems.append("hay un paso de IA sin agente asignado")
            break

    try:
        from src.platform.workflows.capability_registry import build_capability_snapshot

        snapshot = await build_capability_snapshot(
            organization_id, workspace_id, permissions=None, force_refresh=True
        )
        index = snapshot.index()
        for node in graph.get("nodes") or []:
            node_type = str(node.get("type"))
            config = node.get("config") or {}
            ref = ""
            if node_type == "capability_call":
                ref = str(config.get("capability") or "")
            elif node_type == "marketplace_action":
                ref = str(config.get("action_id") or "")
            if not ref:
                continue
            descriptor = index.get(ref)
            problems.extend(
                _capability_publication_problems(
                    ref, config, descriptor, permissions
                )
            )
    except Exception as exc:  # noqa: BLE001 — sin snapshot, el readiness base sigue
        logger.warning("architect publish capability check failed", error=str(exc)[:160])

    capabilities = await load_capabilities(organization_id, workspace_id)
    for check in readiness_checks(graph, capabilities):
        if check.get("status") == "error":
            problems.append(str(check.get("message") or check.get("key")))
    return problems


def _capability_publication_problems(
    ref: str,
    config: dict[str, Any],
    descriptor: Any,
    permissions: frozenset[str] | None,
) -> list[str]:
    """Chequeo puro de contrato/permisos de una capacidad al publicar."""
    if descriptor is None:
        return [f"la capacidad {ref} ya no existe"]
    if not descriptor.availability.executable:
        reasons = "; ".join(descriptor.availability.reasons[:2])
        return [
            f"la capacidad {ref} no está ejecutable ({descriptor.availability.status}"
            + (f": {reasons}" if reasons else "")
            + ")"
        ]
    problems: list[str] = []
    contract_version = config.get("contract_version")
    if contract_version is not None and int(contract_version) != int(descriptor.version):
        problems.append(
            f"la capacidad {ref} cambió de contrato "
            f"(v{contract_version} → v{descriptor.version}); recompila el flujo"
        )
    contract_hash = str(config.get("contract_hash") or "")
    if contract_hash and descriptor.contract_hash and contract_hash != descriptor.contract_hash:
        problems.append(f"el contrato de {ref} cambió desde que se compiló el flujo")
    if permissions is not None:
        missing = [
            permission
            for permission in (descriptor.required_permissions or [])
            if permission not in permissions and "admin:*" not in permissions
        ]
        if missing:
            problems.append(
                f"el rol que publica no puede ejecutar {ref}: "
                + ", ".join(missing[:3])
            )
    return problems


async def publish_workflow(
    organization_id: UUID,
    workflow_id: UUID,
    *,
    notes: str | None = None,
    created_by: UUID | None = None,
    confirm_architect_draft: bool = False,
    permissions: frozenset[str] | None = None,
    workspace_id: UUID | None = None,
) -> dict | None:
    """Publicar = snapshot en production + workflow activo (webhook/schedule).

    Un solo gate de release decide con el certificado persistido. La fila del
    workflow se bloquea (FOR UPDATE) durante el chequeo y la escritura para
    evitar TOCTOU entre edición y publicación.
    """
    from src.platform.workflows.packages import publication_blockers
    from src.platform.workflows.release_policy import (
        ReleaseDenied,
        ensure_release_tables,
        evaluate_release,
    )

    await ensure_release_tables()
    lock_session = await get_async_session()
    try:
        workflow = await _lock_live_workflow(
            lock_session, organization_id, workflow_id
        )
        if workflow is None:
            await lock_session.rollback()
            return None
        blockers = await publication_blockers(organization_id, workflow_id)
        if blockers:
            await lock_session.rollback()
            raise ValueError(
                "requisitos sin resolver: "
                + "; ".join(f"{b['ref']} ({b['status']})" for b in blockers[:5])
            )
        architect_metadata = ((workflow.get("graph") or {}).get("metadata") or {})
        if architect_metadata.get("architect"):
            state = str(architect_metadata.get("architect_state") or "")
            architect_source = str(architect_metadata.get("architect_source") or "")
            if architect_source == "heuristics" and not confirm_architect_draft:
                await lock_session.rollback()
                raise ValueError(
                    "el borrador se generó por reglas (el modelo no estuvo disponible); "
                    "revísalo y confirma la publicación con confirm_architect_draft=true"
                )
            if state and state != "DRAFT_READY" and not confirm_architect_draft:
                await lock_session.rollback()
                raise ValueError(
                    f"el borrador quedó en {state}; revísalo y confirma la publicación "
                    "con confirm_architect_draft=true"
                )
            problems = await _architect_publication_problems(
                organization_id, workflow_id, permissions=permissions
            )
            if problems:
                await lock_session.rollback()
                raise ValueError("requisitos sin resolver: " + "; ".join(problems[:5]))

        snapshot = snapshot_workflow(workflow)
        decision = await evaluate_release(
            organization_id,
            workflow_id,
            action="publish",
            workspace_id=workspace_id,
            permissions=permissions,
            graph_override=snapshot.get("graph"),
        )
        if not decision.allowed:
            await lock_session.rollback()
            raise ReleaseDenied(decision.to_dict())

        graph_hash, trigger_hash = _snapshot_hashes(snapshot)
        certificate_id = (decision.certificate or {}).get("id")
        row = (
            await lock_session.execute(
                text(
                    "INSERT INTO workflow_versions (organization_id, workflow_id, "
                    "workspace_id, version_number, status, config_snapshot, notes, created_by, "
                    "certificate_id, graph_hash, trigger_hash, policy_version, "
                    "published_at, published_by, legacy_baseline) "
                    "SELECT :oid, :wid, CAST(:ws AS uuid), COALESCE(MAX(version_number), 0) + 1, "
                    "'ready', CAST(:snapshot AS jsonb), :notes, :by, :cert, "
                    ":ghash, :thash, 'v1', NOW(), :by, false "
                    "FROM workflow_versions WHERE workflow_id = :wid "
                    "RETURNING id, workflow_id, version_number, status, "
                    "config_snapshot, notes, created_by, created_at, workspace_id, "
                    "graph_hash, trigger_hash, certificate_id, legacy_baseline, published_at"
                ),
                {
                    "oid": organization_id,
                    "wid": workflow_id,
                    "ws": workflow.get("workspace_id"),
                    "snapshot": json.dumps(snapshot),
                    "notes": notes,
                    "by": created_by,
                    "cert": certificate_id,
                    "ghash": graph_hash,
                    "thash": trigger_hash,
                },
            )
        ).fetchone()
        await _demote_other_productions(
            lock_session, organization_id, workflow_id, row.id
        )
        row = (
            await lock_session.execute(
                text(
                    "UPDATE workflow_versions SET status = 'production' WHERE id = :vid "
                    "RETURNING id, workflow_id, version_number, status, "
                    "config_snapshot, notes, created_by, created_at, workspace_id, "
                    "graph_hash, trigger_hash, certificate_id, legacy_baseline, published_at"
                ),
                {"vid": row.id},
            )
        ).fetchone()
        if not workflow.get("solution_id"):
            from src.platform.workflows.effective_policy import _scope_from_graph

            await lock_session.execute(
                text(
                    "UPDATE workflows SET capability_scope = CAST(:scope AS jsonb), "
                    "capability_scope_source = 'publish' WHERE id = :wid "
                    "AND organization_id = :oid"
                ),
                {
                    "scope": json.dumps(sorted(_scope_from_graph(snapshot.get("graph")))),
                    "wid": workflow_id,
                    "oid": organization_id,
                },
            )
        generation = (
            await lock_session.execute(
                text(
                    "UPDATE workflows SET status = 'active', "
                    "published_version_id = :vid, published_certificate_id = :cert, "
                    "published_graph_hash = :ghash, published_at = NOW(), "
                    "published_by = :by, deployment_generation = deployment_generation + 1, "
                    "updated_at = NOW() "
                    "WHERE id = :wid AND organization_id = :oid "
                    "RETURNING deployment_generation"
                ),
                {
                    "vid": row.id,
                    "cert": certificate_id,
                    "ghash": graph_hash,
                    "by": created_by,
                    "wid": workflow_id,
                    "oid": organization_id,
                },
            )
        ).fetchone()
        deployment_generation = int(generation.deployment_generation) if generation else 0
        await lock_session.execute(
            text(
                "INSERT INTO workflow_deployments "
                "(organization_id, workspace_id, workflow_id, version_id, certificate_id, "
                "graph_hash, deployment_generation, action, actor_id, actor_type, reason) "
                "VALUES (:oid, :ws, :wid, :vid, :cert, :ghash, :dgen, 'publish', "
                ":by, 'user', :reason)"
            ),
            {
                "oid": organization_id,
                "ws": workflow.get("workspace_id"),
                "wid": workflow_id,
                "vid": row.id,
                "cert": certificate_id,
                "ghash": graph_hash,
                "dgen": deployment_generation,
                "by": created_by,
                "reason": notes,
            },
        )
        await lock_session.commit()
        logger.info(
            "workflow.published",
            workflow_id=str(workflow_id),
            organization_id=str(organization_id),
            workspace_id=workflow.get("workspace_id"),
            version_id=str(row.id),
            version_number=int(row.version_number),
            certificate_id=str(certificate_id) if certificate_id else None,
            graph_hash=graph_hash,
            deployment_generation=deployment_generation,
            legacy_baseline=False,
        )
    except Exception:
        await lock_session.rollback()
        raise
    finally:
        await lock_session.close()
    return {
        "workflow_id": str(workflow_id),
        "status": "active",
        "published_version_id": str(row.id),
        "deployment_generation": deployment_generation,
        "version": _version_response(row),
        "release": decision.to_dict(),
    }
