# =============================================================================
# Workflow Architect — Capability Discovery (First delivery, brief §4).
#
# Antes de planear: qué existe HOY para este tenant/workspace. Reutiliza
# load_capabilities + registry + event_registry. Nunca inventa capacidades.
# =============================================================================
from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)

_REQUIREMENT_LABELS: dict[str, str] = {
    "agents": "agentes",
    "knowledge_bases": "bases de conocimiento",
    "installed_integrations": "integraciones instaladas",
    "managed_db": "una base de datos de negocio conectada",
    "notification_email": "correo saliente configurado",
}


def requirement_message(kind: str, label: str | None = None) -> str:
    """Mensaje de negocio para una capacidad faltante (brief §4)."""
    if kind == "integration":
        name = label or "esa integración"
        return f"Para usar {name} primero necesitas conectarla en Integraciones."
    if kind.startswith("integration:"):
        return requirement_message("integration", label or kind.split(":", 1)[1])
    human = _REQUIREMENT_LABELS.get(kind, kind)
    return f"Para esto primero necesitas {human}."


async def _agent_capabilities(organization_id: UUID) -> list[dict[str, Any]]:
    """Agentes con propósito/tools/alcance de conocimiento (no solo el nombre)."""
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT id, name, tools, config_json FROM agents "
                    "WHERE organization_id = :oid AND is_active = true "
                    "ORDER BY name LIMIT 100"
                ),
                {"oid": organization_id},
            )
        ).fetchall()
    except Exception as exc:  # noqa: BLE001 — base sin agents
        logger.warning("architect agents discovery failed", error=str(exc)[:200])
        rows = []
    finally:
        await session.close()
    agents: list[dict[str, Any]] = []
    for row in rows:
        config = row.config_json if isinstance(row.config_json, dict) else {}
        tools = row.tools if isinstance(row.tools, list) else []
        agents.append(
            {
                "id": str(row.id),
                "name": str(row.name or ""),
                "purpose": str(config.get("purpose") or "")[:400],
                "tools": [str(tool) for tool in tools][:20],
                "knowledge_base_ids": [
                    str(item) for item in (config.get("knowledge_base_ids") or [])
                ][:20],
                "source_ids": [str(item) for item in (config.get("source_ids") or [])][:20],
                "output_schema": bool(config.get("output_schema")),
            }
        )
    return agents


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


async def discover_capabilities(
    organization_id: UUID,
    *,
    workspace_id: UUID | None = None,
    permissions: frozenset[str] | None = None,
) -> dict[str, Any]:
    """Snapshot real de capacidades del tenant/workspace para el planner."""
    from src.platform.workflows.event_registry import list_catalog
    from src.platform.workflows.plan_compiler import load_capabilities

    caps = await load_capabilities(organization_id, workspace_id)
    agents = await _agent_capabilities(organization_id)

    events: list[dict[str, Any]] = []
    try:
        for event in list_catalog():
            if hasattr(event, "model_dump"):
                events.append(event.model_dump(mode="json"))
            elif isinstance(event, dict):
                events.append(dict(event))
    except Exception as exc:  # noqa: BLE001 — catálogo no crítico
        logger.warning("architect event discovery failed", error=str(exc)[:200])

    actions = [
        {
            "action_id": entry.get("action_id"),
            "display_name": entry.get("display_name"),
            "install_id": entry.get("install_id"),
        }
        for entry in (caps.get("actions") or {}).values()
    ]
    return {
        "organization_id": str(organization_id),
        "workspace_id": str(workspace_id) if workspace_id else None,
        "nodes": _node_capabilities(),
        "triggers": {
            "schedule": ["daily", "weekly", "every_minutes", "cron"],
            "manual": True,
            "webhook": True,
            "events": events,
        },
        "agents": agents,
        "knowledge_bases": sorted(
            {
                value
                for key, value in (caps.get("knowledge_bases") or {}).items()
                if key == value
            }
        ),
        "actions": actions,
        "events": [str(item.get("id") or "") for item in events if item.get("id")],
        "managed_db": bool(caps.get("managed_db")),
        "permissions": sorted(permissions) if permissions is not None else None,
        "available": {
            "agents": bool(agents),
            "knowledge_bases": bool(caps.get("knowledge_bases")),
            "installed_integrations": bool(actions),
            "managed_db": bool(caps.get("managed_db")),
        },
    }


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


def capability_digest(capabilities: dict[str, Any], *, max_items: int = 12) -> str:
    """Resumen compacto de capacidades para el prompt del planner."""
    available = capabilities.get("available") or {}
    agents = capabilities.get("agents") or []
    actions = capabilities.get("actions") or []
    events = capabilities.get("events") or []
    nodes = capabilities.get("nodes") or []
    lines = [
        "Nodos disponibles (backend): " + ", ".join(
            f"{node['node_type']}" for node in nodes[:30]
        ),
    ]
    if agents:
        lines.append(
            "Agentes: "
            + "; ".join(
                f"{agent['name']} (props: {agent.get('purpose') or 'sin propósito declarado'})"
                for agent in agents[:max_items]
            )
        )
    else:
        lines.append("Agentes: NINGUNO disponible.")
    if actions:
        lines.append(
            "Acciones instaladas: "
            + "; ".join(
                f"{action.get('action_id')} ({action.get('display_name') or ''})"
                for action in actions[:max_items]
            )
        )
    else:
        lines.append("Acciones instaladas: NINGUNA.")
    if events:
        lines.append("Eventos: " + ", ".join(events[:max_items]))
    lines.append(
        "Disponibilidad: "
        + ", ".join(f"{key}={'sí' if value else 'no'}" for key, value in available.items())
    )
    return "\n".join(lines)


__all__ = [
    "capability_digest",
    "discover_capabilities",
    "match_agents",
    "requirement_message",
]
