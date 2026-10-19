# =============================================================================
# Capability inspection services — herramientas read-only para el planner.
#
# Reutiliza el snapshot canónico y los servicios existentes (bindings,
# event_registry, templates). No ejecuta capacidades ni toca el runtime.
# =============================================================================
from __future__ import annotations

from typing import Any
from uuid import UUID

from src.infrastructure.observability.logging_config import get_logger
from src.platform.workflows.capability_registry import (
    CapabilityDescriptor,
    CapabilitySnapshot,
    _redact_mapping,
    canonical_hash,
    token_set,
)

logger = get_logger(__name__)

_TYPE_COMPAT: dict[str, set[str]] = {
    "string": {"string"},
    "number": {"number", "integer"},
    "integer": {"integer", "number"},
    "boolean": {"boolean"},
    "array": {"array"},
    "object": {"object"},
}

#: Contenedores cuyo contenido puede alimentar otro paso aunque cambie el nombre.
_GENERIC_CONTAINERS = frozenset({"items", "rows", "data", "results", "products", "records"})
_WEAK_NAME_TOKENS = frozenset({"id", "key", "code", "name", "type", "status", "value", "ref"})


def _json_type(spec: Any) -> str:
    if not isinstance(spec, dict):
        return ""
    type_ = spec.get("type")
    if isinstance(type_, list):
        type_ = type_[0] if type_ else ""
    return str(type_ or "")


def schema_links(
    output_schema: dict[str, Any],
    input_schema: dict[str, Any],
    *,
    max_links: int = 12,
) -> dict[str, Any]:
    """Vínculos deducidos de contratos: nombre + tipo. Nunca inventa campos."""
    out_props = (output_schema or {}).get("properties") or {}
    in_props = (input_schema or {}).get("properties") or {}
    required = [str(item) for item in (input_schema or {}).get("required") or []]
    links: list[dict[str, Any]] = []
    unmatched: list[str] = []
    matched_inputs: set[str] = set()
    for out_name, out_spec in list(out_props.items())[:40]:
        out_type = _json_type(out_spec)
        for in_name, in_spec in list(in_props.items())[:40]:
            in_type = _json_type(in_spec)
            if not out_type or not in_type:
                continue
            same_name = str(out_name).lower() == str(in_name).lower()
            name_overlap = bool(
                (token_set(str(out_name)) & token_set(str(in_name))) - _WEAK_NAME_TOKENS
            )
            generic = str(out_name).lower() in _GENERIC_CONTAINERS or str(
                in_name
            ).lower() in _GENERIC_CONTAINERS
            compatible = in_type in _TYPE_COMPAT.get(out_type, set())
            # Solo unimos por nombre o por contenedores genéricos tipados.
            # Dos strings cualesquiera (checkout_id → currency) NO son vínculo.
            if not same_name and not name_overlap and not (compatible and generic):
                continue
            if same_name and compatible:
                confidence = "high"
            elif compatible:
                confidence = "medium"
            else:
                confidence = "low"
            links.append(
                {
                    "output_field": str(out_name),
                    "input_field": str(in_name),
                    "type": out_type,
                    "confidence": confidence,
                    "reason": (
                        "mismo nombre y tipo"
                        if same_name and compatible
                        else "nombre relacionado"
                        if name_overlap
                        else "contenedor compatible"
                    ),
                }
            )
            matched_inputs.add(str(in_name))
            if len(links) >= max_links:
                break
        if len(links) >= max_links:
            break
    for field in required:
        if field not in matched_inputs:
            unmatched.append(field)
    notes: list[str] = []
    if out_type_of(output_schema) == "array" and not out_props:
        notes.append("el output es una lista sin esquema de ítem; no se puede verificar el mapeo")
    if unmatched:
        notes.append("inputs requeridos sin vínculo verificado: " + ", ".join(unmatched[:8]))
    return {"links": links, "unmatched_required": unmatched, "notes": notes}


def out_type_of(schema: dict[str, Any]) -> str:
    return _json_type(schema)


def _find(snapshot: CapabilitySnapshot, ref: str) -> CapabilityDescriptor | None:
    return snapshot.index().get(ref)


async def inspect_capability(
    snapshot: CapabilitySnapshot, capability_ref: str
) -> dict[str, Any] | None:
    descriptor = _find(snapshot, capability_ref)
    if descriptor is None:
        return None
    return {
        "schema": "zent.capability.inspect/v1",
        "snapshot_hash": snapshot.snapshot_hash,
        "generated_at": snapshot.generated_at.isoformat(),
        "capability": descriptor.model_dump(mode="json"),
        "composes_with": suggest_next(snapshot, capability_ref, limit=5),
    }


async def capability_dependencies(
    snapshot: CapabilitySnapshot, capability_ref: str
) -> dict[str, Any] | None:
    descriptor = _find(snapshot, capability_ref)
    if descriptor is None:
        return None
    index = snapshot.index()
    resources = {item.resource_ref: item for item in snapshot.resources}
    dependencies: list[dict[str, Any]] = []
    for ref in descriptor.dependency_refs:
        parts = ref.split(":", 2)
        kind = parts[0] if parts else "unknown"
        value = parts[1] if len(parts) > 1 else ""
        sub_ref = parts[2] if len(parts) > 2 else ""
        entry: dict[str, Any] = {
            "ref": ref,
            "kind": kind or "unknown",
            "resolved": False,
            "status": "UNKNOWN",
        }
        if kind == "binding":
            entry.update(await resolve_capability_binding(snapshot, value))
            entry["resolved"] = entry.get("found", False)
            entry["status"] = "RESOLVED" if entry["resolved"] else "NEEDS_CONFIGURATION"
        elif kind in ("integration", "capability"):
            matches = [
                item
                for item in snapshot.capabilities
                if item.source == "marketplace"
                and (
                    item.metadata.get("integration_slug") == value
                    if kind == "integration"
                    else item.metadata.get("capability_slug") == value
                )
            ]
            entry["resolved"] = bool(matches)
            entry["status"] = (
                "RESOLVED"
                if any(item.availability.executable for item in matches)
                else (matches[0].availability.status if matches else "MISSING")
            )
            entry["providers"] = [
                {
                    "capability_ref": item.capability_ref,
                    "display_name": item.display_name,
                    "availability": item.availability.model_dump(mode="json"),
                }
                for item in matches[:8]
            ]
        elif kind in ("tool", "agent"):
            target = next(
                (
                    item
                    for item in snapshot.capabilities
                    if item.capability_ref == f"{kind}.{value}"
                    or (kind == "agent" and item.metadata.get("agent_id") == value)
                ),
                None,
            )
            entry["resolved"] = target is not None and target.availability.executable
            entry["status"] = target.availability.status if target else "MISSING"
            entry["capability_ref"] = target.capability_ref if target else None
        elif kind == "resource":
            resource_key = (
                f"resource.{value}.{sub_ref}" if sub_ref else f"resource.{value}"
            )
            target = resources.get(resource_key) or resources.get(value)
            entry["resolved"] = target is not None
            entry["status"] = target.status if target else "MISSING"
            entry["resource_ref"] = target.resource_ref if target else None
        elif kind == "requires":
            entry["resolved"] = bool(
                (value == "agents" and any(item.source == "agent" for item in snapshot.capabilities))
                or (value == "knowledge_bases" and any(item.kind == "knowledge_base" for item in snapshot.resources))
                or (value == "managed_db" and any(item.kind == "managed_db" for item in snapshot.resources))
                or (
                    value == "installed_integrations"
                    and any(
                        item.source == "marketplace" and item.availability.installed
                        for item in snapshot.capabilities
                    )
                )
            )
            entry["status"] = "RESOLVED" if entry["resolved"] else "MISSING"
        elif kind in ("approval", "purpose", "provider"):
            entry["resolved"] = True
            entry["status"] = "POLICY"
        else:
            entry["resolved"] = ref in index
            entry["status"] = "RESOLVED" if entry["resolved"] else "OPTIONAL"
        dependencies.append(entry)
    return {
        "schema": "zent.capability.dependencies/v1",
        "snapshot_hash": snapshot.snapshot_hash,
        "capability_ref": capability_ref,
        "dependencies": dependencies,
        "composes_with": suggest_next(snapshot, capability_ref, limit=8),
        "contract_gaps": descriptor.contract_gaps,
    }


def suggest_next(
    snapshot: CapabilitySnapshot, capability_ref: str, *, limit: int = 5
) -> list[dict[str, Any]]:
    """Candidatos siguientes deducidos de esquemas y tokens (sin hardcodear flujos)."""
    source = _find(snapshot, capability_ref)
    if source is None:
        return []
    scored: list[tuple[float, CapabilityDescriptor, dict[str, Any]]] = []
    source_tokens = token_set(f"{source.display_name} {source.description} {source.category}")
    for candidate in snapshot.capabilities:
        if candidate.capability_ref == capability_ref:
            continue
        analysis = schema_links(source.output_schema, candidate.input_schema, max_links=6)
        links = analysis["links"]
        if not links:
            continue
        score = sum({"high": 3, "medium": 2, "low": 1}.get(link["confidence"], 1) for link in links)
        score += len(source_tokens & token_set(candidate.display_name)) * 0.5
        if candidate.availability.executable:
            score += 1
        scored.append((score, candidate, analysis))
    scored.sort(key=lambda item: (-item[0], item[1].capability_ref))
    return [
        {
            "capability_ref": candidate.capability_ref,
            "display_name": candidate.display_name,
            "score": round(score, 2),
            "links": analysis["links"],
            "unmatched_required": analysis["unmatched_required"],
            "notes": analysis["notes"],
            "availability_status": candidate.availability.status,
            "executable": candidate.availability.executable,
        }
        for score, candidate, analysis in scored[:limit]
    ]


def compose_capabilities(
    snapshot: CapabilitySnapshot, from_ref: str, to_ref: str
) -> dict[str, Any] | None:
    source = _find(snapshot, from_ref)
    target = _find(snapshot, to_ref)
    if source is None or target is None:
        return None
    analysis = schema_links(source.output_schema, target.input_schema, max_links=20)
    return {
        "schema": "zent.capability.compose/v1",
        "from": from_ref,
        "to": to_ref,
        "compatible": bool(analysis["links"]) and not analysis["unmatched_required"],
        **analysis,
        "from_availability": source.availability.status,
        "to_availability": target.availability.status,
    }


def check_availability(
    snapshot: CapabilitySnapshot, capability_ref: str
) -> dict[str, Any] | None:
    descriptor = _find(snapshot, capability_ref)
    if descriptor is None:
        return None
    return {
        "schema": "zent.capability.availability/v1",
        "snapshot_hash": snapshot.snapshot_hash,
        "capability_ref": capability_ref,
        "availability": descriptor.availability.model_dump(mode="json"),
        "contract_hash": descriptor.contract_hash,
        "checked_at": descriptor.availability.checked_at.isoformat(),
    }


async def resolve_capability_binding(
    snapshot: CapabilitySnapshot, capability_ref: str
) -> dict[str, Any]:
    """Binding resuelto sin secretos. Requiere org/ws del snapshot (interno)."""
    # El snapshot no expone org/ws por diseño; el caller pasa el binding resuelto
    # en el servicio API. Este helper devuelve la parte pública del descriptor.
    descriptor = _find(snapshot, capability_ref)
    if descriptor is None:
        return {"found": False, "capability_ref": capability_ref, "reason": "unknown_capability"}
    binding_id = descriptor.metadata.get("binding_id")
    return {
        "found": bool(binding_id),
        "capability_ref": capability_ref,
        "provider_kind": descriptor.provider_kind,
        "binding_id": binding_id,
        "config_keys": [],
        "credential_ref_present": bool(descriptor.metadata.get("credential_ref")),
        "status": descriptor.availability.status,
        "contract_input_schema": descriptor.input_schema,
        "contract_output_schema": descriptor.output_schema,
    }


async def resolve_binding_for_tenant(
    organization_id: UUID,
    capability_ref: str,
    *,
    workspace_id: UUID | None = None,
) -> dict[str, Any]:
    """Resuelve el binding real (config redactada, sin credenciales)."""
    from src.platform.workflows.bindings import resolve_binding

    try:
        binding = await resolve_binding(organization_id, capability_ref, workspace_id)
    except Exception as exc:  # noqa: BLE001 — tabla ausente o error de DB
        logger.warning("resolve binding failed", capability_ref=capability_ref, error=str(exc)[:160])
        binding = None
    if binding is None:
        return {
            "schema": "zent.capability.binding/v1",
            "capability_ref": capability_ref,
            "found": False,
            "status": "NEEDS_CONFIGURATION",
            "provider_kind": None,
        }
    return {
        "schema": "zent.capability.binding/v1",
        "capability_ref": capability_ref,
        "found": True,
        "binding_id": binding.get("id"),
        "provider_kind": binding.get("provider_kind"),
        "status": binding.get("status"),
        "config": _redact_mapping(binding.get("config") or {}),
        "config_keys": sorted((binding.get("config") or {}).keys()),
        "credential_ref_present": bool(binding.get("credential_ref")),
        "contract_input_schema": binding.get("contract_input_schema") or {},
        "contract_output_schema": binding.get("contract_output_schema") or {},
    }


def discover_resources(
    snapshot: CapabilitySnapshot, *, kind: str | None = None, limit: int = 50
) -> dict[str, Any]:
    items = [
        item for item in snapshot.resources if not kind or item.kind == kind
    ][: max(1, min(limit, 200))]
    return {
        "schema": "zent.resource.discover/v1",
        "snapshot_hash": snapshot.snapshot_hash,
        "total": len([item for item in snapshot.resources if not kind or item.kind == kind]),
        "returned": len(items),
        "resources": [item.model_dump(mode="json") for item in items],
    }


def inspect_resource(
    snapshot: CapabilitySnapshot, resource_ref: str
) -> dict[str, Any] | None:
    resource = next(
        (item for item in snapshot.resources if item.resource_ref == resource_ref), None
    )
    if resource is None:
        return None
    return {
        "schema": "zent.resource.inspect/v1",
        "resource": resource.model_dump(mode="json"),
        "snapshot_hash": snapshot.snapshot_hash,
    }


def inspect_event(
    snapshot: CapabilitySnapshot, event_type: str
) -> dict[str, Any] | None:
    event = next(
        (
            item
            for item in snapshot.events
            if item.event_type == event_type or item.event_type == event_type.split("@")[0]
        ),
        None,
    )
    if event is None:
        return None
    return {
        "schema": "zent.event.inspect/v1",
        "event": event.model_dump(mode="json"),
        "snapshot_hash": snapshot.snapshot_hash,
    }


async def search_templates(
    query: str = "", *, limit: int = 10
) -> dict[str, Any]:
    from src.platform.workflows.engine import list_templates

    payload = await list_templates()
    tokens = token_set(query)
    scored: list[tuple[float, dict[str, Any]]] = []
    for template in payload.get("templates") or []:
        haystack = " ".join(
            [
                str(template.get("slug") or ""),
                str(template.get("name") or ""),
                str(template.get("description") or ""),
                str(template.get("category") or ""),
            ]
        )
        overlap = tokens & token_set(haystack)
        score = len(overlap) * 10
        if query and normalize_query(query) in normalize_query(haystack):
            score += 25
        if query and score <= 0:
            continue
        scored.append((score, template))
    scored.sort(key=lambda item: (-item[0], str(item[1].get("name") or "")))
    results = [
        {
            "slug": item.get("slug"),
            "name": item.get("name"),
            "description": item.get("description"),
            "category": item.get("category"),
            "trigger_type": item.get("trigger_type"),
            "step_count": len(item.get("steps") or []),
            "score": score,
        }
        for score, item in scored[: max(1, min(limit, 50))]
    ]
    return {
        "schema": "zent.workflow.template.search/v1",
        "total": len(scored),
        "returned": len(results),
        "results": results,
    }


def normalize_query(value: str) -> str:
    from src.platform.workflows.capability_registry import normalize_text

    return normalize_text(value)


async def inspect_template(slug: str) -> dict[str, Any] | None:
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT slug, name, description, category, trigger_type, trigger_config, "
                    "steps, graph, package FROM workflow_templates WHERE slug = :slug"
                ),
                {"slug": slug},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None:
        return None
    graph = row.graph if isinstance(row.graph, dict) else None
    steps = row.steps if isinstance(row.steps, list) else []
    package = row.package if isinstance(row.package, dict) else {}
    node_types = sorted(
        {
            str(node.get("type"))
            for node in ((graph or {}).get("nodes") or [])
            if isinstance(node, dict) and node.get("type")
        }
    )
    dependencies = package.get("dependencies") or []
    payload = {
        "slug": row.slug,
        "name": row.name,
        "description": row.description,
        "category": row.category,
        "trigger_type": row.trigger_type,
        "trigger_config": row.trigger_config or {},
        "step_count": len(steps),
        "node_types": node_types,
        "dependencies": dependencies[:30],
        "has_graph": graph is not None,
    }
    return {
        "schema": "zent.workflow.template.inspect/v1",
        "template": payload,
        "contract_hash": canonical_hash(payload),
    }


async def capability_search(
    snapshot: CapabilitySnapshot,
    query: str,
    *,
    limit: int = 10,
    offset: int = 0,
    semantic: bool = False,
    **filters: Any,
) -> dict[str, Any]:
    from src.platform.workflows.capability_registry import search_capabilities

    return await search_capabilities(
        snapshot,
        query,
        limit=limit,
        offset=offset,
        semantic=semantic,
        **filters,
    )


__all__ = [
    "capability_dependencies",
    "capability_search",
    "check_availability",
    "compose_capabilities",
    "discover_resources",
    "inspect_capability",
    "inspect_event",
    "inspect_resource",
    "inspect_template",
    "resolve_binding_for_tenant",
    "resolve_capability_binding",
    "schema_links",
    "search_templates",
    "suggest_next",
]
