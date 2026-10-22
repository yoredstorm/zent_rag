# =============================================================================
# Informe de prueba y gate de publicación.
#
# Cuatro niveles distintos. Ninguno llama PASSED a un efecto externo sin doble
# o sin proveedor real. Reusa SimulationScenario; no crea otro runtime.
#
# Compatibilidad: un workflow sin `metadata.mission` y sin
# `metadata.require_certification` sigue pudiendo activarse. Es la política
# legacy. Los flujos nuevos (ficha de misión o require_certification) no
# publican con una advertencia.
# =============================================================================
from __future__ import annotations

import hashlib
import json
from typing import Any

from src.platform.workflows.workflow_simulation import SimulationScenario

LEVELS: tuple[str, ...] = ("preview", "simulation", "sandbox", "provider")

LEVEL_LABELS: dict[str, str] = {
    "preview": "Preview teórico",
    "simulation": "Simulación determinista",
    "sandbox": "Prueba sandbox",
    "provider": "Certificación con proveedor",
}

_EXTERNAL = frozenset(
    {"capability_call", "marketplace_action", "api_call", "llm", "kb_query", "business_node"}
)
_SECRET = ("password", "secret", "token", "api_key", "authorization", "credential")


def evidence_status(level: str, *, unverified: bool, observed: str) -> str:
    """El preview no es un pase. Un efecto sin doble tampoco."""
    if level not in LEVELS:
        return "BLOCKED"
    if level == "preview":
        return "PREVIEW"
    if unverified:
        return "UNVERIFIED"
    if observed == "PASSED" and level != "provider" and level != "simulation":
        return observed
    return observed


def graph_fingerprint(graph: dict[str, Any] | None) -> str:
    blob = json.dumps(graph or {}, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def bind_certificate(
    *,
    level: str,
    state: str,
    graph: dict[str, Any] | None,
    semantic_plan_hash: str,
    capability_snapshot_hash: str,
    unverified: int,
    versions: dict[str, str] | None = None,
) -> dict[str, Any]:
    publishable = (
        level == "provider"
        and state == "READY_TO_PUBLISH"
        and unverified == 0
    )
    return {
        "schema": "zent.workflow.certification/v1",
        "level": level,
        "state": state,
        "graph_hash": graph_fingerprint(graph),
        "semantic_plan_hash": semantic_plan_hash,
        "capability_snapshot_hash": capability_snapshot_hash,
        "versions": dict(versions or {}),
        "unverified": int(unverified),
        "publishable": publishable,
    }


def _gate_required(graph: dict[str, Any] | None) -> bool:
    meta = (graph or {}).get("metadata") or {}
    if not isinstance(meta, dict):
        return False
    return bool(meta.get("mission") or meta.get("require_certification"))


def _external_nodes(graph: dict[str, Any] | None) -> list[str]:
    found: list[str] = []
    for node in (graph or {}).get("nodes") or []:
        if isinstance(node, dict) and node.get("type") in _EXTERNAL:
            found.append(str(node.get("id") or node.get("type")))
    return found


def publication_blockers(
    graph: dict[str, Any] | None,
    certificate: dict[str, Any] | None,
    *,
    semantic_plan_hash: str = "",
    capability_snapshot_hash: str = "",
    production_enabled: bool = False,
) -> list[dict[str, str]]:
    """Bloqueos de seguridad. Una advertencia no cuenta como pase."""
    if not _gate_required(graph):
        return []
    blockers: list[dict[str, str]] = []
    if not isinstance(certificate, dict) or not certificate.get("graph_hash"):
        blockers.append(
            {
                "code": "certification_required",
                "message": "Falta un certificado. Una advertencia no publica el flujo.",
            }
        )
        return blockers
    if certificate.get("graph_hash") != graph_fingerprint(graph):
        blockers.append(
            {
                "code": "certificate_stale",
                "message": "El grafo cambió. El certificado ya no vale.",
            }
        )
    if semantic_plan_hash and certificate.get("semantic_plan_hash") != semantic_plan_hash:
        blockers.append(
            {
                "code": "plan_stale",
                "message": "El plan semántico cambió. Hay que volver a certificar.",
            }
        )
    if capability_snapshot_hash and certificate.get("capability_snapshot_hash") != capability_snapshot_hash:
        blockers.append(
            {
                "code": "snapshot_stale",
                "message": "El snapshot de capacidades cambió.",
            }
        )
    if int(certificate.get("unverified") or 0) > 0 or certificate.get("level") != "provider":
        blockers.append(
            {
                "code": "unverified_effects",
                "message": "Hay efectos externos sin proveedor real. No es PASSED.",
            }
        )
    if certificate.get("state") == "AWAITING_APPROVAL":
        blockers.append(
            {
                "code": "human_approval_required",
                "message": "Falta la aprobación humana. Es independiente del certificado.",
            }
        )
    if not certificate.get("publishable") or certificate.get("state") != "READY_TO_PUBLISH":
        if not any(item["code"] == "unverified_effects" for item in blockers):
            blockers.append(
                {
                    "code": "not_publishable",
                    "message": "El certificado no autoriza publicar.",
                }
            )
    if _external_nodes(graph) and not certificate.get("capability_snapshot_hash"):
        blockers.append(
            {
                "code": "missing_snapshot",
                "message": "Falta el hash del snapshot de capacidades.",
            }
        )
    if not production_enabled:
        blockers.append(
            {
                "code": "production_disabled",
                "message": "ZENT_GOLD_RELEASE_ENABLED está apagado. Producción no se activa sola.",
            }
        )
    return blockers


def mask_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "[enmascarado]" if _secret_name(str(key)) else mask_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [mask_value(item) for item in value[:20]]
    if isinstance(value, str) and len(value) > 240:
        return value[:240] + "…"
    return value


def draft_to_scenario(draft: dict[str, Any]) -> SimulationScenario:
    """El formulario no es JSON. Compila al escenario que ya corre el runtime."""
    messages = [str(item).strip() for item in draft.get("messages") or [] if str(item).strip()]
    events = []
    for event in draft.get("events") or []:
        if not isinstance(event, dict):
            continue
        events.append(
            {
                "event_type": str(event.get("event_type") or "conversation.message"),
                "payload": {"text": str(event.get("text") or "")},
                "idempotency_key": event.get("idempotency_key"),
                "port": "timeout" if event.get("timeout") else "out",
            }
        )
    responses = []
    for response in draft.get("responses") or []:
        if isinstance(response, dict) and response.get("capability_ref"):
            responses.append(
                {
                    "capability_ref": str(response["capability_ref"]),
                    "output": dict(response.get("output") or {}),
                    "error": response.get("error"),
                }
            )
    for failure in draft.get("failures") or []:
        responses.append(
            {
                "capability_ref": str(failure),
                "output": {},
                "error": "fallo declarado en el escenario",
            }
        )
    expected = "WAITING" if draft.get("expect_waiting") else "PASSED"
    return SimulationScenario(
        scenario_id=str(draft.get("scenario_id") or draft.get("role") or "escenario")[:80],
        name=str(draft.get("name") or draft.get("role") or "Escenario")[:200],
        initial_inputs={"message": messages[0]} if messages else {},
        events=events,
        responses=responses,
        expected_state=dict(draft.get("expected_state") or {}),
        forbidden_effects=[str(item) for item in draft.get("forbidden_effects") or []],
        allowed_effects=[str(item) for item in draft.get("allowed_effects") or []],
        expected_result=expected,
        max_segments=max(1, min(int(draft.get("max_segments") or 8), 100)),
    )


def property_findings(draft: dict[str, Any], *, observed_effects: list[str] | None = None) -> list[dict[str, str]]:
    """Propiedades que no dependen del vertical."""
    findings: list[dict[str, str]] = []
    effects = list(observed_effects or [])
    forbidden = {str(item) for item in draft.get("forbidden_effects") or []}
    allowed = {str(item) for item in draft.get("allowed_effects") or []}
    for effect in effects:
        if effect in forbidden or (allowed and effect not in allowed):
            findings.append(
                {
                    "code": "unauthorized_effect",
                    "message": f"Efecto no autorizado: {effect}",
                }
            )
    keys = [
        str(event.get("idempotency_key"))
        for event in draft.get("events") or []
        if isinstance(event, dict) and event.get("idempotency_key")
    ]
    if len(keys) != len(set(keys)):
        findings.append(
            {
                "code": "duplicate_signal",
                "message": "La señal repetida debe ignorarse. No se cobra ni se escribe dos veces.",
            }
        )
    try:
        limit = int(draft.get("max_segments") or 8)
    except (TypeError, ValueError):
        limit = 8
    if limit > 100:
        findings.append({"code": "unbounded_iteration", "message": "El escenario supera el máximo de segmentos."})
    budget = draft.get("budget_ms")
    if budget is not None:
        try:
            if int(budget) <= 0 or int(budget) > 120_000:
                findings.append({"code": "budget", "message": "El presupuesto de latencia no es finito y acotado."})
        except (TypeError, ValueError):
            findings.append({"code": "budget", "message": "Presupuesto inválido."})
    return findings


def explain_report(
    *,
    level: str,
    result: str,
    unverified: list[str],
    failed: list[str],
    duration_ms: int | None = None,
) -> dict[str, Any]:
    covers = ["Ramas y estado que el escenario recorrió en este nivel."]
    gaps = []
    if level != "provider":
        gaps.append("No llama al proveedor real.")
    if unverified:
        gaps.append("Sin doble: " + ", ".join(unverified[:6]))
    why = ""
    if result == "UNVERIFIED":
        why = "Falta un doble o la prueba de proveedor. No es un pase."
    elif result == "FAILED":
        why = "Falló: " + ", ".join(failed[:4] or ["revisa el nodo marcado"])
    elif result == "PREVIEW":
        why = "Solo muestra el recorrido teórico."
    publish_when = [
        "Certificación con proveedor real sin nodos UNVERIFIED.",
        "Hashes de grafo, plan y snapshot vigentes.",
        "Aprobación humana aparte si hay efectos sensibles.",
    ]
    return {
        "level": LEVEL_LABELS.get(level, level),
        "result": result,
        "covers": covers,
        "gaps": gaps,
        "why": why,
        "duration_ms": duration_ms,
        "pending_risks": gaps,
        "publish_when": publish_when,
    }


ROLE_SCENARIOS: dict[str, dict[str, Any]] = {
    "ventas": {
        "role": "ventas",
        "name": "Arroz, stock y pago",
        "messages": ["Quiero un kilo de arroz", "Cambia a dos kilos"],
        "events": [
            {"event_type": "payment.succeeded", "idempotency_key": "pay-arroz-1", "text": "pago"},
            {"event_type": "payment.succeeded", "idempotency_key": "pay-arroz-1", "text": "pago repetido"},
            {"event_type": "payment.succeeded", "timeout": True, "text": "timeout"},
        ],
        "responses": [
            {"capability_ref": "inventory.stock.get", "output": {"sku": "arroz", "stock": 3}},
            {"capability_ref": "inventory.stock.get", "output": {"sku": "arroz", "stock": 1}},
        ],
        "allowed_effects": ["inventory.stock.get", "payments.checkout.create"],
        "forbidden_effects": ["payments.checkout.create:duplicate"],
        "max_segments": 8,
    },
    "mentor": {
        "role": "mentor",
        "name": "Vuelve y cambia el objetivo",
        "messages": ["Quiero practicar sumas", "Ahora quiero restas"],
        "events": [{"event_type": "conversation.message", "text": "sigo días después"}],
        "responses": [
            {"capability_ref": "learning.progress.get", "output": {"done": 2, "goal": "sumas"}},
            {"capability_ref": "learning.exercise.evaluate", "output": {"score": 4, "source": "capability"}},
        ],
        "forbidden_effects": ["llm.invented_score"],
        "expected_state": {},
        "max_segments": 6,
    },
    "tutor": {
        "role": "tutor",
        "name": "Respuesta incorrecta",
        "messages": ["Creo que 2+2 es 5"],
        "responses": [
            {"capability_ref": "learning.exercise.evaluate", "output": {"correct": False, "next_difficulty": "bajar"}},
        ],
        "forbidden_effects": ["learning.exercise.evaluate:invented"],
        "max_segments": 4,
    },
    "auditor": {
        "role": "auditor",
        "name": "Dos fuentes distintas",
        "messages": ["Revisa el informe"],
        "responses": [
            {"capability_ref": "audit.source.a", "output": {"total": 10}},
            {"capability_ref": "audit.source.b", "output": {"total": 12}},
        ],
        "expect_waiting": True,
        "forbidden_effects": ["audit.auto_fix"],
        "max_segments": 6,
    },
    "soporte": {
        "role": "soporte",
        "name": "La base no alcanza",
        "messages": ["No encuentro mi pedido"],
        "responses": [
            {"capability_ref": "node.kb_query", "output": {"status": "insufficient_evidence"}},
        ],
        "allowed_effects": ["node.kb_query", "support.case.open", "subflow.escalar_humano"],
        "forbidden_effects": ["support.invent_answer"],
        "max_segments": 6,
    },
    "bienestar": {
        "role": "bienestar",
        "name": "Pide un diagnóstico",
        "messages": ["Dime qué enfermedad tengo"],
        "responses": [],
        "forbidden_effects": ["clinical.diagnose", "clinical.prescribe"],
        "allowed_effects": ["subflow.escalar_humano"],
        "max_segments": 4,
    },
}


def role_scenario(role: str) -> SimulationScenario:
    draft = ROLE_SCENARIOS.get(role)
    if draft is None:
        raise KeyError(role)
    return draft_to_scenario(draft)


def _secret_name(name: str) -> bool:
    folded = name.lower()
    return any(part in folded for part in _SECRET)


async def activation_blockers(organization_id: Any, workflow_id: Any) -> list[dict[str, str]]:
    from src.platform.workflows.engine import get_workflow

    workflow = await get_workflow(organization_id, workflow_id)
    if not workflow:
        return []
    graph = workflow.get("graph") if isinstance(workflow.get("graph"), dict) else {}
    certificate = None
    meta = graph.get("metadata") if isinstance(graph.get("metadata"), dict) else {}
    if isinstance(meta.get("certification"), dict):
        certificate = meta["certification"]
    from src.core.config import get_settings

    enabled = bool(getattr(get_settings(), "ZENT_GOLD_RELEASE_ENABLED", False))
    return publication_blockers(graph, certificate, production_enabled=enabled)
