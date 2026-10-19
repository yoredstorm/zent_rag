# =============================================================================
# Workflow Architect — Capability Discovery (Prompt 02).
#
# Construye el snapshot canónico (capability_registry) y proyecta el shape que
# consumen validator/compiler + un digest de contratos para el planner.
# Nunca inventa capacidades: todo sale de fuentes de verdad del tenant.
# =============================================================================
from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from src.infrastructure.observability.logging_config import get_logger
from src.platform.workflows.capability_registry import (
    CapabilityDescriptor,
    CapabilitySnapshot,
    build_capability_snapshot,
    search_descriptors,
)

logger = get_logger(__name__)

_REQUIREMENT_LABELS: dict[str, str] = {
    "agents": "agentes",
    "knowledge_bases": "bases de conocimiento",
    "installed_integrations": "integraciones instaladas",
    "managed_db": "una base de datos de negocio conectada",
    "notification_email": "correo saliente configurado",
    "approval:human": "una aprobación humana",
}


def requirement_message(kind: str, label: str | None = None) -> str:
    """Mensaje de negocio para una capacidad faltante."""
    if kind == "integration":
        name = label or "esa integración"
        return f"Para usar {name} primero necesitas conectarla en Integraciones."
    if kind.startswith("integration:"):
        return requirement_message("integration", label or kind.split(":", 1)[1])
    if kind.startswith("capability:"):
        name = label or kind.split(":", 1)[1]
        return (
            f"Para usar la capacidad {name} primero necesitas configurar su proveedor "
            "en Integraciones."
        )
    human = _REQUIREMENT_LABELS.get(kind, kind)
    return f"Para esto primero necesitas {human}."


def _node_capabilities() -> list[dict[str, Any]]:
    from src.platform.workflows.node_catalog import metadata_for
    from src.platform.workflows.nodes import registry

    nodes: list[dict[str, Any]] = []
    for node_def in registry.all():
        meta = metadata_for(node_def.node_type)
        entry: dict[str, Any] = {
            "node_type": node_def.node_type,
            "business_name": str(meta.get("business_name") or node_def.label),
            "category": node_def.category,
            "risk_level": node_def.risk_level,
            "supports_simulation": node_def.simulation_supported,
            "requires": list(meta.get("requires") or ()),
        }
        if node_def.node_type == "kb_query":
            from src.platform.workflows.nodes import KB_OPERATIONS

            entry["operations"] = list(KB_OPERATIONS)
        nodes.append(entry)
    return nodes


def capabilities_from_snapshot(snapshot: CapabilitySnapshot) -> dict[str, Any]:
    """Proyección compatible con validator/compiler + índices de contrato."""
    agents: list[dict[str, Any]] = []
    actions: dict[str, dict[str, Any]] = {}
    knowledge_bases: list[str] = []
    resources: list[dict[str, Any]] = []
    capability_index: dict[str, dict[str, Any]] = {}
    tools: list[dict[str, Any]] = []

    for descriptor in snapshot.capabilities:
        compact = descriptor.compact()
        if descriptor.source == "agent":
            meta = descriptor.metadata
            agents.append(
                {
                    "id": meta.get("agent_id"),
                    "name": descriptor.display_name,
                    "purpose": meta.get("purpose") or descriptor.description,
                    "tools": list(meta.get("tools") or []),
                    "knowledge_base_ids": list(meta.get("knowledge_base_ids") or []),
                    "source_ids": [],
                    "output_schema": bool(
                        (descriptor.output_schema.get("properties") or {})
                    ),
                }
            )
        elif descriptor.source == "marketplace":
            if descriptor.availability.installed:
                actions[descriptor.capability_ref] = {
                    "action_id": descriptor.capability_ref,
                    "display_name": descriptor.display_name,
                    "install_id": descriptor.metadata.get("install_id"),
                    "executable": descriptor.availability.executable,
                    "status": descriptor.availability.status,
                }
        elif descriptor.source in ("commerce", "binding"):
            capability_index[descriptor.capability_ref] = compact
        elif descriptor.source == "tool":
            tools.append(
                {
                    "name": descriptor.metadata.get("tool_name"),
                    "description": descriptor.description,
                    "permission": descriptor.metadata.get("permission") or "",
                    "executable": descriptor.availability.executable,
                    "status": descriptor.availability.status,
                }
            )

    for resource in snapshot.resources:
        resources.append(resource.compact())
        if resource.kind == "knowledge_base" and resource.status == "active":
            knowledge_bases.append(resource.resource_ref.rsplit(".", 1)[-1])

    managed_db = any(
        item.kind == "managed_db" and item.status == "ready" for item in snapshot.resources
    )
    available = {
        "agents": bool(agents),
        "knowledge_bases": bool(knowledge_bases),
        "installed_integrations": bool(actions),
        "managed_db": managed_db,
    }
    return {
        "agents": agents,
        "knowledge_bases": sorted(set(knowledge_bases)),
        "actions": actions,
        "managed_db": managed_db,
        "resources": resources,
        "tools": tools,
        "events": [event.event_type for event in snapshot.events],
        "capability_index": capability_index,
        "capability_snapshot": snapshot.summary(),
        "available": available,
    }


async def discover_capabilities(
    organization_id: UUID,
    *,
    workspace_id: UUID | None = None,
    permissions: frozenset[str] | None = None,
    snapshot: CapabilitySnapshot | None = None,
) -> dict[str, Any]:
    """Snapshot real de capacidades del tenant/workspace para el planner."""
    from src.platform.workflows.event_registry import list_catalog

    registry_snapshot = snapshot
    snapshot_error: str | None = None
    if registry_snapshot is None:
        try:
            registry_snapshot = await build_capability_snapshot(
                organization_id,
                workspace_id,
                permissions=permissions,
            )
        except Exception as exc:  # noqa: BLE001 — el Architect no cae si el registry falla
            snapshot_error = str(exc)[:200]
            logger.warning("architect capability snapshot failed", error=snapshot_error)

    if registry_snapshot is not None:
        projected = capabilities_from_snapshot(registry_snapshot)
    else:
        from src.platform.workflows.plan_compiler import load_capabilities

        caps = await load_capabilities(organization_id, workspace_id)
        projected = {
            "agents": [],
            "knowledge_bases": sorted(set(caps.get("knowledge_bases") or [])),
            "actions": {
                key: {**value, "executable": True}
                for key, value in (caps.get("actions") or {}).items()
            },
            "managed_db": bool(caps.get("managed_db")),
            "resources": [],
            "tools": [],
            "capability_index": {},
            "capability_snapshot": None,
            "available": {
                "agents": False,
                "knowledge_bases": bool(caps.get("knowledge_bases")),
                "installed_integrations": bool(caps.get("actions")),
                "managed_db": bool(caps.get("managed_db")),
            },
            "_descriptor_models": [],
        }

    events: list[dict[str, Any]] = []
    try:
        for event in list_catalog():
            events.append(
                {
                    "id": event.id,
                    "business_name": event.business_name,
                    "category": event.category,
                    "fields": [field.model_dump(mode="json") for field in event.fields],
                }
            )
    except Exception as exc:  # noqa: BLE001 — catálogo no crítico
        logger.warning("architect event discovery failed", error=str(exc)[:200])

    projected.update(
        {
            "organization_id": str(organization_id),
            "workspace_id": str(workspace_id) if workspace_id else None,
            "nodes": _node_capabilities(),
            "triggers": {
                "schedule": ["daily", "weekly", "every_minutes", "cron"],
                "manual": True,
                "webhook": True,
                "events": events,
            },
            "events": [event["id"] for event in events if event.get("id")],
            "event_schemas": events,
            "permissions": sorted(permissions) if permissions is not None else None,
            "registry_error": snapshot_error,
            "_descriptor_models": list(registry_snapshot.capabilities) if registry_snapshot else [],
        }
    )
    return projected


_STOPWORDS = frozenset(
    {
        "que", "con", "para", "una", "uno", "los", "las", "del", "como", "cuando", "sobre",
        "por", "se", "el", "la", "de", "y", "o", "en", "un", "a", "al", "si", "no", "sus",
        "su", "cada", "the", "and", "for", "with", "all", "from", "this", "that",
    }
)


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-záéíóúñ0-9]+", str(text or "").lower())
        if token not in _STOPWORDS and len(token) > 2
    }


def match_agents(text: str, capabilities: dict[str, Any]) -> list[dict[str, Any]]:
    """Agentes compatibles por propósito/tools/nombre (nunca solo por nombre)."""
    words = _tokens(text)
    scored: list[dict[str, Any]] = []
    for agent in capabilities.get("agents") or []:
        haystack = " ".join(
            [
                str(agent.get("name") or ""),
                str(agent.get("purpose") or ""),
                " ".join(agent.get("tools") or []),
            ]
        )
        overlap = words & _tokens(haystack)
        name_overlap = words & _tokens(str(agent.get("name") or ""))
        score = len(overlap) + 2 * len(name_overlap)
        if score > 0:
            scored.append({**agent, "score": score})
    return sorted(scored, key=lambda item: (-int(item["score"]), str(item.get("name") or "")))


def _short(value: str, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _render_capability(descriptor: CapabilityDescriptor) -> list[str]:
    required = ", ".join(
        f"{key}:{str((descriptor.input_schema.get('properties') or {}).get(key, {}).get('type') or 'any')}*"
        for key in descriptor.required_inputs[:6]
    )
    outputs = ", ".join(sorted((descriptor.output_schema.get("properties") or {}).keys())[:8])
    permissions = ", ".join(descriptor.required_permissions[:4]) or "—"
    status = descriptor.availability.status
    executable = "sí" if descriptor.availability.executable else "no"
    lines = [
        f"- {descriptor.capability_ref} v{descriptor.version} "
        f"[{descriptor.source}/{descriptor.provider_kind}] estado={status} ejecutable={executable} "
        f"riesgo={descriptor.risk_level}",
    ]
    detail = _short(descriptor.description, 220) or _short(descriptor.display_name, 120)
    if detail:
        lines.append(f"  {detail}")
    lines.append(
        "  inputs: "
        + (required or "ninguno requerido")
        + f"; outputs: {outputs or 'sin contrato de salida'}"
        + f"; permisos: {permissions}"
    )
    if descriptor.availability.reasons:
        lines.append("  bloqueo: " + _short("; ".join(descriptor.availability.reasons), 180))
    return lines


def _relevant_descriptors(
    capabilities: dict[str, Any], query: str | None, max_items: int
) -> list[CapabilityDescriptor]:
    models: list[CapabilityDescriptor] = list(capabilities.get("_descriptor_models") or [])
    if not models:
        return []
    if not query:
        business = [
            item
            for item in models
            if item.source in ("commerce", "marketplace", "binding", "agent")
        ]
        business.sort(key=lambda item: (not item.availability.executable, item.capability_ref))
        return business[:max_items]
    scored, _ = search_descriptors(models, query, limit=max_items)
    return [
        item
        for item, _ in scored
        if not (
            item.source == "node"
            and not bool((item.planner_usage or {}).get("supported", True))
        )
    ]


def capability_digest(
    capabilities: dict[str, Any], *, max_items: int = 12, query: str | None = None
) -> str:
    """Resumen compacto de capacidades para el prompt del planner.

    No vuelca el catálogo: busca por el pedido y renderiza contratos suficientes
    (inputs/outputs/permisos/estado). El catálogo completo queda accesible por
    `capability.inspect` / API, no en el prompt.
    """
    available = capabilities.get("available") or {}
    agents = capabilities.get("agents") or []
    actions = capabilities.get("actions") or []
    if isinstance(actions, dict):
        actions = list(actions.values())
    events = capabilities.get("events") or []
    nodes = capabilities.get("nodes") or []
    resources = capabilities.get("resources") or []
    snapshot = capabilities.get("capability_snapshot") or {}
    lines: list[str] = []

    if snapshot:
        coverage = snapshot.get("coverage") or {}
        lines.append(
            "Catálogo de capacidades: "
            f"{snapshot.get('counts', {}).get('capabilities', 0)} capacidades "
            f"(snapshot {str(snapshot.get('snapshot_hash') or '')[:12]}, "
            f"cobertura negocio {round(float(coverage.get('business_completeness') or 0) * 100)}%). "
            "Inspecciona con capability.inspect antes de usar una capacidad dudosa."
        )

    relevant = _relevant_descriptors(capabilities, query, max_items)
    if relevant:
        lines.append("Capacidades relevantes (contratos):")
        for descriptor in relevant:
            lines.extend(_render_capability(descriptor))
    else:
        lines.append("Capacidades relevantes: no hay contratos disponibles.")

    supported_nodes = [
        node
        for node in nodes
        if node.get("node_type")
        not in ("loop", "for_each", "ai_decision", "api_call", "set_variable", "business_node", "end")
    ]
    if supported_nodes:
        lines.append(
            "Primitivas de workflow soportadas por el planner: "
            + ", ".join(str(node["node_type"]) for node in supported_nodes[:32])
        )

    if agents:
        lines.append(
            "Agentes (usa params.agent_id; no inventes): "
            + "; ".join(
                f"{agent.get('name')} id={agent.get('id')} "
                f"(props: {_short(agent.get('purpose') or 'sin propósito declarado', 120)})"
                for agent in agents[:max_items]
            )
        )
    else:
        lines.append("Agentes: NINGUNO disponible.")

    if actions:
        lines.append(
            "Acciones de marketplace instaladas: "
            + "; ".join(
                f"{item.get('action_id')} (ejecutable={'sí' if item.get('executable', True) else 'no'}, "
                f"estado={item.get('status') or 'unknown'})"
                for item in actions[:max_items]
            )
        )
    else:
        lines.append("Acciones de marketplace instaladas: NINGUNA.")

    if resources:
        lines.append(
            "Recursos: "
            + "; ".join(
                f"{item.get('display_name') or item.get('resource_ref')} "
                f"({item.get('kind')}, {item.get('status')})"
                for item in resources[:max_items]
            )
        )

    if events:
        event_labels = {
            str(event.get("id")): str(event.get("business_name") or "")
            for event in capabilities.get("event_schemas") or []
        }
        lines.append(
            "Eventos: "
            + ", ".join(
                f"{event} ({event_labels[event]})" if event_labels.get(event) else event
                for event in events[:max_items]
            )
        )
    lines.append(
        "Disponibilidad: "
        + ", ".join(f"{key}={'sí' if value else 'no'}" for key, value in available.items())
    )
    gaps = [
        item
        for item in relevant
        if item.contract_gaps
    ][:6]
    if gaps:
        lines.append(
            "Brechas de contrato: "
            + "; ".join(
                f"{item.capability_ref}: {', '.join(item.contract_gaps)}" for item in gaps
            )
        )
    return "\n".join(lines)


__all__ = [
    "capabilities_from_snapshot",
    "capability_digest",
    "discover_capabilities",
    "match_agents",
    "requirement_message",
]
