# =============================================================================
# Workflow Data Catalog — información disponible durante la edición del grafo
# (Workflow Semantic Core, Fase 6).
#
# Combina: trigger (schema de evento + último payload), contratos de salida por
# tipo de nodo, samples reales del último run y las secciones de contexto que el
# nodo declara escribir. Solo lectura; nunca inventa datos.
# =============================================================================
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable
from uuid import UUID

from src.platform.workflows.references import DataReference, humanize_path
from src.platform.workflows.values import jsonable

TRIGGER_DEFAULT_FIELDS: tuple[dict[str, str], ...] = (
    {"key": "message", "label": "Mensaje recibido", "type": "text"},
    {"key": "query", "label": "Consulta recibida", "type": "text"},
)


async def workflow_data_catalog(
    organization_id: UUID,
    workflow_id: UUID,
    *,
    workspace_id: UUID | None = None,
    run_id: UUID | None = None,
) -> dict[str, Any] | None:
    """Catálogo de datos del grafo para el Data Picker (None si no existe)."""
    from src.platform.workflows.engine import get_workflow
    from src.platform.workflows.ir import LegacyWorkflowAdapter
    from src.platform.workflows.node_catalog import metadata_for
    from src.platform.workflows.parameters import output_contracts
    from src.platform.workflows.samples import latest_node_outputs

    workflow = await get_workflow(organization_id, workflow_id)
    if workflow is None:
        return None
    graph = workflow.get("graph")
    if not graph:
        graph = LegacyWorkflowAdapter.steps_to_graph(
            workflow.get("steps") or [],
            workflow.get("trigger_type") or "webhook",
            workflow.get("trigger_config") or {},
        ).to_dict()

    samples = await latest_node_outputs(organization_id, workflow_id, run_id=run_id)
    contracts = output_contracts()

    sources: list[dict[str, Any]] = []
    trigger_source = _trigger_source(graph, samples)
    if trigger_source is not None:
        sources.append(trigger_source)
    for node in graph.get("nodes") or []:
        source = _node_source(node, samples, contracts, metadata_for)
        if source is not None:
            sources.append(source)

    return {
        "workflow_id": str(workflow_id),
        "trigger_type": workflow.get("trigger_type"),
        "run_id": (samples or {}).get("run_id"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": jsonable(sources),
    }


# ---------------------------------------------------------------------------
# Fuentes
# ---------------------------------------------------------------------------
def _trigger_source(graph: dict[str, Any], samples: dict[str, Any] | None) -> dict[str, Any] | None:
    trigger_node = next(
        (node for node in graph.get("nodes") or [] if str(node.get("type") or "").startswith("trigger_")),
        None,
    )
    if trigger_node is None:
        return None
    payload = (samples or {}).get("trigger_payload") or {}
    fields: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(key: str, label: str, type_: str, sample: Any = None) -> None:
        if key in seen:
            return
        seen.add(key)
        entry: dict[str, Any] = {
            "key": key,
            "label": label,
            "ref": DataReference(source_kind="trigger", source_id="trigger", path=(key,)).render(),
            "type": type_ or "text",
        }
        if sample is not None:
            entry["sample"] = _preview(sample)
        fields.append(entry)

    for default in TRIGGER_DEFAULT_FIELDS:
        add(default["key"], default["label"], default["type"], payload.get(default["key"]))

    label = "Cuando ocurre el evento"
    event_type = str((trigger_node.get("config") or {}).get("event_type") or "")
    if event_type:
        try:
            from src.platform.workflows.event_registry import get_event_schema

            schema = get_event_schema(event_type)
        except Exception:  # noqa: BLE001 — evento no registrado
            schema = None
        if schema is not None:
            label = schema.business_name
            for field in schema.fields:
                add(field.key, field.label, field.type, payload.get(field.key, field.example))

    for key, value in payload.items():
        text_key = str(key)
        if text_key.startswith("_") or text_key in seen:
            continue
        if value is not None and isinstance(value, (dict, list)):
            continue
        add(text_key, humanize_path(text_key), _sample_type(value), value)

    return {"id": "trigger", "kind": "trigger", "label": label, "fields": fields}


def _node_source(
    node: dict[str, Any],
    samples: dict[str, Any] | None,
    contracts: dict[str, dict[str, Any]],
    metadata_for: Callable[[str], dict[str, Any]],
) -> dict[str, Any] | None:
    node_id = str(node.get("id") or "")
    node_type = str(node.get("type") or "")
    if not node_id or node_type.startswith("trigger_") or node_type == "end":
        return None
    output = (((samples or {}).get("nodes") or {}).get(node_id) or {}).get("output") or {}
    contract = contracts.get(node_type) or {}
    declared = {str(field.get("key")) for field in contract.get("outputs") or []}
    fields: list[dict[str, Any]] = []
    seen: set[str] = set()

    for field in contract.get("outputs") or []:
        key = str(field.get("key") or "")
        if not key:
            continue
        label = str(field.get("label") or humanize_path(key))
        type_ = str(field.get("type") or "text")
        entry: dict[str, Any] = {
            "key": key,
            "label": label,
            "ref": DataReference(
                source_kind="node",
                source_id=node_id,
                path=(key,),
                value_type=type_,
                business_label=label,
            ).render(),
            "type": type_,
        }
        sample = output.get(key)
        if sample is None:
            sample = field.get("sample") or field.get("example")
        if sample is not None:
            entry["sample"] = _preview(sample)
        fields.append(entry)
        seen.add(key)

    for key, value in output.items():
        text_key = str(key)
        if text_key in seen or text_key.startswith("_"):
            continue
        fields.extend(_sample_fields(text_key, value, node_id, declared))

    context_writes = list(metadata_for(node_type).get("context_writes") or [])
    if not fields and not output and not context_writes:
        return None
    source: dict[str, Any] = {
        "id": node_id,
        "kind": "node",
        "label": str(node.get("label") or node_type),
        "node_type": node_type,
        "fields": fields,
    }
    if context_writes:
        source["context_writes"] = context_writes
    return source


def _sample_fields(
    key: str, value: Any, node_id: str, declared: set[str]
) -> list[dict[str, Any]]:
    """Aplana dicts y listas de dicts del sample (mismo criterio que el portal)."""
    fields: list[dict[str, Any]] = []
    if isinstance(value, list) and value and isinstance(value[0], dict):
        for child_key, child_value in value[0].items():
            path = (key, "0", str(child_key))
            fields.append(_sample_entry(path, node_id, child_value))
        return fields
    if isinstance(value, dict):
        for child_key, child_value in value.items():
            fields.append(_sample_entry((key, str(child_key)), node_id, child_value))
        return fields
    if key not in declared:
        fields.append(_sample_entry((key,), node_id, value))
    return fields


def _sample_entry(path: tuple[str, ...], node_id: str, value: Any) -> dict[str, Any]:
    label_parts = [part for part in path if not part.isdigit()]
    display = label_parts[-1] if label_parts else path[-1]
    entry: dict[str, Any] = {
        "key": ".".join(path),
        "label": humanize_path(display),
        "ref": DataReference(source_kind="node", source_id=node_id, path=path).render(),
        "type": _sample_type(value),
    }
    preview = _preview(value)
    if preview is not None:
        entry["sample"] = preview
    return entry


def _sample_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    return "text"


def _preview(value: Any) -> Any:
    if value is None or isinstance(value, (dict, list)):
        return None
    return value


__all__ = ["TRIGGER_DEFAULT_FIELDS", "workflow_data_catalog"]
