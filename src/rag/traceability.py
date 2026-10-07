"""Traceability Schema v2 — la única verdad canónica de la ejecución.

Este módulo NO cambia el pipeline: proyecta los hechos ya emitidos por el
runtime (eventos canónicos, bloques del flow, telemetría JEV, evidencia del
run) en entidades separadas y auditables:

    execution, routing, knowledge, retrieval, evidence, jev, generation,
    controls, verification, memory, timing, cost, fallbacks, diagnostics,
    presentation

Reglas:

- Semántica, no texto de UI: códigos, números y referencias; el portal traduce.
- UNKNOWN != ZERO: un dato que no existe se omite o queda `null`, jamás 0.
- Nunca se inventa un paso: cada elemento referencia eventos/ids reales.
- La proyección es aditiva y fail-soft: si algo falla, el flow no se rompe.
- `build_traceability` es EL lugar donde se normaliza, deduplica e interpreta;
  ninguna vista del portal recalcula sus propios números.

Compatibilidad: el bloque conserva las llaves del schema 1 (`counts`,
`evidence.documents/items`, `decisions`, `judgments`, `timeline`,
`verification`, `retrieval`, `diagnostics.invariants/gaps/sources`) derivadas
de la misma estructura v2, y `upgrade_traceability_v1` adapta traces históricos.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from src.rag.trace_controls import (
    MATERIAL_CODES,
    RETAINED_CODES,
    build_controls_section,
)
from src.rag.trace_diagnostics import (
    build_diagnostics,
    diagnostic_item,
)
from src.rag.trace_evidence import build_evidence_section
from src.rag.trace_identity import derive_evidence_id
from src.rag.trace_jev import (
    CLASS_ACTIONABLE,
    CLASS_BLOCKING,
    CLASS_OBSERVATIONAL,
    RETRY_ACTIONS,
    build_jev_section,
    classify,
)
from src.rag.trace_metrics import GLOSSARY_TERMS, metric_refs_for_trace
from src.runtime.decision_verification import (
    DECISION_NOT_VERIFIED,
    DECISION_VERIFIED,
    NARRATIVE_PARTIAL,
    NARRATIVE_TRUNCATED,
    NARRATIVE_UNVERIFIED,
    NARRATIVE_VERIFIED,
    NARRATIVE_VERIFIED_DETERMINISTIC,
    answer_state_from_steps,
    claims_from_steps,
    compose_verification_split,
    envelope_from_steps,
)

TRACEABILITY_SCHEMA_VERSION = 2

# ---------------------------------------------------------------------------
# Tipos de evento de la timeline (compatibilidad schema 1)
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
    # Pasos canónicos de la cadena determinista y de la ejecución agentica:
    # se mapean para que el timeline no los descarte (UNMAPPED_STEPS avisa si
    # aparece un tipo nuevo).
    "build": (EV_CONTEXT_LOADED, False),
    "runtime_identity": (EV_CONTEXT_LOADED, False),
    "deterministic_operation": (EV_VERIFICATION_COMPLETED, False),
    "grounded_reasoning": (EV_VERIFICATION_COMPLETED, False),
    "derivation": (EV_VERIFICATION_COMPLETED, False),
    "decision_verification": (EV_VERIFICATION_COMPLETED, False),
    "narrative_verification": (EV_VERIFICATION_COMPLETED, False),
    "premise_search": (EV_RETRIEVAL_COMPLETED, False),
    "evidence_selection": (EV_EVIDENCE_ASSESSED, False),
    "rule_compilation": (EV_EVIDENCE_ASSESSED, False),
    "query_local_compilation": (EV_EVIDENCE_ASSESSED, False),
    "evidence_first_gate": (EV_EVIDENCE_ASSESSED, False),
    "grounding_override": (EV_VERIFICATION_COMPLETED, False),
    "grounding_required": (EV_RETRIEVAL_EXPANDED, False),
    "retry_released": (EV_RETRIEVAL_EXPANDED, False),
    "approval": (EV_ROUTE_SELECTED, False),
    "response_delivery": (EV_RESPONSE_DELIVERED, False),
    "fast_path": (EV_VERIFICATION_COMPLETED, False),
    "deterministic_verifier": (EV_VERIFICATION_COMPLETED, False),
    "fast_path_polish": (EV_GENERATION_COMPLETED, False),
}

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

#: Propósito canónico de cada paso visible (nunca "model call" = generación).
_PURPOSE_BY_EVENT_TYPE: dict[str, str] = {
    EV_GENERATION_COMPLETED: "answer_generation",
    EV_GENERATION_STARTED: "generation_started",
    EV_ANSWER_REVISED: "revision",
    EV_JEV_DECISION: "jev_decision",
    EV_VERIFICATION_COMPLETED: "verification",
    EV_RETRIEVAL_COMPLETED: "retrieval",
    EV_RETRIEVAL_EXPANDED: "retrieval_expanded",
    EV_EVIDENCE_FOUND: "evidence",
    EV_EVIDENCE_ASSESSED: "evidence_assessed",
}

V_VERIFIED = "VERIFIED"
V_PARTIALLY = "PARTIALLY_VERIFIED"
V_UNVERIFIED = "UNVERIFIED"
V_CONFLICTING = "CONFLICTING_EVIDENCE"
V_INSUFFICIENT = "INSUFFICIENT_EVIDENCE"

_ANSWERED_OUTCOMES = {"ANSWERED", "ANSWERED_WITH_LIMITS", "RETRIED_AND_ANSWERED"}


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


def _int_or_none(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def _scalar_metrics(metrics: Mapping[str, Any] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in (metrics or {}).items():
        if isinstance(value, bool) or isinstance(value, (int, float)):
            out[str(key)] = value
        elif isinstance(value, str) and 0 < len(value) <= 80:
            out[str(key)] = value
    return out


def _steps(flow: Mapping[str, Any], kind: str) -> list[dict[str, Any]]:
    return [
        item for item in _records(flow.get("steps")) if _text(item.get("type")) == kind
    ]


def _answer_delivered(flow: Mapping[str, Any]) -> bool:
    generation = _record(flow.get("generation"))
    if generation.get("skipped") is not None:
        return generation.get("skipped") is False
    for step in _records(flow.get("steps")):
        if _text(step.get("type")) == "final" and _text(step.get("status")) != "error":
            return True
    return _text(flow.get("status")) in {"completed", "answered", "ok", "limit_reached"}


# ---------------------------------------------------------------------------
# Generación
# ---------------------------------------------------------------------------


def _call_purpose(step: Mapping[str, Any], index: int, total: int) -> str:
    explicit = _text(step.get("purpose")).upper()
    mapping = {
        "ANALYSIS": "reasoning",
        "REASONING": "reasoning",
        "ANSWER": "answer_generation",
        "REVISION": "revision",
        "VERIFICATION": "verification",
        "TOOL_DECISION": "tool_decision",
    }
    if explicit in mapping:
        return mapping[explicit]
    action = _record(step.get("action"))
    if action.get("answer") is not None:
        return "answer_generation"
    if action.get("revision") is not None:
        return "revision"
    if action.get("verification") is not None:
        return "verification"
    if action.get("tool") is not None:
        return "tool_decision" if index < total else "reasoning"
    if total > 1 and index < total:
        return "reasoning"
    return "unknown"


def build_generation_section(
    flow: Mapping[str, Any], evidence: Mapping[str, Any]
) -> dict[str, Any]:
    block = _record(flow.get("generation"))
    llm_steps = _steps(flow, "llm")
    call_details: list[dict[str, Any]] = []
    total = len(llm_steps)
    for index, step in enumerate(llm_steps, start=1):
        tokens = _record(step.get("tokens"))
        call_details.append(
            {
                "id": _text(step.get("id")) or f"model-call:{index}",
                "sequence": index,
                "purpose": _call_purpose(step, index, total),
                "model": step.get("model"),
                "provider": step.get("provider"),
                "duration_ms": _number(step.get("duration_ms") or step.get("latency_ms")),
                "input_tokens": tokens.get("input"),
                "output_tokens": tokens.get("output"),
                "total_tokens": (
                    step.get("tokens")
                    if isinstance(step.get("tokens"), (int, float))
                    else tokens.get("total")
                ),
                "cost_usd": _number(step.get("cost_usd")),
                "source_event_ids": [_text(step.get("id"))] if step.get("id") else [],
            }
        )

    declared_calls = _int_or_none(block.get("calls"))
    declared_reasoning = _int_or_none(block.get("reasoning_calls"))
    declared_answers = _int_or_none(block.get("answer_calls"))
    # El runtime declara cuántas llamadas fueron de razonamiento y cuántas de
    # respuesta; eso manda sobre la heurística de la acción cuando coincide el
    # total (§14: model call ≠ generación visible).
    if (
        declared_calls is not None
        and declared_calls == len(call_details)
        and (declared_reasoning or declared_answers)
    ):
        position = 0
        for _ in range(declared_reasoning or 0):
            if position < len(call_details):
                call_details[position]["purpose"] = "reasoning"
                position += 1
        for _ in range(declared_answers or 0):
            if position < len(call_details):
                call_details[position]["purpose"] = "answer_generation"
                position += 1
    if not call_details and block.get("skipped") is False:
        reasoning_count = declared_reasoning or 0
        answer_count = declared_answers or 0
        purposes = ["reasoning"] * reasoning_count + ["answer_generation"] * answer_count
        total_declared = max(declared_calls or 0, len(purposes), 1)
        purposes.extend(["unknown"] * (total_declared - len(purposes)))
        for index, purpose in enumerate(purposes, start=1):
            call_details.append(
                {
                    "id": f"model-call:{index}",
                    "sequence": index,
                    "purpose": purpose,
                    "model": block.get("model"),
                    "provider": block.get("provider"),
                    "duration_ms": _number(block.get("ms")) if total_declared == 1 else None,
                    "input_tokens": None,
                    "output_tokens": None,
                    "total_tokens": None,
                    "cost_usd": None,
                    "source_event_ids": [],
                }
            )
    calls = declared_calls if declared_calls is not None else len(call_details)
    if block.get("skipped") is True:
        calls = declared_calls if declared_calls is not None else 0
    reasoning_calls = declared_reasoning
    if reasoning_calls is None:
        reasoning_calls = sum(
            1 for call in call_details if call["purpose"] in {"reasoning", "tool_decision"}
        )
    answer_calls = declared_answers
    if answer_calls is None:
        answer_calls = sum(
            1 for call in call_details if call["purpose"] == "answer_generation"
        )
    revision_calls = sum(1 for call in call_details if call["purpose"] == "revision")
    tokens = {
        "input": _int_or_none(block.get("prompt_tokens") or block.get("input_tokens")),
        "output": _int_or_none(
            block.get("completion_tokens") or block.get("output_tokens")
        ),
        "total": _int_or_none(block.get("total_tokens")),
    }
    return {
        "observed": bool(block or llm_steps),
        "skipped": block.get("skipped") if isinstance(block.get("skipped"), bool) else None,
        "model": block.get("model") or next(
            (step.get("model") for step in llm_steps if step.get("model")), None
        ),
        "provider": block.get("provider") or next(
            (step.get("provider") for step in llm_steps if step.get("provider")), None
        ),
        "calls": calls,
        "answer_calls": answer_calls,
        "reasoning_calls": reasoning_calls,
        "revision_calls": revision_calls,
        "call_details": call_details,
        "tokens": tokens,
        "duration_ms": _number(block.get("ms")),
        "cost_usd": _number(block.get("cost")),
        "finish_reason": _text(block.get("finish_reason")) or None,
        "warnings": [],
    }


# ---------------------------------------------------------------------------
# Verificación
# ---------------------------------------------------------------------------


def _semantic_checks(flow: Mapping[str, Any]) -> list[dict[str, Any]]:
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
        checks.append(
            {
                "key": "grounding",
                "state": "ok" if bool(grounding.get("grounded")) else "blocked",
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
        checks.append(
            {
                "key": "answerability",
                "state": "ok" if bool(answerability.get("answerable")) else "blocked",
                "detail": ",".join(
                    _text(code) for code in (answerability.get("reason_codes") or [])[:3]
                )
                or None,
                "source": "answerability",
            }
        )
    for step in _records(flow.get("steps")):
        if _text(step.get("type")) != "answer_gate":
            continue
        verdict = _text(step.get("verdict"))
        provider = _text(step.get("provider")) or "jev"
        state = (
            "not_observed"
            if provider == "skip"
            else "blocked"
            if verdict == "abstain"
            else "warn"
            if verdict == "revise"
            else "ok"
        )
        checks = [check for check in checks if check["key"] != "answer_gate"]
        entry = {
            "key": "answer_gate",
            "state": state,
            "detail": verdict or None,
            "source": "agent_step",
        }
        quality = _number(step.get("quality"))
        if quality is not None:
            entry["quality"] = quality
        checks.append(entry)
    return checks


def build_verification_section(
    flow: Mapping[str, Any],
    evidence: Mapping[str, Any],
    jev: Mapping[str, Any],
    controls: Mapping[str, Any],
) -> dict[str, Any]:
    checks = _semantic_checks(flow)
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
        and decision.get("action") in {"abstain", "ask_user"}
        for decision in _records(jev.get("decisions"))
    ) or any(fallback in RETAINED_CODES for fallback in fallbacks)
    grounded = grounding.get("grounded")
    if grounded is None:
        check = next((item for item in checks if item["key"] == "grounding"), None)
        if check is not None and check["state"] in {"ok", "blocked"}:
            grounded = check["state"] == "ok"
    overall = _text(declared.get("overall")) or _text(flow.get("verification_overall"))
    evidence_used = _int_or_none(counts.get("evidence_used")) or 0
    evidence_empty = evidence_used == 0 and not evidence.get("canonical_evidence")
    material_fallback = (
        bool(_record(controls.get("fallbacks")).get("material"))
        or any(fallback in MATERIAL_CODES for fallback in fallbacks)
    )
    evidence_complete = _record(_record(flow.get("evidence")).get("sufficiency")).get(
        "recommended_action"
    )

    explanation: list[dict[str, Any]] = []
    insufficient_reason = ""
    if contradiction_count > 0:
        status = V_CONFLICTING
        explanation.append({"code": "EVIDENCE_CONFLICT", "count": contradiction_count})
    elif retained or evidence_empty:
        status = V_INSUFFICIENT
        insufficient_reason = "retained" if retained else "evidence_empty"
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

    fallback_code = _text(declared.get("fallback_code")) or next(
        (item for item in fallbacks if item), ""
    )
    if (
        declared.get("fallback_used") is True
        and fallback_code
        and status in {V_VERIFIED, V_PARTIALLY}
    ):
        explanation.append({"code": "FALLBACK_VERIFIER_USED", "fallback": fallback_code})

    # §13: un límite de generación no se acepta silenciosamente como VERIFIED.
    degradations: list[dict[str, Any]] = []
    for warning in _records(controls.get("generation_warnings")):
        impact = _text(warning.get("impact"))
        material = warning.get("material_effect") is True
        if not material:
            explanation.append(
                {
                    "code": "MAX_TOKENS_RECOVERED",
                    "impact": impact,
                }
            )
            continue
        degradations.append(
            {
                "code": "MAX_TOKENS_REACHED",
                "impact": impact,
                "material_effect": True,
                "checks": _record(warning.get("checks")),
            }
        )
        if impact == "MATERIAL_ERROR":
            status = V_UNVERIFIED
            explanation.append({"code": "MAX_TOKENS_MATERIAL_ERROR"})
        else:
            if status == V_VERIFIED:
                status = V_PARTIALLY
            if status in {V_VERIFIED, V_PARTIALLY}:
                explanation.append({"code": "MAX_TOKENS_POSSIBLY_INCOMPLETE"})

    # --- DECISIÓN y NARRATIVA: estados independientes --------------------
    # Una decisión determinista autoritativa NO se degrada por la narrativa
    # (max_tokens, citas colgantes, verificador narrativo caído). El estado
    # global puede quedar parcial por la explicación; la decisión no.
    steps = _records(flow.get("steps"))
    envelope = _record(declared.get("decision_envelope")) or envelope_from_steps(steps)
    declared_claims = [
        dict(item)
        for item in declared.get("derived_claims") or ()
        if isinstance(item, Mapping)
    ]
    claims = claims_from_steps(steps) or declared_claims
    answer_state = _record(declared.get("answer_state")) or answer_state_from_steps(
        steps
    )
    citations_summary = _record(evidence.get("citations_summary"))
    dangling = [
        str(item) for item in citations_summary.get("dangling") or [] if str(item)
    ]
    citations_known = (
        citations_summary.get("references") is not None
        or citations_summary.get("dangling") is not None
    )
    citations_valid = (not dangling) if citations_known else None
    grounding_verdict = next(
        (
            _text(step.get("grounding_verdict"))
            for step in steps
            if _text(step.get("type")) == "answer_gate"
            and _text(step.get("grounding_verdict"))
        ),
        "",
    )
    deterministic_verified = any(
        _text(step.get("type")) == "deterministic_verifier"
        and step.get("verified") is True
        for step in steps
    )
    split = compose_verification_split(
        envelope=envelope,
        claims=claims,
        answer_state=answer_state,
        grounded=grounded,
        checks=checks,
        citations_valid=citations_valid,
        generation_warnings=_records(controls.get("generation_warnings")),
        grounding_verdict=grounding_verdict,
        deterministic_verified=deterministic_verified,
    )
    decision_verification = split["decision_verification"]
    narrative_verification = split["narrative_verification"]
    decision_status = _text(decision_verification.get("status"))
    narrative_status = _text(narrative_verification.get("status"))

    if decision_status == DECISION_VERIFIED:
        # DECISION_VERIFICATION_CONSISTENCY: con autoridad determinista la
        # verificación de la DECISIÓN es VERIFIED; la narrativa sólo ajusta el
        # estado global entre verificado y parcial, nunca lo vuelve unverified.
        explanation = [
            item
            for item in explanation
            if item.get("code")
            not in {"SUPPORT_NOT_CONFIRMED", "NO_VERIFICATION_RECORDED"}
            and not (
                item.get("code") == "EVIDENCE_INSUFFICIENT"
                and insufficient_reason == "evidence_empty"
            )
        ]
        narrative_partial = narrative_status in {
            NARRATIVE_PARTIAL,
            NARRATIVE_TRUNCATED,
            NARRATIVE_UNVERIFIED,
        }
        # Un conflicto real de evidencia o una abstención explícita del run
        # mandan; la ausencia de documentos no degrada una decisión por regla.
        if status == V_CONFLICTING or (
            status == V_INSUFFICIENT and insufficient_reason == "retained"
        ):
            pass
        else:
            status = V_PARTIALLY if narrative_partial else V_VERIFIED
        explanation.insert(
            0,
            {
                "code": "DECISION_VERIFIED",
                "operation": decision_verification.get("operation"),
                "result": decision_verification.get("result"),
                "canonical_rule_ids": list(
                    decision_verification.get("canonical_rule_ids") or ()
                )[:3],
                "premise_status": decision_verification.get("premise_status"),
            },
        )
        if narrative_status == NARRATIVE_TRUNCATED:
            explanation.insert(
                1,
                {
                    "code": "NARRATIVE_TRUNCATED",
                    "warning": (
                        "La explicación pudo quedar incompleta; el resultado "
                        "determinista no fue afectado."
                    ),
                },
            )
        elif narrative_status == NARRATIVE_VERIFIED_DETERMINISTIC:
            explanation.insert(
                1,
                {
                    "code": "NARRATIVE_VERIFIED_DETERMINISTIC",
                    "detail": "verificador determinista: hechos y refs confirmados sin LLM",
                },
            )
        elif narrative_status == NARRATIVE_PARTIAL:
            explanation.insert(1, {"code": "NARRATIVE_PARTIAL"})
        elif narrative_status == NARRATIVE_UNVERIFIED:
            explanation.insert(1, {"code": "NARRATIVE_UNVERIFIED"})
    elif decision_status == DECISION_NOT_VERIFIED:
        # Fail closed: una premisa en conflicto invalida la decisión. No se
        # conserva un VERIFIED mientras la autoridad está comprometida.
        status = V_UNVERIFIED
        explanation.insert(
            0,
            {
                "code": "DECISION_NOT_VERIFIED",
                "conflicts": list(decision_verification.get("conflicts") or ())[:4],
            },
        )
    elif envelope and decision_status:
        explanation.append({"code": "DECISION_UNDETERMINED"})

    primary = next(
        (check for check in checks if check["key"] in {"grounding", "answer_gate"}), None
    )
    quality = None
    for check in checks:
        if check.get("quality") is not None:
            quality = check["quality"]
            break
    payload = {
        "status": status,
        "explanation_codes": explanation[:8],
        "checks": checks,
        "degradations": degradations,
        # Separación explícita: la decisión determinista y la narrativa generada
        # tienen estados independientes (DECISION_NARRATIVE_SEPARATION).
        "decision_verification": decision_verification,
        "narrative_verification": narrative_verification,
        "decision_grounding": split["decision_grounding"],
        "narrative_grounding": split["narrative_grounding"],
        "decision_envelope": envelope or None,
        "derived_claims": claims[:6],
        "answer_state": answer_state or None,
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
            "decision_status": decision_status or None,
            "narrative_status": narrative_status or None,
            "decision_grounding": split["decision_grounding"],
            "narrative_grounding": split["narrative_grounding"],
        },
        "metrics": {"quality": {"value": quality, "ref": "quality"}}
        if quality is not None
        else {},
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
    return payload


# ---------------------------------------------------------------------------
# Timeline
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


def build_timeline(
    flow: Mapping[str, Any],
    events: list[dict[str, Any]],
    evidence: Mapping[str, Any],
    jev: Mapping[str, Any],
) -> list[dict[str, Any]]:
    timeline: list[dict[str, Any]] = []
    seen_verification = False
    seen_generation = False
    seen_decisions: set[str] = set()
    delivered = _answer_delivered(flow)
    decisions = _records(jev.get("decisions"))
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
            visible = visible and not seen_verification
            seen_verification = seen_verification or visible
        if event_type == EV_GENERATION_COMPLETED:
            # §14: varias "generaciones" visibles para la misma respuesta se
            # colapsan; la segunda queda referenciada, no repetida.
            if seen_generation:
                visible = False
            else:
                seen_generation = True
        if kind == "jev_pack":
            decision = _record(event.get("decision"))
            applied = decision.get("applied") is True
            classification = classify(
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
                if entry_decision_id in seen_decisions:
                    visible = False
                else:
                    seen_decisions.add(entry_decision_id)
            if not visible:
                continue
        else:
            entry_decision_id = decision_by_phase.get(event_phase)
            if kind == "tool_call" and event_type == EV_EVIDENCE_FOUND:
                technical = _record(event.get("technical"))
                tool = _text(technical.get("tool") or metrics.get("tool")).lower()
                visible = any(
                    marker in tool for marker in ("search", "know", "retriev")
                )
        sequence = len(timeline) + 1
        phase = _text(event.get("phase"))
        params = _event_summary_params(event, event_type, evidence)
        entry: dict[str, Any] = {
            "id": f"trace:{sequence}",
            "type": event_type,
            "purpose": _PURPOSE_BY_EVENT_TYPE.get(event_type, event_type.lower()),
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

    for decision in decisions:
        if (
            decision.get("action_applied") is not True
            or decision.get("action") not in RETRY_ACTIONS
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
                "purpose": "retrieval_expanded",
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
        generation_refs: list[str] = []
        for entry in reversed(timeline):
            if entry["type"] in {EV_GENERATION_COMPLETED, EV_GENERATION_STARTED}:
                generation_refs = list(entry.get("source_event_ids") or [])
                break
        timeline.append(
            {
                "id": f"trace:{sequence}",
                "type": EV_RESPONSE_DELIVERED,
                "purpose": "delivery",
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


# ---------------------------------------------------------------------------
# Tiempo, costo, memoria, routing, conocimiento
# ---------------------------------------------------------------------------


_TIMING_PART_CODES: tuple[tuple[str, str], ...] = (
    ("llm_ms", "model"),
    ("tools_ms", "tools"),
    ("gates_ms", "gates"),
    ("generation_ms", "model"),
    ("retrieval_ms", "retrieval"),
    ("embedding_ms", "retrieval"),
    ("evidence_ms", "evidence"),
    ("evidence_selection_ms", "evidence"),
    ("grounding_ms", "verification"),
    ("decision_ms", "routing"),
    ("plan_ms", "planning"),
    ("sql_ms", "sql"),
    ("long_context_ms", "context"),
    ("unattributed_ms", "unattributed"),
)


def build_timing_section(flow: Mapping[str, Any]) -> dict[str, Any]:
    timings = _record(flow.get("timings"))
    wall_clock = _number(timings.get("total_ms"))
    breakdown: dict[str, float] = {}
    for key, code in _TIMING_PART_CODES:
        value = _number(timings.get(key))
        if value is None or value <= 0:
            continue
        breakdown[code] = breakdown.get(code, 0.0) + value
    if not breakdown:
        for key, value in timings.items():
            if key == "total_ms":
                continue
            number = _number(value)
            if number is not None and number > 0:
                breakdown["other"] = breakdown.get("other", 0.0) + number
    accumulated = sum(breakdown.values()) if breakdown else None
    if wall_clock is None and accumulated is None:
        parallel: bool | None = None
    elif accumulated is None or wall_clock is None:
        parallel = None
    else:
        parallel = accumulated > wall_clock + 1.0
    return {
        "wall_clock_ms": wall_clock,
        "accumulated_ms": accumulated,
        "parallel": parallel,
        "breakdown": [
            {"code": code, "ms": round(ms, 1)} for code, ms in breakdown.items()
        ],
        "source_keys": sorted(timings.keys()),
    }


def build_cost_section(
    flow: Mapping[str, Any], jev: Mapping[str, Any], generation: Mapping[str, Any]
) -> dict[str, Any]:
    breakdown: dict[str, float] = {}
    generation_cost = _number(generation.get("cost_usd"))
    if generation_cost is not None:
        breakdown["generation"] = generation_cost
    jev_cost = _number(jev.get("cost_usd"))
    if jev_cost is not None:
        breakdown["jev"] = jev_cost
    total = sum(breakdown.values()) if breakdown else None
    pricing = _record(flow.get("pricing"))
    return {
        "total_usd": round(total, 8) if total is not None else None,
        "breakdown": [
            {"code": code, "usd": round(usd, 8)} for code, usd in breakdown.items()
        ],
        "pricing": pricing or None,
        "currency": "USD" if total is not None else None,
    }


def build_memory_section(flow: Mapping[str, Any]) -> dict[str, Any]:
    block = _record(flow.get("memory"))
    if block:
        return {
            "observed": True,
            "used": block.get("used"),
            "created": block.get("created"),
            "reinforced": block.get("reinforced"),
            "contradicted": block.get("contradicted"),
            "available": True,
        }
    steps = _steps(flow, "memory")
    if steps:
        return {
            "observed": True,
            "used": None,
            "created": None,
            "reinforced": None,
            "contradicted": None,
            "available": True,
            "source_event_ids": [
                _text(step.get("id")) for step in steps if step.get("id")
            ],
        }
    return {"observed": False, "available": None, "reason_code": "not_observed"}


def build_routing_section(flow: Mapping[str, Any]) -> dict[str, Any]:
    verdict = _record(flow.get("verdict"))
    decision = _record(flow.get("decision"))
    turn = _record(flow.get("turn"))
    route = _text(verdict.get("route")) or _text(decision.get("route")) or None
    decider = _text(verdict.get("decider")) or _text(decision.get("decider")) or None
    return {
        "route": route,
        "decider": decider,
        "confidence": _number(decision.get("confidence")),
        "provider": _text(decision.get("provider")) or None,
        "capability": _text(decision.get("capability")) or None,
        "intent": _text(flow.get("intent")) or _text(turn.get("intent")) or None,
        "skill": _text(flow.get("skill")) or None,
        "method": _text(flow.get("method")) or None,
    }


def build_knowledge_section(flow: Mapping[str, Any]) -> dict[str, Any]:
    retrieval = _record(flow.get("retrieval"))
    knowledge = _record(flow.get("knowledge_representation"))
    if knowledge:
        representation = dict(knowledge)
    else:
        representation = {
            "document_understanding": None,
            "retrieval": None,
            "warning": None,
        }
    return {
        "strategy": _text(retrieval.get("strategy")) or None,
        "engine_strategy": _text(retrieval.get("engine_strategy")) or None,
        "used": retrieval.get("used") if isinstance(retrieval.get("used"), bool) else None,
        "chunks": _int_or_none(retrieval.get("chunks")),
        "top_score": _number(retrieval.get("top_score")),
        "rewritten_query": retrieval.get("rewritten_query")
        if isinstance(retrieval.get("rewritten_query"), bool)
        else None,
        "rewritten_query_text": _text(retrieval.get("rewritten_query_text")) or None,
        "representation": representation,
        "source_routing": _record(flow.get("source_routing")) or None,
    }


def _retrieval_rounds(flow: Mapping[str, Any]) -> list[dict[str, Any]]:
    rounds = _records(_record(flow.get("retrieval")).get("rounds"))
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


def build_retrieval_section(flow: Mapping[str, Any]) -> dict[str, Any]:
    retrieval = _record(flow.get("retrieval"))
    return {
        "rounds": _retrieval_rounds(flow),
        "expanded": bool(retrieval.get("expanded")),
        "strategy": _text(retrieval.get("strategy")) or None,
        "skip_retrieval": retrieval.get("skip_retrieval")
        if isinstance(retrieval.get("skip_retrieval"), bool)
        else None,
        "attempts": _int_or_none(retrieval.get("attempts")),
        "used": retrieval.get("used") if isinstance(retrieval.get("used"), bool) else None,
    }


# ---------------------------------------------------------------------------
# Cognitiva (C6)
# ---------------------------------------------------------------------------


def _cognitive_section(flow: Mapping | None) -> dict:
    """Sección cognitiva de la traza (C6): resumen estable, sin texto de UI."""
    cognitive = flow.get("cognitive") if isinstance(flow, Mapping) else None
    if not isinstance(cognitive, Mapping):
        cognitive = {}
    plan = cognitive.get("plan") if isinstance(cognitive.get("plan"), Mapping) else {}
    strategy = (
        cognitive.get("strategy")
        if isinstance(cognitive.get("strategy"), Mapping)
        else {}
    )
    entities = (
        cognitive.get("entities")
        if isinstance(cognitive.get("entities"), Mapping)
        else {}
    )
    evidence = (
        cognitive.get("evidence")
        if isinstance(cognitive.get("evidence"), Mapping)
        else {}
    )
    brief = (
        cognitive.get("brief") if isinstance(cognitive.get("brief"), Mapping) else {}
    )
    verification = (
        cognitive.get("verification")
        if isinstance(cognitive.get("verification"), Mapping)
        else {}
    )
    budget = (
        cognitive.get("budget") if isinstance(cognitive.get("budget"), Mapping) else {}
    )
    loop = cognitive.get("loop") if isinstance(cognitive.get("loop"), Mapping) else {}
    deep = cognitive.get("deep") if isinstance(cognitive.get("deep"), Mapping) else {}
    learning = cognitive.get("learning") if isinstance(cognitive.get("learning"), list) else []
    representations = strategy.get("representations")
    conflicts = evidence.get("conflicts")
    return {
        "mode": cognitive.get("mode"),
        "run_id": cognitive.get("run_id"),
        "complexity": plan.get("complexity"),
        "strategy_primary": strategy.get("primary"),
        "representations": (
            len(representations) if isinstance(representations, list) else None
        ),
        "entities_resolved": entities.get("resolved"),
        "evidence_counts": dict(evidence.get("counts") or {})
        if isinstance(evidence.get("counts"), Mapping)
        else {},
        "conflicts": len(conflicts) if isinstance(conflicts, list) else None,
        "brief_chars": brief.get("chars"),
        "verification_action": verification.get("action"),
        "budget_within": budget.get("within_budget"),
        "loop_rounds": loop.get("count"),
        "loop_exhausted": loop.get("exhausted"),
        "learning_count": len(learning),
        "deep_status": deep.get("status"),
        "deep_failure_mode": deep.get("failure_mode") or None,
    }


# ---------------------------------------------------------------------------
# Invariantes temporales (schema 1, preservados)
# ---------------------------------------------------------------------------


def _temporal_items(
    flow: Mapping[str, Any], timeline: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    rounds = _retrieval_rounds(flow)
    if not rounds:
        return []
    delivered = any(item["type"] == EV_RESPONSE_DELIVERED for item in timeline)
    if not delivered:
        return []
    first = rounds[0]
    if first.get("sufficient") is not False:
        return []
    later_ok = any(round_.get("sufficient") is True for round_ in rounds[1:])
    expanded = any(item["type"] == EV_RETRIEVAL_EXPANDED for item in timeline)
    fallbacks = [_text(item) for item in (flow.get("fallbacks") or [])]
    explicit_limit = any(
        item in MATERIAL_CODES or item in RETAINED_CODES for item in fallbacks
    )
    if later_ok or expanded or explicit_limit:
        return []
    return [
        diagnostic_item(
            "INSUFFICIENT_THEN_GENERATED",
            params={"rounds": len(rounds)},
        )
    ]


# ---------------------------------------------------------------------------
# Presentación
# ---------------------------------------------------------------------------


def _outcome_code(
    flow: Mapping[str, Any],
    evidence: Mapping[str, Any],
    verification: Mapping[str, Any],
    jev: Mapping[str, Any],
) -> dict[str, Any]:
    status = _text(flow.get("status"))
    delivered = _answer_delivered(flow)
    overall = _text(verification.get("status"))
    applied_retry = any(
        decision.get("action_applied") and decision.get("action") in RETRY_ACTIONS
        for decision in _records(jev.get("decisions"))
    )
    abstained = any(
        check.get("key") == "answer_gate" and check.get("detail") == "abstain"
        for check in _records(verification.get("checks"))
    )
    complete = evidence.get("complete")
    material_fallback = verification.get("signals", {}).get("material_fallback") is True
    if abstained:
        code, reason = "ABSTAINED", "explicit_abstention"
    elif status in {"failed", "error"} and not delivered:
        code, reason = "FAILED", "execution_failed"
    elif overall == "blocked" and not delivered:
        code, reason = "BLOCKED", "verification_blocked"
    elif delivered and (
        complete is False or overall == V_PARTIALLY or material_fallback
    ):
        code = "ANSWERED_WITH_LIMITS"
        reason = (
            "verification_partial"
            if overall == V_PARTIALLY
            else "evidence_incomplete"
            if complete is False
            else "material_fallback"
        )
    elif delivered and applied_retry:
        code, reason = "RETRIED_AND_ANSWERED", "retry_applied"
    elif delivered:
        code, reason = "ANSWERED", "answer_delivered"
    else:
        code, reason = "BLOCKED", "answer_not_delivered"
    return {
        "code": code,
        "reason_code": reason,
        "evidence_state": (
            "complete" if complete is True else "incomplete" if complete is False else "unknown"
        ),
        "verification_state": overall,
        "final_status": status or None,
        "material_fallback": material_fallback,
        "answer_delivered": delivered,
    }


def _headline_code(outcome: Mapping[str, Any], verification: Mapping[str, Any]) -> str:
    code = _text(outcome.get("code"))
    if code in {"ABSTAINED", "FAILED", "BLOCKED"}:
        return f"RESPONSE_{code}"
    decision = _record(verification.get("decision_verification"))
    decision_status = _text(decision.get("status"))
    if decision_status == DECISION_VERIFIED:
        narrative_status = _text(
            _record(verification.get("narrative_verification")).get("status")
        )
        if narrative_status in {NARRATIVE_VERIFIED, NARRATIVE_VERIFIED_DETERMINISTIC}:
            return "RESPONSE_VERIFIED"
        if narrative_status == NARRATIVE_UNVERIFIED:
            return "RESPONSE_DECISION_VERIFIED_NARRATIVE_UNVERIFIED"
        return "RESPONSE_DECISION_VERIFIED_NARRATIVE_PARTIAL"
    if decision_status == DECISION_NOT_VERIFIED:
        return "RESPONSE_DECISION_NOT_VERIFIED"
    status = _text(verification.get("status"))
    return {
        V_VERIFIED: "RESPONSE_SUPPORTED",
        V_PARTIALLY: "RESPONSE_PARTIALLY_SUPPORTED",
        V_INSUFFICIENT: "RESPONSE_INSUFFICIENT_EVIDENCE",
        V_CONFLICTING: "RESPONSE_CONFLICTING_EVIDENCE",
        V_UNVERIFIED: "RESPONSE_UNVERIFIED",
    }.get(status, "RESPONSE_UNVERIFIED")


def build_journey(
    *,
    evidence: Mapping[str, Any],
    jev: Mapping[str, Any],
    generation: Mapping[str, Any],
    verification: Mapping[str, Any],
    controls: Mapping[str, Any],
    outcome: Mapping[str, Any],
    steps: Sequence[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    journey: list[dict[str, Any]] = []

    def emit(kind: str, params: Mapping[str, Any] | None = None) -> None:
        journey.append(
            {
                "id": f"journey:{len(journey) + 1}:{kind.lower()}",
                "kind": kind,
                "sequence": len(journey) + 1,
                "params": dict(params or {}),
                "source_event_ids": [],
            }
        )

    counts = _record(evidence.get("counts"))
    emit("QUERY_UNDERSTOOD")
    if counts.get("evidence_retrieved") is not None:
        emit(
            "KNOWLEDGE_SEARCHED",
            {
                "retrieved": counts.get("evidence_retrieved"),
                "deduplicated": counts.get("evidence_deduplicated"),
                "unique": counts.get("evidence_unique"),
            },
        )
    if counts.get("documents_retrieved"):
        emit(
            "EVIDENCE_ASSESSED",
            {
                "documents": counts.get("documents_used"),
                "documents_retrieved": counts.get("documents_retrieved"),
                "unique": counts.get("evidence_unique"),
            },
        )
    if evidence.get("complete") is False:
        emit("EVIDENCE_INCOMPLETE")
    if jev.get("executed"):
        emit(
            "JEV_CHECKED",
            {
                "checks": jev.get("checks"),
                "material_intervention": bool(jev.get("material_intervention")),
                "changed_route": bool(jev.get("changed_route")),
                "requested_more_evidence": bool(jev.get("requested_more_evidence")),
            },
        )
    if jev.get("requested_more_evidence"):
        emit("RETRIEVAL_RETRIED")
    # Cronología determinista: Premise Closure cierra premisas, la regla se
    # ensambla y la evaluación produce el resultado autoritativo. Sin esto, un
    # juicio intermedio parecía el estado final.
    premise_closure = next(
        (
            _record(step)
            for step in steps
            if _text(step.get("type")) == "premise_closure"
        ),
        None,
    )
    if premise_closure is not None:
        detail = _record(premise_closure.get("detail"))
        missing_after = premise_closure.get("missing_after")
        if not isinstance(missing_after, list):
            missing_after = detail.get("missing_after") or []
        rules_added = _int_or_none(premise_closure.get("rules_added"))
        if rules_added is None:
            rules_added = _int_or_none(detail.get("rules_added"))
        evidence_added = _int_or_none(premise_closure.get("evidence_added"))
        if evidence_added is None:
            evidence_added = _int_or_none(detail.get("evidence_added"))
        emit(
            "PREMISES_CLOSED",
            {
                "termination": _text(
                    premise_closure.get("termination") or detail.get("termination")
                )
                or None,
                "rules_added": rules_added,
                "evidence_added": evidence_added,
                "missing_after": missing_after[:6],
            },
        )
    decision = _record(verification.get("decision_verification"))
    if _text(decision.get("status")) == DECISION_VERIFIED:
        rule_ids = [
            str(item) for item in decision.get("canonical_rule_ids") or [] if item
        ]
        emit(
            "RULE_COMPILED",
            {
                "rules": len(rule_ids) or None,
                "rule_ids": rule_ids[:3],
                "premise_status": decision.get("premise_status"),
            },
        )
        emit(
            "DETERMINISTIC_AUTHORITY",
            {
                "operation": decision.get("operation"),
                "result": decision.get("result"),
                "rule_ids": rule_ids[:3],
            },
        )
    reasoning_calls = _int_or_none(generation.get("reasoning_calls")) or 0
    if reasoning_calls:
        emit("REASONING_PREPARED", {"calls": reasoning_calls})
    for control in _records(controls.get("material_controls")):
        emit(
            "RECOVERY_APPLIED",
            {
                "control_code": control.get("control_code"),
                "severity": control.get("severity"),
            },
        )
    answer_calls = _int_or_none(generation.get("answer_calls")) or 0
    if outcome.get("answer_delivered"):
        emit("ANSWER_GENERATED", {"calls": answer_calls or 1})
    if verification.get("status"):
        emit("ANSWER_VERIFIED", {"status": verification.get("status")})
    if outcome.get("answer_delivered"):
        emit("ANSWER_DELIVERED")
    return journey


def build_presentation(
    *,
    execution: Mapping[str, Any],
    evidence: Mapping[str, Any],
    jev: Mapping[str, Any],
    generation: Mapping[str, Any],
    verification: Mapping[str, Any],
    controls: Mapping[str, Any],
    timing: Mapping[str, Any],
    cost: Mapping[str, Any],
    outcome: Mapping[str, Any],
    steps: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    counts = _record(evidence.get("counts"))
    explanations: list[dict[str, Any]] = []
    if _int_or_none(generation.get("calls")) and int(generation["calls"]) > 1:
        explanations.append(
            {
                "code": "MODEL_CALLS_PURPOSES",
                "params": {
                    "calls": generation.get("calls"),
                    "reasoning_calls": generation.get("reasoning_calls"),
                    "answer_calls": generation.get("answer_calls"),
                    "revision_calls": generation.get("revision_calls"),
                },
            }
        )
    if timing.get("parallel") is True:
        explanations.append(
            {
                "code": "PARALLEL_TIME",
                "params": {
                    "wall_clock_ms": timing.get("wall_clock_ms"),
                    "accumulated_ms": timing.get("accumulated_ms"),
                },
            }
        )
    used = _int_or_none(counts.get("evidence_used"))
    cited = _int_or_none(counts.get("evidence_cited"))
    if used is not None and cited is not None and used > cited:
        explanations.append(
            {
                "code": "USED_NOT_CITED",
                "params": {"used": used, "cited": cited, "difference": used - cited},
            }
        )
    retrieved = _int_or_none(counts.get("evidence_retrieved"))
    unique = _int_or_none(counts.get("evidence_unique"))
    if retrieved is not None and unique is not None and retrieved > unique:
        explanations.append(
            {
                "code": "DEDUPLICATION_SUMMARY",
                "params": {
                    "retrieved": retrieved,
                    "deduplicated": counts.get("evidence_deduplicated"),
                    "unique": unique,
                    "dedup": evidence.get("dedup"),
                },
            }
        )
    if jev.get("executed") and not jev.get("material_intervention"):
        explanations.append(
            {
                "code": "JEV_CONFIRMED_NO_CHANGE",
                "params": {"checks": jev.get("checks")},
            }
        )
    if jev.get("material_intervention"):
        explanations.append(
            {
                "code": "JEV_CHANGED_PATH",
                "params": {
                    "decisions": [
                        {
                            "action": decision.get("action"),
                            "phase": decision.get("phase"),
                            "reason_codes": decision.get("reason_codes"),
                        }
                        for decision in _records(jev.get("material_decisions"))
                    ][:4]
                },
            }
        )
    for warning in _records(controls.get("generation_warnings")):
        explanations.append(
            {
                "code": "MAX_TOKENS_RECOVERY",
                "params": {
                    "impact": warning.get("impact"),
                    "checks": warning.get("checks"),
                },
            }
        )
    fallback_events = _records(_record(controls.get("fallbacks")).get("events"))
    if fallback_events:
        explanations.append(
            {
                "code": "FALLBACK_TAXONOMY",
                "params": {
                    "classes": _record(controls.get("fallbacks")).get("classes"),
                    "events": [
                        {"code": event.get("code"), "class": event.get("class")}
                        for event in fallback_events[:6]
                    ],
                },
            }
        )
    if evidence.get("collection") == "partial":
        explanations.append(
            {
                "code": "PARTIAL_EVIDENCE_DETAIL",
                "params": {
                    "collected": evidence.get("raw_hits_count"),
                    "retrieved": counts.get("evidence_retrieved"),
                },
            }
        )

    return {
        "headline": {
            "code": _headline_code(outcome, verification),
            "params": {
                "documents_used": counts.get("documents_used"),
                "evidence_unique": counts.get("evidence_unique"),
                "evidence_used": counts.get("evidence_used"),
                "evidence_cited": counts.get("evidence_cited"),
            },
        },
        "support": {
            "documents_used": counts.get("documents_used"),
            "documents_selected": counts.get("documents_selected"),
            "documents_used_for_decision": counts.get("documents_used_for_decision"),
            "documents_cited": counts.get("documents_cited"),
            "evidence_unique": counts.get("evidence_unique"),
            "evidence_used": counts.get("evidence_used"),
            "evidence_used_for_reasoning": counts.get("evidence_used_for_reasoning"),
            "evidence_used_for_rule_compilation": counts.get(
                "evidence_used_for_rule_compilation"
            ),
            "evidence_used_for_premise_closure": counts.get(
                "evidence_used_for_premise_closure"
            ),
            "evidence_used_for_decision": counts.get("evidence_used_for_decision"),
            "evidence_cited": counts.get("evidence_cited"),
            "collection": evidence.get("collection"),
        },
        "journey": build_journey(
            evidence=evidence,
            jev=jev,
            generation=generation,
            verification=verification,
            controls=controls,
            outcome=outcome,
            steps=steps,
        ),
        "explanations": explanations,
        "metric_refs": metric_refs_for_trace(
            judgments=_records(jev.get("judgments")),
            evidence=evidence,
            timing=timing,
            cost=cost,
            verification=verification,
        ),
        "glossary_refs": ["jev", "gate", "retrieval", "evidence", "deduplication"]
        + (["fallback"] if fallback_events else [])
        + (["wall_clock", "span"] if timing.get("parallel") is not None else [])
        + (["grounding", "verified"] if verification.get("status") else []),
        "question": execution.get("question"),
    }


# ---------------------------------------------------------------------------
# Ensamble
# ---------------------------------------------------------------------------


def build_traceability(flow: Mapping[str, Any] | None) -> dict[str, Any]:
    """Proyecta el flow completo en Traceability Schema v2."""
    safe: Mapping[str, Any] = flow if isinstance(flow, Mapping) else {}
    events = _records(safe.get("events"))
    organization_id = _text(safe.get("organization_id")) or None
    knowledge_base = _record(safe.get("knowledge_base"))
    knowledge_base_id = (
        _text(safe.get("knowledge_base_id"))
        or _text(knowledge_base.get("id"))
        or None
    )

    evidence = build_evidence_section(
        safe,
        events,
        organization_id=organization_id,
        knowledge_base_id=knowledge_base_id,
    )
    jev = build_jev_section(safe, events)
    generation = build_generation_section(safe, evidence)
    controls = build_controls_section(safe, evidence=evidence, jev=jev)
    verification = build_verification_section(safe, evidence, jev, controls)
    timing = build_timing_section(safe)
    cost = build_cost_section(safe, jev, generation)
    memory = build_memory_section(safe)
    retrieval = build_retrieval_section(safe)
    knowledge = build_knowledge_section(safe)
    routing = build_routing_section(safe)
    outcome = _outcome_code(safe, evidence, verification, jev)
    timeline = build_timeline(safe, events, evidence, jev)

    execution = {
        "kind": (
            _text(_record(safe.get("execution")).get("kind"))
            or {
                "agent": "agent_run",
                "workflow": "workflow_run",
            }.get(_text(safe.get("method")))
            or "query"
        ),
        "id": _text(_record(safe.get("execution")).get("id")) or None,
        "question": _text(safe.get("question"))[:2000] or None,
        "status": _text(safe.get("status")) or None,
        "delivered": outcome.get("answer_delivered"),
        "method": _text(safe.get("method")) or None,
        "mode": _text(safe.get("execution_mode")) or None,
        "fast_path": _record(safe.get("fast_path")) or None,
    }

    generation["warnings"] = list(_records(controls.get("generation_warnings")))

    steps = _records(safe.get("steps"))
    # Pasos del runtime tal como los emitió, con su estado de mapeo canónico:
    # un tipo sin mapping NO se descarta; se marca `unmapped` y se muestra en
    # el detalle técnico.
    runtime_steps: list[dict[str, Any]] = []
    for step in steps[:80]:
        runtime_steps.append(
            {
                "type": _text(step.get("type")),
                "name": _text(step.get("name")) or None,
                "status": _text(step.get("status")) or "ok",
                "detail": _text(step.get("detail"))[:200] or None,
                "ms": _number(step.get("ms")),
                "unmapped": step.get("unmapped") is True,
            }
        )
    extra_items: list[dict[str, Any]] = _temporal_items(safe, timeline)
    diagnostics = build_diagnostics(
        evidence=evidence,
        jev=jev,
        generation=generation,
        controls=controls,
        verification=verification,
        timeline=timeline,
        timing=timing,
        memory=memory,
        cost=cost,
        sources={
            "events": len(events),
            "steps": len(steps),
            "packs": jev.get("packs") or 0,
            "upgraded_from_schema": None,
        },
        extra_items=extra_items,
    )
    presentation = build_presentation(
        execution=execution,
        evidence=evidence,
        jev=jev,
        generation=generation,
        verification=verification,
        controls=controls,
        timing=timing,
        cost=cost,
        outcome=outcome,
        steps=steps,
    )
    # Evidencias usadas sin cita: hecho, no especulación.
    presentation["support"]["evidence_used_not_cited"] = (
        max(0, (evidence["counts"].get("evidence_used") or 0) - (evidence["counts"].get("evidence_cited") or 0))
        if evidence["counts"].get("evidence_used") is not None
        and evidence["counts"].get("evidence_cited") is not None
        else None
    )

    counts_legacy = {
        "documents_consulted": evidence["counts"].get("documents_retrieved"),
        "documents_used": evidence["counts"].get("documents_used"),
        "documents_selected": evidence["counts"].get("documents_selected"),
        "documents_used_for_decision": evidence["counts"].get(
            "documents_used_for_decision"
        ),
        "documents_cited": evidence["counts"].get("documents_cited"),
        "evidence_retrieved": evidence["counts"].get("evidence_retrieved"),
        "evidence_unique": evidence["counts"].get("evidence_unique"),
        "evidence_selected": evidence["counts"].get("evidence_selected"),
        "evidence_used": evidence["counts"].get("evidence_used"),
        "evidence_used_for_reasoning": evidence["counts"].get(
            "evidence_used_for_reasoning"
        ),
        "evidence_used_for_rule_compilation": evidence["counts"].get(
            "evidence_used_for_rule_compilation"
        ),
        "evidence_used_for_premise_closure": evidence["counts"].get(
            "evidence_used_for_premise_closure"
        ),
        "evidence_used_for_decision": evidence["counts"].get(
            "evidence_used_for_decision"
        ),
        "evidence_cited": evidence["counts"].get("evidence_cited"),
    }

    return {
        "schema_version": TRACEABILITY_SCHEMA_VERSION,
        # --- entidades v2 ---
        "execution": execution,
        "routing": routing,
        "knowledge": knowledge,
        "retrieval": retrieval,
        "evidence": {
            "counts": evidence["counts"],
            "collection": evidence["collection"],
            "raw_hits_count": evidence["raw_hits_count"],
            "raw_hits": evidence["raw_hits"],
            "canonical_evidence": evidence["canonical_evidence"],
            "sources": evidence["sources"],
            "dedup": evidence["dedup"],
            "citations": evidence["citations"],
            "citations_summary": evidence["citations_summary"],
            "documents": evidence["documents"],
            "items": evidence["items"],
        },
        "jev": jev,
        "generation": generation,
        "controls": controls,
        "verification": verification,
        "memory": memory,
        "timing": timing,
        "cost": cost,
        "fallbacks": controls["fallbacks"],
        "diagnostics": diagnostics,
        "presentation": presentation,
        "cognitive": _cognitive_section(safe),
        "runtime_steps": runtime_steps,
        # --- espejo schema 1 (misma verdad, nombres históricos) ---
        "counts": counts_legacy,
        "decisions": jev["decisions"],
        "judgments": jev["judgments"],
        "timeline": timeline,
    }


# ---------------------------------------------------------------------------
# Compatibilidad schema 1 → 2
# ---------------------------------------------------------------------------


def _upgrade_item(item: Mapping[str, Any]) -> dict[str, Any]:
    canonical = dict(item)
    source_id = _text(item.get("document_id")) or _text(item.get("source_id"))
    canonical.setdefault("canonical_source_id", f"legacy:{source_id}" if source_id else None)
    if not canonical.get("evidence_id"):
        derived = derive_evidence_id(
            canonical_source_id=canonical.get("canonical_source_id"),
            page=_int_or_none(item.get("page")),
            section=_text(item.get("section"))
            if isinstance(item.get("section"), str)
            else " · ".join(
                [str(part) for part in item.get("section_path") or [] if str(part)]
            )
            or None,
            text=_text(item.get("excerpt")) or None,
            chunk_id=_text(item.get("chunk_id")) or None,
        )
        canonical["evidence_id"] = derived["evidence_id"]
    return canonical


def upgrade_traceability_v1(trace: Mapping[str, Any] | None) -> dict[str, Any]:
    """Adapta un trace schema 1 almacenado a Schema v2 (fidelidad parcial)."""
    safe = _record(trace)
    counts = _record(safe.get("counts"))
    evidence_block = _record(safe.get("evidence"))
    items = [_upgrade_item(item) for item in _records(evidence_block.get("items"))]
    decisions = _records(safe.get("decisions"))
    judgments = _records(safe.get("judgments"))
    verification = _record(safe.get("verification"))
    diagnostics_v1 = _record(safe.get("diagnostics"))
    material_decisions = [
        decision
        for decision in decisions
        if decision.get("action_applied") is True
        and decision.get("classification") in {CLASS_ACTIONABLE, CLASS_BLOCKING}
    ]
    evidence_counts = {
        "documents_retrieved": counts.get("documents_consulted"),
        "documents_used": counts.get("documents_used"),
        "evidence_retrieved": counts.get("evidence_retrieved"),
        "evidence_deduplicated": None,
        "evidence_unique": None,
        "evidence_selected": None,
        "evidence_used": counts.get("evidence_used"),
        "evidence_cited": counts.get("evidence_cited"),
        "documents_consulted": counts.get("documents_consulted"),
    }
    items_upgraded: list[dict[str, Any]] = []
    for item in items:
        display = _record(item.get("display"))
        alternatives = _records(item.get("alternatives"))
        selected_probability = display.get("probability")
        items_upgraded.append(
            {
                "judgment_id": _text(item.get("judgment_id")) or _text(item.get("id")),
                "id": _text(item.get("id")),
                "phase": _text(item.get("phase")) or None,
                "purpose": _text(item.get("purpose")) or None,
                "question_code": _text(item.get("question_code")),
                "type": _text(item.get("type")),
                "answer": item.get("outcome_key") or None,
                "display": display,
                "interpretation": {
                    "outcome_key": display.get("outcome_key"),
                    "selected_probability": selected_probability,
                    "confidence": display.get("confidence"),
                    "certainty": display.get("certainty"),
                    "margin": None,
                    "entropy": None,
                    "band": display.get("confidence_band"),
                    "verdict": "UNKNOWN",
                    "options": [
                        {
                            "key": alternative.get("key"),
                            "probability": alternative.get("probability"),
                            "selected": alternative.get("key") == display.get("outcome_key"),
                        }
                        for alternative in alternatives
                    ],
                },
                "alternatives": alternatives,
                "raw": _record(item.get("technical")),
                "technical": _record(item.get("technical")),
                "source_event_ids": list(item.get("source_event_ids") or []),
            }
        )

    def _upgrade_decision(decision: Mapping[str, Any]) -> dict[str, Any]:
        upgraded = dict(decision)
        classification = _text(decision.get("classification")) or CLASS_OBSERVATIONAL
        applied = decision.get("action_applied") is True
        upgraded.setdefault("material", applied and classification != CLASS_OBSERVATIONAL)
        upgraded.setdefault("is_default", applied and classification == CLASS_OBSERVATIONAL)
        upgraded.setdefault("changed_route", applied and classification == CLASS_ACTIONABLE)
        return upgraded

    upgraded_decisions = [_upgrade_decision(decision) for decision in decisions]
    diagnostics = build_diagnostics(
        evidence={
            "counts": evidence_counts,
            "canonical_evidence": items,
            "citations_summary": {},
            "collection": "partial",
            "diagnostics": [],
        },
        jev={
            "executed": bool(judgments or decisions),
            "decisions": upgraded_decisions,
            "judgments": items_upgraded,
            "diagnostics": [],
        },
        generation={"calls": None, "observed": False},
        controls={"fallbacks": {"events": [], "material": False}, "material_controls": []},
        verification=verification,
        timeline=_records(safe.get("timeline")),
        timing={},
        memory={},
        cost={},
        extra_items=[
            diagnostic_item(
                "HISTORICAL_TRACE_UPGRADED",
                params={"from_schema": 1, "fidelity": "partial"},
            )
        ],
    )
    outcome_status = _text(verification.get("status"))
    return {
        "schema_version": TRACEABILITY_SCHEMA_VERSION,
        "upgraded_from_schema": 1,
        "execution": {
            "kind": None,
            "id": None,
            "question": None,
            "status": None,
            "delivered": None,
            "method": None,
        },
        "routing": {},
        "knowledge": {},
        "retrieval": _record(safe.get("retrieval")),
        "evidence": {
            "counts": evidence_counts,
            "collection": "partial",
            "raw_hits_count": None,
            "raw_hits": [],
            "canonical_evidence": items,
            "sources": _records(evidence_block.get("documents")),
            "dedup": {"merged": None, "exact": None, "overlap": None, "semantic": None},
            "citations": [],
            "citations_summary": {},
            "documents": _records(evidence_block.get("documents")),
            "items": _records(evidence_block.get("items")),
        },
        "jev": {
            "executed": bool(judgments or decisions),
            "checks": len(judgments),
            "judgments_count": len(judgments),
            "material_intervention": bool(material_decisions),
            "changed_route": bool(material_decisions),
            "requested_more_evidence": any(
                decision.get("action_applied") and decision.get("action") in RETRY_ACTIONS
                for decision in decisions
            ),
            "blocked_generation": False,
            "decisions": upgraded_decisions,
            "decisions_applied": [
                decision for decision in upgraded_decisions if decision.get("action_applied")
            ],
            "material_decisions": [_upgrade_decision(d) for d in material_decisions],
            "judgments": items_upgraded,
            "summary": None,
            "calls": None,
            "packs": None,
            "latency_ms": None,
            "cost_usd": None,
            "tokens": {"input": None, "output": None},
        },
        "generation": {
            "observed": False,
            "calls": None,
            "answer_calls": None,
            "reasoning_calls": None,
            "revision_calls": None,
            "call_details": [],
            "tokens": {"input": None, "output": None, "total": None},
            "cost_usd": None,
            "warnings": [],
        },
        "controls": {
            "controls": [],
            "fallbacks": {"events": [], "material": False, "classes": {}},
            "generation_warnings": [],
            "material_controls": [],
        },
        "verification": {**verification, "degradations": []},
        "memory": {"observed": False, "available": None, "reason_code": "historical"},
        "timing": {"wall_clock_ms": None, "accumulated_ms": None, "parallel": None, "breakdown": []},
        "cost": {"total_usd": None, "breakdown": [], "currency": None},
        "fallbacks": {"events": [], "material": False, "classes": {}},
        "diagnostics": diagnostics,
        "presentation": {
            "headline": {
                "code": {
                    V_VERIFIED: "RESPONSE_SUPPORTED",
                    V_PARTIALLY: "RESPONSE_PARTIALLY_SUPPORTED",
                    V_INSUFFICIENT: "RESPONSE_INSUFFICIENT_EVIDENCE",
                    V_CONFLICTING: "RESPONSE_CONFLICTING_EVIDENCE",
                }.get(outcome_status, "RESPONSE_UNVERIFIED"),
                "params": {
                    "documents_used": counts.get("documents_used"),
                    "evidence_unique": None,
                    "evidence_used": counts.get("evidence_used"),
                    "evidence_cited": counts.get("evidence_cited"),
                },
            },
            "support": {
                "documents_used": counts.get("documents_used"),
                "evidence_unique": None,
                "evidence_used": counts.get("evidence_used"),
                "evidence_cited": counts.get("evidence_cited"),
                "collection": "partial",
            },
            "journey": [],
            "explanations": [
                {"code": "HISTORICAL_TRACE", "params": {"from_schema": 1}}
            ],
            "metric_refs": [],
            "glossary_refs": list(GLOSSARY_TERMS[:5]),
            "question": None,
        },
        "counts": dict(counts),
        "decisions": upgraded_decisions,
        "judgments": items_upgraded,
        "timeline": _records(safe.get("timeline")),
        "runtime_steps": [],
    }


def upgrade_flow_traceability(flow: Mapping[str, Any] | None) -> dict[str, Any]:
    """En lectura: si el flow guarda un trace schema 1, se adapta a v2.

    No muta el almacenamiento; sólo la respuesta. Así el portal viejo sigue
    recibiendo sus llaves y el nuevo puede consumir v2.
    """
    safe = dict(flow) if isinstance(flow, Mapping) else {}
    trace = safe.get("traceability")
    if isinstance(trace, Mapping) and _int_or_none(trace.get("schema_version")) == 1:
        try:
            safe["traceability"] = upgrade_traceability_v1(trace)
        except Exception:  # noqa: BLE001 - nunca romper la lectura
            pass
    return safe


__all__ = [
    "CLASS_ACTIONABLE",
    "CLASS_BLOCKING",
    "CLASS_OBSERVATIONAL",
    "TRACEABILITY_SCHEMA_VERSION",
    "build_traceability",
    "upgrade_flow_traceability",
    "upgrade_traceability_v1",
]
