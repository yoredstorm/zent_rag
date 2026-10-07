# =============================================================================
# Evidence usage provenance — qué evidencia sostuvo la decisión (lectura)
# =============================================================================
# El runtime decide con código: una CanonicalRule puede compilarse con
# evidencia que nunca se mostró al LLM y un DerivedClaim puede heredar refs de
# premisas cerradas por Premise Closure. Ese uso es un hecho auditable y no
# puede perderse como `used=false`.
#
# Este módulo SÓLO lee estructuras ya publicadas (grounded public dict, steps
# del run) y extrae las referencias por eje. No compila reglas, no cierra
# premisas y no modifica la decisión.
# =============================================================================
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

USAGE_AXES = (
    "envelope",
    "claims",
    "rule_compilation",
    "rule_evaluation",
    "premises",
    "premise_closure",
)


def _payload(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    to_public = getattr(value, "to_public_dict", None)
    if callable(to_public):
        try:
            payload = to_public()
            return dict(payload) if isinstance(payload, Mapping) else {}
        except Exception:  # noqa: BLE001 — la observabilidad nunca rompe
            return {}
    return {}


def _texts(value: Any) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)):
        text = str(value).strip()
        return (text,) if text else ()
    if not isinstance(value, Sequence):
        return ()
    return tuple(
        text
        for item in value
        if (text := str(item or "").strip())
    )


def _records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _grounded_usage(grounded: Mapping[str, Any]) -> dict[str, tuple[str, ...]]:
    envelope = _payload(grounded.get("decision_envelope"))
    claim = _payload(grounded.get("derived_claim"))
    derivations = _payload(grounded.get("derivations"))

    envelope_refs: list[str] = []
    envelope_refs.extend(_texts(envelope.get("evidence_refs")))

    claim_refs: list[str] = []
    claim_refs.extend(_texts(claim.get("evidence_refs")))
    for item in _records(derivations.get("claims")):
        claim_refs.extend(_texts(item.get("evidence_refs")))

    rule_refs: list[str] = []
    for rule in _records(grounded.get("canonical_rules_used")):
        rule_refs.extend(_texts(rule.get("evidence_ids")))
        properties = rule.get("properties")
        if isinstance(properties, Mapping):
            for prop in properties.values():
                if isinstance(prop, Mapping):
                    rule_refs.extend(_texts(prop.get("evidence")))

    evaluation_refs: list[str] = []
    for evaluation in _records(grounded.get("canonical_rule_flow")):
        evaluation_refs.extend(_texts(evaluation.get("evidence_refs")))
        for check in _records(evaluation.get("checks")):
            evaluation_refs.extend(_texts(check.get("evidence")))
        for requirement in _records(evaluation.get("requirements")):
            evaluation_refs.extend(_texts(requirement.get("evidence")))

    premise_refs: list[str] = []
    for premise in _records(grounded.get("premises")):
        origin = str(premise.get("origin") or "")
        if origin and origin != "source":
            continue
        premise_refs.extend(_texts(premise.get("evidence_refs")))
    for requirement in _records(grounded.get("knowledge_requirements")):
        premise_refs.extend(_texts(requirement.get("evidence_refs")))

    return {
        "envelope": _unique(envelope_refs),
        "claims": _unique(claim_refs),
        "rule_compilation": _unique(rule_refs),
        "rule_evaluation": _unique(evaluation_refs),
        "premises": _unique(premise_refs),
        "premise_closure": (),
    }


def _step_usage(steps: Any) -> dict[str, tuple[str, ...]]:
    envelope_refs: list[str] = []
    claim_refs: list[str] = []
    rule_refs: list[str] = []
    evaluation_refs: list[str] = []
    premise_refs: list[str] = []
    closure_refs: list[str] = []
    for step in _records(steps):
        step_type = str(step.get("type") or "")
        if step_type == "grounded_reasoning":
            usage = _grounded_usage(step)
            envelope_refs.extend(usage["envelope"])
            claim_refs.extend(usage["claims"])
            rule_refs.extend(usage["rule_compilation"])
            evaluation_refs.extend(usage["rule_evaluation"])
            premise_refs.extend(usage["premises"])
        elif step_type == "decision_envelope":
            envelope_refs.extend(_texts(step.get("evidence_refs")))
        elif step_type == "final_authority_lock":
            envelope_refs.extend(_texts(step.get("evidence_refs")))
        elif step_type == "premise_closure":
            detail = _payload(step.get("detail"))
            for round_ in _records(detail.get("rounds")):
                closure_refs.extend(_texts(round_.get("new_evidence_refs")))
            if not detail:
                closure_refs.extend(_texts(step.get("new_evidence_refs")))
        elif step_type in {"rule_retrieval", "rule_compilation"}:
            for rule in _records(step.get("canonical")):
                rule_refs.extend(_texts(rule.get("evidence_ids")))
                properties = rule.get("properties")
                if isinstance(properties, Mapping):
                    for prop in properties.values():
                        if isinstance(prop, Mapping):
                            rule_refs.extend(_texts(prop.get("evidence")))
        elif step_type == "rule_evaluation":
            evaluation_refs.extend(_texts(step.get("evidence_refs")))
    return {
        "envelope": _unique(envelope_refs),
        "claims": _unique(claim_refs),
        "rule_compilation": _unique(rule_refs),
        "rule_evaluation": _unique(evaluation_refs),
        "premises": _unique(premise_refs),
        "premise_closure": _unique(closure_refs),
    }


def _unique(values: Sequence[str]) -> tuple[str, ...]:
    seen: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.append(text)
    return tuple(seen)


def merge_usage(
    *parts: Mapping[str, Sequence[str]] | None,
) -> dict[str, tuple[str, ...]]:
    merged: dict[str, list[str]] = {axis: [] for axis in USAGE_AXES}
    for part in parts:
        if not isinstance(part, Mapping):
            continue
        for axis in merged:
            merged[axis].extend(_texts(part.get(axis)))
    return {axis: _unique(values) for axis, values in merged.items()}


def collect_evidence_usage(
    grounded_public: Any = None,
    *,
    steps: Any = (),
) -> dict[str, Any]:
    """Refs por eje + unión de decisión (regla, evaluación, premisas, claim).

    Devuelve tuplas deduplicadas. `decision` es la unión de todo lo que
    contribuyó a una regla soportada, una premisa satisfecha, una evaluación,
    un claim derivado o el envelope: esa evidencia es `used_for_decision` aunque
    el texto final no la mencione.
    """
    usage = merge_usage(_grounded_usage(_payload(grounded_public)), _step_usage(steps))
    decision: list[str] = []
    for axis in (
        "envelope",
        "claims",
        "rule_compilation",
        "rule_evaluation",
        "premises",
        "premise_closure",
    ):
        decision.extend(usage[axis])
    return {**usage, "decision": _unique(decision)}


__all__ = [
    "USAGE_AXES",
    "collect_evidence_usage",
    "merge_usage",
]
