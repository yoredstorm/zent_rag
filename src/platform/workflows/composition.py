# =============================================================================
# Composición durable — subworkflow.call/v1 y router adaptativo.
#
# No es un runtime. `execute_graph` sigue siendo el único ejecutor.
# El LLM propone una transición; este módulo la valida contra allowlist
# congelada y contra el registry anunciado. El backend aplica la decisión.
# =============================================================================
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from src.platform.workflows.error_contract import TYPED_PORTS, typed_port_for_decision

CONTRACT = "subworkflow.call/v1"
CONTRACT_VERSION = 1
MAX_DEPTH_HARD = 8
DEFAULT_MAX_DEPTH = 3
MAX_RETRIES_HARD = 5
MAX_FANOUT_HARD = 20
DEFAULT_CONFIDENCE_MIN = 0.6
SUBFLOW_STATES: tuple[str, ...] = ("draft", "published", "deprecated")

STAGES: tuple[str, ...] = (
    "intent_understanding",
    "decision",
    "capability_execution",
    "state_update",
    "human_handoff",
    "wait",
    "result",
    "compensation",
)

FAILURE_MODES: tuple[str, ...] = (
    "low_confidence",
    "provider_unavailable",
    "missing_data",
    "unauthorized_tool",
    "contract_mismatch",
    "timeout",
    "user_cancelled",
    "human_requested",
)

PROPOSAL_FIELDS: tuple[str, ...] = (
    "route",
    "confidence",
    "rationale_summary",
    "missing_information",
    "recommended_next_action",
    "allowed_transition_id",
)

DURABLE_NODE_TYPES = frozenset({"wait_event", "loop", "human_approval"})
SIDE_EFFECT_NODES = frozenset(
    {
        "capability_call",
        "kb_query",
        "llm",
        "api_call",
        "marketplace_action",
        "business_node",
        "business_result",
        "subworkflow_call",
        "state_get",
        "state_set",
        "state_merge",
        "state_append",
        "state_remove",
        "notify",
        "query_business_data",
    }
)
DIAGNOSIS_REFS = frozenset(
    {"clinical.diagnose", "clinical.prescribe", "wellness.diagnose"}
)
SENSITIVE_FIELDS = frozenset(
    {"diagnosis", "symptoms", "medication", "health_notes", "self_harm_detail"}
)
CRITICAL_MARKERS = (
    "suicid",
    "autoles",
    "matarme",
    "no quiero vivir",
    "me voy a hacer daño",
    "hacerme daño",
)

PORTABLE_SUBFLOWS: tuple[str, ...] = (
    "identificar_intencion",
    "consultar_conocimiento",
    "preguntar_aclaracion",
    "evaluar_ejercicio",
    "registrar_progreso",
    "solicitar_aprobacion",
    "cobrar_pedido",
    "escalar_humano",
)

# Sync: el hijo termina y el padre ramifica con el puerto devuelto.
# Inline: WAIT/LOOP/aprobación viven en el mismo proceso (el worker se libera).
NESTED_SUBFLOWS = frozenset(
    {
        "identificar_intencion",
        "consultar_conocimiento",
        "evaluar_ejercicio",
        "registrar_progreso",
        "cobrar_pedido",
    }
)


class CompositionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def engine_inventory() -> dict[str, Any]:
    """Cobertura del motor único y contratos que cierran los huecos."""
    from src.platform.workflows.nodes import registry

    handlers = sorted(node.node_type for node in registry.all())
    return {
        "executor": "execute_graph",
        "engine": "run_workflow",
        "scheduler": "workflow_v2_scheduler_loop",
        "parallel_runtime": False,
        "handlers": handlers,
        "loop_wait": {
            "wait_node": "wait_event",
            "loop_node": "loop",
            "wait_releases_worker": True,
            "resume": "signal_workflow_instance",
            "conversation_resume": "resume_conversation_message",
            "snapshot": "definition_snapshot",
            "concurrency": "CAS state_version + claim WAITING→RUNNING",
            "business_key": "una instancia activa por business_key",
        },
        "covered": {
            "nodes": "registry de handlers; el runtime despacha por tipo",
            "runtime": "DAG, permisos, retries, timeout, resume sin re-ejecutar pasos",
            "engine": "run_workflow, aprobaciones, scheduler único",
            "instances": "snapshot congelado, WAIT, LOOP con checkpoint, dedupe de signals",
            "conversation_router": "conversation_id WAITING reanuda; si no hay, routing normal",
            "capability_registry": "snapshot de capacidades; no ejecuta",
            "packages": "export/import del grafo con checksum",
            "context_store": "contribuciones y timeline append-only",
            "conversation_guard": "contador durable; no es un router",
        },
        "contracts": {
            "subworkflow": CONTRACT,
            "adaptive_route": "adaptive_route",
            "stages": list(STAGES),
            "failure_modes": list(FAILURE_MODES),
        },
        "remaining_gaps": [
            "run_workflow no abre solo una instancia; el proceso durable entra por start_workflow_instance",
        ],
    }


def canonical_snapshot_hash(graph: dict[str, Any], version: int) -> str:
    blob = json.dumps(
        {"version": int(version), "graph": graph},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def freeze_snapshot(
    graph: dict[str, Any],
    version: int,
    *,
    workflow_ref: str,
    status: str = "published",
    output_ports: tuple[str, ...] | list[str] | None = None,
    input_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    frozen = json.loads(json.dumps(graph, default=str))
    digest = canonical_snapshot_hash(frozen, int(version))
    return {
        "contract": CONTRACT,
        "workflow_ref": workflow_ref,
        "version": int(version),
        "status": status,
        "graph": frozen,
        "snapshot_hash": digest,
        "output_ports": list(output_ports or TYPED_PORTS),
        "input_schema": input_schema or {"type": "object"},
    }


def resume_definition(instance: dict[str, Any], live_graph: dict[str, Any] | None = None) -> dict[str, Any]:
    """Grafo del snapshot congelado. `live_graph` no se usa."""
    del live_graph
    snap = instance.get("definition_snapshot") if isinstance(instance, dict) else None
    graph = snap.get("graph") if isinstance(snap, dict) else None
    if not isinstance(graph, dict) or not graph.get("nodes"):
        raise CompositionError("contract_mismatch", "resume sin snapshot congelado")
    return graph


def inherit_permissions(
    parent: frozenset[str] | set[str],
    requested: frozenset[str] | set[str] | None,
) -> frozenset[str]:
    parent_set = frozenset(parent)
    if not requested:
        return parent_set
    return parent_set & frozenset(requested)


def effect_digest(key: str) -> str:
    return hashlib.sha256(str(key).encode("utf-8")).hexdigest()[:32]


def business_effect_key(capability_ref: str, business_id: str) -> str:
    return f"{capability_ref}:{business_id}"


def claim_effect(ledger: dict[str, Any], key: str) -> dict[str, Any]:
    current = ledger.get(key)
    if isinstance(current, dict) and current.get("status") == "applied":
        return {"action": "replay", "output": dict(current.get("output") or {})}
    if isinstance(current, dict) and current.get("status") == "incomplete":
        return {"action": "blocked"}
    ledger[key] = {"status": "started", "output": None, "key": key}
    return {"action": "run"}


def commit_effect(ledger: dict[str, Any], key: str, status: str, output: Any = None) -> None:
    ledger[key] = {"status": status, "output": output, "key": key}


def read_effect(state: dict[str, Any] | None, key: str) -> dict[str, Any] | None:
    bucket = (state or {}).get("__effects")
    if not isinstance(bucket, dict):
        return None
    found = bucket.get(effect_digest(key))
    return dict(found) if isinstance(found, dict) else None


def effect_state_path(key: str) -> str:
    return f"__effects.{effect_digest(key)}"


def schema_errors(payload: Any, schema: dict[str, Any] | None) -> list[str]:
    if not schema:
        return []
    errors: list[str] = []
    expected = str(schema.get("type") or "")
    if expected and not _type_ok(payload, expected):
        errors.append("tipo raíz")
        return errors
    if not isinstance(payload, dict):
        return errors
    for key in schema.get("required") or []:
        if key not in payload:
            errors.append(f"falta {key}")
    props = schema.get("properties") or {}
    if isinstance(props, dict):
        for key, spec in props.items():
            if key not in payload or not isinstance(spec, dict):
                continue
            kind = str(spec.get("type") or "")
            if kind and not _type_ok(payload[key], kind):
                errors.append(f"tipo {key}")
    return errors


def _type_ok(value: Any, expected: str) -> bool:
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    return True


def capability_refs_in_graph(graph: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for node in graph.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        ntype = str(node.get("type") or "")
        cfg = node.get("config") if isinstance(node.get("config"), dict) else {}
        if ntype == "capability_call":
            ref = str(cfg.get("capability") or "").strip()
            if ref:
                refs.append(ref)
        elif ntype == "kb_query":
            refs.append("node.kb_query")
        elif ntype == "subworkflow_call":
            ref = str(cfg.get("workflow_ref") or "").strip()
            if ref:
                refs.append(ref if ref.startswith("subflow.") else f"subflow.{ref}")
    return refs


def durable_nodes(graph: dict[str, Any]) -> list[str]:
    found: list[str] = []
    for node in graph.get("nodes") or []:
        if isinstance(node, dict) and node.get("type") in DURABLE_NODE_TYPES:
            found.append(str(node.get("id") or node.get("type")))
    return found


def prepare_subworkflow_call(
    config: dict[str, Any],
    *,
    parent_permissions: frozenset[str] | set[str],
    stack: list[str] | None = None,
    depth: int = 0,
) -> dict[str, Any]:
    if config.get("resolve") == "live" or config.get("use_live"):
        raise CompositionError("contract_mismatch", "versión viva rechazada")
    snapshot = config.get("snapshot")
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("graph"), dict):
        raise CompositionError("contract_mismatch", "subworkflow.call exige snapshot congelado")
    status = str(snapshot.get("status") or "published")
    if status not in SUBFLOW_STATES:
        raise CompositionError("contract_mismatch", f"estado de subflujo inválido: {status}")
    if status != "published":
        raise CompositionError(
            "contract_mismatch", f"subflujo {status}; solo se ejecuta published"
        )
    try:
        version = int(snapshot.get("version", config.get("version")))
    except (TypeError, ValueError):
        raise CompositionError("contract_mismatch", "version ausente") from None
    graph = snapshot["graph"]
    actual = canonical_snapshot_hash(graph, version)
    expected = str(snapshot.get("snapshot_hash") or "")
    if expected and expected != actual:
        raise CompositionError("contract_mismatch", "snapshot_hash no coincide")
    ref = str(config.get("workflow_ref") or snapshot.get("workflow_ref") or "").strip()
    if not ref:
        raise CompositionError("contract_mismatch", "workflow_ref ausente")
    trail = list(stack or [])
    if ref in trail:
        raise CompositionError("contract_mismatch", "ciclo de subworkflow")
    try:
        max_depth = int(config.get("max_depth") or DEFAULT_MAX_DEPTH)
        max_retries = int(config.get("max_retries") or 1)
    except (TypeError, ValueError):
        raise CompositionError("contract_mismatch", "límites inválidos") from None
    if max_depth < 1 or max_depth > MAX_DEPTH_HARD:
        raise CompositionError("contract_mismatch", "max_depth supera el límite")
    if depth >= max_depth:
        raise CompositionError("contract_mismatch", "profundidad máxima")
    if max_retries < 1 or max_retries > MAX_RETRIES_HARD:
        raise CompositionError("contract_mismatch", "reintentos fuera de rango")
    try:
        max_fanout = int(config.get("max_fanout") or 10)
    except (TypeError, ValueError):
        raise CompositionError("contract_mismatch", "fan-out inválido") from None
    if max_fanout < 1 or max_fanout > MAX_FANOUT_HARD:
        raise CompositionError("contract_mismatch", "fan-out supera el límite")
    blockers = durable_nodes(graph)
    if blockers:
        raise CompositionError(
            "contract_mismatch",
            "WAIT, LOOP o aprobación van en el proceso padre: " + ", ".join(blockers),
        )
    try:
        from src.platform.workflows.ir import WorkflowGraph, WorkflowGraphError, validate_graph

        validate_graph(WorkflowGraph.from_dict(graph))
    except WorkflowGraphError as exc:
        raise CompositionError("contract_mismatch", f"grafo hijo inválido: {exc}") from exc
    if "registry_refs" not in config or not isinstance(config.get("registry_refs"), list):
        raise CompositionError("contract_mismatch", "registry_refs congelados ausentes")
    registry_refs = set(config.get("registry_refs") or [])
    unknown = [ref_id for ref_id in capability_refs_in_graph(graph) if ref_id not in registry_refs]
    if unknown:
        raise CompositionError("unauthorized_tool", "capacidad no anunciada: " + ", ".join(unknown))
    requested_raw = config.get("permissions")
    requested = frozenset(str(item) for item in requested_raw) if isinstance(requested_raw, list) else None
    effective = inherit_permissions(parent_permissions, requested)
    dropped = sorted(frozenset(requested) - frozenset(parent_permissions)) if requested else []
    budget = config.get("budget") if isinstance(config.get("budget"), dict) else {}
    try:
        timeout_seconds = int(
            budget.get("max_duration_seconds") or config.get("timeout_seconds") or 60
        )
    except (TypeError, ValueError):
        raise CompositionError("contract_mismatch", "timeout inválido") from None
    if timeout_seconds < 1 or timeout_seconds > 86400:
        raise CompositionError("contract_mismatch", "timeout fuera de rango")
    inputs = config.get("inputs") if isinstance(config.get("inputs"), dict) else {}
    input_schema = config.get("input_schema")
    if not isinstance(input_schema, dict):
        input_schema = {"type": "object"}
    input_errors = schema_errors(inputs, input_schema)
    if input_errors:
        raise CompositionError("contract_mismatch", "; ".join(input_errors))
    idempotency_key = str(config.get("idempotency_key") or "").strip()
    if not idempotency_key:
        raise CompositionError("contract_mismatch", "idempotency_key ausente")
    return {
        "contract": CONTRACT,
        "version": version,
        "workflow_ref": ref,
        "snapshot_hash": actual,
        "snapshot": {
            "version": version,
            "status": status,
            "graph": graph,
            "snapshot_hash": actual,
            "workflow_ref": ref,
            "output_ports": list(snapshot.get("output_ports") or TYPED_PORTS),
        },
        "status": status,
        "output_ports": list(snapshot.get("output_ports") or TYPED_PORTS),
        "inputs": inputs,
        "output_schema": (
            config.get("output_schema")
            if isinstance(config.get("output_schema"), dict)
            else {"type": "object"}
        ),
        "effective_permissions": sorted(effective),
        "dropped_permissions": dropped,
        "max_depth": max_depth,
        "depth": depth,
        "stack": trail + [ref],
        "timeout_seconds": timeout_seconds,
        "max_retries": max_retries,
        "max_fanout": max_fanout,
        "idempotency_key": idempotency_key,
        "budget": {
            "max_duration_seconds": timeout_seconds,
            "max_cost_usd": budget.get("max_cost_usd"),
            "max_tokens": budget.get("max_tokens"),
        },
        "correlation": config.get("correlation") if isinstance(config.get("correlation"), dict) else {},
    }


def composition_frame(payload: dict[str, Any] | None) -> tuple[list[str], int]:
    raw = payload.get("__composition") if isinstance(payload, dict) else None
    if not isinstance(raw, dict):
        return [], 0
    stack = [str(item) for item in raw.get("stack") or []]
    try:
        depth = int(raw.get("depth") or 0)
    except (TypeError, ValueError):
        depth = 0
    return stack, depth


def normalize_proposal(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    if any(field not in raw for field in PROPOSAL_FIELDS):
        return None
    try:
        confidence = float(raw["confidence"])
    except (TypeError, ValueError):
        return None
    if confidence < 0 or confidence > 1:
        return None
    missing = raw.get("missing_information")
    if not isinstance(missing, list):
        return None
    transition = raw.get("allowed_transition_id")
    return {
        "route": str(raw.get("route") or ""),
        "confidence": confidence,
        "rationale_summary": str(raw.get("rationale_summary") or "")[:500],
        "missing_information": [str(item) for item in missing][:8],
        "recommended_next_action": str(raw.get("recommended_next_action") or "")[:200],
        "allowed_transition_id": None if transition in (None, "") else str(transition),
    }


def clarification_message(
    mode: str,
    missing: list[str],
    guard: dict[str, Any] | None,
    recommended: str = "",
) -> str:
    warning = bool((guard or {}).get("warning"))
    if mode == "missing_data":
        detail = ", ".join(missing) or "un dato concreto"
        text = f"Me falta: {detail}."
    elif mode == "provider_unavailable":
        text = "Esa función no está disponible ahora. Puedes reformular o pedir a una persona."
    elif mode == "unauthorized_tool":
        text = "No tengo permiso para esa acción. Puedo ayudarte con otra cosa o pasarte con una persona."
    elif recommended:
        text = f"No estoy seguro. Si quieres, puedo {recommended}."
    else:
        text = "Necesito un dato más concreto para seguir."
    if warning:
        return text + " Si prefieres, te paso con una persona."
    return text


def _blank_decision() -> dict[str, Any]:
    return {
        "route": "",
        "confidence": 0.0,
        "rationale_summary": "",
        "missing_information": [],
        "recommended_next_action": "",
        "allowed_transition_id": None,
        "capability_ref": None,
        "execute_capability": False,
        "stage": None,
        "message": "",
        "failure_mode": None,
        "decision": "halt",
        "port": "halt",
        "typed_port": "needs_human",
        "control": None,
        "causal": None,
        "handoff": None,
    }


def _finish(decision: dict[str, Any]) -> dict[str, Any]:
    kind = decision["decision"]
    if kind in {"transition", "compensation"} and decision.get("allowed_transition_id"):
        decision["port"] = str(decision["allowed_transition_id"])
    elif kind == "clarification":
        decision["port"] = "clarify"
    elif kind == "wait":
        decision["port"] = "wait"
    elif kind == "intervention":
        decision["port"] = "intervene"
    else:
        decision["port"] = "halt"
    decision["execute_capability"] = kind in {"transition", "compensation"} and bool(
        decision.get("capability_ref")
    )
    decision["typed_port"] = typed_port_for_decision(
        kind,
        failure_mode=decision.get("failure_mode"),
        control=decision.get("control"),
    )
    return decision


def _selectable(
    allowlist: list[dict[str, Any]],
    registry_refs: set[str],
    permissions: frozenset[str] | None,
    denied_refs: set[str],
) -> list[dict[str, Any]]:
    chosen: list[dict[str, Any]] = []
    for item in allowlist:
        if not isinstance(item, dict):
            continue
        ref = str(item.get("capability_ref") or "")
        if not ref or ref not in registry_refs or ref in denied_refs:
            continue
        needed = item.get("requires_permission")
        if needed and permissions is not None and str(needed) not in permissions:
            continue
        if not item.get("id"):
            continue
        chosen.append(item)
    return chosen


def _find_item(items: list[dict[str, Any]], transition_id: str | None) -> dict[str, Any] | None:
    if not transition_id:
        return None
    for item in items:
        if str(item.get("id")) == transition_id:
            return item
    return None


def _proposal_matches(proposal: dict[str, Any], item: dict[str, Any]) -> bool:
    ref = str(item.get("capability_ref") or "")
    route = proposal["route"]
    return route in {str(item.get("id")), ref}


def build_handoff(
    *,
    purpose: str,
    target_role: str,
    source_role: str,
    state: dict[str, Any] | None,
    allow_fields: list[str],
    consent: bool = False,
) -> dict[str, Any]:
    if not str(purpose or "").strip():
        raise CompositionError("contract_mismatch", "handoff sin finalidad")
    if not str(target_role or "").strip():
        raise CompositionError("contract_mismatch", "handoff sin rol destino")
    source = state or {}
    context: dict[str, Any] = {}
    for field in allow_fields:
        key = str(field)
        if key not in source:
            continue
        if key in SENSITIVE_FIELDS and not consent:
            continue
        context[key] = source[key]
    return {
        "purpose": str(purpose).strip(),
        "source_role": str(source_role or ""),
        "target_role": str(target_role).strip(),
        "context": context,
        "consent": bool(consent),
        "return_schema": {
            "type": "object",
            "required": ["status", "result", "reason_codes"],
            "properties": {
                "status": {"type": "string"},
                "result": {"type": "object"},
                "reason_codes": {"type": "array"},
            },
        },
    }


def causal_record(
    *,
    message_id: str | None,
    decision_id: str | None,
    action_id: str | None,
    instance_id: str | None = None,
) -> dict[str, Any]:
    return {
        "message_id": message_id,
        "decision_id": decision_id,
        "action_id": action_id,
        "instance_id": instance_id,
    }


def _attach_handoff(
    decision: dict[str, Any],
    handoff: dict[str, Any] | None,
    state: dict[str, Any] | None,
) -> dict[str, Any]:
    if decision["decision"] not in {"intervention", "wait"} or not isinstance(handoff, dict):
        return decision
    try:
        decision["handoff"] = build_handoff(
            purpose=str(handoff.get("purpose") or ""),
            target_role=str(handoff.get("target_role") or ""),
            source_role=str(handoff.get("source_role") or ""),
            state=state,
            allow_fields=[str(item) for item in handoff.get("allow_fields") or []],
            consent=bool(handoff.get("consent")),
        )
    except CompositionError as exc:
        halted = _blank_decision()
        halted.update(
            {
                "decision": "halt",
                "failure_mode": exc.code,
                "control": "stop_fail",
                "rationale_summary": exc.message,
                "message": exc.message,
            }
        )
        return _finish(halted)
    return decision


def decide_adaptive(
    proposal: dict[str, Any] | None,
    *,
    allowlist: list[dict[str, Any]] | None,
    registry_refs: set[str] | list[str] | None,
    guard: dict[str, Any] | None = None,
    failure_mode: str | None = None,
    confidence_min: float = DEFAULT_CONFIDENCE_MIN,
    on_unauthorized: str = "handoff",
    on_contract_mismatch: str = "halt",
    permissions: frozenset[str] | set[str] | None = None,
    denied_refs: set[str] | None = None,
    handoff: dict[str, Any] | None = None,
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    guard = guard or {}
    allowlist = [item for item in (allowlist or []) if isinstance(item, dict)]
    announced = {str(item) for item in (registry_refs or [])}
    denied = set(denied_refs or ())
    perms = frozenset(permissions) if permissions is not None else None
    blocked = bool(guard.get("blocked") or guard.get("allowed") is False)
    parsed = normalize_proposal(proposal)
    selectable = _selectable(allowlist, announced, perms, denied)

    def emit(**kwargs: Any) -> dict[str, Any]:
        decision = _blank_decision()
        if parsed:
            decision.update(
                {
                    "route": parsed["route"],
                    "confidence": parsed["confidence"],
                    "rationale_summary": parsed["rationale_summary"],
                    "missing_information": list(parsed["missing_information"]),
                    "recommended_next_action": parsed["recommended_next_action"],
                    "allowed_transition_id": parsed["allowed_transition_id"],
                }
            )
        decision.update(kwargs)
        return _attach_handoff(_finish(decision), handoff, state)

    if failure_mode == "user_cancelled":
        return emit(
            decision="halt",
            failure_mode="user_cancelled",
            control="stop_success",
            rationale_summary="usuario canceló",
            message="Proceso cancelado.",
            execute_capability=False,
            capability_ref=None,
            allowed_transition_id=None,
        )
    if failure_mode == "human_requested":
        return emit(
            decision="intervention",
            failure_mode="human_requested",
            rationale_summary="la persona pidió a un humano",
            message="Te paso con una persona.",
            capability_ref=None,
            allowed_transition_id=None,
        )
    if failure_mode == "timeout":
        return emit(
            decision="halt",
            failure_mode="timeout",
            control="stop_fail",
            rationale_summary="timeout",
            message="Se agotó el tiempo. Puedes reintentar con un dato concreto.",
            capability_ref=None,
            allowed_transition_id=None,
        )
    if failure_mode == "contract_mismatch":
        if on_contract_mismatch == "compensate":
            compensation = next((item for item in selectable if item.get("stage") == "compensation"), None)
            if compensation is not None:
                return emit(
                    decision="compensation",
                    failure_mode="contract_mismatch",
                    allowed_transition_id=str(compensation["id"]),
                    capability_ref=str(compensation["capability_ref"]),
                    stage="compensation",
                    route=str(compensation["id"]),
                    rationale_summary="contrato inválido; compensación anunciada",
                    message="No pude completar la acción. Sigo la compensación anunciada.",
                )
        return emit(
            decision="halt",
            failure_mode="contract_mismatch",
            control="stop_fail",
            rationale_summary="contrato inválido",
            message="El contrato no coincide. No ejecuté la acción.",
            capability_ref=None,
            allowed_transition_id=None,
        )

    def intervene(mode: str, message: str) -> dict[str, Any]:
        return emit(
            decision="intervention",
            failure_mode=mode,
            message=message,
            rationale_summary=message,
            capability_ref=None,
            allowed_transition_id=None,
        )

    def clarify(mode: str, missing: list[str], recommended: str = "") -> dict[str, Any]:
        if blocked:
            return intervene(mode, "Te paso con una persona para no seguir en círculo.")
        text = clarification_message(mode, missing, guard, recommended)
        return emit(
            decision="clarification",
            failure_mode=mode,
            missing_information=missing,
            message=text,
            rationale_summary=text,
            capability_ref=None,
            allowed_transition_id=None,
        )

    def unauthorized(mode: str = "unauthorized_tool") -> dict[str, Any]:
        if on_unauthorized == "next_authorized":
            nxt = next((item for item in selectable if item.get("stage") == "capability_execution"), None)
            if nxt is not None and (not parsed or str(nxt.get("id")) != parsed.get("allowed_transition_id")):
                return emit(
                    decision="transition",
                    failure_mode=None,
                    allowed_transition_id=str(nxt["id"]),
                    capability_ref=str(nxt["capability_ref"]),
                    stage=str(nxt.get("stage") or "capability_execution"),
                    route=str(nxt["id"]),
                    rationale_summary="la acción pedida no está autorizada; sigo la siguiente anunciada",
                    recommended_next_action=str(nxt["id"]),
                    message="",
                )
        handoff_item = next((item for item in selectable if item.get("stage") == "human_handoff"), None)
        if on_unauthorized in {"handoff", "next_authorized"} and handoff_item is not None:
            return emit(
                decision="intervention",
                failure_mode=mode,
                message="No puedo hacer esa acción. Te paso con una persona.",
                rationale_summary="sin permiso o sin capacidad anunciada",
                capability_ref=None,
                allowed_transition_id=None,
            )
        return clarify(mode, [], "")

    if failure_mode == "provider_unavailable":
        return clarify("provider_unavailable", [], "")
    if failure_mode == "unauthorized_tool":
        return unauthorized()
    if failure_mode == "low_confidence":
        recommended = parsed["recommended_next_action"] if parsed else ""
        return clarify("low_confidence", [], recommended)
    if failure_mode == "missing_data":
        missing = parsed["missing_information"] if parsed else ["dato requerido"]
        return clarify("missing_data", missing or ["dato requerido"], "")
    if parsed is None:
        return clarify("missing_data", ["propuesta de ruta"], "")
    if parsed["missing_information"]:
        return clarify("missing_data", parsed["missing_information"], parsed["recommended_next_action"])
    if parsed["confidence"] < float(confidence_min):
        return clarify("low_confidence", [], parsed["recommended_next_action"])

    if allowlist and not selectable:
        return emit(
            decision="halt",
            failure_mode="contract_mismatch",
            control="stop_fail",
            rationale_summary="ninguna acción anunciada",
            message="El contrato no coincide. No ejecuté la acción.",
            capability_ref=None,
            allowed_transition_id=None,
        )
    item = _find_item(selectable, parsed["allowed_transition_id"])
    if item is None or not _proposal_matches(parsed, item):
        return unauthorized()
    if str(item.get("stage") or "") == "human_handoff":
        return emit(
            decision="wait",
            failure_mode=None,
            allowed_transition_id=str(item["id"]),
            capability_ref=None,
            stage="human_handoff",
            route=str(item["id"]),
            rationale_summary=parsed["rationale_summary"],
            message="Quedo a la espera de una persona.",
            execute_capability=False,
        )
    if str(item.get("stage") or "") == "compensation":
        return emit(
            decision="compensation",
            allowed_transition_id=str(item["id"]),
            capability_ref=str(item["capability_ref"]),
            stage="compensation",
            route=str(item["id"]),
            rationale_summary=parsed["rationale_summary"],
        )
    return emit(
        decision="transition",
        allowed_transition_id=str(item["id"]),
        capability_ref=str(item["capability_ref"]),
        stage=str(item.get("stage") or "capability_execution"),
        route=parsed["route"],
        rationale_summary=parsed["rationale_summary"],
        recommended_next_action=parsed["recommended_next_action"],
        confidence=parsed["confidence"],
        missing_information=[],
    )


def downstream_matches(route: dict[str, Any], node_type: str, config: dict[str, Any] | None) -> bool:
    ref = str(route.get("capability_ref") or "")
    cfg = config or {}
    if node_type == "capability_call":
        return ref == str(cfg.get("capability") or "")
    if node_type == "kb_query":
        return ref in {"node.kb_query", "kb_query"}
    if node_type == "subworkflow_call":
        wanted = str(cfg.get("workflow_ref") or "")
        return ref in {wanted, f"subflow.{wanted}"}
    return ref == f"node.{node_type}"


def upstream_route_block(
    inputs: dict[str, Any] | None,
    node_types: dict[str, str] | None,
    node_type: str,
    config: dict[str, Any] | None,
) -> str | None:
    route: dict[str, Any] | None = None
    for by_port in (inputs or {}).values():
        if not isinstance(by_port, dict):
            continue
        for node_id, execution in by_port.items():
            ntype = (node_types or {}).get(node_id)
            output = getattr(execution, "output", None)
            if not isinstance(output, dict):
                continue
            if ntype == "adaptive_route" or (ntype == "subworkflow_call" and output.get("decision")):
                route = output
    if route is None or node_type in {"adaptive_route", "end", "stop", "condition", "set_variable"}:
        return None
    decision = str(route.get("decision") or "")
    if decision in {"transition", "compensation"}:
        if node_type not in SIDE_EFFECT_NODES:
            return None
        if downstream_matches(route, node_type, config):
            return None
        return "unauthorized_tool"
    if node_type in SIDE_EFFECT_NODES:
        return "unauthorized_tool"
    return None


def accept_evaluation(payload: dict[str, Any] | None) -> dict[str, Any]:
    body = payload or {}
    if body.get("source") != "capability":
        return {"accepted": False, "failure_mode": "contract_mismatch", "score": None}
    if "score" not in body:
        return {"accepted": False, "failure_mode": "missing_data", "score": None}
    return {
        "accepted": True,
        "failure_mode": None,
        "score": body.get("score"),
        "capability_ref": body.get("capability_ref"),
    }


def wellness_critical(text: str) -> bool:
    folded = str(text or "").lower()
    return any(marker in folded for marker in CRITICAL_MARKERS)


def apply_seller_product_change(state: dict[str, Any], product: str) -> dict[str, Any]:
    cart = list(state.get("cart") or [])
    updated = dict(state)
    updated["cart"] = cart
    updated["pending_product"] = product
    order_id = str(state.get("order_id") or "draft")
    return {
        "state": updated,
        "cart": cart,
        "payment_effect_key": business_effect_key("payments.checkout.create", order_id),
        "process_key": state.get("business_key") or state.get("conversation_id"),
    }


def route_mentor(
    state: dict[str, Any],
    new_goal: str | None,
    progress: dict[str, Any] | None,
    proposed_evaluation: dict[str, Any] | None,
) -> dict[str, Any]:
    updated = dict(state)
    if new_goal:
        updated["goal"] = new_goal
    evaluation = accept_evaluation(proposed_evaluation)
    exercise = None
    if isinstance(progress, dict) and progress.get("source") == "capability":
        exercise = progress.get("next_exercise")
    return {
        "state": updated,
        "evaluation": evaluation,
        "next_exercise": exercise,
        "progress_kept": state.get("progress"),
    }


def route_support(
    proposal: dict[str, Any] | None,
    *,
    registry_refs: set[str],
    permissions: frozenset[str],
    guard: dict[str, Any] | None = None,
) -> dict[str, Any]:
    allowlist = [
        {
            "id": "consultar_conocimiento",
            "capability_ref": "node.kb_query",
            "stage": "capability_execution",
        },
        {
            "id": "abrir_caso",
            "capability_ref": "support.case.open",
            "stage": "capability_execution",
            "requires_permission": "support:case",
        },
        {
            "id": "escalar_humano",
            "capability_ref": "subflow.escalar_humano",
            "stage": "human_handoff",
        },
    ]
    return decide_adaptive(
        proposal,
        allowlist=allowlist,
        registry_refs=registry_refs,
        permissions=permissions,
        guard=guard,
        on_unauthorized="next_authorized",
        handoff={
            "purpose": "derivar soporte",
            "target_role": "support_human",
            "source_role": "support",
            "allow_fields": ["topic", "locale"],
        },
        state=None,
    )


def route_auditor(
    *,
    incongruent: bool,
    evidence: dict[str, Any],
    registry_refs: set[str],
) -> dict[str, Any]:
    if not incongruent:
        return {
            "decision": "transition",
            "execute_capability": False,
            "evidence": evidence,
            "port": "out",
            "failure_mode": None,
        }
    decision = decide_adaptive(
        {
            "route": "solicitar_aprobacion",
            "confidence": 0.95,
            "rationale_summary": "incongruencia en la evidencia",
            "missing_information": [],
            "recommended_next_action": "solicitar_aprobacion",
            "allowed_transition_id": "solicitar_aprobacion",
        },
        allowlist=[
            {
                "id": "solicitar_aprobacion",
                "capability_ref": "subflow.solicitar_aprobacion",
                "stage": "human_handoff",
            }
        ],
        registry_refs=registry_refs,
        handoff={
            "purpose": "aprobar evidencia incongruente",
            "target_role": "auditor",
            "source_role": "auditor_agent",
            "allow_fields": ["finding_id"],
        },
        state=evidence,
    )
    decision["evidence"] = evidence
    return decision


def route_wellness(
    message: str,
    state: dict[str, Any],
    proposal: dict[str, Any] | None,
    *,
    registry_refs: set[str],
    consent: bool = False,
    guard: dict[str, Any] | None = None,
) -> dict[str, Any]:
    safe_state = {
        key: value
        for key, value in state.items()
        if key not in SENSITIVE_FIELDS or consent
    }
    handoff = {
        "purpose": "contención y derivación, sin diagnóstico",
        "target_role": "human_support",
        "source_role": "wellness",
        "allow_fields": ["locale"],
        "consent": consent,
    }
    if wellness_critical(message):
        decision = decide_adaptive(
            None,
            allowlist=[
                {
                    "id": "escalar_humano",
                    "capability_ref": "subflow.escalar_humano",
                    "stage": "human_handoff",
                }
            ],
            registry_refs=registry_refs | {"subflow.escalar_humano"},
            failure_mode="human_requested",
            handoff=handoff,
            state=safe_state,
            denied_refs=set(DIAGNOSIS_REFS),
        )
    else:
        decision = decide_adaptive(
            proposal,
            allowlist=[
                {
                    "id": "conversar",
                    "capability_ref": "conversation.reply",
                    "stage": "capability_execution",
                },
                {
                    "id": "escalar_humano",
                    "capability_ref": "subflow.escalar_humano",
                    "stage": "human_handoff",
                },
            ],
            registry_refs=registry_refs,
            guard=guard,
            handoff=handoff,
            state=safe_state,
            denied_refs=set(DIAGNOSIS_REFS),
            on_unauthorized="handoff",
        )
    decision["stored_state"] = {
        key: value
        for key, value in safe_state.items()
        if key not in SENSITIVE_FIELDS or consent
    }
    decision["diagnosis"] = None
    return decision


def _node(
    nid: str,
    ntype: str,
    label: str,
    config: dict[str, Any] | None = None,
    *,
    ports: list[str] | None = None,
) -> dict[str, Any]:
    node: dict[str, Any] = {
        "id": nid,
        "type": ntype,
        "label": label,
        "config": config or {},
        "input_ports": [{"name": "in", "type": "json"}],
        "output_ports": [{"name": port, "type": "json"} for port in (ports or ["out"])],
    }
    return node


def _edge(src: str, dst: str, port: str = "out") -> dict[str, str]:
    return {
        "id": f"{src}_{port}_{dst}",
        "from_node": src,
        "from_port": port,
        "to_node": dst,
        "to_port": "in",
    }


def _graph(name: str, nodes: list[dict[str, Any]], edges: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "workflow_version": 2,
        "nodes": nodes,
        "edges": edges,
        "entrypoints": [nodes[0]["id"]],
        "variables": {},
        "metadata": {"subflow": name, "contract": CONTRACT, "kind": "nested" if name in NESTED_SUBFLOWS else "inline"},
    }


_ADAPTIVE_PORTS = ["transition", "clarify", "wait", "intervene", "compensate", "halt"]


def portable_subflow(name: str) -> dict[str, Any]:
    if name == "identificar_intencion":
        ports = [
            "consultar_conocimiento",
            "preguntar_aclaracion",
            "escalar_humano",
            "clarify",
            "wait",
            "intervene",
            "halt",
        ]
        return _graph(
            name,
            [
                _node("start", "trigger_event", "Inicio"),
                _node("intent", "llm", "Entender intención", {"purpose": "intent_understanding"}),
                _node(
                    "result",
                    "adaptive_route",
                    "Elegir ruta",
                    {
                        "stage": "intent_understanding",
                        "registry_refs": [
                            "node.kb_query",
                            "subflow.preguntar_aclaracion",
                            "subflow.escalar_humano",
                        ],
                        "allowlist": [
                            {
                                "id": "consultar_conocimiento",
                                "capability_ref": "node.kb_query",
                                "stage": "capability_execution",
                            },
                            {
                                "id": "preguntar_aclaracion",
                                "capability_ref": "subflow.preguntar_aclaracion",
                                "stage": "wait",
                            },
                            {
                                "id": "escalar_humano",
                                "capability_ref": "subflow.escalar_humano",
                                "stage": "human_handoff",
                            },
                        ],
                    },
                    ports=ports,
                ),
                _node("end", "end", "Fin"),
            ],
            [
                _edge("start", "intent"),
                _edge("intent", "result"),
                *[_edge("result", "end", port) for port in ports],
            ],
        )
    if name == "consultar_conocimiento":
        return _graph(
            name,
            [
                _node("start", "trigger_event", "Inicio"),
                _node(
                    "result",
                    "kb_query",
                    "Consultar conocimiento",
                    {"operation": "search", "query": "{{trigger.text}}"},
                ),
                _node("end", "end", "Fin"),
            ],
            [_edge("start", "result"), _edge("result", "end")],
        )
    if name == "preguntar_aclaracion":
        return _graph(
            name,
            [
                _node("start", "trigger_event", "Inicio"),
                _node("guard", "conversation_guard", "Guardia", {"mode": "check", "scope": "conversation"}),
                _node("wait", "wait_event", "Esperar dato", {"preset": "message", "timeout": "PT24H"}),
                _node("end", "end", "Fin"),
            ],
            [_edge("start", "guard"), _edge("guard", "wait"), _edge("wait", "end")],
        )
    if name == "evaluar_ejercicio":
        return _graph(
            name,
            [
                _node("start", "trigger_event", "Inicio"),
                _node(
                    "result",
                    "capability_call",
                    "Evaluar ejercicio",
                    {
                        "capability": "learning.exercise.evaluate",
                        "inputs": {"exercise_id": "{{trigger.exercise_id}}"},
                    },
                ),
                _node("end", "end", "Fin"),
            ],
            [_edge("start", "result"), _edge("result", "end")],
        )
    if name == "registrar_progreso":
        return _graph(
            name,
            [
                _node("start", "trigger_event", "Inicio"),
                _node(
                    "result",
                    "state_merge",
                    "Registrar progreso",
                    {"path": "progress", "value": {"goal": "{{trigger.goal}}"}},
                ),
                _node("end", "end", "Fin"),
            ],
            [_edge("start", "result"), _edge("result", "end")],
        )
    if name == "solicitar_aprobacion":
        return _graph(
            name,
            [
                _node("start", "trigger_event", "Inicio"),
                _node(
                    "approval",
                    "human_approval",
                    "Aprobación",
                    {"action": "aprobar evidencia", "summary": "{{trigger.summary}}"},
                ),
                _node("end", "end", "Fin"),
            ],
            [_edge("start", "approval"), _edge("approval", "end")],
        )
    if name == "cobrar_pedido":
        return _graph(
            name,
            [
                _node("start", "trigger_event", "Inicio"),
                _node(
                    "result",
                    "capability_call",
                    "Cobrar",
                    {
                        "capability": "payments.checkout.create",
                        "inputs": {
                            "order_id": "{{trigger.order_id}}",
                            "idempotency_key": "{{trigger.idempotency_key}}",
                        },
                    },
                ),
                _node("end", "end", "Fin"),
            ],
            [_edge("start", "result"), _edge("result", "end")],
        )
    if name == "escalar_humano":
        return _graph(
            name,
            [
                _node("start", "trigger_event", "Inicio"),
                _node(
                    "route",
                    "adaptive_route",
                    "Escalar",
                    {
                        "failure_mode": "human_requested",
                        "handoff": {
                            "purpose": "escalar a un especialista",
                            "target_role": "specialist",
                            "source_role": "router",
                            "allow_fields": ["topic", "locale"],
                        },
                    },
                    ports=["intervene", "halt"],
                ),
                _node("wait", "wait_event", "Esperar humano", {"preset": "human"}),
                _node("end", "end", "Fin"),
            ],
            [
                _edge("start", "route"),
                _edge("route", "wait", "intervene"),
                _edge("route", "end", "halt"),
                _edge("wait", "end"),
            ],
        )
    raise CompositionError("contract_mismatch", f"subflujo desconocido: {name}")


@dataclass(frozen=True)
class SubflowDefinition:
    """Definición publicada de un subflujo. No es un segundo workflow store."""

    name: str
    version: int
    status: str
    graph: dict[str, Any]
    output_ports: tuple[str, ...] = TYPED_PORTS
    durable: bool = False

    @property
    def capability_ref(self) -> str:
        return subflow_capability_ref(self.name)

    def snapshot(self) -> dict[str, Any]:
        return freeze_snapshot(
            self.graph,
            self.version,
            workflow_ref=self.name,
            status=self.status,
            output_ports=self.output_ports,
        )

    def public(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "status": self.status,
            "capability_ref": self.capability_ref,
            "durable": self.durable,
            "runnable_inline": not self.durable,
            "output_ports": list(self.output_ports),
            "node_config": self.node_config(),
        }

    def node_config(self) -> dict[str, Any]:
        return {
            "workflow_ref": self.name,
            "version": self.version,
            "snapshot": self.snapshot(),
            "registry_refs": capability_refs_in_graph(self.graph),
            "idempotency_key": "{{trigger.idempotency_key}}",
            "max_depth": DEFAULT_MAX_DEPTH,
            "max_retries": 1,
            "max_fanout": 10,
            "input_schema": {"type": "object"},
            "output_schema": {"type": "object"},
        }


def subflow_definition(
    name: str,
    version: int = 1,
    *,
    status: str = "published",
) -> SubflowDefinition:
    if name not in PORTABLE_SUBFLOWS:
        raise CompositionError("contract_mismatch", f"subflujo desconocido: {name}")
    if status not in SUBFLOW_STATES:
        raise CompositionError("contract_mismatch", f"estado de subflujo inválido: {status}")
    graph = portable_subflow(name)
    return SubflowDefinition(
        name=name,
        version=max(1, int(version)),
        status=status,
        graph=graph,
        durable=bool(durable_nodes(graph)),
    )


def subflow_library() -> list[dict[str, Any]]:
    return [subflow_definition(name).public() for name in PORTABLE_SUBFLOWS]


def fanout_plan(items: list[Any], *, max_fanout: int = 10) -> dict[str, Any]:
    """Un fan-out nunca crece por encima del contrato congelado."""
    try:
        limit = int(max_fanout)
    except (TypeError, ValueError):
        raise CompositionError("contract_mismatch", "fan-out inválido") from None
    if limit < 1 or limit > MAX_FANOUT_HARD:
        raise CompositionError("contract_mismatch", "fan-out supera el límite")
    body = list(items or [])
    return {
        "items": body[:limit],
        "requested": len(body),
        "dropped": max(0, len(body) - limit),
        "truncated": len(body) > limit,
        "max_fanout": limit,
    }


def saga_compensation_plan(effects: list[dict[str, Any]]) -> dict[str, Any]:
    """Compensaciones en orden inverso, con claves idempotentes propias."""
    steps: list[dict[str, Any]] = []
    for index, effect in enumerate(reversed([item for item in effects if isinstance(item, dict)])):
        ref = str(effect.get("capability_ref") or effect.get("action") or "").strip()
        if not ref:
            raise CompositionError("contract_mismatch", "compensación sin capacidad")
        business_id = str(effect.get("business_id") or effect.get("order_id") or "")
        key = str(effect.get("effect_key") or "").strip() or (
            business_effect_key(ref, business_id) if business_id else f"{ref}:{index}"
        )
        steps.append(
            {
                "capability_ref": ref,
                "effect_key": key,
                "idempotency_key": f"compensate:{effect_digest(key)}:{index}",
                "output": effect.get("output"),
            }
        )
    return {"steps": steps, "typed_port": "compensated", "compensated": len(steps) > 0}


def is_nestable(name: str) -> bool:
    if name not in NESTED_SUBFLOWS:
        return False
    return not durable_nodes(portable_subflow(name))


def subflow_capability_ref(name: str) -> str:
    return f"subflow.{name}"


async def execute_frozen_subworkflow(
    spec: dict[str, Any],
    *,
    organization_id: Any,
    workflow_id: Any,
    run_id: Any,
    actor_type: str,
    permissions: frozenset[str],
    correlation_id: str | None,
    workspace_id: Any,
    actor_id: Any,
    instance_id: Any,
) -> Any:
    from src.platform.workflows.ir import WorkflowGraph
    from src.platform.workflows.runtime import ExecutionContext, execute_graph

    graph = WorkflowGraph.from_dict(spec["snapshot"]["graph"])
    ctx = ExecutionContext(
        organization_id=organization_id,
        workflow_id=workflow_id,
        run_id=run_id,
        actor_type=actor_type,
        trigger_type="subworkflow",
        permissions=frozenset(permissions),
        correlation_id=correlation_id,
        workspace_id=workspace_id,
        actor_id=actor_id,
        simulate=False,
        instance_id=instance_id,
    )
    payload = dict(spec["inputs"])
    payload["idempotency_key"] = spec["idempotency_key"]
    payload["__composition"] = {"depth": spec["depth"] + 1, "stack": list(spec["stack"])}
    correlation = spec.get("correlation") or {}
    for key in ("conversation_id", "business_key"):
        if correlation.get(key) and key not in payload:
            payload[key] = correlation[key]
    return await execute_graph(graph, ctx, payload, persist_execution=False)


def child_public_output(result: Any) -> dict[str, Any]:
    nodes = getattr(result, "node_executions", {}) or {}
    if "result" in nodes:
        output = getattr(nodes["result"], "output", None)
        if isinstance(output, dict):
            return dict(output)
    public: dict[str, Any] = {}
    for node_id, execution in nodes.items():
        output = getattr(execution, "output", None)
        if isinstance(output, dict) and output:
            public[str(node_id)] = output
    return {"nodes": public, "status": getattr(result, "status", None)}
