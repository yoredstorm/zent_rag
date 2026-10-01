"""Controles, taxonomía de fallbacks y evaluación de límites de generación.

Un "fallback" mezclaba cosas distintas (§12): un límite de tokens recuperado sin
impacto aparecía como fallback material, mientras `fallback_used = false`. Acá
se separa:

- `warning`: anomalía observada, sin acción correctiva.
- `recoverable_event`: el sistema reaccionó y siguió.
- `retry`: se reintentó una operación.
- `continuation`: se continuó tras un límite interno.
- `provider_fallback` / `model_fallback` / `retrieval_fallback`: mecanismo
  alternativo concreto.
- `material_fallback`: cambió el resultado (límites, abstención, claims).
- `fatal_error`: el run no pudo completar.

`MAX_TOKENS_REACHED` se evalúa antes de aceptar la verificación declarada (§13)
y produce `RECOVERED_NO_IMPACT | MINOR_DEGRADATION | POSSIBLY_INCOMPLETE |
MATERIAL_ERROR`, con `material_effect` sólo en los dos últimos.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

SEVERITY_INFO = "INFO"
SEVERITY_NOTICE = "NOTICE"
SEVERITY_WARNING = "WARNING"
SEVERITY_ERROR = "ERROR"
SEVERITY_CRITICAL = "CRITICAL"

#: clase -> material_effect por defecto
FALLBACK_CLASSES: dict[str, str] = {
    "claims_answer_with_limits": "material_fallback",
    "partial_evidence_answer_with_limits": "material_fallback",
    "figures_unverified": "material_fallback",
    "hierarchy_unverified": "material_fallback",
    "disclaimer_contradiction": "material_fallback",
    "claims_conflict": "material_fallback",
    "claims_abstain": "material_fallback",
    "preflight_abstained": "material_fallback",
    "max_tokens exceeded": "continuation",
    "plan_failed": "recoverable_event",
    "model_escalation_skipped_retrieval_uncertainty": "recoverable_event",
    "weak_alignment_overridden_by_claims": "warning",
    "citation_out_of_package": "warning",
    "ungrounded": "warning",
    "claims_revision": "recoverable_event",
}

RETAINED_CODES = {"claims_abstain", "preflight_abstained"}
MATERIAL_CODES = {
    code for code, kind in FALLBACK_CLASSES.items() if kind == "material_fallback"
}

#: guardrail detail (fragmento normalizado) -> (control_code, severity, action)
GUARDRAIL_CONTROLS: tuple[tuple[str, tuple[str, str, str]], ...] = (
    ("max_tokens exceeded", ("MAX_TOKENS_REACHED", SEVERITY_WARNING, "continue_generation")),
    ("max_cost exceeded", ("COST_LIMIT_REACHED", SEVERITY_WARNING, "finalize_answer")),
    ("max_tool_calls exceeded", ("TOOL_CALL_LIMIT_REACHED", SEVERITY_NOTICE, "stop_tools")),
    (
        "max_execution_seconds exceeded",
        ("EXECUTION_TIME_LIMIT_REACHED", SEVERITY_WARNING, "finish_run"),
    ),
    ("max_steps reached", ("STEP_LIMIT_REACHED", SEVERITY_WARNING, "finish_run")),
    (
        "model_budget_exceeded",
        ("MODEL_PROTECTION_TRIGGERED", SEVERITY_WARNING, "degrade_model"),
    ),
    ("model_circuit_open", ("MODEL_CIRCUIT_OPEN", SEVERITY_WARNING, "fallback_provider")),
    (
        "deployment_rate_exceeded",
        ("PROVIDER_RATE_LIMIT", SEVERITY_WARNING, "retry_or_fallback"),
    ),
    ("quota_exceeded", ("PROVIDER_QUOTA_EXCEEDED", SEVERITY_ERROR, "fallback_provider")),
    ("retrieval blocked", ("RETRIEVAL_BLOCKED", SEVERITY_WARNING, "answer_without_retrieval")),
    ("invalid json", ("MALFORMED_MODEL_OUTPUT", SEVERITY_NOTICE, "repair")),
    ("loop prevention", ("LOOP_PREVENTED", SEVERITY_WARNING, "stop_loop")),
)

FATAL_CLASS = "fatal_error"

_TERMINAL = (".", "!", "?", "…", '"', "'", ")", "]", "»", ":", ";", "`")


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


def classify_fallback(code: str) -> str:
    """Clasifica un código de fallback; heurística explícita para desconocidos."""
    normalized = code.strip()
    if normalized in FALLBACK_CLASSES:
        return FALLBACK_CLASSES[normalized]
    lowered = normalized.casefold()
    if "abstain" in lowered:
        return "material_fallback"
    if "provider" in lowered:
        return "provider_fallback"
    if "model" in lowered and "fallback" in lowered:
        return "model_fallback"
    if "retrieval" in lowered or "search" in lowered:
        return "retrieval_fallback"
    if "retry" in lowered or "reintent" in lowered:
        return "retry"
    if "token" in lowered:
        return "continuation"
    if "unverified" in lowered or "contradiction" in lowered or "conflict" in lowered:
        return "warning"
    if "fail" in lowered or "error" in lowered:
        return "recoverable_event"
    return "warning"


def _answer_text(flow: Mapping[str, Any]) -> str | None:
    direct = _text(flow.get("answer"))
    if direct:
        return direct
    for step in reversed(_records(flow.get("steps"))):
        if _text(step.get("type")) in {"final", "generation"}:
            answer = _text(step.get("answer"))
            if answer:
                return answer
    response = _record(flow.get("response"))
    answer = _text(response.get("answer") or response.get("content"))
    return answer or None


def _finish_reason(flow: Mapping[str, Any]) -> str | None:
    for key in ("finish_reason",):
        value = _text(flow.get(key))
        if value:
            return value
    generation = _record(flow.get("generation"))
    value = _text(generation.get("finish_reason"))
    if value:
        return value
    for step in reversed(_records(flow.get("steps"))):
        if _text(step.get("type")) != "llm":
            continue
        action = _record(step.get("action"))
        value = _text(step.get("finish_reason") or action.get("finish_reason"))
        if value:
            return value
    return None


def _answer_gate(flow: Mapping[str, Any]) -> dict[str, Any]:
    for step in _records(flow.get("steps")):
        if _text(step.get("type")) == "answer_gate":
            return step
    return {}


def assess_max_tokens_impact(
    flow: Mapping[str, Any],
    *,
    evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Evalúa si el límite de tokens afectó materialmente la respuesta (§13)."""
    answer = _answer_text(flow)
    finish_reason = _finish_reason(flow)
    gate = _answer_gate(flow)
    counts = _record(_record(evidence or {}).get("counts"))
    citations = _record(_record(evidence or {}).get("citations_summary"))
    steps = _records(flow.get("steps"))
    delivered = bool(
        answer
        or any(_text(step.get("type")) == "final" for step in steps)
        or _record(flow.get("generation")).get("skipped") is False
    )
    answer_terminated: bool | None = None
    if answer:
        answer = answer.rstrip()
        answer_terminated = answer.endswith(_TERMINAL)
    gate_complete = gate.get("complete")
    if not isinstance(gate_complete, bool):
        gate_complete = None
    citations_complete: bool | None = None
    if citations:
        dangling = _records(citations.get("dangling"))
        if citations.get("unique_cited") is not None or citations.get("references"):
            citations_complete = not dangling

    if not delivered:
        impact = "MATERIAL_ERROR"
    elif finish_reason == "length":
        impact = "POSSIBLY_INCOMPLETE"
    elif answer_terminated is False or gate_complete is False:
        impact = "POSSIBLY_INCOMPLETE"
    elif citations_complete is False:
        impact = "MINOR_DEGRADATION"
    else:
        impact = "RECOVERED_NO_IMPACT"

    material = impact in {"POSSIBLY_INCOMPLETE", "MATERIAL_ERROR"}
    return {
        "code": "MAX_TOKENS_REACHED",
        "impact": impact,
        "material_effect": material,
        "recovered": not material,
        "checks": {
            "answer_delivered": delivered,
            "answer_terminated": answer_terminated,
            "finish_reason": finish_reason,
            "answer_gate_complete": gate_complete,
            "citations_complete": citations_complete,
        },
    }


def build_controls_section(
    flow: Mapping[str, Any],
    *,
    evidence: Mapping[str, Any],
    jev: Mapping[str, Any],
) -> dict[str, Any]:
    """Controles explicables + fallbacks clasificados + warnings de generación."""
    controls: list[dict[str, Any]] = []
    seen_codes: set[str] = set()

    def add_control(
        code: str,
        *,
        severity: str,
        trigger: str,
        action_taken: str,
        recovered: bool,
        material_effect: bool,
        source_event_ids: list[str] | None = None,
        params: dict[str, Any] | None = None,
    ) -> None:
        if code in seen_codes:
            return
        seen_codes.add(code)
        controls.append(
            {
                "control_code": code,
                "severity": severity,
                "trigger": trigger,
                "action_taken": action_taken,
                "recovered": recovered,
                "material_effect": material_effect,
                "source_event_ids": source_event_ids or [],
                "params": params or {},
            }
        )

    max_tokens_impacts: list[dict[str, Any]] = []
    guardrail_steps = [
        step for step in _records(flow.get("steps")) if _text(step.get("type")) == "guardrail"
    ]
    for step in guardrail_steps:
        detail = _text(step.get("detail"))
        lowered = detail.casefold()
        for marker, (code, severity, action) in GUARDRAIL_CONTROLS:
            if marker not in lowered:
                continue
            if code == "MAX_TOKENS_REACHED":
                impact = assess_max_tokens_impact(flow, evidence=evidence)
                max_tokens_impacts.append(impact)
                add_control(
                    code,
                    severity=severity,
                    trigger=detail,
                    action_taken=action,
                    recovered=bool(impact["recovered"]),
                    material_effect=bool(impact["material_effect"]),
                    source_event_ids=[_text(step.get("id"))] if step.get("id") else [],
                    params={"impact": impact["impact"], "checks": impact["checks"]},
                )
            else:
                add_control(
                    code,
                    severity=severity,
                    trigger=detail,
                    action_taken=action,
                    recovered=True,
                    material_effect=False,
                    source_event_ids=[_text(step.get("id"))] if step.get("id") else [],
                )
            break

    fallbacks = [_text(item) for item in (flow.get("fallbacks") or []) if _text(item)]
    fallback_events: list[dict[str, Any]] = []
    for code in fallbacks:
        kind = classify_fallback(code)
        material = kind == "material_fallback"
        fallback_events.append(
            {
                "code": code,
                "class": kind,
                "material_effect": material,
                "recovered": not material,
                "source_event_ids": [],
            }
        )
        if code in {"max_tokens exceeded", "tokens_exceeded"} and "MAX_TOKENS_REACHED" not in seen_codes:
            impact = assess_max_tokens_impact(flow, evidence=evidence)
            max_tokens_impacts.append(impact)
            add_control(
                "MAX_TOKENS_REACHED",
                severity=SEVERITY_WARNING,
                trigger=code,
                action_taken="continue_generation",
                recovered=bool(impact["recovered"]),
                material_effect=bool(impact["material_effect"]),
                params={"impact": impact["impact"], "checks": impact["checks"]},
            )
        elif kind in {"provider_fallback", "model_fallback", "retrieval_fallback"}:
            add_control(
                kind.upper(),
                severity=SEVERITY_NOTICE,
                trigger=code,
                action_taken="use_alternative",
                recovered=True,
                material_effect=False,
            )
        elif kind == "fatal_error":
            add_control(
                FATAL_CLASS.upper(),
                severity=SEVERITY_ERROR,
                trigger=code,
                action_taken="abort",
                recovered=False,
                material_effect=True,
            )

    embedding = _record(flow.get("embedding"))
    if embedding.get("fallback"):
        add_control(
            "EMBEDDING_FALLBACK",
            severity=SEVERITY_NOTICE,
            trigger=_text(embedding.get("fallback")),
            action_taken="use_alternative_provider",
            recovered=True,
            material_effect=False,
        )

    verification = _record(flow.get("verification"))
    if verification.get("fallback_used") or verification.get("fallback_code"):
        add_control(
            "VERIFIER_FALLBACK",
            severity=SEVERITY_NOTICE,
            trigger=_text(verification.get("fallback_code")) or "fallback_used",
            action_taken="use_alternative_check",
            recovered=True,
            material_effect=False,
        )

    for step in _records(flow.get("steps")):
        if _text(step.get("type")) != "answer_revision":
            continue
        add_control(
            "ANSWER_REVISED",
            severity=SEVERITY_NOTICE,
            trigger=_text(step.get("detail")) or "revision",
            action_taken="rewrite_answer",
            recovered=True,
            material_effect=False,
            source_event_ids=[_text(step.get("id"))] if step.get("id") else [],
        )

    # Coherencia: material_fallback declarado en eventos ⇒ evento material.
    # Los controles de generación (max_tokens) se siguen aparte en degradations.
    material_declared = any(event["material_effect"] for event in fallback_events)
    fallbacks_material = material_declared

    return {
        "controls": controls,
        "fallbacks": {
            "events": fallback_events,
            "material": fallbacks_material,
            "classes": _class_counts(fallback_events),
            "retained": any(code in RETAINED_CODES for code in fallbacks),
        },
        "generation_warnings": max_tokens_impacts,
        "material_controls": [
            control for control in controls if control["material_effect"]
        ],
    }


def _class_counts(events: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in events:
        kind = _text(event.get("class")) or "warning"
        counts[kind] = counts.get(kind, 0) + 1
    return counts


__all__ = [
    "FALLBACK_CLASSES",
    "GUARDRAIL_CONTROLS",
    "MATERIAL_CODES",
    "RETAINED_CODES",
    "SEVERITY_CRITICAL",
    "SEVERITY_ERROR",
    "SEVERITY_INFO",
    "SEVERITY_NOTICE",
    "SEVERITY_WARNING",
    "assess_max_tokens_impact",
    "build_controls_section",
    "classify_fallback",
]
