# =============================================================================
# Response quality — chequeos de la RESPUESTA, no del contrato.
# =============================================================================
# Distingue explícitamente:
#   contrato configurado != contrato aplicado != respuesta generada
#   != respuesta semánticamente evaluada.
#
# Estos chequeos son deterministas. No se etiquetan como "validado semántico";
# si no hubo juez semántico, `semantic_evaluated=False` y la UI muestra
# "No evaluado" o "Chequeos deterministas".
# =============================================================================
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping

from src.intelligence.response.intent import EVALUATIVE_INTENTS, detect_user_intent

_REFUSAL_RE = re.compile(
    r"(?:no\s+puedo\s+(?:darte|ofrecerte|expresar)\s+(?:una\s+)?opini[oó]n|"
    r"no\s+tengo\s+(?:experiencias?|opiniones?|sentimientos?)\s+personales?|"
    r"como\s+(?:modelo|ia|inteligencia\s+artificial)\s+no\s+puedo|"
    r"no\s+estoy\s+autorizad[oa]\s+a\s+opinar|"
    r"i\s+cannot\s+give\s+you\s+an\s+opinion|"
    r"as\s+an\s+ai,?\s+i\s+(?:cannot|can't))",
    re.IGNORECASE,
)
_INTERNAL_METADATA_RE = re.compile(
    r"(?:fragmentos\s*=|cobertura_entidades\s*=|policy_version|run_id|trace_id|"
    r"evidence_id|correlation_id|blueprint\s*=|decided_by\s*=|"
    r"respuesta\s+determinista|motor\s+de\s+recuperaci[oó]n|"
    r"\b\d+\s*%\s*(?:de\s+)?cobertura|retrieval\s+(?:score|score:)\s*=)",
    re.IGNORECASE,
)
_EVALUATION_CUE_RE = re.compile(
    r"(?:\bme\s+parece\b|\bconsidero\b|\ben\s+mi\s+lectura\b|\bmi\s+lectura\b|"
    r"\bmi\s+interpretaci[oó]n\b|"
    r"\binterpreto\b|\bvaloro\b|\bopino\b|\bcreo\s+que\b|\brecomiendo\b|"
    r"\brecomendar[ií]a\b|\ba\s+mi\s+juicio\b|\bdesde\s+mi\s+lectura\b|"
    r"\bwhat\s+i\s+think\b|\bin\s+my\s+reading\b|\bi\s+would\s+recommend\b)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ResponseQuality:
    """Chequeos independientes de intención, persona, estilo y evidencia."""

    status: str = "not_evaluated"
    semantic_evaluated: bool = False
    intent_fulfilled: bool | None = None
    persona_preserved: bool | None = None
    style_applied: bool | None = None
    evidence_integrity: bool | None = None
    direct_answer_present: bool | None = None
    unnecessary_refusal: bool | None = None
    irrelevant_internal_metadata: bool | None = None
    verbosity_appropriate: bool | None = None
    notes: tuple[str, ...] = ()
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def label(self) -> str:
        if self.semantic_evaluated:
            return "Evaluación semántica"
        if self.status in {"deterministic_checks", "needs_review"}:
            return "Chequeos deterministas"
        return "No evaluado"

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "semantic_evaluated": bool(self.semantic_evaluated),
            "label": self.label,
            "intent_fulfilled": self.intent_fulfilled,
            "persona_preserved": self.persona_preserved,
            "style_applied": self.style_applied,
            "evidence_integrity": self.evidence_integrity,
            "direct_answer_present": self.direct_answer_present,
            "unnecessary_refusal": self.unnecessary_refusal,
            "irrelevant_internal_metadata": self.irrelevant_internal_metadata,
            "verbosity_appropriate": self.verbosity_appropriate,
            "notes": list(self.notes)[:8],
            "details": dict(self.details),
        }


def _answer_text(answer: Any) -> str:
    return str(answer or "").strip()


def _length_bounds(detail: str) -> tuple[int, int]:
    return {
        "brief": (20, 1200),
        "normal": (30, 2200),
        "detailed": (40, 3500),
        "deep": (40, 6000),
    }.get(str(detail or "normal"), (30, 2200))


def evaluate_response_quality(
    *,
    answer: Any,
    contract: Mapping[str, Any] | None = None,
    intent: Mapping[str, Any] | None = None,
    identity: Mapping[str, Any] | None = None,
    claims: Mapping[str, Any] | None = None,
    semantic_evaluated: bool = False,
) -> ResponseQuality:
    """Evalúa la respuesta con criterios deterministas y separados.

    No reemplaza una evaluación semántica con LLM. Si `semantic_evaluated` es
    falso, el estado nunca se presenta como "validado".
    """
    text = _answer_text(answer)
    contract = dict(contract or {})
    intent = dict(intent or {})
    identity = dict(identity or {})
    claims = dict(claims or {})
    if not text:
        return ResponseQuality(status="not_evaluated", semantic_evaluated=semantic_evaluated)

    kind = str(intent.get("kind") or intent.get("intent") or "")
    if not kind:
        kind = detect_user_intent(text).kind
    evaluative = bool(intent.get("evaluative")) or kind in EVALUATIVE_INTENTS
    refusal = bool(_REFUSAL_RE.search(text))
    metadata = bool(_INTERNAL_METADATA_RE.search(text))
    detail = str(contract.get("detail") or "normal")
    low, high = _length_bounds(detail)
    length_ok = low <= len(text) <= high
    direct = bool(text) and not (refusal and len(text) < 320)
    cue = bool(_EVALUATION_CUE_RE.search(text))
    intent_ok = bool(text) and not refusal
    if evaluative:
        intent_ok = intent_ok and (cue or len(text) > 80)
    identity_active = bool(identity.get("voice") or identity.get("identity_id"))
    persona_ok: bool | None = None
    if identity_active:
        persona_ok = not refusal and not re.search(
            r"\b(no tengo personalidad|soy un modelo|as an ai)\b", text, re.IGNORECASE
        )
    style_ok = bool(contract) and not bool(contract.get("style_degraded"))
    unsupported = int(claims.get("unsupported") or 0)
    contradicted = int(claims.get("contradicted") or 0)
    evidence_ok: bool | None = None
    if claims:
        evidence_ok = unsupported == 0 and contradicted == 0

    checks = {
        "intent_fulfilled": intent_ok,
        "persona_preserved": persona_ok,
        "style_applied": style_ok,
        "evidence_integrity": evidence_ok,
        "direct_answer_present": direct,
        "unnecessary_refusal": refusal,
        "irrelevant_internal_metadata": metadata,
        "verbosity_appropriate": length_ok,
    }
    notes: list[str] = []
    if refusal:
        notes.append("refusal_detected")
    if metadata:
        notes.append("internal_metadata_detected")
    if evaluative and not cue:
        notes.append("evaluative_cue_missing")
    if not length_ok:
        notes.append(f"length_out_of_bounds:{len(text)}")
    if not style_ok:
        notes.append("contract_not_applied")
    if evidence_ok is False:
        notes.append("unsupported_claims")
    hard_fail = refusal or metadata or not intent_ok or not direct
    status = "deterministic_checks"
    if semantic_evaluated:
        status = "semantic_evaluated"
    elif hard_fail:
        status = "needs_review"
    return ResponseQuality(
        status=status,
        semantic_evaluated=semantic_evaluated,
        intent_fulfilled=intent_ok,
        persona_preserved=persona_ok,
        style_applied=style_ok,
        evidence_integrity=evidence_ok,
        direct_answer_present=direct,
        unnecessary_refusal=refusal,
        irrelevant_internal_metadata=metadata,
        verbosity_appropriate=length_ok,
        notes=tuple(notes),
        details={
            "intent_kind": kind,
            "evaluative": evaluative,
            "length": len(text),
            "identity_active": identity_active,
        },
    )


__all__ = ["ResponseQuality", "evaluate_response_quality"]
