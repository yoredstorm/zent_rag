# =============================================================================
# Effect verification — clasificación de efectos simulados de un run.
#
# Un dato fijado (pinned) es un doble declarado, no una verificación de
# proveedor. Un nodo interno simulado no es un efecto externo sin doble.
# =============================================================================
from __future__ import annotations

from typing import Any, Mapping

EXTERNAL_EFFECT_NODE_TYPES = frozenset(
    {
        "capability_call",
        "marketplace_action",
        "api_call",
        "business_node",
    }
)

EXTERNAL_READ_NODE_TYPES = frozenset(
    {
        "llm",
        "kb_query",
        "query_business_data",
    }
)


def classify_effects(
    executions: Mapping[str, Any],
    graph: Any | None,
) -> dict[str, Any]:
    """Clasifica los efectos simulados de un run.

    Devuelve el nivel más severo y las listas de nodos que lo explican.
    `declared` no es un pase: solo indica que el usuario fijó la respuesta.
    Los nodos no externos se consideran simulados por diseño.
    """
    node_map = graph.node_map if graph is not None else {}
    unverified: list[dict[str, Any]] = []
    declared: list[dict[str, Any]] = []
    simulated: list[dict[str, Any]] = []

    for node_id, execution in executions.items():
        if not getattr(execution, "simulated", False):
            continue
        planned = getattr(execution, "planned", None) or {}
        if not planned:
            continue
        node = node_map.get(node_id)
        node_type = str(getattr(node, "type", "") or "")
        label = str(getattr(node, "label", "") or "") or str(node_id)
        item = {
            "node_id": str(node_id),
            "node_type": node_type,
            "label": label,
            "kind": str(planned.get("kind") or ""),
        }
        if planned.get("pinned") or planned.get("pinned_failure"):
            declared.append(item)
        elif node_type in EXTERNAL_EFFECT_NODE_TYPES:
            unverified.append(item)
        else:
            simulated.append(item)

    if unverified:
        level = "UNVERIFIED"
    elif declared:
        level = "DECLARED"
    elif simulated:
        level = "SIMULATED"
    else:
        level = "NONE"

    return {
        "level": level,
        "unverified": unverified,
        "declared": declared,
        "simulated": simulated,
    }
