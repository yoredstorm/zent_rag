"""JEV canónico — juicios interpretados y decisiones con efecto real.

Reglas (§8, §9, §10):

- Ejecutar JEV no es intervenir. `material_intervention` exige una decisión
  aplicada que cambie o bloquee el camino; `generate/default` aplicada queda
  como observación.
- Toda distribución cruda se preserva (`raw`), pero la interpretación expone
  por separado `selected_probability`, `confidence`, `certainty`, `margin`,
  `entropy` y `band`. Nunca se llama "confianza" a dos magnitudes distintas.
- `PROBABILITY_MISMATCH` se emite sólo cuando dos magnitudes homónimas se
  contradicen; la UI muestra ambas etiquetadas en vez de ocultar una.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

CLASS_OBSERVATIONAL = "OBSERVATIONAL"
CLASS_ACTIONABLE = "ACTIONABLE"
CLASS_BLOCKING = "BLOCKING"

#: Acciones compuestas del preflight que cambian la ejecución.
CHANGING_ACTIONS = {
    "retrieve_more",
    "reconstruct_more",
    "deterministic_answer",
    "ask_user",
    "abstain",
    "revise",
}
BLOCKING_ACTIONS = {"abstain", "ask_user"}
RETRY_ACTIONS = {"retrieve_more", "search_knowledge", "reconstruct_more"}

#: Acciones que sólo confirman la marcha: no son intervención material.
DEFAULT_ACTIONS = {"generate", "answer", "final", "allow", "approve", "continue", "none"}

#: action compuesta -> efecto semántico (mismo vocabulario que preflight.choices).
ACTION_EFFECTS = {
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
PHASE_PURPOSE = {
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


def classify(action: str, applied: bool, allow_generation: bool | None,
             influenced: bool | None) -> str:
    if applied and (action in BLOCKING_ACTIONS or allow_generation is False):
        return CLASS_BLOCKING
    if applied and (influenced is True or action in CHANGING_ACTIONS):
        return CLASS_ACTIONABLE
    return CLASS_OBSERVATIONAL


def confidence_band(
    confidence: float | None, *, certain: bool | None = None, ambiguous: bool | None = None
) -> str | None:
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


def _options(distribution: Mapping[str, Any], outcome: str) -> list[dict[str, Any]]:
    probabilities = _record(distribution.get("probabilities"))
    return [
        {
            "key": str(key),
            "probability": _probability(value),
            "selected": str(key) == outcome,
        }
        for key, value in probabilities.items()
    ]


def _interpretation(
    question: Mapping[str, Any], display: Mapping[str, Any]
) -> dict[str, Any]:
    distribution = _record(question.get("distribution"))
    outcome = _text(question.get("decision")) or _text(display.get("outcome_key"))
    options = _options(distribution, outcome)
    selected_probability = display.get("probability")
    runner_up_key = _text(distribution.get("runner_up")) or None
    runner_up_probability = _probability(distribution.get("runner_up_probability"))
    if runner_up_probability is None and options:
        others = [
            option["probability"]
            for option in options
            if not option["selected"] and option["probability"] is not None
        ]
        runner_up_probability = max(others) if others else None
    margin = _probability(distribution.get("margin"))
    if margin is None and selected_probability is not None and runner_up_probability is not None:
        margin = round(max(0.0, selected_probability - runner_up_probability), 4)
    entropy = _probability(distribution.get("entropy"))
    band = display.get("confidence_band")
    if band is None:
        band = confidence_band(
            selected_probability,
            certain=display.get("certain"),
            ambiguous=display.get("ambiguous"),
        )
    certain = display.get("certain")
    ambiguous = display.get("ambiguous")
    if certain is True:
        verdict = "CONFIDENT"
    elif ambiguous is True or (margin is not None and margin <= 0.1):
        verdict = "UNCERTAIN"
    elif selected_probability is not None and selected_probability >= 0.75:
        verdict = "CONFIDENT"
    elif selected_probability is None:
        verdict = "UNKNOWN"
    else:
        verdict = "LEANING"
    return {
        "outcome_key": outcome or None,
        "selected_probability": selected_probability,
        "confidence": _probability(question.get("confidence")),
        "certainty": _probability(
            display.get("certainty")
            if display.get("certainty") is not None
            else question.get("certainty")
        ),
        "margin": margin,
        "entropy": entropy,
        "runner_up_key": runner_up_key,
        "runner_up_probability": runner_up_probability,
        "band": band,
        "certain": certain if isinstance(certain, bool) else None,
        "ambiguous": ambiguous if isinstance(ambiguous, bool) else None,
        "verdict": verdict,
        "options": options,
    }


def _judgment_display(question: Mapping[str, Any]) -> dict[str, Any]:
    """Transformación única pregunta → resultado mostrado.

    `probability` SIEMPRE es P(opción elegida) desde la propia distribución; la
    confianza derivada viaja aparte en `confidence` (nunca se mezclan).
    """
    kind = _text(question.get("type")).lower()
    decision = _text(question.get("decision"))
    distribution = _record(question.get("distribution"))
    probabilities = _record(distribution.get("probabilities"))
    display: dict[str, Any] = {
        "outcome_key": decision or None,
        "confidence_band": None,
        "confidence": _probability(
            distribution.get("confidence")
            if distribution.get("confidence") is not None
            else question.get("confidence")
        ),
    }
    if kind == "choice":
        certain = distribution.get("certain")
        ambiguous = distribution.get("ambiguous")
        probability = _probability(distribution.get("confidence"))
        if probability is None:
            probability = _probability(question.get("confidence"))
        if decision and decision in probabilities:
            probability = _probability(probabilities.get(decision))
        display["certain"] = bool(certain) if isinstance(certain, bool) else None
        display["ambiguous"] = bool(ambiguous) if isinstance(ambiguous, bool) else None
        display["probability"] = probability
        display["confidence_band"] = confidence_band(
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
        display["confidence_band"] = confidence_band(certainty)
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
        display["confidence_band"] = confidence_band(confidence)
    else:
        confidence = _probability(question.get("confidence"))
        display["probability"] = confidence
        display["confidence_band"] = confidence_band(confidence)
    display["probability"] = display.get("probability")
    return display


def _judgments(
    flow: Mapping[str, Any],
    events: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
    diagnostics: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    decisions_by_phase = {
        _text(decision.get("phase")): decision["decision_id"] for decision in decisions
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
            display = _judgment_display(question)
            entry = {
                "judgment_id": f"{phase or 'unknown'}:{question_id}",
                "id": question_id,
                "phase": phase,
                "purpose": PHASE_PURPOSE.get(phase, phase or "judgment"),
                "question_code": question_id,
                "type": _text(question.get("type")).lower() or "noul",
                "answer": question.get("decision"),
                "effect_code": _text(question.get("effect")) or None,
                "decision_id": decisions_by_phase.get(phase),
                "applied_decision_id": None,
                "display": display,
                "interpretation": _interpretation(question, display),
                "alternatives": [
                    {"key": str(key), "probability": _probability(value)}
                    for key, value in _record(
                        _record(question.get("distribution")).get("probabilities")
                    ).items()
                ],
                "raw": {
                    "type": _text(question.get("type")) or None,
                    "decision": question.get("decision"),
                    "version": _int_or_none(question.get("version")),
                    "risk": _text(question.get("risk")) or None,
                    "value": _number(question.get("value")),
                    "confidence": _number(question.get("confidence")),
                    "certainty": _number(question.get("certainty")),
                    "ambiguous": question.get("ambiguous"),
                    "distribution": _record(question.get("distribution")) or None,
                },
                "technical": {
                    "version": _int_or_none(question.get("version")),
                    "risk": _text(question.get("risk")) or None,
                    "value": _number(question.get("value")),
                    "certainty": _probability(question.get("certainty")),
                    "distribution": _record(question.get("distribution")) or None,
                },
                "source_event_ids": [],
            }
            entries[identity] = entry
            order.append(identity)
            _check_probability(entry, diagnostics)
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

    applied_by_question = {
        _text(decision.get("question_id")): decision["decision_id"]
        for decision in decisions
        if _text(decision.get("question_id"))
    }
    for judgment in (entries[key] for key in order):
        judgment["applied_decision_id"] = applied_by_question.get(judgment["id"])
    return [entries[key] for key in order]


def _check_probability(
    judgment: Mapping[str, Any], diagnostics: list[dict[str, Any]]
) -> None:
    # Sólo aplica a elecciones con distribución: ahí P(opción elegida) y la
    # confianza derivada pueden confundirse. En noul la magnitud es la certeza.
    if _text(judgment.get("type")) != "choice":
        return
    interpretation = _record(judgment.get("interpretation"))
    selected = interpretation.get("selected_probability")
    confidence = interpretation.get("confidence")
    if selected is None or confidence is None:
        return
    if abs(float(selected) - float(confidence)) > 1e-3:
        diagnostics.append(
            {
                "code": "PROBABILITY_MISMATCH",
                "judgment_id": judgment["judgment_id"],
                "selected_probability": selected,
                "confidence": confidence,
                "outcome_key": interpretation.get("outcome_key"),
            }
        )


def _decision_events(
    flow: Mapping[str, Any],
    events: list[dict[str, Any]],
    diagnostics: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    block = _record(flow.get("jev_preflight"))
    raw_decisions = _records(block.get("decisions"))
    if not raw_decisions:
        raw_decisions = _records(_record(flow.get("jev")).get("decisions"))

    effects_by_phase: dict[str, list[str]] = {}
    event_by_phase: dict[str, str] = {}
    for event in events:
        if _text(event.get("kind")) != "jev_pack":
            continue
        metrics = _record(event.get("metrics"))
        phase = _text(metrics.get("phase")) or _text(event.get("phase"))
        effects = [_text(item) for item in (metrics.get("effects") or []) if _text(item)]
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
        allow_bool = allow_generation if isinstance(allow_generation, bool) else None
        influenced = raw.get("influer")
        if influenced is None and applied:
            influenced = bool(
                raw.get("influer")
                or allow_generation is False
                or action in CHANGING_ACTIONS
            )
        classification = classify(
            action,
            applied,
            allow_bool,
            influenced if isinstance(influenced, bool) else None,
        )
        reasons = [_text(item) for item in (raw.get("reasons") or []) if _text(item)][:8]
        # `generate/default` aplicada confirma la marcha: no es intervención.
        is_default = bool(
            applied
            and action in DEFAULT_ACTIONS
            and influenced is not True
            and allow_bool is not False
        )
        material = (
            applied
            and not is_default
            and classification in {CLASS_ACTIONABLE, CLASS_BLOCKING}
        )
        changed_route = bool(
            material
            and (
                action in CHANGING_ACTIONS
                or allow_bool is False
            )
        )
        effect_codes: list[str] = []
        for effect in effects_by_phase.get(phase, []):
            if effect not in effect_codes:
                effect_codes.append(effect)
        action_effect = ACTION_EFFECTS.get(action)
        if action_effect and action_effect not in effect_codes:
            effect_codes.append(action_effect)
        confidence = _probability(raw.get("confidence"))
        decided_by = _text(raw.get("decided_by"))
        provider = "JEV" if not decided_by or decided_by.startswith("jev") else decided_by
        decision_id = f"decision:{index}:{phase or 'unknown'}"
        decision: dict[str, Any] = {
            "decision_id": decision_id,
            "id": decision_id,
            "provider": provider,
            "phase": phase or None,
            "purpose": PHASE_PURPOSE.get(phase, phase or "decision"),
            "question_id": question_id or None,
            "verdict": action or None,
            "action": action or None,
            "action_applied": applied,
            "classification": classification,
            "is_default": is_default,
            "material": material,
            "changed_route": changed_route,
            "effect_codes": effect_codes,
            "reason_codes": reasons,
            "unsatisfied": [
                _text(item) for item in (raw.get("unsatisfied") or []) if _text(item)
            ][:8],
            "uncertain_critical": [
                _text(item)
                for item in (raw.get("uncertain_critical") or [])
                if _text(item)
            ][:8],
            "tier": _text(raw.get("tier")) or None,
            "allow_generation": allow_bool,
            "display": {
                "outcome_key": action or None,
                "probability": confidence,
                "confidence_band": confidence_band(confidence),
            },
            "source_event_ids": [event_by_phase[phase]] if phase in event_by_phase else [],
        }
        if (
            action in RETRY_ACTIONS
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

    for decision in decisions:
        if (
            decision["classification"] in {CLASS_ACTIONABLE, CLASS_BLOCKING}
            and decision["action_applied"] is not True
        ):
            diagnostics.append(
                {
                    "code": "ACTION_APPLIED_REQUIRED",
                    "decision_id": decision["decision_id"],
                    "classification": decision["classification"],
                }
            )
    return decisions


def build_jev_section(
    flow: Mapping[str, Any],
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    """Sección `jev` completa + listas compatibles con la proyección v1."""
    diagnostics: list[dict[str, Any]] = []
    decisions = _decision_events(flow, events, diagnostics)
    judgments = _judgments(flow, events, decisions, diagnostics)

    block = _record(flow.get("jev_preflight"))
    packs = _records(block.get("packs"))
    summary = _record(block.get("summary"))
    agent_jev = _record(flow.get("jev"))

    calls = _int_or_none(summary.get("calls"))
    pack_events = sum(1 for event in events if _text(event.get("kind")) == "jev_pack")
    if calls is None:
        calls = max(len(packs), pack_events) or None
    material_decisions = [decision for decision in decisions if decision["material"]]
    applied_decisions = [decision for decision in decisions if decision["action_applied"]]
    requested_more = any(
        decision["action_applied"] and decision["action"] in RETRY_ACTIONS
        for decision in decisions
    )
    blocked = any(
        decision["action_applied"]
        and (
            decision["action"] in BLOCKING_ACTIONS
            or decision["allow_generation"] is False
        )
        for decision in decisions
    )
    checks = len(judgments) or len(decisions)
    executed = bool(packs or judgments or decisions or _int_or_none(summary.get("calls")))

    latency_ms = _number(summary.get("latency_ms"))
    cost_usd = _number(summary.get("cost_usd"))
    if latency_ms is None:
        latency_ms = _number(agent_jev.get("ms"))
    if cost_usd is None:
        cost_usd = _number(agent_jev.get("cost"))
    tokens = _record(summary.get("tokens"))
    mode = _text(block.get("mode")) or _text(agent_jev.get("mode")) or None

    return {
        "executed": executed,
        "mode": mode,
        "calls": calls,
        "packs": len(packs) or sum(
            1 for event in events if _text(event.get("kind")) == "jev_pack"
        ),
        "judgments_count": len(judgments),
        "checks": checks,
        "material_intervention": bool(material_decisions),
        "changed_route": any(decision["changed_route"] for decision in decisions),
        "requested_more_evidence": requested_more,
        "blocked_generation": blocked,
        "latency_ms": latency_ms,
        "cost_usd": cost_usd,
        "tokens": {
            "input": _int_or_none(tokens.get("input")),
            "output": _int_or_none(tokens.get("output")),
        },
        "decisions": decisions,
        "decisions_applied": applied_decisions,
        "material_decisions": material_decisions,
        "judgments": judgments,
        "summary": summary or None,
        "diagnostics": diagnostics,
    }


__all__ = [
    "ACTION_EFFECTS",
    "BLOCKING_ACTIONS",
    "CHANGING_ACTIONS",
    "CLASS_ACTIONABLE",
    "CLASS_BLOCKING",
    "CLASS_OBSERVATIONAL",
    "DEFAULT_ACTIONS",
    "PHASE_PURPOSE",
    "RETRY_ACTIONS",
    "build_jev_section",
    "classify",
    "confidence_band",
]
