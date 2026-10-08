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
import re
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
OPERATION_INCOMPATIBLE = "OPERATION_INCOMPATIBLE"
NO_RESULT = "NO_RESULT"
SOURCE_SCOPE_UNRESOLVED = "SOURCE_SCOPE_UNRESOLVED"
OUT_OF_SCOPE_RULE = "OUT_OF_SCOPE_RULE"

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
    scope_explicit: bool | None = None,
    out_of_scope_rule_ids: Sequence[str] = (),
) -> DeterministicFastPathDecision:
    """Elegible sólo con autoridad completa y sin incertidumbre (§1, §2).

    P0.1: con `scope_explicit=False` (agente sin fuentes/KB/workspace) el fast
    path NO decide sobre un universo no declarado: SOURCE_SCOPE_UNRESOLVED.
    Una regla ganadora excluida por scope/mezcla tampoco puede sostenerlo.
    """
    if not requires_deterministic:
        return _fail(NOT_EXECUTABLE)
    if scope_explicit is False:
        return _fail(SOURCE_SCOPE_UNRESOLVED)
    if str(preparation_status or "ok") == "error":
        return _fail(PREPARATION_ERROR)
    env = _payload(envelope)
    if env.get("authoritative") is not True:
        return _fail(NO_AUTHORITY)
    # Invariante AUTHORITATIVE_OPERATION_COMPATIBILITY: una operación
    # incompatible con la query no habilita el fast path.
    compatibility = env.get("operation_compatibility")
    if isinstance(compatibility, Mapping) and compatibility.get("compatible") is False:
        return _fail(OPERATION_INCOMPATIBLE)
    excluded = {str(value) for value in out_of_scope_rule_ids if str(value or "").strip()}
    if excluded:
        winning = set(_texts(env.get("canonical_rule_ids")))
        for claim in claims or ():
            winning.update(_texts(_payload(claim).get("canonical_rule_ids")))
        if winning & excluded:
            return _fail(OUT_OF_SCOPE_RULE)
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


def fast_path_decision_for(
    prep: Any,
    *,
    requires_deterministic: bool,
    scope_explicit: bool | None = None,
    out_of_scope_rule_ids: Sequence[str] = (),
) -> DeterministicFastPathDecision:
    """Conveniencia sobre `DerivedPreparationResult` (duck-typed)."""
    if scope_explicit is None:
        scope_public = _payload(getattr(prep, "authorized_scope", None))
        if "is_explicit" in scope_public:
            scope_explicit = bool(scope_public.get("is_explicit"))
    excluded_ids = list(out_of_scope_rule_ids)
    for item in _records(getattr(prep, "scope_excluded_rules", ()) or ()):
        reason = str(item.get("reason") or "")
        rule_id = str(item.get("rule_id") or "")
        if rule_id and reason in {
            "OUT_OF_SCOPE_RULE",
            "MIXED_SOURCE_RULE",
            "RULE_PROVENANCE_UNVERIFIED",
        }:
            excluded_ids.append(rule_id)
    return evaluate_deterministic_fast_path(
        requires_deterministic=requires_deterministic,
        envelope=getattr(prep, "authoritative_envelope", None),
        grounded=getattr(prep, "grounded_reasoning", None),
        claims=list(getattr(prep, "derived_claims", ()) or ()),
        missing_premises=list(getattr(prep, "missing_premises", ()) or ()),
        conflicts=list(getattr(prep, "conflicts", ()) or ()),
        preparation_status=str(getattr(prep, "status", "ok") or "ok"),
        scope_explicit=scope_explicit,
        out_of_scope_rule_ids=tuple(excluded_ids),
    )


_INPUT_RE = re.compile(r"^\s*([^=]+?)\s*=\s*(.*)$")

_RESULT_WORDS: dict[str, str] = {
    "MATCH": "cumple",
    "NO_MATCH": "no cumple",
    "TRUE": "verdadero",
    "FALSE": "falso",
    "VALID": "válido",
    "INVALID": "no válido",
    "ELIGIBLE": "elegible",
    "NOT_ELIGIBLE": "no elegible",
}


def _inputs(runtime_inputs: Sequence[Any]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for raw in runtime_inputs or ():
        match = _INPUT_RE.match(str(raw or ""))
        if match is None:
            continue
        key = match.group(1).strip().lower().replace(" ", "_")
        value = match.group(2).strip()
        if key and key not in parsed:
            parsed[key] = value
    return parsed


def _input_values(runtime_inputs: Sequence[Any]) -> list[str]:
    """Valores crudos (con o sin `clave=valor`), deduplicados."""
    values: list[str] = []
    for raw in runtime_inputs or ():
        text = str(raw or "").strip()
        if not text:
            continue
        match = _INPUT_RE.match(text)
        if match is not None:
            text = match.group(2).strip()
        if text and text not in values:
            values.append(text)
    return values


def _first_value(inputs: Mapping[str, str]) -> str:
    for key in ("value", "valor", "input", "amount", "number", "age", "date", "fecha"):
        if inputs.get(key):
            return inputs[key]
    for value in inputs.values():
        if value:
            return value
    return ""


def _normalized_result(operation: str, result: Any) -> str:
    from src.runtime.decision_envelope import normalize_decision_result

    return str(normalize_decision_result(operation, result) or "").upper()


def _result_word(operation: str, result: str) -> str:
    if operation in {"POSITIONAL_MATCH", "MATCH", "STRING_EQUALITY"}:
        return "cumple" if result in {"MATCH", "TRUE", "VALID"} else "no cumple"
    return _RESULT_WORDS.get(result, result.lower() or "evaluado")


def _user_sources(citations: Sequence[Mapping[str, Any]]) -> list[str]:
    sources: list[str] = []
    for citation in citations or ():
        item = _payload(citation)
        name = str(
            item.get("document_name")
            or item.get("title")
            or item.get("display_name")
            or ""
        ).strip()
        if not name or name.lower().startswith("documento "):
            continue
        label = f"Fuente: {name}"
        page = item.get("page")
        if isinstance(page, int):
            label += f" · pág. {page}"
        section = item.get("section_path")
        if isinstance(section, (list, tuple)):
            section_text = " · ".join(str(part) for part in section[:2] if str(part))
            if section_text:
                label += f" · {section_text[:60]}"
        if label not in sources:
            sources.append(label)
    return sources


def build_user_deterministic_explanation(
    envelope: Any,
    *,
    grounded: Any = None,
    checks: Sequence[Any] = (),
    runtime_inputs: Sequence[Any] = (),
) -> str:
    """Explicación natural, genérica por operación. Sin LLM y sin códigos.

    Usa sólo resultado, checks e inputs publicados: nunca UUIDs, IDs de regla,
    códigos internos ni cadenas de verificación. El detalle técnico completo
    sigue disponible en `build_operation_explanation()`.
    """
    env = _payload(envelope)
    operation = str(env.get("operation") or "").upper()
    result = _normalized_result(operation, env.get("result"))
    inputs = _inputs(
        runtime_inputs or _texts(env.get("runtime_inputs"))
    )
    check_records = [_payload(check) for check in checks or ()]
    lines: list[str] = []

    if operation in {"POSITIONAL_MATCH", "MATCH", "STRING_EQUALITY"}:
        pattern = inputs.get("pattern") or inputs.get("patrón") or ""
        value = inputs.get("value") or inputs.get("valor") or ""
        values = _input_values(runtime_inputs)
        if not pattern:
            pattern = next(
                (item for item in values if any(ch in item for ch in "&*?%#$@!~^")),
                "",
            )
        if not value:
            value = next(
                (
                    item
                    for item in values
                    if item != pattern and item.replace(" ", "").isalnum()
                ),
                "",
            )
        if pattern and value:
            described: list[str] = []
            for index, char in enumerate(pattern):
                if char.isalnum():
                    described.append(f"posición {index + 1} debe ser «{char}»")
                else:
                    described.append(f"posición {index + 1} admite un carácter")
            lines.append(
                f"El patrón `{pattern}` exige que " + ", ".join(described) + "."
            )
            head = value[: len(pattern)]
            if result in {"MATCH", "TRUE", "VALID"}:
                lines.append(
                    f"`{value}` comienza con `{head}`, por lo que satisface esas "
                    "posiciones."
                )
            else:
                lines.append(
                    f"`{value}` no satisface todas las posiciones del patrón."
                )
            length_checked = any(
                "length" in str(check.get("name") or "").lower()
                or "length" in str(check.get("detail") or "").lower()
                for check in check_records
            )
            if length_checked and len(value) > len(pattern):
                lines.append(
                    "La política de longitud documentada permite caracteres "
                    "adicionales después de las posiciones del patrón."
                )
        else:
            lines.append(
                "El patrón documentado se comparó posición a posición con el "
                "valor provisto."
            )
    elif operation in {"RANGE_CHECK", "COMPARISON", "NUMERIC_COMPARE"}:
        value = _first_value(inputs)
        if operation == "RANGE_CHECK":
            inside = result in {"VALID", "TRUE", "MATCH"}
            lines.append(
                f"El valor `{value}` {('queda dentro' if inside else 'queda fuera')} "
                "del rango documentado."
                if value
                else "El valor provisto se comparó contra el rango documentado."
            )
        else:
            lines.append(
                "Los valores provistos se compararon según la condición documentada."
            )
    elif operation in {"ENUM_CHECK", "SET_MEMBERSHIP"}:
        value = _first_value(inputs)
        inside = result in {"VALID", "TRUE", "MATCH"}
        lines.append(
            f"`{value}` {('figura' if inside else 'no figura')} entre los valores "
            "documentados."
            if value
            else "El valor provisto se contrastó contra los valores documentados."
        )
    elif operation in {"DATE_COMPARE", "DATE_COMPARISON", "DATE_RANGE"}:
        value = _first_value(inputs)
        lines.append(
            f"La fecha `{value}` {('cumple' if result in {'VALID', 'TRUE', 'MATCH'} else 'no cumple')} "
            "la condición temporal documentada."
            if value
            else "La fecha provista se comparó contra la condición temporal documentada."
        )
    elif operation in {"BOOLEAN", "BOOLEAN_RULE"}:
        lines.append(
            "La condición documentada se evaluó como "
            + ("verdadera." if result in {"TRUE", "VALID", "MATCH"} else "falsa.")
        )
    elif operation in {"FORMULA", "FORMULA_EVALUATION"}:
        lines.append(
            "La fórmula documentada se evaluó con los datos provistos."
        )
    else:
        lines.append("La operación documentada se evaluó de forma determinista.")

    lines.append(f"Resultado: {_result_word(operation, result)}.")
    text = "\n\n".join(line for line in lines if line)
    # Formato: nunca una barra invertida suelta entre líneas.
    return text.replace("\\\n", "\n").strip()


def render_deterministic_answer(
    envelope: Any,
    *,
    grounded: Any = None,
    checks: Sequence[Any] = (),
    runtime_inputs: Sequence[Any] = (),
    citations: Sequence[Mapping[str, Any]] = (),
) -> str:
    """Headline + explicación natural determinista + fuentes. Sin LLM.

    La respuesta visible no expone IDs ni códigos internos; el detalle técnico
    completo vive en la traza (`build_operation_explanation`).
    """
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
    explanation = build_user_deterministic_explanation(
        envelope,
        grounded=grounded,
        checks=checks,
        runtime_inputs=runtime_inputs,
    )
    sources = _user_sources(citations)
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
    "OPERATION_INCOMPATIBLE",
    "OUT_OF_SCOPE_RULE",
    "SOURCE_SCOPE_UNRESOLVED",
    "build_user_deterministic_explanation",
    "evaluate_deterministic_fast_path",
    "fast_path_decision_for",
    "fast_path_metrics",
    "render_deterministic_answer",
    "verify_deterministic_answer",
]
