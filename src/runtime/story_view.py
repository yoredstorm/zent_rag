# =============================================================================
# Story View — dos vistas del «Ver flujo»: negocio y técnica (P7).
# =============================================================================
# Normaliza los steps internos a contratos semánticos con `reason_code` y
# `facts`. El frontend TRADUCE; el backend no manda textos hardcodeados por
# vista. Prohibido Chain-of-Thought: solo estados, decisiones, hechos,
# evidencia, reglas, eventos, reason codes y resultados.
# =============================================================================
from __future__ import annotations

from typing import Any, Iterable

STORY_VIEW_VERSION = "story-view-1"

#: step.type -> tipo de negocio.
_BUSINESS_TYPE = {
    "evidence_sufficiency": "evidence_evaluation",
    "answer_gate": "answer_decision",
    "finalization_policy": "authority_resolution",
    "run_invariants": "consistency_check",
    "tool_call": "tool_use",
    "final": "answer",
    "answer_state": "answer_limited",
    "narrative_fast_path": "delivery_path",
    "fast_path": "delivery_path",
    "final_authority_lock": "authority_lock",
    "derived_guard": "authority_guard",
    "termination_gate": "completion_check",
    "conversation_intent": "intent",
    "turn_route": "intent",
    "grounded_reasoning": "deterministic_analysis",
    "deterministic_verifier": "deterministic_verification",
    "narrative_evidence": "evidence_binding",
    "jev_retrieval": "retrieval",
    "tool_routing": "tool_selection",
}


def _status(step: dict) -> str:
    return str(step.get("status") or "")


def _reason_code(step: dict) -> str:
    step_type = str(step.get("type") or "")
    status = _status(step)
    if step_type == "evidence_sufficiency":
        action = str(step.get("recommended_action") or "")
        if action == "generate":
            return "EVIDENCE_COMPLETE"
        if action == "answer_with_limits":
            return "EVIDENCE_PARTIAL"
        if action in ("retrieve_more",):
            return "EVIDENCE_INCOMPLETE"
        if action in ("abstain",):
            return "EVIDENCE_INSUFFICIENT"
        return "EVIDENCE_EVALUATED"
    if step_type == "answer_gate":
        verdict = str(step.get("verdict") or "")
        return {
            "approve": "ANSWER_APPROVED",
            "revise": "ANSWER_REVISION_REQUESTED",
            "retrieve_more": "RETRIEVAL_REQUESTED",
            "answer_with_limits": "ANSWER_LIMITED",
            "abstain": "ANSWER_ABSTAINED",
            "skipped": "GATE_SKIPPED",
        }.get(verdict, "GATE_EVALUATED")
    if step_type == "finalization_policy":
        return f"AUTHORITY_{str(step.get('action') or '').upper()}"
    if step_type == "run_invariants":
        return "CONSISTENCY_VIOLATIONS"
    if step_type == "tool_call":
        if step.get("error"):
            return "TOOL_FAILED"
        return "TOOL_EXECUTED"
    if step_type == "final":
        return "ANSWER_READY"
    if step_type == "answer_state":
        state = str(step.get("state") or "")
        return {
            "UNDETERMINED_RULE": "ANSWER_UNDETERMINED",
            "INSUFFICIENT_EVIDENCE": "ANSWER_ABSTAINED",
            "CONFLICTING_EVIDENCE": "ANSWER_CONFLICTING",
            "RETRIEVAL_UNAVAILABLE": "RETRIEVAL_UNAVAILABLE",
            "CONFLICTING_RULE": "ANSWER_CONFLICTING",
            "DERIVED_RESULT": "ANSWER_DERIVED",
        }.get(state, "ANSWER_STATE")
    if step_type in ("narrative_fast_path", "fast_path"):
        mode = str(step.get("mode") or "").upper()
        return f"DELIVERY_{mode}" if mode else "DELIVERY_PATH"
    if step_type == "final_authority_lock":
        return "AUTHORITY_LOCKED"
    if step_type == "derived_guard":
        action = str(step.get("action") or "")
        return "AUTHORITY_OVERRIDDEN" if action == "override" else "AUTHORITY_VERIFIED"
    if step_type == "termination_gate":
        return "REQUEST_SATISFIED" if step.get("stop") else "REQUEST_NOT_SATISFIED"
    if status == "error":
        return "STEP_FAILED"
    if status == "warn":
        return "STEP_WITH_WARNING"
    return "STEP_RECORDED"


def _facts(step: dict) -> dict:
    step_type = str(step.get("type") or "")
    facts: dict[str, Any] = {}
    if step_type == "evidence_sufficiency":
        for key in ("supporting_chunks", "missing_entities", "missing_anchors", "reason"):
            value = step.get(key)
            if value not in (None, (), [], ""):
                facts[key] = value
    elif step_type == "answer_gate":
        for key in ("grounding_verdict", "complete", "grounded", "unsupported_claims"):
            value = step.get(key)
            if value not in (None, (), [], ""):
                facts[key] = value
    elif step_type == "finalization_policy":
        for key in (
            "authority",
            "signals",
            "signals_ignored",
            "conflicts",
            "missing_requirements",
            "limited",
        ):
            value = step.get(key)
            if value not in (None, (), [], "", False):
                facts[key] = value
    elif step_type == "run_invariants":
        facts["violations"] = step.get("violations") or []
    elif step_type == "tool_call":
        for key in ("tool", "error", "new_evidence"):
            if step.get(key) not in (None, ""):
                facts[key] = step[key]
    return facts


def business_steps(steps: Iterable[Any]) -> list[dict]:
    """Vista de NEGOCIO: qué entendió/buscó/encontró/decidió, con reason codes.

    Sin CoT, sin campos técnicos (provider/tokens/latencia/checks): el portal
    traduce `reason_code` + `facts` a lenguaje humano.
    """
    rows: list[dict] = []
    for step in steps or ():
        if not isinstance(step, dict):
            continue
        step_type = str(step.get("type") or "")
        entry: dict[str, Any] = {
            "type": _BUSINESS_TYPE.get(step_type, step_type or "step"),
            "source_type": step_type or None,
            "status": _status(step) or "ok",
            "reason_code": _reason_code(step),
        }
        facts = _facts(step)
        if facts:
            entry["facts"] = facts
        detail = str(step.get("detail") or "").strip()
        if detail and not any(key in detail.lower() for key in ("prompt", "chain of thought")):
            entry["detail"] = detail[:200]
        rows.append(entry)
    return rows


#: Campos que la vista técnica recorta (contenido pesado, nunca CoT).
_TECHNICAL_TRUNCATE = 240


def technical_steps(steps: Iterable[Any]) -> list[dict]:
    """Vista TÉCNICA: steps crudos con payloads, sin contenido pesado.

    Tool args/outputs quedan truncados; no se inventan valores y UNKNOWN != 0.
    """
    rows: list[dict] = []
    for step in steps or ():
        if not isinstance(step, dict):
            continue
        entry = {}
        for key, value in step.items():
            if key in ("output", "content", "rendered_context", "excerpt"):
                text = str(value or "")
                entry[key] = text[:_TECHNICAL_TRUNCATE]
                entry[f"{key}_truncated"] = len(text) > _TECHNICAL_TRUNCATE
            else:
                entry[key] = value
        rows.append(entry)
    return rows


def build_story(steps: Iterable[Any], *, view: str = "business") -> dict:
    """Contrato único: `business` (portal) o `technical` (forense)."""
    if view == "technical":
        return {
            "version": STORY_VIEW_VERSION,
            "view": "technical",
            "steps": technical_steps(steps),
        }
    return {
        "version": STORY_VIEW_VERSION,
        "view": "business",
        "steps": business_steps(steps),
    }


__all__ = [
    "STORY_VIEW_VERSION",
    "build_story",
    "business_steps",
    "technical_steps",
]
