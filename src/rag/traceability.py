"""Contrato canónico de trazabilidad — la única fuente de verdad para "Cómo llegó Zent".

Este módulo NO cambia el pipeline: proyecta hechos ya emitidos por el runtime
(eventos canónicos, bloques históricos del flow, telemetría JEV y evidencia del
run) en cinco conceptos:

1. EJECUCIÓN   -> `timeline`: eventos reales del pipeline, con `user_visible`.
2. EVIDENCIA   -> `evidence`: documentos agrupados y fragmentos normalizados.
3. DECISIONES  -> `decisions`: eventos de decisión con efecto y clasificación.
4. VERIFICACIÓN-> `verification`: estado semántico + códigos de explicación.
5. DIAGNÓSTICO -> `diagnostics`: invariantes y gaps de datos.

Reglas:
- Semántica, no texto de UI: códigos y números. El portal traduce.
- UNKNOWN != ZERO: un dato que no existe se omite, no se rellena.
- Nunca se inventa un paso: cada elemento referencia eventos/ids reales.
- La proyección es aditiva y fail-soft: si algo falla, el flow no se rompe.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from typing import Any

TRACEABILITY_SCHEMA_VERSION = 1

# ---------------------------------------------------------------------------
# Clasificación de decisiones (requisito §21)
# ---------------------------------------------------------------------------

CLASS_OBSERVATIONAL = "OBSERVATIONAL"
CLASS_ACTIONABLE = "ACTIONABLE"
CLASS_BLOCKING = "BLOCKING"

#: Acciones compuestas del preflight que cambian la ejecución.
_CHANGING_ACTIONS = {
    "retrieve_more",
    "reconstruct_more",
    "deterministic_answer",
    "ask_user",
    "abstain",
}
_BLOCKING_ACTIONS = {"abstain", "ask_user"}

#: action compuesta -> efecto semántico (mismo vocabulario que preflight.choices).
_ACTION_EFFECTS = {
    "generate": "generation_allowed",
    "retrieve_more": "retrieval_round_requested",
    "reconstruct_more": "reconstruction_requested",
    "deterministic_answer": "generation_skipped",
    "ask_user": "user_input_requested",
    "abstain": "generation_blocked",
    "approve": "answer_approved",
    "revise": "revision_requested",
}

#: Fases de juicio -> código de propósito (el portal traduce).
_PHASE_PURPOSE = {
    "pre_reasoning": "plan",
    "post_retrieval": "evidence",
    "post_reconstruction": "reconstruction",
    "pre_generation": "generation",
    "post_generation": "verification",
    "response_composition": "composition",
    "agent_step": "agent_step",
    "tool_routing": "tool_routing",
    "termination": "termination",
    "answer_gate": "answer_gate",
    "routing": "routing",
    "evidence": "evidence",
    "grounding": "grounding",
}

# ---------------------------------------------------------------------------
# Tipos de evento de la timeline (requisito §14)
# ---------------------------------------------------------------------------

EV_QUERY_CLASSIFIED = "QUERY_CLASSIFIED"
EV_CONTEXT_LOADED = "CONTEXT_LOADED"
EV_PLAN_CREATED = "PLAN_CREATED"
EV_ROUTE_SELECTED = "ROUTE_SELECTED"
EV_RETRIEVAL_COMPLETED = "RETRIEVAL_COMPLETED"
EV_EVIDENCE_FOUND = "EVIDENCE_FOUND"
EV_EVIDENCE_ASSESSED = "EVIDENCE_ASSESSED"
EV_SQL_EXECUTED = "SQL_EXECUTED"
EV_JEV_DECISION = "JEV_DECISION"
EV_RETRIEVAL_EXPANDED = "RETRIEVAL_EXPANDED"
EV_GENERATION_STARTED = "GENERATION_STARTED"
EV_GENERATION_COMPLETED = "GENERATION_COMPLETED"
EV_ANSWER_REVISED = "ANSWER_REVISED"
EV_VERIFICATION_COMPLETED = "VERIFICATION_COMPLETED"
EV_GUARDRAIL = "GUARDRAIL"
EV_RESPONSE_DELIVERED = "RESPONSE_DELIVERED"

#: kind canónico de evento -> (tipo de timeline, visible para el usuario).
_EVENT_KIND_MAP: dict[str, tuple[str, bool]] = {
    "reasoning_classification": (EV_QUERY_CLASSIFIED, True),
    "conversation_intent": (EV_QUERY_CLASSIFIED, True),
    "context": (EV_CONTEXT_LOADED, False),
    "company_context": (EV_CONTEXT_LOADED, False),
    "memory": (EV_CONTEXT_LOADED, False),
    "embedding": (EV_RETRIEVAL_COMPLETED, False),
    "reasoning_plan": (EV_PLAN_CREATED, False),
    "response_planning": (EV_PLAN_CREATED, False),
    "decision": (EV_ROUTE_SELECTED, False),
    "turn_route": (EV_ROUTE_SELECTED, False),
    "turn_guard": (EV_ROUTE_SELECTED, False),
    "tool_filter": (EV_ROUTE_SELECTED, False),
    "tool_routing": (EV_ROUTE_SELECTED, False),
    "router_fallback": (EV_ROUTE_SELECTED, False),
    "termination_gate": (EV_ROUTE_SELECTED, False),
    "retrieval": (EV_RETRIEVAL_COMPLETED, True),
    "tool_call": (EV_EVIDENCE_FOUND, False),
    "sources": (EV_EVIDENCE_FOUND, False),
    "evidence": (EV_EVIDENCE_ASSESSED, False),
    "evidence_sufficiency": (EV_EVIDENCE_ASSESSED, False),
    "generation_package": (EV_EVIDENCE_ASSESSED, False),
    "anchor_roles": (EV_EVIDENCE_ASSESSED, False),
    "long_context": (EV_EVIDENCE_ASSESSED, False),
    "source_routing": (EV_EVIDENCE_ASSESSED, False),
    "sql": (EV_SQL_EXECUTED, True),
    "jev_retrieval": (EV_RETRIEVAL_EXPANDED, True),
    "agent_step": (EV_JEV_DECISION, False),
    "jev_pack": (EV_JEV_DECISION, False),
    "llm": (EV_GENERATION_STARTED, False),
    "generation": (EV_GENERATION_COMPLETED, True),
    "final": (EV_GENERATION_COMPLETED, True),
    "answer_revision": (EV_ANSWER_REVISED, True),
    "reasoning_incomplete": (EV_ANSWER_REVISED, True),
    "grounding": (EV_VERIFICATION_COMPLETED, True),
    "verification": (EV_VERIFICATION_COMPLETED, True),
    "inference_verification": (EV_VERIFICATION_COMPLETED, False),
    "analysis_completion": (EV_VERIFICATION_COMPLETED, False),
    "answer_gate": (EV_VERIFICATION_COMPLETED, True),
    "guardrail": (EV_GUARDRAIL, True),
    "fallback": (EV_GUARDRAIL, True),
    "error": (EV_GUARDRAIL, True),
}

#: Resumen semántico por tipo + kind (el portal compone la frase).
_SUMMARY_CODES: dict[str, str] = {
    EV_QUERY_CLASSIFIED: "understood.query",
    EV_CONTEXT_LOADED: "context.loaded",
    EV_PLAN_CREATED: "plan.created",
    EV_ROUTE_SELECTED: "route.selected",
    EV_RETRIEVAL_COMPLETED: "retrieval.completed",
    EV_EVIDENCE_FOUND: "evidence.found",
    EV_EVIDENCE_ASSESSED: "evidence.assessed",
    EV_SQL_EXECUTED: "sql.executed",
    EV_JEV_DECISION: "jev.decision",
    EV_RETRIEVAL_EXPANDED: "retrieval.expanded",
    EV_GENERATION_STARTED: "generation.started",
    EV_GENERATION_COMPLETED: "generation.completed",
    EV_ANSWER_REVISED: "answer.revised",
    EV_VERIFICATION_COMPLETED: "verification.completed",
    EV_GUARDRAIL: "run.guardrail",
    EV_RESPONSE_DELIVERED: "response.delivered",
}

#: Fallbacks materiales: cambian el resultado (vocabulario de flow_story).
_MATERIAL_FALLBACKS = {
    "claims_answer_with_limits",
    "partial_evidence_answer_with_limits",
    "figures_unverified",
    "hierarchy_unverified",
    "disclaimer_contradiction",
}
_RETAINED_FALLBACKS = {"claims_abstain", "preflight_abstained"}
_RETRY_ACTIONS = {"retrieve_more", "search_knowledge"}

_UUIDISH = re.compile(r"^[0-9a-fA-F-]{20,36}$")
_GENERATED_NAME = re.compile(r"^documento\s+[0-9a-f]{6,}$", re.IGNORECASE)
_UNAVAILABLE_NAMES = {"", "documento sin título", "sin título", "fuente sin nombre"}


# ---------------------------------------------------------------------------
# Helpers base
# ---------------------------------------------------------------------------


def _record(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _records(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _text(value: Any) -> str:
    return str(value or "").strip()


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def _probability(value: Any) -> float | None:
    number = _number(value)
    if number is None or number < 0.0 or number > 1.0:
        return None
    return round(number, 4)


def _int_or_none(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def _scalar_metrics(metrics: Mapping[str, Any] | None) -> dict[str, Any]:
    """Métricas de timeline: sólo escalares cortos (los detalles van al técnico)."""
    out: dict[str, Any] = {}
    for key, value in (metrics or {}).items():
        if isinstance(value, bool) or isinstance(value, (int, float)):
            out[str(key)] = value
        elif isinstance(value, str) and 0 < len(value) <= 80:
            out[str(key)] = value
    return out


def _base_name(value: str) -> str:
    candidate = value.replace("\\", "/").rstrip("/").split("/")[-1]
    return candidate.strip()


def _is_uuidish(value: str) -> bool:
    return bool(_UUIDISH.fullmatch(value.replace(" ", "")))


def _display_name_from(sources: Mapping[str, Any]) -> str:
    """Fallback de identidad: title -> filename -> original/uploaded -> uri -> —."""
    for key in (
        "document_name",
        "display_name",
        "source_title",
        "document_title",
        "title",
        "filename",
        "original_filename",
        "uploaded_filename",
        "source_uri",
    ):
        value = _text(sources.get(key))
        if not value:
            continue
        if _is_uuidish(value) or _GENERATED_NAME.match(value):
            continue
        if value.casefold() in _UNAVAILABLE_NAMES:
            continue
        if key == "source_uri":
            value = _base_name(value)
        if value:
            return value
    external = _text(sources.get("external_id"))
    if external and not _is_uuidish(external):
        return _base_name(external)
    return ""


def _document_key(item: Mapping[str, Any]) -> str:
    document_id = _text(item.get("document_id"))
    if document_id:
        return f"document:{document_id}"
    source_id = _text(item.get("source_id"))
    if source_id:
        return f"source:{source_id}"
    name = _display_name_from(item).casefold()
    if name:
        return f"name:{name}"
    return "document:unknown"


def _item_key(item: Mapping[str, Any]) -> str:
    evidence_id = _text(item.get("evidence_id"))
    if evidence_id:
        return f"evidence:{evidence_id}"
    document = _document_key(item)
    chunk = _text(item.get("chunk_id"))
    if chunk:
        return f"{document}:chunk:{chunk}"
    excerpt = _text(item.get("excerpt"))
    digest = hashlib.sha256(excerpt.encode("utf-8", "ignore")).hexdigest()[:16]
    return f"{document}:p:{_text(item.get('page'))}:{digest}"


# ---------------------------------------------------------------------------
# Evidencia: consulta y normalización (requisitos §2, §3, §4, §25)
# ---------------------------------------------------------------------------


def _evidence_raw_items(flow: Mapping[str, Any], events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Recolecta candidatos de evidencia de cada fuente real del flow.

    Prioridad: detalle del registry (con excerpt) > selección (con match) >
    fuentes > citas > meta de steps. Nunca inventa contenido.
    """
    raw: list[dict[str, Any]] = []
    evidence = _record(flow.get("evidence"))
    # RAG: `items_detail` es la proyección del registry. Agent: `items` ya es lista.
    for key in ("items_detail", "items"):
        value = evidence.get(key)
        if isinstance(value, list):
            raw.extend(item for item in _records(value) if isinstance(item, Mapping))
    selection = _record(evidence.get("selection"))
    match_by_id = {
        _text(match.get("evidence_id")): match
        for match in _records(selection.get("matches"))
        if _text(match.get("evidence_id"))
    }
    selected_ids = {
        _text(item) for item in (selection.get("evidence_ids") or []) if _text(item)
    }
    raw.extend(_records(flow.get("sources")))
    raw.extend(_records(flow.get("citations")))
    steps = _records(flow.get("steps"))
    for step in steps:
        meta = _record(step.get("meta"))
        for item in _records(meta.get("evidence")):
            raw.append(item)
    # Enriquecer con la selección (match/priority) sin tocar el original.
    enriched: list[dict[str, Any]] = []
    for item in raw:
        merged = dict(item)
        evidence_id = _text(merged.get("evidence_id"))
        match = match_by_id.get(evidence_id)
        if match is not None:
            merged.setdefault("match", match.get("match"))
            merged.setdefault("match_score", match.get("score"))
            merged.setdefault("match_complete", match.get("complete"))
        if evidence_id and evidence_id in selected_ids:
            merged.setdefault("status", "USED")
            merged.setdefault("used_for_generation", True)
        enriched.append(merged)
    return enriched


def _normalize_item(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Objeto de evidencia único. UNKNOWN != ZERO: sólo lo que existe."""
    document_name = _display_name_from(raw)
    item: dict[str, Any] = {}
    for key in (
        "evidence_id",
        "document_id",
        "source_id",
        "chunk_id",
        "table",
        "row_ref",
    ):
        value = _text(raw.get(key))
        if value:
            item[key] = value
    if document_name:
        item["document_name"] = document_name
    else:
        item["document_name"] = None
    page = _int_or_none(raw.get("page"))
    if page is None:
        page = _int_or_none(raw.get("page_start"))
    if page is not None:
        item["page"] = page
    section = raw.get("section_path")
    if isinstance(section, str):
        section = [section] if section else []
    if isinstance(section, Sequence) and not isinstance(section, (str, bytes)):
        parts = [str(part).strip() for part in section if str(part).strip()]
        if parts:
            item["section_path"] = parts[:6]
    else:
        section_text = _text(raw.get("section") or raw.get("heading"))
        if section_text:
            item["section_path"] = [section_text][:6]
    excerpt = _text(raw.get("excerpt") or raw.get("content") or raw.get("snippet"))
    if excerpt:
        item["excerpt"] = " ".join(excerpt.split())[:600]
    score = _number(raw.get("score"))
    if score is not None:
        item["score"] = round(score, 4)
    rerank = _number(raw.get("rerank_score"))
    if rerank is not None:
        item["rerank_score"] = round(rerank, 4)
    retrieval = _text(raw.get("retrieval") or raw.get("retrieval_method"))
    if retrieval:
        item["retrieval"] = retrieval
    match = _text(raw.get("match"))
    if match:
        item["match"] = match
    status = _text(raw.get("status")).upper()
    if status:
        item["status"] = status
    doc_index = _int_or_none(raw.get("doc_index"))
    if doc_index is not None:
        item["doc_index"] = doc_index
    authority = _text(raw.get("authority"))
    if authority:
        item["authority"] = authority
    knowledge_type = _text(raw.get("knowledge_type"))
    if knowledge_type:
        item["knowledge_type"] = knowledge_type
    if raw.get("entity_pin") is True:
        item["entity_pin"] = True
    if raw.get("used_for_generation") is True:
        item["used_for_generation"] = True
    if raw.get("cited") is not None:
        item["cited"] = bool(raw.get("cited"))
    # used_in_answer: cita confirmada > selección para generación > estado USED.
    if isinstance(item.get("cited"), bool):
        used: bool | None = item["cited"]
    elif item.get("used_for_generation") is True or item.get("doc_index") is not None:
        used = True
    elif item.get("status") in {"USED", "CITED"}:
        used = True
    elif item.get("status") in {"RETRIEVED", "CANDIDATE", "DISCARDED", "DROPPED"}:
        used = False
    else:
        used = None
    if used is not None:
        item["used_in_answer"] = used
    return item


def _merge_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for item in items:
        key = _item_key(item)
        if key not in merged:
            merged[key] = {}
            order.append(key)
        target = merged[key]
        for field, value in item.items():
            if value is None or value == "" or value == []:
                continue
            if field not in target or target[field] in (None, "", []):
                target[field] = value
            elif field == "used_in_answer":
                target[field] = bool(target[field]) or bool(value)
            elif field == "score" and _number(value) is not None:
                current = _number(target.get(field))
                target[field] = max(current or 0.0, float(value))
    return [merged[key] for key in order]


def _document_groups(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for item in items:
        key = _document_key(item)
        if key not in groups:
            groups[key] = {
                "document_key": key,
                "document_id": item.get("document_id"),
                "source_id": item.get("source_id"),
                "document_name": item.get("document_name"),
                "evidence_count": 0,
                "used_count": 0,
                "items": [],
            }
            order.append(key)
        group = groups[key]
        if not group.get("document_name") and item.get("document_name"):
            group["document_name"] = item["document_name"]
        if not group.get("document_id") and item.get("document_id"):
            group["document_id"] = item["document_id"]
        group["evidence_count"] += 1
        if item.get("used_in_answer") is True:
            group["used_count"] += 1
        group["items"].append(item)
    return [groups[key] for key in order]


def _evidence_section(
    flow: Mapping[str, Any],
    events: list[dict[str, Any]],
    diagnostics: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    raw_items = _evidence_raw_items(flow, events)
    items = _merge_items([_normalize_item(raw) for raw in raw_items if raw])
    documents = _document_groups(items)
    for item in items:
        if item.get("used_in_answer") is True and not item.get("excerpt"):
            diagnostics["gaps"].append(
                {"code": "EVIDENCE_EXCERPT_MISSING", "evidence_id": item.get("evidence_id")}
            )
        if item.get("used_in_answer") is True and not item.get("evidence_id"):
            diagnostics["gaps"].append(
                {
                    "code": "EVIDENCE_ID_MISSING",
                    "document_id": item.get("document_id"),
                    "page": item.get("page"),
                }
            )
    for document in documents:
        if not document.get("document_name"):
            diagnostics["gaps"].append(
                {"code": "SOURCE_NAME_MISSING", "document_key": document["document_key"]}
            )
        document["document_name"] = document.get("document_name") or ""

    declared = _record(_record(flow.get("evidence")).get("counts"))
    consulted_documents = _int_or_none(declared.get("documents_consulted"))
    consulted_evidence = _int_or_none(declared.get("evidence_retrieved"))
    used_documents = _int_or_none(declared.get("documents_used"))
    used_evidence = _int_or_none(declared.get("evidence_used"))
    cited_evidence = _int_or_none(declared.get("evidence_cited"))

    distinct_documents = len(documents)
    used_documents_items = sum(1 for doc in documents if doc["used_count"] > 0)
    used_items = sum(1 for item in items if item.get("used_in_answer") is True)
    cited_items = sum(1 for item in items if item.get("cited") is True)
    return {
        "documents": documents,
        "items": items,
        "counts": {
            # Métricas separadas: documento != fragmento (requisito §2).
            "documents_consulted": consulted_documents
            if consulted_documents is not None
            else distinct_documents,
            "documents_used": used_documents
            if used_documents is not None
            else used_documents_items,
            "evidence_retrieved": consulted_evidence
            if consulted_evidence is not None
            else len(items),
            "evidence_used": used_evidence if used_evidence is not None else used_items,
            "evidence_cited": cited_evidence if cited_evidence is not None else cited_items,
        },
    }


# ---------------------------------------------------------------------------
# Verificación (requisitos §11, §12, §13)
# ---------------------------------------------------------------------------

V_VERIFIED = "VERIFIED"
V_PARTIALLY = "PARTIALLY_VERIFIED"
V_UNVERIFIED = "UNVERIFIED"
V_CONFLICTING = "CONFLICTING_EVIDENCE"
V_INSUFFICIENT = "INSUFFICIENT_EVIDENCE"


def _semantic_checks(
    flow: Mapping[str, Any], evidence: Mapping[str, Any]
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    declared = _record(flow.get("verification"))
    for check in _records(declared.get("checks")):
        key = _text(check.get("key"))
        if key:
            checks.append(
                {
                    "key": key,
                    "state": _text(check.get("state")) or "not_observed",
                    "detail": _text(check.get("detail")) or None,
                    "source": "verification",
                }
            )

    grounding = _record(flow.get("grounding"))
    if grounding.get("grounded") is not None and not any(
        check["key"] == "grounding" for check in checks
    ):
        grounded = bool(grounding.get("grounded"))
        checks.append(
            {
                "key": "grounding",
                "state": "ok" if grounded else "blocked",
                "detail": _text(grounding.get("policy")) or None,
                "source": "grounding",
            }
        )

    sufficiency = _record(_record(flow.get("evidence")).get("sufficiency"))
    action = _text(sufficiency.get("recommended_action"))
    if action:
        checks.append(
            {
                "key": "evidence_sufficiency",
                "state": (
                    "ok"
                    if action in {"generate", "answer_with_limits"}
                    else "warn"
                    if action == "retrieve_more"
                    else "blocked"
                ),
                "detail": _text(sufficiency.get("reason")) or None,
                "source": "evidence",
            }
        )

    answerability = _record(flow.get("answerability"))
    if answerability.get("answerable") is not None:
        answerable = bool(answerability.get("answerable"))
        checks.append(
            {
                "key": "answerability",
                "state": "ok" if answerable else "blocked",
                "detail": ",".join(
                    _text(code) for code in (answerability.get("reason_codes") or [])[:3]
                )
                or None,
                "source": "answerability",
            }
        )

    # Un paso answer_gate del run manda sobre la verificación declarada.
    for step in _records(flow.get("steps")):
        if _text(step.get("type")) != "answer_gate":
            continue
        verdict = _text(step.get("verdict"))
        provider = _text(step.get("provider")) or "jev"
        if provider == "skip":
            state = "not_observed"
        elif verdict == "abstain":
            state = "blocked"
        elif verdict == "revise":
            state = "warn"
        else:
            state = "ok"
        checks = [check for check in checks if check["key"] != "answer_gate"]
        checks.append(
            {
                "key": "answer_gate",
                "state": state,
                "detail": verdict or None,
                "source": "agent_step",
            }
        )
    return checks


def _verification_section(
    flow: Mapping[str, Any],
    evidence: Mapping[str, Any],
    decisions: list[dict[str, Any]],
    diagnostics: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    checks = _semantic_checks(flow, evidence)
    grounding = _record(flow.get("grounding"))
    declared = _record(flow.get("verification"))
    fallbacks = [_text(item) for item in (flow.get("fallbacks") or []) if _text(item)]
    answerability = _record(flow.get("answerability"))
    sufficiency = _record(_record(flow.get("evidence")).get("sufficiency"))
    counts = _record(evidence.get("counts"))
    contradiction_count = _int_or_none(sufficiency.get("conflicting_chunks")) or 0
    for fallback in fallbacks:
        if "conflict" in fallback:
            contradiction_count += 1

    retained = any(
        decision.get("action_applied") is True
        and decision.get("action") in _BLOCKING_ACTIONS
        for decision in decisions
    ) or any(fallback in _RETAINED_FALLBACKS for fallback in fallbacks)
    grounded = grounding.get("grounded")
    if grounded is None:
        check = next((item for item in checks if item["key"] == "grounding"), None)
        if check is not None and check["state"] in {"ok", "blocked"}:
            grounded = check["state"] == "ok"
    overall = _text(declared.get("overall")) or _text(flow.get("verification_overall"))
    evidence_used = _int_or_none(counts.get("evidence_used")) or 0
    evidence_empty = evidence_used == 0 and not evidence.get("items")
    material_fallback = any(fallback in _MATERIAL_FALLBACKS for fallback in fallbacks)
    evidence_complete = _record(_record(flow.get("evidence")).get("sufficiency")).get(
        "recommended_action"
    )

    explanation: list[dict[str, Any]] = []
    if contradiction_count > 0:
        status = V_CONFLICTING
        explanation.append({"code": "EVIDENCE_CONFLICT", "count": contradiction_count})
    elif retained or evidence_empty:
        status = V_INSUFFICIENT
        explanation.append(
            {"code": "GENERATION_RETAINED"} if retained else {"code": "EVIDENCE_INSUFFICIENT"}
        )
    elif grounded is False or overall == "blocked":
        status = V_UNVERIFIED
        explanation.append({"code": "SUPPORT_NOT_CONFIRMED"})
    elif grounded is True:
        unavailable = [
            check["key"]
            for check in checks
            if check["state"] in {"not_observed", "not_available", "skipped"}
        ]
        warned = [check["key"] for check in checks if check["state"] == "warn"]
        if unavailable or warned or material_fallback:
            status = V_PARTIALLY
            explanation.append({"code": "DOCUMENTARY_SUPPORT_CONFIRMED"})
            for key in (unavailable + warned)[:3]:
                explanation.append({"code": "SECONDARY_CHECK_UNAVAILABLE", "check": key})
            if material_fallback:
                explanation.append({"code": "ANSWER_WITH_LIMITS"})
        else:
            status = V_VERIFIED
            explanation.append({"code": "DOCUMENTARY_SUPPORT_CONFIRMED"})
    else:
        status = V_UNVERIFIED
        explanation.append({"code": "NO_VERIFICATION_RECORDED"})

    primary = next(
        (check for check in checks if check["key"] in {"grounding", "answer_gate"}), None
    )
    fallback_code = _text(declared.get("fallback_code")) or next(
        (item for item in fallbacks if item), ""
    )
    # Mecanismo alternativo: sólo cuando el run DECLARÓ fallback de verificación.
    if (
        declared.get("fallback_used") is True
        and fallback_code
        and status in {V_VERIFIED, V_PARTIALLY}
    ):
        explanation.append({"code": "FALLBACK_VERIFIER_USED", "fallback": fallback_code})
    payload = {
        "status": status,
        "explanation_codes": explanation[:6],
        "checks": checks,
        "signals": {
            "grounded": grounded if isinstance(grounded, bool) else None,
            "overall": overall or None,
            "fallback_used": bool(declared.get("fallback_used") or fallback_code),
            "fallback_code": fallback_code or None,
            "material_fallback": material_fallback,
            "evidence_complete": evidence_complete or None,
            "answerability": answerability.get("answerable")
            if answerability.get("answerable") is not None
            else None,
        },
        "technical": {
            "primary_check": primary["key"] if primary else None,
            "primary_state": primary["state"] if primary else None,
            "answer_gate": next(
                (
                    {"verdict": check.get("detail"), "state": check.get("state")}
                    for check in checks
                    if check["key"] == "answer_gate"
                ),
                None,
            ),
            "grounding": {
                "grounded": grounding.get("grounded"),
                "score": _number(grounding.get("score")),
                "policy": grounding.get("policy"),
            }
            if grounding
            else None,
            "fallback_codes": fallbacks[:8],
        },
    }
    if status == V_UNVERIFIED and not checks and grounded is None:
        diagnostics["gaps"].append({"code": "VERIFICATION_NOT_OBSERVED"})
    return payload


# ---------------------------------------------------------------------------
# Decisiones JEV (requisitos §6, §7, §8, §21, §22)
# ---------------------------------------------------------------------------


def _classify(action: str, applied: bool, allow_generation: bool | None, influenced: bool | None) -> str:
    if applied and (action in _BLOCKING_ACTIONS or allow_generation is False):
        return CLASS_BLOCKING
    if applied and (
        influenced is True or action in _CHANGING_ACTIONS or action == "revise"
    ):
        return CLASS_ACTIONABLE
    return CLASS_OBSERVATIONAL


def _confidence_band(confidence: float | None, *, certain: bool | None = None,
                     ambiguous: bool | None = None) -> str | None:
    if confidence is None:
        return None
    if certain is True:
        return "high"
    if ambiguous is True:
        return "low"
    if confidence >= 0.8:
        return "high"
    if confidence >= 0.55:
        return "medium"
    return "low"


def _judgment_display(question: Mapping[str, Any]) -> dict[str, Any]:
    """Única transformación de distribución/formato → resultado mostrado."""
    kind = _text(question.get("type")).lower()
    decision = _text(question.get("decision"))
    distribution = _record(question.get("distribution"))
    probabilities = _record(distribution.get("probabilities"))
    display: dict[str, Any] = {
        "outcome_key": decision or None,
        "confidence_band": None,
    }
    if kind == "choice":
        certain = distribution.get("certain")
        ambiguous = distribution.get("ambiguous")
        probability = _probability(distribution.get("confidence"))
        if probability is None:
            probability = _probability(question.get("confidence"))
        if probability is None and decision and decision in probabilities:
            probability = _probability(probabilities.get(decision))
        display["probability"] = probability
        display["certain"] = bool(certain) if isinstance(certain, bool) else None
        display["ambiguous"] = bool(ambiguous) if isinstance(ambiguous, bool) else None
        display["confidence_band"] = _confidence_band(
            probability, certain=display["certain"], ambiguous=display["ambiguous"]
        )
        runner_up = _text(distribution.get("runner_up"))
        if runner_up:
            display["runner_up_key"] = runner_up
        if "runner_up_probability" in distribution:
            display["runner_up_probability"] = _probability(
                distribution.get("runner_up_probability")
            )
    elif kind == "noul":
        certainty = _probability(distribution.get("certainty"))
        if certainty is None:
            certainty = _probability(question.get("certainty"))
        display["probability"] = certainty
        display["certainty"] = certainty
        display["confidence_band"] = _confidence_band(certainty)
        direction = _text(distribution.get("direction"))
        if direction:
            display["direction"] = direction
    elif kind == "score":
        confidence = _probability(distribution.get("confidence"))
        if confidence is None:
            confidence = _probability(question.get("confidence"))
        display["probability"] = confidence
        level = _text(distribution.get("level")) or _text(question.get("value"))
        if level:
            display["level"] = level
        display["confidence_band"] = _confidence_band(confidence)
    else:
        confidence = _probability(question.get("confidence"))
        display["probability"] = confidence
        display["confidence_band"] = _confidence_band(confidence)
    return display


def _judgments(
    flow: Mapping[str, Any],
    events: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
    diagnostics: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Un juicio por (fase, pregunta) con su distribución y su display único."""
    decisions_by_phase = {
        _text(decision.get("phase")): decision["decision_id"]
        for decision in decisions
    }
    entries: dict[tuple[str, str], dict[str, Any]] = {}
    order: list[tuple[str, str]] = []

    def append(question: Mapping[str, Any], phase: str, source_event_id: str | None) -> None:
        question_id = _text(question.get("id"))
        if not question_id:
            return
        identity = (phase, question_id)
        entry = entries.get(identity)
        if entry is None:
            entry = {
                "judgment_id": f"{phase or 'unknown'}:{question_id}",
                "phase": phase,
                "purpose": _PHASE_PURPOSE.get(phase, phase or "judgment"),
                "question_code": question_id,
                "type": _text(question.get("type")).lower() or "noul",
                "effect_code": _text(question.get("effect")) or None,
                "decision_id": decisions_by_phase.get(phase),
                "display": _judgment_display(question),
                "alternatives": [
                    {"key": str(key), "probability": _probability(value)}
                    for key, value in _record(
                        _record(question.get("distribution")).get("probabilities")
                    ).items()
                ],
                "source_event_ids": [],
                "technical": {
                    "version": _int_or_none(question.get("version")),
                    "risk": _text(question.get("risk")) or None,
                    "value": _number(question.get("value")),
                    "certainty": _probability(question.get("certainty")),
                    "distribution": _record(question.get("distribution")) or None,
                },
            }
            entries[identity] = entry
            order.append(identity)
        if source_event_id and source_event_id not in entry["source_event_ids"]:
            entry["source_event_ids"].append(source_event_id)
        if not entry.get("effect_code") and question.get("effect"):
            entry["effect_code"] = _text(question.get("effect")) or None

    block = _record(flow.get("jev_preflight"))
    for pack in _records(block.get("packs")):
        phase = _text(pack.get("phase"))
        for question in _records(pack.get("questions")):
            append(question, phase, None)
    for event in events:
        if _text(event.get("kind")) != "jev_pack":
            continue
        metrics = _record(event.get("metrics"))
        phase = _text(metrics.get("phase")) or _text(event.get("phase"))
        event_id = _text(event.get("id")) or None
        for question in _records(metrics.get("questions")):
            append(question, phase, event_id)

    judgments = [entries[key] for key in order]
    # §9: validación de la probabilidad mostrada contra su propia distribución.
    for judgment in judgments:
        display = judgment["display"]
        probability = display.get("probability")
        alternatives = {
            alt["key"]: alt["probability"]
            for alt in judgment["alternatives"]
            if alt.get("probability") is not None
        }
        outcome = display.get("outcome_key")
        if (
            probability is not None
            and outcome
            and outcome in alternatives
            and abs(float(alternatives[outcome]) - float(probability)) > 1e-3
        ):
            diagnostics["invariants"].append(
                {
                    "code": "PROBABILITY_MISMATCH",
                    "judgment_id": judgment["judgment_id"],
                    "displayed": probability,
                    "distribution": alternatives[outcome],
                }
            )
    return judgments


def _decision_events(
    flow: Mapping[str, Any],
    events: list[dict[str, Any]],
    evidence: Mapping[str, Any],
    diagnostics: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    block = _record(flow.get("jev_preflight"))
    raw_decisions = _records(block.get("decisions"))
    if not raw_decisions:
        # El runtime del agente también publica veredictos en `flow["jev"]`.
        raw_decisions = _records(_record(flow.get("jev")).get("decisions"))

    effects_by_phase: dict[str, list[str]] = {}
    event_by_phase: dict[str, str] = {}
    for event in events:
        if _text(event.get("kind")) != "jev_pack":
            continue
        metrics = _record(event.get("metrics"))
        phase = _text(metrics.get("phase")) or _text(event.get("phase"))
        effects = [
            _text(item) for item in (metrics.get("effects") or []) if _text(item)
        ]
        if effects:
            effects_by_phase.setdefault(phase, [])
            for effect in effects:
                if effect not in effects_by_phase[phase]:
                    effects_by_phase[phase].append(effect)
        if phase and event.get("id") and phase not in event_by_phase:
            event_by_phase[phase] = _text(event.get("id"))

    rounds = _records(_record(flow.get("retrieval")).get("rounds"))
    expanded = bool(_record(flow.get("retrieval")).get("expanded"))
    before_state: dict[str, Any] = {}
    after_state: dict[str, Any] = {}
    if len(rounds) >= 2:
        first, last = rounds[0], rounds[-1]
        before_state = {
            "evidence": _int_or_none(first.get("n_items")),
            "sufficient": first.get("sufficient"),
        }
        after_state = {
            "evidence": _int_or_none(last.get("n_items")),
            "sufficient": last.get("sufficient"),
        }

    decisions: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for index, raw in enumerate(raw_decisions, start=1):
        phase = _text(raw.get("phase"))
        action = _text(raw.get("action"))
        question_id = _text(raw.get("question_id"))
        identity = (phase, action, question_id)
        if identity in seen:
            continue
        seen.add(identity)
        applied = bool(raw.get("applied"))
        allow_generation = raw.get("allow_generation")
        influenced = raw.get("influer")
        if influenced is None and applied:
            influenced = bool(
                raw.get("influer")
                or allow_generation is False
                or action in _CHANGING_ACTIONS
            )
        classification = _classify(
            action,
            applied,
            allow_generation if isinstance(allow_generation, bool) else None,
            influenced if isinstance(influenced, bool) else None,
        )
        effect_codes: list[str] = []
        for effect in effects_by_phase.get(phase, []):
            if effect not in effect_codes:
                effect_codes.append(effect)
        action_effect = _ACTION_EFFECTS.get(action)
        if action_effect and action_effect not in effect_codes:
            effect_codes.append(action_effect)
        confidence = _probability(raw.get("confidence"))
        decided_by = _text(raw.get("decided_by"))
        provider = "JEV" if not decided_by or decided_by.startswith("jev") else decided_by
        decision_id = f"decision:{index}:{phase or 'unknown'}"
        decision: dict[str, Any] = {
            "decision_id": decision_id,
            "provider": provider,
            "phase": phase or None,
            "purpose": _PHASE_PURPOSE.get(phase, phase or "decision"),
            "question_id": question_id or None,
            "verdict": action or None,
            "action": action or None,
            "action_applied": applied,
            "classification": classification,
            "effect_codes": effect_codes,
            "reason_codes": [
                _text(item) for item in (raw.get("reasons") or []) if _text(item)
            ][:8],
            "unsatisfied": [
                _text(item) for item in (raw.get("unsatisfied") or []) if _text(item)
            ][:8],
            "uncertain_critical": [
                _text(item)
                for item in (raw.get("uncertain_critical") or [])
                if _text(item)
            ][:8],
            "tier": _text(raw.get("tier")) or None,
            "allow_generation": allow_generation
            if isinstance(allow_generation, bool)
            else None,
            "display": {
                "outcome_key": action or None,
                "probability": confidence,
                "confidence_band": _confidence_band(confidence),
            },
            "source_event_ids": [event_by_phase[phase]] if phase in event_by_phase else [],
        }
        if (
            action in _RETRY_ACTIONS
            and applied
            and (expanded or len(rounds) >= 2)
        ):
            decision["before_state"] = before_state or None
            decision["after_state"] = after_state or None
            before = before_state.get("evidence")
            after = after_state.get("evidence")
            if before is not None and after is not None:
                decision["delta_evidence"] = int(after) - int(before)
        decisions.append(decision)

    # Integridad: una decisión que no se aplicó no puede declararse ejecutable.
    for decision in decisions:
        if (
            decision["classification"] in {CLASS_ACTIONABLE, CLASS_BLOCKING}
            and decision["action_applied"] is not True
        ):
            diagnostics["invariants"].append(
                {
                    "code": "ACTION_APPLIED_REQUIRED",
                    "decision_id": decision["decision_id"],
                    "classification": decision["classification"],
                }
            )
    counts = _record(evidence.get("counts"))
    if (
        _int_or_none(counts.get("evidence_used")) is not None
        and _int_or_none(counts.get("evidence_retrieved")) is not None
        and int(counts["evidence_used"]) > int(counts["evidence_retrieved"])
    ):
        diagnostics["invariants"].append(
            {
                "code": "USED_EVIDENCE_EXCEEDS_RETRIEVED",
                "used": counts["evidence_used"],
                "retrieved": counts["evidence_retrieved"],
            }
        )
    return decisions


# ---------------------------------------------------------------------------
# Timeline (requisito §14)
# ---------------------------------------------------------------------------


def _event_summary_params(
    event: Mapping[str, Any], event_type: str, evidence: Mapping[str, Any]
) -> dict[str, Any]:
    metrics = _record(event.get("metrics"))
    technical = _record(event.get("technical"))
    params: dict[str, Any] = {}
    if event_type == EV_RETRIEVAL_COMPLETED:
        for key in ("chunks", "sources_used", "sources_discarded", "top_score"):
            if metrics.get(key) is not None:
                params[key] = metrics[key]
        counts = _record(evidence.get("counts"))
        for key in ("evidence_used", "documents_used", "evidence_retrieved"):
            if params.get(key) is None and counts.get(key) is not None:
                params[key] = counts[key]
    elif event_type == EV_EVIDENCE_FOUND:
        if metrics.get("items") is not None:
            params["evidence"] = metrics["items"]
        elif metrics.get("sources") is not None:
            params["documents"] = metrics["sources"]
        meta = _record(metrics.get("meta"))
        tool_items = meta.get("evidence")
        if isinstance(tool_items, list) and tool_items:
            used = [
                item
                for item in tool_items
                if isinstance(item, Mapping)
                and str(item.get("status") or "USED").upper() == "USED"
            ]
            params["evidence"] = len(used)
            params["documents"] = len(
                {
                    str(item.get("document_id") or item.get("source_id") or "")
                    for item in used
                }
                - {""}
            ) or None
    elif event_type == EV_EVIDENCE_ASSESSED:
        if metrics.get("sufficient") is not None:
            params["sufficient"] = metrics["sufficient"]
        if metrics.get("recommended_action"):
            params["action"] = metrics["recommended_action"]
    elif event_type == EV_SQL_EXECUTED:
        if metrics.get("rows") is not None:
            params["rows"] = metrics["rows"]
    elif event_type == EV_GENERATION_COMPLETED:
        if metrics.get("total_tokens") is not None:
            params["tokens"] = metrics["total_tokens"]
    elif event_type == EV_VERIFICATION_COMPLETED:
        overall = metrics.get("overall")
        if isinstance(overall, str) and overall:
            params["overall"] = overall
        elif isinstance(metrics.get("grounded"), bool):
            params["grounded"] = metrics["grounded"]
        if metrics.get("score") is not None:
            params["score"] = metrics["score"]
    elif event_type == EV_ANSWER_REVISED:
        # §14: "la respuesta fue corregida" sólo con el qué se corrigió.
        detail = _text(technical.get("detail")) or _text(event.get("summary"))
        if detail:
            params["reason"] = detail[:160]
        for key in ("verdict", "reason_code", "reason"):
            if metrics.get(key):
                params[key] = metrics[key]
    elif event_type == EV_GUARDRAIL:
        reason = _text(event.get("summary"))
        if reason:
            params["reason"] = reason
    if not params and event_type == EV_EVIDENCE_FOUND:
        counts = _record(evidence.get("counts"))
        if counts.get("evidence_retrieved") is not None:
            params["evidence"] = counts["evidence_retrieved"]
    return params


def _timeline(
    flow: Mapping[str, Any],
    events: list[dict[str, Any]],
    evidence: Mapping[str, Any],
    decisions: list[dict[str, Any]],
    diagnostics: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    timeline: list[dict[str, Any]] = []
    seen_verification = False
    seen_decisions: set[str] = set()
    delivered = _answer_delivered(flow)
    decision_by_phase = {
        decision.get("phase"): decision["decision_id"]
        for decision in decisions
        if decision.get("action_applied") is True
    }

    for event in events:
        kind = _text(event.get("kind"))
        mapped = _EVENT_KIND_MAP.get(kind)
        if mapped is None:
            continue
        event_type, visible = mapped
        event_phase = _text(event.get("phase"))
        entry_decision_id: str | None = None
        metrics = _record(event.get("metrics"))
        if event_type == EV_VERIFICATION_COMPLETED:
            if seen_verification:
                visible = False
            else:
                seen_verification = True
        if kind == "jev_pack":
            decision = _record(event.get("decision"))
            applied = decision.get("applied") is True
            classification = _classify(
                _text(decision.get("action")),
                applied,
                decision.get("allow_generation")
                if isinstance(decision.get("allow_generation"), bool)
                else None,
                None,
            )
            visible = applied and classification != CLASS_OBSERVATIONAL
            pack_phase = _text(metrics.get("phase")) or event_phase
            entry_decision_id = decision_by_phase.get(pack_phase)
            if visible and entry_decision_id:
                # UNA decisión = UN evento visible: un segundo pack de la misma
                # fase no duplica "JEV intervino" (§8).
                if entry_decision_id in seen_decisions:
                    visible = False
                else:
                    seen_decisions.add(entry_decision_id)
            if not visible:
                # §7: sin intervención, el detalle queda en diagnóstico técnico.
                continue
        else:
            entry_decision_id = decision_by_phase.get(event_phase)
            if kind == "tool_call" and event_type == EV_EVIDENCE_FOUND:
                technical = _record(event.get("technical"))
                tool = _text(technical.get("tool") or metrics.get("tool")).lower()
                # Sólo la búsqueda de conocimiento aparece como paso de evidencia.
                visible = any(
                    marker in tool for marker in ("search", "know", "retriev")
                )
        sequence = len(timeline) + 1
        phase = _text(event.get("phase"))
        params = _event_summary_params(event, event_type, evidence)
        entry: dict[str, Any] = {
            "id": f"trace:{sequence}",
            "type": event_type,
            "stage": phase or None,
            "sequence": sequence,
            "summary_code": _SUMMARY_CODES.get(event_type, event_type.lower()),
            "summary_params": params,
            "user_visible": visible,
            "status": _text(event.get("status")) or "ok",
            "duration_ms": _number(event.get("duration_ms")),
            "metrics": _scalar_metrics(event.get("metrics")),
            "source_event_ids": [_text(event.get("id"))] if event.get("id") else [],
        }
        if entry_decision_id:
            entry["decision_id"] = entry_decision_id
        timeline.append(entry)

    # §13: la expansión de búsqueda existe sólo si una decisión aplicada la pidió
    # y la telemetría real muestra más de una ronda. Sin eso, NO se muestra.
    for decision in decisions:
        if (
            decision.get("action_applied") is not True
            or decision.get("action") not in _RETRY_ACTIONS
            or not decision.get("before_state")
            or not decision.get("after_state")
        ):
            continue
        sequence = len(timeline) + 1
        before = _record(decision.get("before_state"))
        after = _record(decision.get("after_state"))
        timeline.append(
            {
                "id": f"trace:{sequence}",
                "type": EV_RETRIEVAL_EXPANDED,
                "stage": "evidence",
                "sequence": sequence,
                "summary_code": _SUMMARY_CODES[EV_RETRIEVAL_EXPANDED],
                "summary_params": {
                    "before": before.get("evidence"),
                    "after": after.get("evidence"),
                    "delta": decision.get("delta_evidence"),
                },
                "user_visible": True,
                "status": "ok",
                "duration_ms": None,
                "metrics": {
                    key: value
                    for key, value in {
                        "before": before.get("evidence"),
                        "after": after.get("evidence"),
                        "delta": decision.get("delta_evidence"),
                    }.items()
                    if value is not None
                },
                "decision_id": decision["decision_id"],
                "source_event_ids": list(decision.get("source_event_ids") or []),
            }
        )

    if delivered:
        sequence = len(timeline) + 1
        # La entrega se sustenta en el evento de generación que ya existe; si no
        # hay ninguno, se apoya en el estado final del flow (sin referencias).
        generation_refs: list[str] = []
        for entry in reversed(timeline):
            if entry["type"] in {EV_GENERATION_COMPLETED, EV_GENERATION_STARTED}:
                generation_refs = list(entry.get("source_event_ids") or [])
                break
        timeline.append(
            {
                "id": f"trace:{sequence}",
                "type": EV_RESPONSE_DELIVERED,
                "stage": "generation",
                "sequence": sequence,
                "summary_code": _SUMMARY_CODES[EV_RESPONSE_DELIVERED],
                "summary_params": {},
                "user_visible": True,
                "status": "ok",
                "duration_ms": None,
                "metrics": {},
                "source_event_ids": generation_refs,
            }
        )
    return timeline


def _answer_delivered(flow: Mapping[str, Any]) -> bool:
    generation = _record(flow.get("generation"))
    if generation.get("skipped") is not None:
        return generation.get("skipped") is False
    for step in _records(flow.get("steps")):
        if _text(step.get("type")) == "final" and _text(step.get("status")) != "error":
            return True
    return _text(flow.get("status")) in {"completed", "answered", "ok"}


# ---------------------------------------------------------------------------
# Invariantes y ensamble (requisito §26)
# ---------------------------------------------------------------------------


def _rounds(flow: Mapping[str, Any]) -> list[dict[str, Any]]:
    retrieval = _record(flow.get("retrieval"))
    rounds = _records(retrieval.get("rounds"))
    out: list[dict[str, Any]] = []
    for index, raw in enumerate(rounds, start=1):
        out.append(
            {
                "attempt": _int_or_none(raw.get("attempt")) or index,
                "strategy": _text(raw.get("strategy")) or None,
                "evidence": _int_or_none(raw.get("n_items")),
                "sufficient": raw.get("sufficient")
                if isinstance(raw.get("sufficient"), bool)
                else None,
                "quality_score": _number(raw.get("quality_score")),
            }
        )
    return out


def _temporal_invariants(
    flow: Mapping[str, Any],
    timeline: list[dict[str, Any]],
    diagnostics: dict[str, list[dict[str, Any]]],
) -> None:
    """Suficiencia temporal: un 'insuficiente' seguido de respuesta necesita causa."""
    rounds = _rounds(flow)
    if len(rounds) < 1:
        return
    delivered = any(item["type"] == EV_RESPONSE_DELIVERED for item in timeline)
    if not delivered:
        return
    first = rounds[0]
    if first.get("sufficient") is not False:
        return
    later_ok = any(round_.get("sufficient") is True for round_ in rounds[1:])
    expanded = any(item["type"] == EV_RETRIEVAL_EXPANDED for item in timeline)
    fallbacks = [_text(item) for item in (flow.get("fallbacks") or [])]
    explicit_limit = any(
        item in _MATERIAL_FALLBACKS or item in _RETAINED_FALLBACKS for item in fallbacks
    )
    if not (later_ok or expanded or explicit_limit):
        diagnostics["invariants"].append(
            {
                "code": "INSUFFICIENT_THEN_GENERATED",
                "rounds": len(rounds),
            }
        )


def build_traceability(flow: Mapping[str, Any] | None) -> dict[str, Any]:
    """Proyecta el flow completo en el contrato canónico de trazabilidad."""
    safe: Mapping[str, Any] = flow if isinstance(flow, Mapping) else {}
    events = _records(safe.get("events"))
    diagnostics: dict[str, list[dict[str, Any]]] = {"invariants": [], "gaps": []}

    evidence = _evidence_section(safe, events, diagnostics)
    decisions = _decision_events(safe, events, evidence, diagnostics)
    judgments = _judgments(safe, events, decisions, diagnostics)
    verification = _verification_section(safe, evidence, decisions, diagnostics)
    timeline = _timeline(safe, events, evidence, decisions, diagnostics)
    _temporal_invariants(safe, timeline, diagnostics)

    # Diagnóstico: duplicados de evidencia dentro de un mismo documento.
    for document in evidence["documents"]:
        ids = [item.get("evidence_id") for item in document["items"] if item.get("evidence_id")]
        if len(ids) != len(set(ids)):
            diagnostics["invariants"].append(
                {"code": "DUPLICATE_EVIDENCE_ID", "document_key": document["document_key"]}
            )

    events_count = len(events)
    steps = _records(safe.get("steps"))
    return {
        "schema_version": TRACEABILITY_SCHEMA_VERSION,
        "counts": dict(evidence["counts"]),
        "evidence": {
            "documents": evidence["documents"],
            "items": evidence["items"],
        },
        "retrieval": {
            "rounds": _rounds(safe),
            "expanded": bool(_record(safe.get("retrieval")).get("expanded")),
            "strategy": _text(_record(safe.get("retrieval")).get("strategy")) or None,
            "skip_retrieval": _record(safe.get("retrieval")).get("skip_retrieval")
            if isinstance(_record(safe.get("retrieval")).get("skip_retrieval"), bool)
            else None,
        },
        "decisions": decisions,
        "judgments": judgments,
        "timeline": timeline,
        "verification": verification,
        "diagnostics": {
            "invariants": diagnostics["invariants"][:24],
            "gaps": diagnostics["gaps"][:24],
            "sources": {
                "events": events_count,
                "steps": len(steps),
                "packs": len(_records(_record(safe.get("jev_preflight")).get("packs"))),
            },
        },
    }


__all__ = [
    "CLASS_ACTIONABLE",
    "CLASS_BLOCKING",
    "CLASS_OBSERVATIONAL",
    "TRACEABILITY_SCHEMA_VERSION",
    "build_traceability",
]
