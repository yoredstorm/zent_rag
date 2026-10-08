# =============================================================================
# Decision Envelope — la decisión determinista es inmutable
# =============================================================================
# Cuando existe un DerivedClaim `deterministic=True` con
# `verification_status=SUPPORTED`, la decisión la produjo CÓDIGO. El generador
# nunca escribe `result`: sólo redacta explicación, resumen, citas y caveats.
#
# Este módulo:
#   1. crea el DecisionEnvelope inmutable (state, operation, result, reglas,
#      runtime inputs, premisas, condition results, evidencia);
#   2. normaliza el resultado a un vocabulario binario general
#      (MATCH/NO_MATCH/TRUE/FALSE/VALID/INVALID/ELIGIBLE/NOT_ELIGIBLE);
#   3. construye el HEADLINE determinista (primera línea = código);
#   4. construye la explicación determinista desde los checks estructurados
#      (POSITIONAL_MATCH, RANGE_CHECK, DATE_COMPARE, ENUM, ...);
#   5. expone `finalize_authoritative_answer(...)`: TODA ruta final debe pasar
#      por acá antes de mostrar la respuesta.
#
# Sin envelope no se toca la respuesta: el comportamiento histórico se conserva.
# =============================================================================
from __future__ import annotations

from collections.abc import Mapping as MappingABC
from collections.abc import Sequence as SequenceABC
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from src.runtime.derived_guard import DerivedGuardOutcome, enforce_derived_result
from src.runtime.deterministic_authority import undetermined_authoritative_answer

DECISION_ENVELOPE_VERSION = "decision-envelope-1"

#: Estados binarios generales (sin vocabulario de dominio).
_POSITIVE_DEFAULT = "TRUE"
_NEGATIVE_DEFAULT = "FALSE"

#: Resultado normalizado -> headline determinista (primera línea visible).
#: Genérico: no hardcodea dominio, sólo el estado.
HEADLINES: dict[str, str] = {
    "MATCH": "Sí, cumple.",
    "NO_MATCH": "No, no cumple.",
    "TRUE": "Sí.",
    "FALSE": "No.",
    "VALID": "Sí, es válido.",
    "INVALID": "No, no es válido.",
    "ELIGIBLE": "Sí, es elegible.",
    "NOT_ELIGIBLE": "No, no es elegible.",
}

#: Operación -> estados que usa para un booleano.
_BINARY_STATES_BY_OPERATION: dict[str, tuple[str, str]] = {
    "POSITIONAL_MATCH": ("MATCH", "NO_MATCH"),
    "MATCH": ("MATCH", "NO_MATCH"),
    "STRING_EQUALITY": ("MATCH", "NO_MATCH"),
    "SET_MEMBERSHIP": ("VALID", "INVALID"),
    "ENUM_CHECK": ("VALID", "INVALID"),
    "RANGE_CHECK": ("VALID", "INVALID"),
    "DATE_COMPARE": ("VALID", "INVALID"),
    "COMPARISON": ("VALID", "INVALID"),
    "BOOLEAN": ("TRUE", "FALSE"),
    "ELIGIBILITY": ("ELIGIBLE", "NOT_ELIGIBLE"),
}

_KNOWN_STATES = frozenset(HEADLINES)


def normalize_decision_result(operation: str, result: Any) -> Any:
    """Normaliza un resultado booleano al vocabulario binario general.

    Un int/float/str no booleano se devuelve tal cual (el headline no aplica).
    """
    if not isinstance(result, bool):
        if isinstance(result, str) and result.strip().upper() in _KNOWN_STATES:
            return result.strip().upper()
        return result
    positive, negative = _BINARY_STATES_BY_OPERATION.get(
        str(operation or "").upper(), (_POSITIVE_DEFAULT, _NEGATIVE_DEFAULT)
    )
    return positive if result else negative


def decision_headline(operation: str, result: Any) -> str:
    """Primera línea determinista para resultados binarios ('' si no aplica)."""
    normalized = normalize_decision_result(operation, result)
    if isinstance(normalized, str) and normalized.upper() in HEADLINES:
        return HEADLINES[normalized.upper()]
    return ""


@dataclass(frozen=True, kw_only=True)
class DecisionEnvelope:
    """Resultado autoritativo e inmutable. El generador NO lo escribe."""

    state: str
    operation: str
    result: Any
    canonical_rule_ids: tuple[str, ...] = ()
    runtime_inputs: tuple[str, ...] = ()
    premises: tuple[dict, ...] = ()
    condition_results: tuple[dict, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    checks: tuple[dict, ...] = ()
    statement: str = ""
    confidence: float = 0.0
    rule_version: str = ""
    #: Gate OPERACIÓN↔QUERY de la regla decisiva (OperationCompatibilityResult
    #: público). Invariante AUTHORITATIVE_OPERATION_COMPATIBILITY: con
    #: compatible=False (o familia de operación no permitida) el envelope NO
    #: se construye: sin autoridad.
    operation_compatibility: dict[str, Any] = field(default_factory=dict)
    version: str = DECISION_ENVELOPE_VERSION
    authoritative: bool = True

    @property
    def normalized_result(self) -> Any:
        return normalize_decision_result(self.operation, self.result)

    @property
    def headline(self) -> str:
        return decision_headline(self.operation, self.result)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "state": self.state,
            "operation": self.operation,
            "result": self.normalized_result,
            "authoritative": bool(self.authoritative),
            "canonical_rule_ids": list(self.canonical_rule_ids[:8]),
            "runtime_inputs": list(self.runtime_inputs[:8]),
            "premises": [dict(item) for item in self.premises[:8]],
            "condition_results": [dict(item) for item in self.condition_results[:12]],
            "evidence_refs": list(self.evidence_refs[:8]),
            "checks": [dict(item) for item in self.checks[:12]],
            "statement": self.statement[:300],
            "confidence": round(float(self.confidence), 4),
            "rule_version": self.rule_version,
            "operation_compatibility": dict(self.operation_compatibility),
        }


def _public(value: Any) -> dict:
    if value is None:
        return {}
    if isinstance(value, MappingABC):
        return dict(value)
    if hasattr(value, "to_public_dict"):
        try:
            payload = value.to_public_dict()
            return dict(payload) if isinstance(payload, MappingABC) else {}
        except Exception:  # noqa: BLE001
            return {}
    return {}


def _deterministic_claim(grounded_public: Mapping[str, Any]) -> dict | None:
    derivations = grounded_public.get("derivations")
    if not isinstance(derivations, MappingABC):
        return None
    claims = [
        claim
        for claim in derivations.get("claims") or ()
        if isinstance(claim, MappingABC)
        and bool(claim.get("deterministic"))
        and str(claim.get("verification_status") or "") == "SUPPORTED"
    ]
    if not claims:
        return None
    # Preferencia determinista: la primera con operación concreta.
    with_operation = [claim for claim in claims if claim.get("operation")]
    return (with_operation or claims)[0]


def _rule_evaluation_for(
    grounded_public: Mapping[str, Any], rule_ids: Sequence[str]
) -> dict | None:
    flow = grounded_public.get("canonical_rule_flow")
    if not isinstance(flow, SequenceABC) or isinstance(flow, (str, bytes)):
        return None
    wanted = {str(value) for value in rule_ids if value}
    fallback: dict | None = None
    for evaluation in flow:
        if not isinstance(evaluation, MappingABC):
            continue
        payload = dict(evaluation)
        if fallback is None:
            fallback = payload
        if str(payload.get("rule_id") or "") in wanted:
            return payload
    return fallback


def build_decision_envelope(grounded: Any) -> DecisionEnvelope | None:
    """Construye el envelope desde el resultado del grounded engine.

    Invariante AUTHORITATIVE_OPERATION_COMPATIBILITY: si la operación de la
    regla decisiva no es semánticamente compatible con la consulta (p.ej.
    COMPARISON para un patrón de runtime aplicado a un valor), NO se construye
    envelope: sin autoridad, fail closed.

    Devuelve None si no hay DerivedClaim determinista SUPPORTED.
    """
    grounded_public = _public(grounded)
    if not grounded_public:
        return None
    claim = _deterministic_claim(grounded_public)
    if claim is None:
        return None

    rule_ids = tuple(
        str(value) for value in claim.get("canonical_rule_ids") or () if value
    )
    evaluation = _rule_evaluation_for(grounded_public, rule_ids) or {}

    # --- Gate OPERACIÓN↔QUERY (invariante de autoridad) ---------------------
    from src.runtime.operation_compatibility import (
        derive_query_operation_requirements,
        envelope_operation_compatible,
    )

    semantics_public = (
        grounded_public.get("semantics")
        if isinstance(grounded_public.get("semantics"), MappingABC)
        else None
    )
    requirements = derive_query_operation_requirements(
        question=str(
            getattr(grounded, "question", "") or grounded_public.get("question") or ""
        ),
        semantics=getattr(grounded, "semantics", None),
        semantics_public=semantics_public,
        runtime_patterns=tuple(
            str(item) for item in grounded_public.get("runtime_patterns") or ()
        ),
    )
    compatibility = dict(evaluation.get("operation_compatibility") or {})
    operation = str(claim.get("operation") or evaluation.get("operation") or "")
    operation_compatible = envelope_operation_compatible(
        operation, requirements
    )[0]
    if compatibility.get("compatible") is False:
        operation_compatible = False
    if not operation_compatible:
        # La operación no pertenece a ninguna familia compatible con la query:
        # no hay autoridad. (La razón queda en `canonical_rule_flow` y en la
        # telemetría del stage operation_compatibility.)
        return None

    checks: list[dict] = []
    for check in evaluation.get("checks") or ():
        if isinstance(check, MappingABC):
            checks.append(dict(check))
    condition_results: list[dict] = [
        dict(item)
        for item in evaluation.get("condition_results") or ()
        if isinstance(item, MappingABC)
    ]
    premises = [
        dict(premise)
        for premise in claim.get("premises") or ()
        if isinstance(premise, MappingABC)
    ]
    statement = str(claim.get("statement") or evaluation.get("reason") or "")
    return DecisionEnvelope(
        state=str(grounded_public.get("answerability") or ""),
        operation=str(claim.get("operation") or ""),
        result=normalize_decision_result(
            str(claim.get("operation") or ""), claim.get("result")
        ),
        canonical_rule_ids=rule_ids,
        runtime_inputs=tuple(
            str(value) for value in claim.get("user_inputs") or () if value
        ),
        premises=tuple(premises),
        condition_results=tuple(condition_results),
        evidence_refs=tuple(
            str(value) for value in claim.get("evidence_refs") or () if value
        ),
        checks=tuple(checks),
        statement=statement,
        confidence=float(claim.get("confidence") or 0.0),
        rule_version=str(claim.get("version") or ""),
        operation_compatibility=compatibility,
    )


def _check_line(check: Mapping[str, Any]) -> str:
    name = str(check.get("name") or check.get("operation") or "check")
    status = str(check.get("status") or "")
    result = check.get("result")
    detail = str(check.get("detail") or check.get("matched_text") or "")
    parts = [str(name)]
    if detail:
        parts.append(detail[:220])
    if result is not None:
        parts.append(f"resultado={result}")
    if status:
        parts.append(f"estado={status}")
    return "- " + " · ".join(parts)


def build_operation_explanation(envelope: DecisionEnvelope) -> str:
    """Bloque explicativo DETERMINISTA desde los checks estructurados.

    Genérico: no conoce dominios; renderiza nombre/valor/resultado tal como los
    produce la operación determinista. El LLM puede reformularlo, pero los
    hechos salen de acá.
    """
    lines: list[str] = [
        f"Resultado determinista ({envelope.operation or 'OPERACIÓN'}): "
        f"{envelope.normalized_result}"
    ]
    if envelope.canonical_rule_ids:
        lines.append("Regla canónica: " + ", ".join(envelope.canonical_rule_ids[:3]))
    if envelope.statement:
        lines.append("Premisa: " + envelope.statement[:300])
    if envelope.runtime_inputs:
        lines.append("Datos aplicados: " + ", ".join(envelope.runtime_inputs[:6]))
    if envelope.checks:
        lines.append("Comprobaciones:")
        lines.extend(_check_line(check) for check in envelope.checks[:8])
    if envelope.condition_results:
        conditions = ", ".join(
            f"{item.get('condition_id')}={item.get('result')}"
            for item in envelope.condition_results[:8]
        )
        lines.append("Condiciones: " + conditions)
    if envelope.evidence_refs:
        lines.append("Evidencia: " + ", ".join(envelope.evidence_refs[:6]))
    return "\n".join(lines)


@dataclass(frozen=True, kw_only=True)
class FinalizedAnswer:
    answer: str
    envelope: DecisionEnvelope | None = None
    guard: DerivedGuardOutcome | None = None
    overridden: bool = False
    changed: bool = False
    #: Estado de respuesta (`DERIVED_RESULT`, `UNDETERMINED_RULE`, ...). Vacío si
    #: el texto pasó sin intervención de la autoridad determinista.
    state: str = ""
    #: True cuando una consulta ejecutable se bloqueó por falta de autoridad.
    blocked: bool = False
    #: Acción del FINAL_AUTHORITY_LOCK: preserved | rebuilt | blocked.
    lock_action: str = "preserved"
    version: str = DECISION_ENVELOPE_VERSION

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "authoritative": bool(self.envelope and self.envelope.authoritative),
            "overridden": bool(self.overridden),
            "changed": bool(self.changed),
            "state": self.state,
            "blocked": bool(self.blocked),
            "lock_action": self.lock_action,
            "result": self.envelope.normalized_result if self.envelope else None,
            "envelope": self.envelope.to_public_dict() if self.envelope else None,
            "guard": self.guard.to_public_dict() if self.guard else None,
        }


def _ensure_headline(answer: str, headline: str) -> str:
    """Garantiza que la primera línea visible sea la determinista."""
    text = str(answer or "").strip()
    if not headline:
        return text
    first_lines = text.splitlines()
    first = first_lines[0].strip() if first_lines else ""
    if first.lower().rstrip(".! ") == headline.lower().rstrip(".! "):
        return text
    if not text:
        return headline
    return f"{headline}\n\n{text}"


def finalize_authoritative_answer(
    answer: str,
    grounded: Any = None,
    *,
    envelope: DecisionEnvelope | None = None,
    claims: Sequence[Any] | None = None,
    requires_deterministic_decision: bool = False,
    failure_code: str = "",
    failure_stage: str = "",
    failure_message: str = "",
    missing_premises: Sequence[Any] = (),
) -> FinalizedAnswer:
    """Única función final: un resultado determinista no puede invertirse.

    - Con envelope autoritativo: aplica `enforce_derived_result`; si el borrador
      contradice, la respuesta se sustituye por headline + explicación
      determinista. Si no contradice, se garantiza el headline como primera
      línea. La decisión sale del envelope, jamás del generador.
    - Sin envelope y `requires_deterministic_decision`: estado no concluyente
      construido por código (UNDETERMINED_RULE / *_FAILED). Nunca una respuesta
      binaria libre del LLM.
    - Sin envelope y sin exigencia determinista: se conserva el texto (con el
      guard histórico si hay claims).
    """
    resolved = envelope or build_decision_envelope(grounded)
    resolved_claims: list[Any] = list(claims or ())
    if not resolved_claims and grounded is not None:
        grounded_public = _public(grounded)
        derivations = grounded_public.get("derivations")
        if isinstance(derivations, MappingABC):
            resolved_claims = list(derivations.get("claims") or ())

    guard = enforce_derived_result(str(answer or ""), resolved_claims)

    if resolved is None:
        if requires_deterministic_decision:
            state = "UNDETERMINED_RULE"
            if failure_stage == "grounding" or failure_code == "GROUNDING_ENGINE_FAILED":
                state = "GROUNDING_ENGINE_FAILED"
            elif failure_stage == "rule_retrieval" or failure_code == "RULE_RETRIEVAL_UNAVAILABLE":
                state = "RULE_RETRIEVAL_UNAVAILABLE"
            elif failure_stage == "rule_evaluation" or failure_code == "RULE_EVALUATION_FAILED":
                state = "RULE_EVALUATION_FAILED"
            elif failure_stage == "derivation" or failure_code == "DERIVATION_FAILED":
                state = "DERIVATION_FAILED"
            if failure_message:
                message = str(failure_message)
            elif missing_premises:
                from src.runtime.answer_gate import undetermined_answer

                message = undetermined_answer(missing_premises)
            else:
                message = undetermined_authoritative_answer()
            if not message.strip():
                message = undetermined_authoritative_answer(failure_code)
            return FinalizedAnswer(
                answer=message,
                guard=guard,
                overridden=True,
                changed=True,
                state=state,
                blocked=True,
                lock_action="blocked",
            )
        return FinalizedAnswer(
            answer=str(guard.answer or ""),
            guard=guard,
            overridden=guard.overridden,
            changed=guard.overridden,
            lock_action="preserved",
        )

    headline = resolved.headline
    if guard.overridden:
        explanation = build_operation_explanation(resolved)
        final = headline or guard.answer
        if headline and explanation:
            final = f"{headline}\n\n{explanation}"
        elif explanation:
            final = explanation
        return FinalizedAnswer(
            answer=final,
            envelope=resolved,
            guard=guard,
            overridden=True,
            changed=True,
            state="DERIVED_RESULT",
            lock_action="rebuilt",
        )

    final = _ensure_headline(str(guard.answer or ""), headline)
    # FINAL_AUTHORITY_LOCK — invariante AUTHORITATIVE_RESPONSE_CONSISTENCY:
    # el texto final no puede dudar ni invertir la decisión autoritativa. El
    # guard pudo dejar pasar una oración epistémica no anclada; acá se
    # reconstruye deterministicamente desde el envelope.
    if resolved.authoritative:
        from src.runtime.derived_guard import contradicts_authoritative_result

        contradiction = contradicts_authoritative_result(
            final, resolved.normalized_result
        )
        if contradiction:
            explanation = build_operation_explanation(resolved)
            rebuilt = headline or explanation
            if headline and explanation:
                rebuilt = f"{headline}\n\n{explanation}"
            return FinalizedAnswer(
                answer=rebuilt,
                envelope=resolved,
                guard=guard,
                overridden=True,
                changed=True,
                state="DERIVED_RESULT",
                lock_action="rebuilt",
            )
    return FinalizedAnswer(
        answer=final,
        envelope=resolved,
        guard=guard,
        overridden=False,
        changed=final != str(answer or ""),
        state="DERIVED_RESULT",
        lock_action="preserved",
    )


__all__ = [
    "DECISION_ENVELOPE_VERSION",
    "DecisionEnvelope",
    "FinalizedAnswer",
    "HEADLINES",
    "build_decision_envelope",
    "build_operation_explanation",
    "decision_headline",
    "finalize_authoritative_answer",
    "normalize_decision_result",
]
