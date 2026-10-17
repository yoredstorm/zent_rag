# =============================================================================
# Workflow Packages — formato portable versionado (zent.workflow.package/v1).
#
# Un package contiene el grafo, dependencias, capacidades requeridas, eventos,
# parámetros, permisos y metadata — NUNCA secretos, credenciales, connection
# strings ni IDs de tenant/workspace.
#
# Import en dos fases:
#   inspect → valida todo y produce readiness report (no persiste);
#   import  → re-valida y crea SOLO draft (publicar exige requisitos resueltos).
# =============================================================================
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

SCHEMA_ID = "zent.workflow.package/v1"

#: Estados del readiness report (workflow portability).
STATUSES: tuple[str, ...] = (
    "RESOLVED",
    "OPTIONAL_MISSING",
    "NEEDS_CONFIGURATION",
    "NEEDS_CREDENTIALS",
    "DISABLED",
    "MISSING",
    "VERSION_MISMATCH",
    "PERMISSION_DENIED",
    "AMBIGUOUS",
    "UNSAFE",
)

_BLOCKING = {"MISSING", "VERSION_MISMATCH", "PERMISSION_DENIED", "UNSAFE"}

_FORBIDDEN_KEYS = {
    "password",
    "passwd",
    "api_key",
    "apikey",
    "secret",
    "client_secret",
    "token",
    "access_token",
    "refresh_token",
    "private_key",
    "connection_string",
    "dsn",
    "credentials",
    "authorization",
}
_TENANT_KEYS = {"organization_id", "workspace_id", "tenant_id", "install_id", "credential_ref", "created_by"}
_UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_DSN_RE = re.compile(r"postgres(?:ql)?://|mysql://|mongodb(\+srv)?://|redis://", re.I)


# ---------------------------------------------------------------------------
# Seguridad (denylist dura)
# ---------------------------------------------------------------------------
def scan_security(value: Any, *, path: str = "") -> list[str]:
    """Problemas de seguridad: claves sensibles, DSNs, IDs de tenant/UUIDs."""
    issues: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            key_l = str(key).lower()
            child_path = f"{path}.{key}" if path else str(key)
            if key_l in _FORBIDDEN_KEYS:
                issues.append(f"clave sensible prohibida: {child_path}")
            if key_l in _TENANT_KEYS and child is not None:
                issues.append(f"referencia de tenant prohibida: {child_path}")
            issues.extend(scan_security(child, path=child_path))
    elif isinstance(value, list):
        for idx, child in enumerate(value[:200]):
            issues.extend(scan_security(child, path=f"{path}[{idx}]"))
    elif isinstance(value, str):
        if _DSN_RE.search(value):
            issues.append(f"connection string detectada en {path or '<root>'}")
    return issues


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------
def _extract_requirements(graph: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    capabilities: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    for node in graph.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        ntype = str(node.get("type") or "")
        config = node.get("config") or {}
        if ntype == "capability_call":
            ref = str(config.get("capability") or "").strip()
            if ref:
                capabilities.append({"ref": ref, "requirement": "required", "node_id": str(node.get("id"))})
        elif ntype == "marketplace_action":
            action_id = str(config.get("action_id") or "").strip()
            if action_id:
                actions.append({"ref": action_id, "requirement": "required", "node_id": str(node.get("id"))})
        elif ntype == "trigger_event":
            event_type = str(config.get("event_type") or "").strip()
            if event_type:
                events.append({"ref": event_type, "requirement": "required", "node_id": str(node.get("id"))})
        elif ntype == "wait_event":
            # Un WAIT también declara una dependencia de evento: el paquete debe
            # decir que el proceso espera `payment.succeeded`, no solo el trigger.
            event_type = str(config.get("event_type") or "").strip()
            if not event_type:
                from src.platform.workflows.instances import WAIT_PRESET_EVENTS

                preset = str(config.get("preset") or "")
                event_type = str(WAIT_PRESET_EVENTS.get(preset, ""))
                if preset == "webhook" and event_type == "webhook":
                    event_type = f"webhook.{node.get('id')}"
            if event_type and event_type not in ("signal", "workflow.wait.timeout"):
                events.append({"ref": event_type, "requirement": "required", "node_id": str(node.get("id"))})
    return {"capabilities": capabilities, "actions": actions, "events": events}


def _node_permissions(graph: dict[str, Any]) -> list[str]:
    perms: set[str] = set()
    try:
        from src.platform.workflows.nodes import capability_permission, registry
    except Exception:  # noqa: BLE001
        return []
    for node in graph.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        node_def = registry.get(str(node.get("type") or ""))
        if node_def is None:
            continue
        for cap in node_def.capabilities:
            perm = capability_permission(cap)
            if perm:
                perms.add(perm)
    return sorted(perms)


def build_package(workflow_row: Any, graph: dict[str, Any]) -> dict[str, Any]:
    """Construye el paquete portable (sin checksum; se añade al final)."""
    reqs = _extract_requirements(graph)
    dependencies = [
        *[
            {"kind": "capability", "ref": c["ref"], "requirement": c["requirement"], "node_id": c.get("node_id")}
            for c in reqs["capabilities"]
        ],
        *[
            {"kind": "action", "ref": a["ref"], "requirement": a["requirement"], "node_id": a.get("node_id")}
            for a in reqs["actions"]
        ],
    ]
    package: dict[str, Any] = {
        "schema": SCHEMA_ID,
        "schema_version": 1,
        "package_version": "1.0.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "metadata": {
            "name": str(getattr(workflow_row, "name", "") or ""),
            "description": str(getattr(workflow_row, "description", "") or ""),
            "min_zent_version": None,
        },
        "workflow": {
            "graph": graph,
            "trigger_type": str(getattr(workflow_row, "trigger_type", "manual") or "manual"),
            "trigger_config": {
                k: v
                for k, v in dict(getattr(workflow_row, "trigger_config", {}) or {}).items()
                if k != "hook_secret_hash"  # nunca viaja el hash del secret inbound
            },
        },
        "dependencies": dependencies,
        "capabilities": [
            {"ref": c["ref"], "requirement": c["requirement"], "node_id": c.get("node_id")}
            for c in reqs["capabilities"]
        ],
        "events": [
            {"ref": e["ref"], "requirement": e["requirement"], "node_id": e.get("node_id")}
            for e in reqs["events"]
        ],
        "parameters": dict((graph.get("variables") or {})),
        "permissions": _node_permissions(graph),
        "tests": list((graph.get("metadata") or {}).get("tests") or []),
        "security": {"contains_secrets": False, "tenant_scoped": False},
    }
    return package


def package_checksum(package: dict[str, Any]) -> str:
    canonical = json.dumps(package, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def export_workflow_package(organization_id: UUID, workflow_id: UUID) -> dict | None:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT id, name, description, steps, graph, trigger_type, trigger_config, "
                    "workflow_version FROM workflows WHERE id = :wid AND organization_id = :oid"
                ),
                {"wid": str(workflow_id), "oid": str(organization_id)},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None:
        return None
    graph = dict(row.graph) if row.graph else None
    if graph is None:
        from src.platform.workflows.ir import LegacyWorkflowAdapter

        graph = LegacyWorkflowAdapter.steps_to_graph(
            row.steps or [], str(row.trigger_type or "webhook"), dict(row.trigger_config or {})
        ).to_dict()
    package = build_package(row, graph)
    issues = scan_security(package)
    package["security"] = {
        "contains_secrets": False,
        "tenant_scoped": False,
        "scan": "ok" if not issues else "issues",
    }
    package["checksum"] = package_checksum(package)
    return package


# ---------------------------------------------------------------------------
# Inspect (readiness report, sin persistir)
# ---------------------------------------------------------------------------
def _item(
    ref: str,
    kind: str,
    status: str,
    requirement: str = "required",
    message: str = "",
    hint: str | None = None,
    resolution: str | None = None,
    node_id: str | None = None,
) -> dict[str, Any]:
    return {
        "ref": ref,
        "kind": kind,
        "requirement": requirement,
        "status": status,
        "message": message,
        "hint": hint,
        "resolution": resolution,
        "node_id": node_id,
    }


def _version_tuple(value: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", str(value or ""))[:3]
    return tuple(int(p) for p in parts) if parts else (0,)


async def inspect_package(
    organization_id: UUID,
    package: dict[str, Any],
    *,
    workspace_id: UUID | None = None,
    permissions: frozenset[str] | None = None,
) -> dict[str, Any]:
    """Valida un package y produce el readiness report (sin persistir nada)."""
    from src.platform.marketplace.resolver import resolve_capability
    from src.platform.workflows.bindings import resolve_binding
    from src.platform.workflows.event_registry import is_registered

    items: list[dict[str, Any]] = []
    blockers = 0

    def add(item: dict[str, Any]) -> None:
        nonlocal blockers
        items.append(item)
        if item["status"] in _BLOCKING or (
            item["requirement"] == "required"
            and item["status"] in ("NEEDS_CONFIGURATION", "NEEDS_CREDENTIALS", "DISABLED", "AMBIGUOUS")
        ):
            blockers += 1

    # 1) schema / versión
    if str(package.get("schema") or "") != SCHEMA_ID:
        add(_item("schema", "package", "UNSAFE", message=f"schema no soportado: {package.get('schema')}"))
        return {"schema": SCHEMA_ID, "ready": False, "score": 0, "items": items, "blocking": blockers}
    min_version = (package.get("metadata") or {}).get("min_zent_version")
    zent_version = "0.0.0"
    try:
        from src.core.config import get_settings

        zent_version = str(getattr(get_settings(), "app_version", None) or "0.0.0")
    except Exception:  # noqa: BLE001
        pass
    if min_version and _version_tuple(min_version) > _version_tuple(zent_version):
        add(_item("min_zent_version", "version", "VERSION_MISMATCH", message=f"requiere Zent >= {min_version}"))

    # 2) seguridad
    security_issues = scan_security(
        {
            "workflow": package.get("workflow"),
            "parameters": package.get("parameters"),
            "tests": package.get("tests"),
        }
    )
    if security_issues:
        add(_item("security", "package", "UNSAFE", message="; ".join(security_issues[:5])))

    # 3) grafo
    graph = (package.get("workflow") or {}).get("graph")
    try:

        validate_graph_from_dict(graph)
    except Exception as exc:  # noqa: BLE001
        add(_item("graph", "package", "UNSAFE", message=f"grafo inválido: {str(exc)[:160]}"))
        return {
            "schema": SCHEMA_ID,
            "ready": False,
            "score": 0,
            "items": items,
            "blocking": blockers,
        }

    # 4) capacidades (binding del tenant o provider del marketplace)
    caps = package.get("capabilities")
    if not caps:
        caps = [
            dep
            for dep in (package.get("dependencies") or [])
            if isinstance(dep, dict) and str(dep.get("kind")) == "capability"
        ]
    for cap in caps:
        if not isinstance(cap, dict):
            continue
        ref = str(cap.get("ref") or "")
        requirement = str(cap.get("requirement") or "required")
        node_id = str(cap.get("node_id") or "") or None
        if not ref:
            continue
        binding = await resolve_binding(organization_id, ref, workspace_id)
        if binding is not None:
            add(_item(ref, "capability", "RESOLVED", requirement, "binding configurado", node_id=node_id))
            continue
        resolved = await resolve_capability(organization_id, ref, workspace_id=workspace_id)
        if not resolved.get("resolved"):
            status = "OPTIONAL_MISSING" if requirement == "optional" else "MISSING"
            add(
                _item(
                    ref,
                    "capability",
                    status,
                    requirement,
                    "sin provider publicado",
                    resolution="marketplace",
                    node_id=node_id,
                )
            )
        elif resolved.get("installed"):
            add(
                _item(
                    ref,
                    "capability",
                    "RESOLVED",
                    requirement,
                    f"provider {resolved.get('integration_slug')}",
                    node_id=node_id,
                )
            )
        elif not resolved.get("requires_installation", True):
            add(
                _item(
                    ref,
                    "capability",
                    "RESOLVED",
                    requirement,
                    f"proveedor incorporado {resolved.get('integration_slug')}",
                    node_id=node_id,
                )
            )
        else:
            add(
                _item(
                    ref,
                    "capability",
                    "NEEDS_CREDENTIALS",
                    requirement,
                    f"provider {resolved.get('provider_name')} disponible, falta instalar/conectar",
                    resolution="marketplace",
                    node_id=node_id,
                )
            )

    # 5) acciones de marketplace
    session = await get_async_session()
    try:
        for dep in package.get("dependencies") or []:
            if not isinstance(dep, dict) or str(dep.get("kind")) != "action":
                continue
            action_id = str(dep.get("ref") or "")
            requirement = str(dep.get("requirement") or "required")
            node_id = str(dep.get("node_id") or "") or None
            if not action_id:
                continue
            configured = (
                await session.execute(
                    text(
                        "SELECT 1 FROM installed_integrations i "
                        "JOIN integration_actions a ON a.integration_id = i.integration_id "
                        "WHERE i.organization_id = :oid AND a.action_id = :aid "
                        "AND i.status IN ('installed', 'connected') "
                        "AND (i.enabled_actions = '[]'::jsonb OR i.enabled_actions @> CAST(:act AS jsonb)) "
                        "LIMIT 1"
                    ),
                    {"oid": str(organization_id), "aid": action_id, "act": json.dumps([action_id])},
                )
            ).fetchone()
            if configured:
                add(_item(action_id, "action", "RESOLVED", requirement, "acción disponible", node_id=node_id))
                continue
            exists = (
                await session.execute(
                    text(
                        "SELECT 1 FROM integration_actions WHERE action_id = :aid "
                        "AND status <> 'END_OF_LIFE' LIMIT 1"
                    ),
                    {"aid": action_id},
                )
            ).fetchone()
            status = (
                "NEEDS_CREDENTIALS"
                if exists
                else ("OPTIONAL_MISSING" if requirement == "optional" else "MISSING")
            )
            add(
                _item(
                    action_id,
                    "action",
                    status,
                    requirement,
                    "instalar o habilitar la acción",
                    resolution="marketplace",
                    node_id=node_id,
                )
            )
    finally:
        await session.close()

    # 6) eventos
    for event in package.get("events") or []:
        if not isinstance(event, dict):
            continue
        event_type = str(event.get("ref") or "")
        requirement = str(event.get("requirement") or "required")
        node_id = str(event.get("node_id") or "") or None
        if not event_type:
            continue
        if is_registered(event_type):
            add(_item(event_type, "event", "RESOLVED", requirement, "evento registrado", node_id=node_id))
        elif event_type.startswith(("custom.", "webhook.", "signal.")):
            add(
                _item(
                    event_type,
                    "event",
                    "NEEDS_CONFIGURATION",
                    requirement,
                    "evento custom: configura su emisor (webhook o API de señales)",
                    node_id=node_id,
                )
            )
        else:
            add(_item(event_type, "event", "OPTIONAL_MISSING", requirement, "evento desconocido", node_id=node_id))

    # 7) permisos
    if permissions is not None:
        for perm in package.get("permissions") or []:
            if perm not in permissions:
                add(_item(str(perm), "permission", "PERMISSION_DENIED", message="tu rol no tiene este permiso"))

    total = len(items) or 1
    resolved = sum(1 for i in items if i["status"] == "RESOLVED")
    score = round(100 * resolved / total)
    return {
        "schema": SCHEMA_ID,
        "ready": blockers == 0,
        "score": score,
        "items": items,
        "blocking": blockers,
        "summary": {
            "total": len(items),
            "resolved": resolved,
            "pending": len(items) - resolved,
        },
    }


def validate_graph_from_dict(graph: Any) -> None:
    from src.platform.workflows.ir import WorkflowGraph, validate_graph

    if not isinstance(graph, dict):
        raise ValueError("package sin grafo")
    validate_graph(WorkflowGraph.from_dict(dict(graph)))


# ---------------------------------------------------------------------------
# Import (solo draft) + gate de publicación
# ---------------------------------------------------------------------------
async def import_workflow_package(
    organization_id: UUID,
    package: dict[str, Any],
    *,
    workspace_id: UUID | None = None,
    created_by: UUID | None = None,
    permissions: frozenset[str] | None = None,
) -> dict[str, Any]:
    """Importa SOLO draft: valida, exige requisitos críticos resueltos y crea
    el workflow en estado draft con el package adjunto."""
    report = await inspect_package(
        organization_id, package, workspace_id=workspace_id, permissions=permissions
    )
    if report["blocking"]:
        blockers = [i for i in report["items"] if i["status"] != "RESOLVED"]
        raise ValueError(
            "requisitos sin resolver: "
            + "; ".join(f"{b['ref']} ({b['status']})" for b in blockers[:5])
        )
    graph = (package.get("workflow") or {}).get("graph")
    validate_graph_from_dict(graph)
    metadata = package.get("metadata") or {}
    name = str(metadata.get("name") or "Workflow importado")[:150]
    trigger_type = str((package.get("workflow") or {}).get("trigger_type") or "manual")
    if trigger_type not in ("webhook", "schedule", "event", "manual"):
        trigger_type = "manual"
    trigger_config = {
        k: v
        for k, v in dict((package.get("workflow") or {}).get("trigger_config") or {}).items()
        if k != "hook_secret_hash"
    }
    from src.platform.workflows.engine import create_workflow

    created = await create_workflow(
        organization_id,
        name,
        trigger_type,
        trigger_config,
        [],
        str(metadata.get("description") or ""),
        created_by,
        {},
        workspace_id=workspace_id,
        graph=dict(graph),
        workflow_version=2,
    )
    workflow_id = UUID(str(created["workflow_id"]))
    stored = {
        "schema": SCHEMA_ID,
        "package_version": package.get("package_version"),
        "checksum": package_checksum(package),
        "metadata": metadata,
        "dependencies": package.get("dependencies") or [],
        "capabilities": package.get("capabilities") or [],
        "events": package.get("events") or [],
        "permissions": package.get("permissions") or [],
    }
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "UPDATE workflows SET package = CAST(:pkg AS jsonb) "
                "WHERE id = :wid AND organization_id = :oid"
            ),
            {
                "pkg": json.dumps(stored, ensure_ascii=False, default=str),
                "wid": str(workflow_id),
                "oid": str(organization_id),
            },
        )
        await session.commit()
    finally:
        await session.close()
    return {
        "workflow_id": str(workflow_id),
        "status": "draft",
        "readiness": report,
        "checksum": stored["checksum"],
    }


async def publication_blockers(
    organization_id: UUID,
    workflow_id: UUID,
    *,
    workspace_id: UUID | None = None,
    permissions: frozenset[str] | None = None,
) -> list[dict[str, Any]]:
    """Requisitos críticos pendientes de un workflow importado (gate de publicación)."""
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT package, graph, steps, trigger_type, trigger_config, name, description "
                    "FROM workflows WHERE id = :wid AND organization_id = :oid"
                ),
                {"wid": str(workflow_id), "oid": str(organization_id)},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None or not row.package:
        return []  # workflows nativos: sin gate
    graph = dict(row.graph) if row.graph else None
    if graph is None:
        from src.platform.workflows.ir import LegacyWorkflowAdapter

        graph = LegacyWorkflowAdapter.steps_to_graph(
            row.steps or [], str(row.trigger_type or "webhook"), dict(row.trigger_config or {})
        ).to_dict()
    package = build_package(row, graph)
    report = await inspect_package(organization_id, package, workspace_id=workspace_id, permissions=permissions)
    return [item for item in report["items"] if item["status"] != "RESOLVED"]
