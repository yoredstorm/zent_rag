# =============================================================================
# Deterministic Fast Path — responder sin LLM cuando la autoridad ya existe
# =============================================================================
# Una consulta ejecutable cuya autoridad determinista quedó resuelta
# (CanonicalRule SUPPORTED + premisas SATISFIED + RuleEvaluation MATCH/NO_MATCH
# + DerivedClaim SUPPORTED + DecisionEnvelope autoritativo) no necesita
# razonamiento, JEV ni generación: el código ya tiene la respuesta.
#
# Este módulo SÓLO decide elegibilidad, redacta la respuesta determinista y
# verifica hechos publicados. No compila reglas, no cierra premisas y no cambia
# la decisión: el FINAL_AUTHORITY_LOCK sigue siendo obligatorio.
# =============================================================================
from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

FAST_PATH_VERSION = "deterministic-fast-path-1"

EXECUTION_MODE_FAST_PATH = "DETERMINISTIC_FAST_PATH"
EXECUTION_MODE_STANDARD = "STANDARD"

#: Motivos de elegibilidad / rechazo (códigos estables para telemetría).
ELIGIBLE_SUPPORTED_DECISION = "SUPPORTED_DECISION"
NOT_EXECUTABLE = "NOT_EXECUTABLE"
PREPARATION_ERROR = "PREPARATION_ERROR"
NO_AUTHORITY = "NO_AUTHORITY"
NO_GROUNDED_REASONING = "NO_GROUNDED_REASONING"
ANSWERABILITY_NOT_DERIVED = "ANSWERABILITY_NOT_DERIVED"
NO_SUPPORTED_CLAIM = "NO_SUPPORTED_CLAIM"
MISSING_PREMISES = "MISSING_PREMISES"
CONFLICTS = "CONFLICTS"
RULE_NOT_SUPPORTED = "RULE_NOT_SUPPORTED"
RULE_CONFLICTS = "RULE_CONFLICTS"
UNRESOLVED_EVALUATION = "UNRESOLVED_EVALUATION"
AMBIGUOUS_RULES = "AMBIGUOUS_RULES"
MISSING_RUNTIME_INPUTS = "MISSING_RUNTIME_INPUTS"
UNSUPPORTED_OPERATION = "UNSUPPORTED_OPERATION"
NO_RESULT = "NO_RESULT"

_DERIVED_RESULTS = frozenset({"MATCH", "NO_MATCH"})
_IGNORED_EVALUATION_STATUSES = frozenset({"NOT_APPLICABLE"})
_UNKNOWN_EVALUATION_STATUSES = frozenset(
    {"", "UNKNOWN", "UNDETERMINED", "PENDING", "ERROR"}
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
    return tuple(text for item in value if (text := str(item or "").strip()))


def _records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


@dataclass(frozen=True, kw_only=True)
class DeterministicFastPathDecision:
    """Elegibilidad del fast path y hechos que lo habilitan."""

    eligible: bool
    reason: str = ""
    operation: str = ""
    result: Any = None
    rule_ids: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    checks: tuple[dict[str, Any], ...] = ()
    premise_status: str = ""
    #: Huella verificable de la autoridad (operación, resultado, reglas, refs).
    #: Base para invalidar caché futura por knowledge/canonical version.
    fingerprint: str = ""
    version: str = FAST_PATH_VERSION

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "eligible": bool(self.eligible),
            "reason": self.reason,
            "operation": self.operation,
            "result": self.result,
            "rule_ids": list(self.rule_ids[:8]),
            "evidence_refs": list(self.evidence_refs[:8]),
            "checks": [dict(check) for check in self.checks[:12]],
            "premise_status": self.premise_status,
            "fingerprint": self.fingerprint,
        }


def _fail(reason: str) -> DeterministicFastPathDecision:
    return DeterministicFastPathDecision(eligible=False, reason=reason)


def evaluate_deterministic_fast_path(
    *,
    requires_deterministic: bool,
    envelope: Any = None,
    grounded: Any = None,
    claims: Sequence[Any] = (),
    missing_premises: Sequence[Any] = (),
    conflicts: Sequence[Any] = (),
    preparation_status: str = "ok",
) -> DeterministicFastPathDecision:
    """Elegible sólo con autoridad completa y sin incertidumbre (§1, §2)."""
    if not requires_deterministic:
        return _fail(NOT_EXECUTABLE)
    if str(preparation_status or "ok") == "error":
        return _fail(PREPARATION_ERROR)
    env = _payload(envelope)
    if env.get("authoritative") is not True:
        return _fail(NO_AUTHORITY)
    g = _payload(grounded)
    if not g:
        return _fail(NO_GROUNDED_REASONING)
    answerability = str(g.get("answerability") or "")
    if answerability and answerability != "ANSWERABLE_DERIVED":
        return _fail(ANSWERABILITY_NOT_DERIVED)

    claim_views = [_payload(claim) for claim in claims or ()]
    supported = [
        view
        for view in claim_views
        if view.get("deterministic") is True
        and str(view.get("verification_status") or "") == "SUPPORTED"
    ]
    if not supported:
        return _fail(NO_SUPPORTED_CLAIM)
    if any(view.get("conflicts") for view in claim_views):
        return _fail(CONFLICTS)
    missing = _texts(missing_premises) or _texts(g.get("missing_premises"))
    if missing:
        return _fail(MISSING_PREMISES)
    declared_conflicts = _texts(conflicts) or _texts(g.get("conflicts"))
    if declared_conflicts:
        return _fail(CONFLICTS)

    rules_used = _records(g.get("canonical_rules_used"))
    for rule in rules_used:
        state = str(rule.get("verification_state") or "").upper()
        if state and state != "SUPPORTED":
            return _fail(RULE_NOT_SUPPORTED)
        if rule.get("conflicts_with"):
            return _fail(RULE_CONFLICTS)
        if rule.get("executable") is False:
            return _fail(RULE_NOT_SUPPORTED)

    evaluations = _records(g.get("canonical_rule_flow"))
    derived = [
        evaluation
        for evaluation in evaluations
        if str(evaluation.get("status") or "").upper() in _DERIVED_RESULTS
    ]
    for evaluation in evaluations:
        status = str(evaluation.get("status") or "").upper()
        if status in _IGNORED_EVALUATION_STATUSES:
            continue
        if status in _UNKNOWN_EVALUATION_STATUSES:
            return _fail(UNRESOLVED_EVALUATION)
        if evaluation.get("missing_premises"):
            return _fail(MISSING_PREMISES)
    results = {str(item.get("result")) for item in derived}
    if len(results) > 1:
        return _fail(AMBIGUOUS_RULES)
    if not derived:
        return _fail(UNRESOLVED_EVALUATION)

    semantics = _payload(g.get("semantics"))
    runtime_inputs = _texts(g.get("runtime_inputs"))
    if semantics.get("runtime_inputs") and not runtime_inputs:
        return _fail(MISSING_RUNTIME_INPUTS)

    operation = str(env.get("operation") or supported[0].get("operation") or "")
    if not operation:
        return _fail(UNSUPPORTED_OPERATION)
    result = env.get("result")
    if result is None:
        result = supported[0].get("result")
    if result is None:
        return _fail(NO_RESULT)

    checks: list[dict] = []
    for evaluation in derived:
        for check in _records(evaluation.get("checks")):
            checks.append(check)
    rule_ids = _texts(env.get("canonical_rule_ids")) or _texts(
        supported[0].get("canonical_rule_ids")
    )
    evidence_refs: list[str] = []
    for view in supported:
        evidence_refs.extend(_texts(view.get("evidence_refs")))
    evidence_refs.extend(_texts(env.get("evidence_refs")))
    unique_refs = tuple(dict.fromkeys(evidence_refs))
    unique_rules = tuple(dict.fromkeys(rule_ids))
    fingerprint_material = "|".join(
        (operation, str(result), ",".join(unique_rules), ",".join(unique_refs))
    )
    fingerprint = hashlib.sha256(
        fingerprint_material.encode("utf-8", "ignore")
    ).hexdigest()[:16]
    return DeterministicFastPathDecision(
        eligible=True,
        reason=ELIGIBLE_SUPPORTED_DECISION,
        operation=operation,
        result=result,
        rule_ids=unique_rules,
        evidence_refs=unique_refs,
        checks=tuple(checks),
        premise_status="SATISFIED",
        fingerprint=fingerprint,
    )


def fast_path_decision_for(prep: Any, *, requires_deterministic: bool) -> DeterministicFastPathDecision:
    """Conveniencia sobre `DerivedPreparationResult` (duck-typed)."""
    return evaluate_deterministic_fast_path(
        requires_deterministic=requires_deterministic,
        envelope=getattr(prep, "authoritative_envelope", None),
        grounded=getattr(prep, "grounded_reasoning", None),
        claims=list(getattr(prep, "derived_claims", ()) or ()),
        missing_premises=list(getattr(prep, "missing_premises", ()) or ()),
        conflicts=list(getattr(prep, "conflicts", ()) or ()),
        preparation_status=str(getattr(prep, "status", "ok") or "ok"),
    )


def render_deterministic_answer(
    envelope: Any,
    *,
    citations: Sequence[Mapping[str, Any]] = (),
) -> str:
    """Headline + explicación determinista + fuentes citadas. Sin LLM."""
    from src.runtime.decision_envelope import build_operation_explanation

    env = _payload(envelope)
    headline = ""
    operation = str(env.get("operation") or "")
    result = env.get("result")
    try:
        from src.runtime.decision_envelope import DecisionEnvelope, decision_headline

        if isinstance(envelope, DecisionEnvelope):
            headline = envelope.headline
        else:
            headline = decision_headline(operation, result)
    except Exception:  # noqa: BLE001 — el render nunca rompe la respuesta
        headline = ""
    explanation = ""
    if hasattr(envelope, "normalized_result"):
        explanation = build_operation_explanation(envelope)  # type: ignore[arg-type]
    else:
        from src.runtime.decision_envelope import normalize_decision_result

        normalized = normalize_decision_result(operation, result)
        lines = [f"Resultado determinista ({operation or 'OPERACIÓN'}): {normalized}"]
        rule_ids = _texts(env.get("canonical_rule_ids"))
        if rule_ids:
            lines.append("Regla canónica: " + ", ".join(rule_ids[:3]))
        inputs = _texts(env.get("runtime_inputs"))
        if inputs:
            lines.append("Datos aplicados: " + ", ".join(inputs[:6]))
        explanation = "\n".join(lines)
    sources: list[str] = []
    for citation in citations or ():
        item = _payload(citation)
        name = str(item.get("document_name") or item.get("title") or "").strip()
        page = item.get("page")
        if not name:
            continue
        label = f"Fuente: {name}" + (f" · pág. {page}" if isinstance(page, int) else "")
        if label not in sources:
            sources.append(label)
    parts = [part for part in (headline, explanation, "\n".join(sources[:3])) if part]
    return "\n\n".join(parts).strip()


def verify_deterministic_answer(
    *,
    envelope: Any,
    grounded: Any = None,
    claims: Sequence[Any] = (),
    citations: Sequence[Mapping[str, Any]] = (),
    evidence_ids: Sequence[str] = (),
) -> dict[str, Any]:
    """Verificador determinista (§6): reemplaza al verifier LLM cuando aplica.

    Comprueba hechos publicados: autoridad, claim soportado, regla soportada,
    sin conflictos, checks completos y citas con referencia existente.
    """
    problems: list[str] = []
    env = _payload(envelope)
    if env.get("authoritative") is not True:
        problems.append("envelope_not_authoritative")
    claim_views = [_payload(claim) for claim in claims or ()]
    supported = [
        view
        for view in claim_views
        if view.get("deterministic") is True
        and str(view.get("verification_status") or "") == "SUPPORTED"
    ]
    if not supported:
        problems.append("no_supported_claim")
    g = _payload(grounded)
    if _texts(g.get("conflicts")):
        problems.append("grounded_conflicts")
    rule_ids = _texts(env.get("canonical_rule_ids"))
    if not rule_ids:
        rule_ids = _texts(supported[0].get("canonical_rule_ids")) if supported else ()
    if not rule_ids:
        problems.append("rule_not_supported")
    for evaluation in _records(g.get("canonical_rule_flow")):
        status = str(evaluation.get("status") or "").upper()
        if status in _UNKNOWN_EVALUATION_STATUSES:
            problems.append("evaluation_incomplete")
            break
    known = {str(value) for value in evidence_ids if str(value or "").strip()}
    if known:
        for citation in citations or ():
            evidence_id = str(_payload(citation).get("evidence_id") or "")
            if evidence_id and evidence_id not in known:
                problems.append(f"citation_ref_missing:{evidence_id}")
    return {
        "version": FAST_PATH_VERSION,
        "verified": not problems,
        "status": "VERIFIED_DETERMINISTIC" if not problems else "UNVERIFIED",
        "problems": problems[:8],
        "rule_ids": list(rule_ids[:6]),
        "checks": [
            {"name": "authority", "ok": env.get("authoritative") is True},
            {"name": "supported_claim", "ok": bool(supported)},
            {"name": "rule_supported", "ok": bool(rule_ids)},
            {"name": "no_conflicts", "ok": not _texts(g.get("conflicts"))},
            {"name": "citations_valid", "ok": not any(p.startswith("citation_ref_missing") for p in problems)},
        ],
    }


def fast_path_metrics(
    *,
    latency_ms: float,
    llm_calls_avoided: int,
    tokens_avoided: int | None = None,
) -> dict[str, Any]:
    """Payload de telemetría del fast path (latencia real, evitado medible)."""
    payload: dict[str, Any] = {
        "execution_mode": EXECUTION_MODE_FAST_PATH,
        "latency_ms": round(float(latency_ms or 0.0), 2),
        "llm_calls": 0,
        "llm_calls_avoided": max(0, int(llm_calls_avoided or 0)),
    }
    if tokens_avoided is not None and tokens_avoided > 0:
        payload["tokens_avoided"] = int(tokens_avoided)
    return payload


__all__ = [
    "AMBIGUOUS_RULES",
    "CONFLICTS",
    "DeterministicFastPathDecision",
    "ELIGIBLE_SUPPORTED_DECISION",
    "EXECUTION_MODE_FAST_PATH",
    "EXECUTION_MODE_STANDARD",
    "FAST_PATH_VERSION",
    "MISSING_PREMISES",
    "NO_AUTHORITY",
    "NOT_EXECUTABLE",
    "evaluate_deterministic_fast_path",
    "fast_path_decision_for",
    "fast_path_metrics",
    "render_deterministic_answer",
    "verify_deterministic_answer",
]
