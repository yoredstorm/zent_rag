# =============================================================================
# Derived Guard — el generador no sobrescribe un resultado determinista
# =============================================================================
# Si existe un DerivedClaim `deterministic=True` con premisas SATISFIED, el
# resultado lo decidió código. La respuesta del modelo puede explicarlo y
# citarlo; no puede invertirlo ni introducir una premisa nueva.
#
# Este guard es determinista, sin LLM. Si detecta contradicción:
#   - reemplaza la respuesta por el resultado canónico (override);
#   - si además la contradicción toca la evidencia misma, marca
#     INTERNAL_GROUNDING_CONFLICT para diagnóstico (no elige una versión).
#
# No muestra cadena de pensamiento: solo resultado, premisas y evidencia.
# =============================================================================
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

DERIVED_GUARD_VERSION = "derived-guard-1"

_POSITIVE_PHRASES: tuple[str, ...] = (
    "cumple",
    "coincide",
    "es válido",
    "es valido",
    "válido",
    "valido",
    "sí aplica",
    "si aplica",
    "es correcto",
    "match",
    "true",
    "verdadero",
    "aprobado",
    "permitido",
    "está permitido",
    "esta permitido",
    "se permite",
    "pertenece",
    "dentro del",
)
_NEGATIVE_PHRASES: tuple[str, ...] = (
    "no cumple",
    "no coincide",
    "no es válido",
    "no es valido",
    "inválido",
    "invalido",
    "no aplica",
    "no es correcto",
    "no match",
    "false",
    "falso",
    "rechazado",
    "no permitido",
    "no está permitido",
    "no esta permitido",
    "no se permite",
    "no pertenece",
    "no figura",
    "excede",
    "fuera del",
)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+|\n+")
_VALUE_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_\-&*#%?.]{2,}")
_NUMBER_RE = re.compile(r"-?\d+(?:[.,]\d+)?")


def _numeric_result(result: Any) -> float | None:
    if isinstance(result, bool):
        return None
    if isinstance(result, (int, float)):
        return float(result)
    return None


def _numbers(text: str) -> list[float]:
    found: list[float] = []
    for raw in _NUMBER_RE.findall(str(text or "")):
        try:
            found.append(float(raw.replace(",", ".")))
        except ValueError:
            continue
    return found


@dataclass(kw_only=True)
class DerivedGuardOutcome:
    answer: str
    action: str = "ok"  # ok | override | internal_conflict
    contradictions: tuple[str, ...] = ()
    claims_checked: int = 0
    note: str = ""
    version: str = DERIVED_GUARD_VERSION

    @property
    def overridden(self) -> bool:
        return self.action in ("override", "internal_conflict")

    def to_public_dict(self) -> dict:
        return {
            "version": self.version,
            "action": self.action,
            "contradictions": [item[:200] for item in self.contradictions[:4]],
            "claims_checked": self.claims_checked,
            "note": self.note[:300],
        }


def _sentences(text: str) -> list[str]:
    return [
        " ".join(part.split())
        for part in _SENTENCE_SPLIT.split(str(text or ""))
        if part.strip()
    ]


def _claim_result_polarity(result: Any) -> str:
    if isinstance(result, bool):
        return "positive" if result else "negative"
    text = str(result or "").strip().upper()
    if text in ("MATCH", "TRUE"):
        return "positive"
    if text in ("NO_MATCH", "FALSE"):
        return "negative"
    return ""


def _anchors(claim: dict) -> list[str]:
    anchors: list[str] = []
    for raw in claim.get("user_inputs") or ():
        text = str(raw or "")
        value = text.split("=", 1)[-1].strip() if "=" in text else text.strip()
        for token in _VALUE_TOKEN_RE.findall(value):
            lowered = token.lower()
            if len(lowered) >= 3 and lowered not in anchors:
                anchors.append(lowered)
    for token in _VALUE_TOKEN_RE.findall(str(claim.get("statement") or "")):
        lowered = token.lower()
        if len(lowered) >= 4 and lowered not in anchors:
            anchors.append(lowered)
    return anchors[:8]


def _sentence_has_anchor(sentence: str, anchors: Sequence[str]) -> bool:
    lowered = sentence.lower()
    return any(anchor in lowered for anchor in anchors if anchor)


def _detect_contradiction(sentence: str, polarity: str, anchors: Sequence[str]) -> str:
    lowered = sentence.lower()
    positive_hit = next((phrase for phrase in _POSITIVE_PHRASES if phrase in lowered), "")
    negative_hit = next((phrase for phrase in _NEGATIVE_PHRASES if phrase in lowered), "")
    if not positive_hit and not negative_hit:
        return ""
    anchored = _sentence_has_anchor(sentence, anchors)
    short = len(sentence) <= 90
    if polarity == "positive" and negative_hit and not positive_hit:
        return sentence if anchored or short else ""
    if polarity == "negative" and positive_hit and not negative_hit:
        return sentence if anchored or short else ""
    if positive_hit and negative_hit and (anchored or short):
        # Ambas señales en la misma oración: contradicción interna del borrador.
        return sentence
    return ""


def _canonical_answer(claim: dict) -> str:
    result = claim.get("result")
    if isinstance(result, bool):
        result_text = "cumple" if result else "no cumple"
    else:
        result_text = "MATCH" if str(result) == "MATCH" else (
            "NO_MATCH" if str(result) == "NO_MATCH" else str(result)
        )
    rule_ids = [str(value) for value in claim.get("canonical_rule_ids") or () if value]
    statement = str(claim.get("statement") or "")[:400]
    inputs = [str(value) for value in claim.get("user_inputs") or () if value]
    operation = str(claim.get("operation") or "")
    refs = [str(value) for value in claim.get("evidence_refs") or () if value]
    lines = [f"Resultado: {result_text}."]
    motive = f"Motivo: {statement}"
    if operation:
        motive += f" (operación determinista: {operation})"
    lines.append(motive)
    if inputs:
        lines.append("Datos aplicados: " + ", ".join(inputs[:6]) + ".")
    if refs:
        lines.append("Evidencia: " + ", ".join(refs[:6]) + ".")
    if rule_ids:
        lines.append("Regla canónica: " + ", ".join(rule_ids[:3]) + ".")
    return "\n".join(lines)


def enforce_derived_result(
    answer: str,
    claims: Iterable[Any],
) -> DerivedGuardOutcome:
    """Impide que el texto final contradiga un DerivedClaim determinista."""
    deterministic: list[dict] = []
    numeric_claims: list[tuple[dict, float]] = []
    for claim in claims or ():
        payload = (
            claim.to_public_dict() if hasattr(claim, "to_public_dict") else dict(claim)
        )
        if not payload.get("deterministic"):
            continue
        if str(payload.get("verification_status") or "") != "SUPPORTED":
            continue
        polarity = _claim_result_polarity(payload.get("result"))
        if polarity in ("positive", "negative"):
            deterministic.append(payload)
            continue
        numeric = _numeric_result(payload.get("result"))
        if numeric is not None:
            numeric_claims.append((payload, numeric))

    if not deterministic and not numeric_claims:
        return DerivedGuardOutcome(answer=str(answer or ""))

    contradictions: list[str] = []
    for claim in deterministic:
        polarity = _claim_result_polarity(claim.get("result"))
        anchors = _anchors(claim)
        for sentence in _sentences(answer):
            hit = _detect_contradiction(sentence, polarity, anchors)
            if hit:
                contradictions.append(hit)
                break
    for claim, expected in numeric_claims:
        anchors = _anchors(claim)
        for sentence in _sentences(answer):
            numbers = _numbers(sentence)
            if not numbers:
                continue
            anchored = _sentence_has_anchor(sentence, anchors)
            if not (anchored or len(sentence) <= 120):
                continue
            # El resultado suele ser el último número de la oración ("total = X").
            candidate = numbers[-1]
            if abs(candidate - expected) > 1e-9:
                contradictions.append(sentence)
                break

    if not contradictions:
        return DerivedGuardOutcome(
            answer=str(answer or ""),
            claims_checked=len(deterministic) + len(numeric_claims),
        )

    primary = deterministic[0] if deterministic else numeric_claims[0][0]
    conflicting = bool(primary.get("conflicts"))
    canonical = _canonical_answer(primary)
    action = "internal_conflict" if conflicting else "override"
    note = (
        "INTERNAL_GROUNDING_CONFLICT: el borrador contradice un resultado "
        "determinista y su evidencia; no se elige una versión."
        if conflicting
        else "respuesta del modelo contradijo el resultado determinista; se "
        "mantuvo el resultado canónico"
    )
    if conflicting:
        canonical = canonical + (
            "\n\nINTERNAL_GROUNDING_CONFLICT: revisar la contradicción entre la "
            "regla, su evidencia y el borrador."
        )
    return DerivedGuardOutcome(
        answer=canonical,
        action=action,
        contradictions=tuple(contradictions),
        claims_checked=len(deterministic),
        note=note,
    )


def deterministic_claims(claims: Iterable[Any]) -> list[dict]:
    """Vista pública de los claims que el generador no puede sobrescribir."""
    found: list[dict] = []
    for claim in claims or ():
        payload = (
            claim.to_public_dict() if hasattr(claim, "to_public_dict") else dict(claim)
        )
        if payload.get("deterministic") and str(
            payload.get("verification_status") or ""
        ) == "SUPPORTED":
            found.append(payload)
    return found


__all__ = [
    "DERIVED_GUARD_VERSION",
    "DerivedGuardOutcome",
    "deterministic_claims",
    "enforce_derived_result",
]
