# =============================================================================
# Verification split — la decisión y la narrativa se verifican por separado
# =============================================================================
# Una decisión determinista (DecisionEnvelope autoritativo + DerivedClaim
# `deterministic=True` con `verification_status=SUPPORTED`) NO puede degradarse
# por problemas de la NARRATIVA generada: max_tokens, citas colgantes, un
# verificador que no termina o grounding documental bloqueado.
#
# Este módulo define el modelo explícito:
#
#   DecisionVerification   status / authoritative / deterministic / operation /
#                          result / canonical_rule_ids / premise_status /
#                          evidence_refs
#   NarrativeVerification  status / citations_valid / explanation_complete /
#                          grounding_complete / truncated / warnings
#
# `decision_grounding` (CONFIRMED cuando la decisión está respaldada) y
# `narrative_grounding` (COMPLETE/PARTIAL/BLOCKED/UNKNOWN) también salen de
# acá. Ninguna función de este módulo toca la decisión: sólo la describen.
# =============================================================================
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

VERIFICATION_SPLIT_VERSION = "verification-split-1"

#: Estados de la DECISIÓN determinista. `UNVERIFIED` no existe acá: una
#: decisión o se verifica, o falla cerrada (NOT_VERIFIED), o no hay decisión
#: (UNDETERMINED). La narrativa jamás escribe estos estados.
DECISION_VERIFIED = "VERIFIED"
DECISION_NOT_VERIFIED = "NOT_VERIFIED"
DECISION_UNDETERMINED = "UNDETERMINED"

#: Estados de la NARRATIVA generada.
NARRATIVE_VERIFIED = "VERIFIED"
NARRATIVE_VERIFIED_DETERMINISTIC = "VERIFIED_DETERMINISTIC"
NARRATIVE_PARTIAL = "PARTIAL"
NARRATIVE_UNVERIFIED = "UNVERIFIED"
NARRATIVE_TRUNCATED = "TRUNCATED"

#: Grounding de la decisión (respaldado por regla/premisas) vs. grounding del
#: texto generado (respaldo documental).
GROUNDING_CONFIRMED = "CONFIRMED"
GROUNDING_COMPLETE = "COMPLETE"
GROUNDING_BLOCKED = "BLOCKED"
GROUNDING_PARTIAL = "PARTIAL"
GROUNDING_UNKNOWN = "UNKNOWN"

PREMISE_SATISFIED = "SATISFIED"
PREMISE_MISSING = "MISSING"
PREMISE_CONFLICTING = "CONFLICTING"
PREMISE_UNKNOWN = "UNKNOWN"

_SUPPORTED = "SUPPORTED"
_CONFLICT_STATUSES = frozenset(
    {"CONFLICTING", "CONTRADICTED", "REFUTED", "UNSUPPORTED"}
)
_MAX_TOKENS_CODE = "MAX_TOKENS_REACHED"
_MATERIAL_ERROR = "MATERIAL_ERROR"
_POSSIBLY_INCOMPLETE = "POSSIBLY_INCOMPLETE"


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
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        return ()
    return tuple(str(item) for item in value if str(item or "").strip())


def envelope_view(envelope: Any) -> dict[str, Any]:
    return _payload(envelope)


def claim_view(claim: Any) -> dict[str, Any]:
    payload = _payload(claim)
    return {
        "deterministic": bool(payload.get("deterministic")),
        "verification_status": str(payload.get("verification_status") or "").upper(),
        "operation": str(payload.get("operation") or ""),
        "result": payload.get("result"),
        "canonical_rule_ids": _texts(payload.get("canonical_rule_ids")),
        "evidence_refs": _texts(payload.get("evidence_refs")),
        "statement": str(payload.get("statement") or ""),
        "missing_premises": _texts(payload.get("missing_premises")),
        "conflicts": _texts(payload.get("conflicts")),
        "premises": list(payload.get("premises") or ()),
    }


@dataclass(frozen=True, kw_only=True)
class DecisionVerification:
    """Estado de la DECISIÓN determinista. Independiente de la narrativa."""

    status: str = DECISION_UNDETERMINED
    authoritative: bool = False
    deterministic: bool = False
    operation: str = ""
    result: Any = None
    canonical_rule_ids: tuple[str, ...] = ()
    premise_status: str = ""
    evidence_refs: tuple[str, ...] = ()
    rule_verification: str = ""
    conflicts: tuple[str, ...] = ()
    version: str = VERIFICATION_SPLIT_VERSION

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "status": self.status,
            "authoritative": bool(self.authoritative),
            "deterministic": bool(self.deterministic),
            "operation": self.operation,
            "result": self.result,
            "canonical_rule_ids": list(self.canonical_rule_ids[:8]),
            "premise_status": self.premise_status,
            "evidence_refs": list(self.evidence_refs[:8]),
            "rule_verification": self.rule_verification,
            "conflicts": list(self.conflicts[:6]),
        }


@dataclass(frozen=True, kw_only=True)
class NarrativeVerification:
    """Estado de la NARRATIVA generada. No modifica la decisión."""

    status: str = NARRATIVE_UNVERIFIED
    citations_valid: bool | None = None
    explanation_complete: bool | None = None
    grounding_complete: bool | None = None
    truncated: bool = False
    warnings: tuple[str, ...] = ()
    version: str = VERIFICATION_SPLIT_VERSION

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "status": self.status,
            "citations_valid": self.citations_valid,
            "explanation_complete": self.explanation_complete,
            "grounding_complete": self.grounding_complete,
            "truncated": bool(self.truncated),
            "warnings": list(self.warnings[:8]),
        }


def _premise_status(
    deterministic: Mapping[str, Any] | None,
    envelope: Mapping[str, Any],
) -> str:
    if deterministic is not None:
        if deterministic.get("conflicts"):
            return PREMISE_CONFLICTING
        if deterministic.get("missing_premises"):
            return PREMISE_MISSING
        return PREMISE_SATISFIED
    missing = _texts(envelope.get("missing_premises"))
    conflicts = _texts(envelope.get("conflicts"))
    if conflicts:
        return PREMISE_CONFLICTING
    if missing:
        return PREMISE_MISSING
    return PREMISE_UNKNOWN


def build_decision_verification(
    *,
    envelope: Any = None,
    claims: Sequence[Any] = (),
    answer_state: Any = None,
) -> DecisionVerification:
    """VERIFIED sólo con envelope autoritativo + claim determinista SUPPORTED.

    Un claim CONFLICTING falla cerrado: NOT_VERIFIED, aunque haya envelope.
    Sin autoridad determinista: UNDETERMINED. Nunca inventa VERIFIED.
    """
    env = envelope_view(envelope)
    views = [claim_view(claim) for claim in claims or ()]
    authoritative = bool(env.get("authoritative"))
    supported = [
        view
        for view in views
        if view["deterministic"] and view["verification_status"] == _SUPPORTED
    ]
    conflicting = [
        view
        for view in views
        if view["conflicts"] or view["verification_status"] in _CONFLICT_STATUSES
    ]
    if authoritative and supported and not conflicting:
        primary = supported[0]
        return DecisionVerification(
            status=DECISION_VERIFIED,
            authoritative=True,
            deterministic=True,
            operation=str(env.get("operation") or primary.get("operation") or ""),
            # El envelope publica el resultado NORMALIZADO (MATCH/TRUE/...); el
            # claim guarda el crudo (bool). La decisión canónica es el envelope.
            result=(
                env.get("result")
                if env.get("result") is not None
                else primary.get("result")
            ),
            canonical_rule_ids=tuple(primary.get("canonical_rule_ids") or ())
            or _texts(env.get("canonical_rule_ids")),
            premise_status=_premise_status(primary, env),
            evidence_refs=tuple(primary.get("evidence_refs") or ())
            or _texts(env.get("evidence_refs")),
            rule_verification=_SUPPORTED,
        )
    if conflicting:
        primary = conflicting[0]
        return DecisionVerification(
            status=DECISION_NOT_VERIFIED,
            authoritative=authoritative,
            deterministic=bool(primary.get("deterministic")),
            operation=str(primary.get("operation") or env.get("operation") or ""),
            result=primary.get("result"),
            canonical_rule_ids=tuple(primary.get("canonical_rule_ids") or ()),
            premise_status=PREMISE_CONFLICTING,
            evidence_refs=tuple(primary.get("evidence_refs") or ()),
            rule_verification=primary.get("verification_status") or "",
            conflicts=tuple(primary.get("conflicts") or ()) or ("claim_conflict",),
        )
    return DecisionVerification(
        status=DECISION_UNDETERMINED,
        authoritative=authoritative,
        deterministic=any(view["deterministic"] for view in views),
        operation=str(env.get("operation") or ""),
        result=env.get("result"),
        canonical_rule_ids=_texts(env.get("canonical_rule_ids")),
        premise_status=_premise_status(None, env),
        evidence_refs=_texts(env.get("evidence_refs")),
        rule_verification=(
            _SUPPORTED
            if any(view["verification_status"] == _SUPPORTED for view in views)
            else ""
        ),
    )


def _check_states(checks: Sequence[Any]) -> dict[str, set[str]]:
    states: dict[str, set[str]] = {"unavailable": set(), "warned": set(), "blocked": set()}
    for check in checks or ():
        item = _payload(check)
        key = str(item.get("key") or "")
        state = str(item.get("state") or "")
        if state in {"not_observed", "not_available", "skipped"}:
            states["unavailable"].add(key)
        elif state == "warn":
            states["warned"].add(key)
        elif state == "blocked" and key != "grounding":
            # El grounding narrativo ya viaja como `grounded`; otro chequeo
            # bloqueado (p. ej. el answer gate) vuelve parcial la narrativa.
            states["blocked"].add(key)
    return states


def build_narrative_verification(
    *,
    grounded: bool | None = None,
    citations_valid: bool | None = None,
    explanation_complete: bool | None = None,
    truncated: bool = False,
    warnings: Sequence[str] = (),
    checks: Sequence[Any] = (),
    decision_status: str = DECISION_UNDETERMINED,
    grounding_verdict: str = "",
    material_error: bool = False,
    deterministic_verified: bool = False,
) -> NarrativeVerification:
    """Estado de la narrativa: VERIFIED / VERIFIED_DETERMINISTIC / PARTIAL /
    UNVERIFIED / TRUNCATED.

    `truncated` describe un límite de generación (max_tokens) y sólo afecta a
    la narrativa. `deterministic_verified` indica que un verificador
    determinista (fast path) confirmó los hechos sin LLM.
    """
    warning_list = [str(item) for item in warnings if str(item or "").strip()]
    states = _check_states(checks)
    verifier_unavailable = bool(states["unavailable"] - {""})
    warned = bool(states["warned"] - {""})
    blocked = bool(states["blocked"] - {""})
    normalized_verdict = str(grounding_verdict or "").upper()
    unsupported_verdict = normalized_verdict in {"UNSUPPORTED", "CONTRADICTED"}
    decision_verified = decision_status == DECISION_VERIFIED

    if truncated or material_error:
        status = NARRATIVE_TRUNCATED
        if _MAX_TOKENS_CODE not in warning_list:
            warning_list.append(_MAX_TOKENS_CODE)
        if explanation_complete is None:
            explanation_complete = False
    elif unsupported_verdict or (grounded is False and not decision_verified):
        status = NARRATIVE_UNVERIFIED
    elif (
        citations_valid is False
        or verifier_unavailable
        or warned
        or blocked
        or grounded is False
        or explanation_complete is False
    ):
        status = NARRATIVE_PARTIAL
        if citations_valid is False and "CITATIONS_DANGLING" not in warning_list:
            warning_list.append("CITATIONS_DANGLING")
        if verifier_unavailable and "VERIFIER_NOT_AVAILABLE" not in warning_list:
            warning_list.append("VERIFIER_NOT_AVAILABLE")
        if grounded is False and "GROUNDING_BLOCKED" not in warning_list:
            warning_list.append("GROUNDING_BLOCKED")
    elif deterministic_verified:
        status = NARRATIVE_VERIFIED_DETERMINISTIC
        if "DETERMINISTIC_VERIFIER" not in warning_list:
            warning_list.append("DETERMINISTIC_VERIFIER")
    elif grounded is True:
        status = NARRATIVE_VERIFIED
    else:
        status = NARRATIVE_UNVERIFIED
        if "NO_VERIFICATION_RECORDED" not in warning_list:
            warning_list.append("NO_VERIFICATION_RECORDED")

    if status == NARRATIVE_TRUNCATED and "NARRATIVE_TRUNCATED" not in warning_list:
        warning_list.append("NARRATIVE_TRUNCATED")
    if material_error and "MAX_TOKENS_MATERIAL_ERROR" not in warning_list:
        warning_list.append("MAX_TOKENS_MATERIAL_ERROR")

    return NarrativeVerification(
        status=status,
        citations_valid=citations_valid,
        explanation_complete=explanation_complete,
        grounding_complete=grounded if isinstance(grounded, bool) else None,
        truncated=bool(truncated or material_error),
        warnings=tuple(dict.fromkeys(warning_list)),
    )


def decision_grounding_for(decision: DecisionVerification) -> str:
    if decision.status == DECISION_VERIFIED:
        return GROUNDING_CONFIRMED
    if decision.status == DECISION_NOT_VERIFIED:
        return GROUNDING_BLOCKED
    return GROUNDING_UNKNOWN


def narrative_grounding_for(
    narrative: NarrativeVerification, *, grounded: bool | None
) -> str:
    if narrative.status == NARRATIVE_VERIFIED_DETERMINISTIC:
        return GROUNDING_COMPLETE
    if grounded is True and narrative.status in {NARRATIVE_VERIFIED, NARRATIVE_TRUNCATED}:
        return GROUNDING_COMPLETE
    if grounded is False:
        return GROUNDING_BLOCKED
    if narrative.status in {NARRATIVE_PARTIAL, NARRATIVE_TRUNCATED}:
        return GROUNDING_PARTIAL
    if grounded is True:
        return GROUNDING_COMPLETE
    return GROUNDING_UNKNOWN


def compose_verification_split(
    *,
    envelope: Any = None,
    claims: Sequence[Any] = (),
    answer_state: Any = None,
    grounded: bool | None = None,
    checks: Sequence[Any] = (),
    citations_valid: bool | None = None,
    generation_warnings: Sequence[Any] = (),
    grounding_verdict: str = "",
    deterministic_verified: bool = False,
) -> dict[str, Any]:
    """Compone decisión + narrativa + groundings sin mezclarlos."""
    decision = build_decision_verification(
        envelope=envelope, claims=claims, answer_state=answer_state
    )
    truncated = False
    material_error = False
    warnings: list[str] = []
    explanation_complete: bool | None = None
    for raw in generation_warnings or ():
        warning = _payload(raw)
        if warning.get("material_effect") is not True:
            continue
        code = str(warning.get("code") or _MAX_TOKENS_CODE)
        impact = str(warning.get("impact") or "")
        warnings.append(code)
        if impact == _MATERIAL_ERROR:
            material_error = True
            explanation_complete = False
        elif impact == _POSSIBLY_INCOMPLETE or not impact:
            truncated = True
            explanation_complete = False
    narrative = build_narrative_verification(
        grounded=grounded,
        citations_valid=citations_valid,
        explanation_complete=explanation_complete,
        truncated=truncated,
        warnings=warnings,
        checks=checks,
        decision_status=decision.status,
        grounding_verdict=grounding_verdict,
        material_error=material_error,
        deterministic_verified=deterministic_verified,
    )
    return {
        "decision_verification": decision.to_public_dict(),
        "narrative_verification": narrative.to_public_dict(),
        "decision_grounding": decision_grounding_for(decision),
        "narrative_grounding": narrative_grounding_for(narrative, grounded=grounded),
    }


def _steps(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def envelope_from_steps(steps: Any) -> dict[str, Any]:
    """Envelope autoritativo publicado por el runtime, si existe."""
    for step in _steps(steps):
        step_type = str(step.get("type") or "")
        if step_type == "grounded_reasoning":
            envelope = _record(step.get("decision_envelope"))
            if envelope:
                return envelope
        if step_type == "decision_envelope" and step.get("authoritative") is not None:
            return {
                key: value
                for key, value in step.items()
                if key not in {"type", "id"}
            }
        if step_type == "final_authority_lock" and step.get("authoritative") is True:
            return {
                "authoritative": True,
                "operation": step.get("operation"),
                "result": step.get("result"),
                "lock_action": step.get("lock_action"),
                "source": "final_authority_lock",
            }
    return {}


def claims_from_steps(steps: Any) -> list[dict[str, Any]]:
    """Claims deterministas publicados en los pasos del run."""
    claims: list[dict[str, Any]] = []
    for step in _steps(steps):
        step_type = str(step.get("type") or "")
        if step_type == "grounded_reasoning":
            primary = _record(step.get("derived_claim"))
            if primary:
                claims.append(primary)
            for item in step.get("derived_claims") or ():
                if isinstance(item, Mapping):
                    claims.append(dict(item))
        elif step_type == "derived_claim":
            claims.append(
                {key: value for key, value in step.items() if key not in {"type", "id"}}
            )
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for claim in claims:
        key = (
            str(claim.get("operation") or ""),
            str(claim.get("result")),
            str(claim.get("statement") or "")[:80],
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(claim)
    return deduped


def answer_state_from_steps(steps: Any) -> dict[str, Any]:
    for step in _steps(steps):
        if str(step.get("type") or "") != "answer_state":
            continue
        return {
            key: value
            for key, value in step.items()
            if key not in {"type", "id", "latency_ms"}
        }
    return {}


def _record(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


__all__ = [
    "DECISION_NOT_VERIFIED",
    "DECISION_UNDETERMINED",
    "DECISION_VERIFIED",
    "DecisionVerification",
    "GROUNDING_BLOCKED",
    "GROUNDING_COMPLETE",
    "GROUNDING_CONFIRMED",
    "GROUNDING_PARTIAL",
    "GROUNDING_UNKNOWN",
    "NARRATIVE_PARTIAL",
    "NARRATIVE_TRUNCATED",
    "NARRATIVE_UNVERIFIED",
    "NARRATIVE_VERIFIED",
    "NARRATIVE_VERIFIED_DETERMINISTIC",
    "NarrativeVerification",
    "PREMISE_CONFLICTING",
    "PREMISE_MISSING",
    "PREMISE_SATISFIED",
    "PREMISE_UNKNOWN",
    "VERIFICATION_SPLIT_VERSION",
    "answer_state_from_steps",
    "build_decision_verification",
    "build_narrative_verification",
    "claim_view",
    "claims_from_steps",
    "compose_verification_split",
    "decision_grounding_for",
    "envelope_from_steps",
    "envelope_view",
    "narrative_grounding_for",
]
