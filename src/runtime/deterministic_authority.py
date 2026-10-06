# =============================================================================
# Deterministic Authority — una consulta ejecutable jamás la decide el LLM
# =============================================================================
# Principio único:
#
#   NO AUTHORITATIVE DERIVED CLAIM = NO AUTHORITATIVE BINARY ANSWER
#
# Para una consulta que EXIGE aplicar/validar/comparar/calcular una regla, el
# pipeline determinista falla CERRADO:
#
#   deterministic pipeline failed -> explicit non-answer state (UNDETERMINED)
#
# nunca:
#
#   deterministic pipeline failed -> el LLM adivina el resultado
#
# Este módulo centraliza:
#   1. `requires_deterministic_decision` (una sola función, sin dominio);
#   2. los ESTADOS de error diferenciados (operativo != documental);
#   3. las FASES deterministas con su step de telemetría (se emiten aunque una
#      fase posterior falle: rule_retrieval sobrevive a un fallo de grounding);
#   4. `prepare_derived_authority`: retrieval → evaluación → grounding →
#      derivation → envelope, con `DerivedPreparationResult` estructurado;
#   5. la política `executable_gate_action`: sin autoridad no hay respuesta
#      binaria libre (retrieve_more si hay presupuesto; si no, UNDETERMINED).
# =============================================================================
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from src.infrastructure.observability.logging_config import get_logger
from src.runtime.answer_gate import (
    ANSWER_STATE_CONFLICTING_RULE,
    ANSWER_STATE_DERIVATION_FAILED,
    ANSWER_STATE_DERIVED,
    ANSWER_STATE_GROUNDING_ENGINE_FAILED,
    ANSWER_STATE_RULE_EVALUATION_FAILED,
    ANSWER_STATE_RULE_RETRIEVAL_UNAVAILABLE,
    ANSWER_STATE_UNDETERMINED,
    undetermined_answer,
)

logger = get_logger(__name__)

DETERMINISTIC_AUTHORITY_VERSION = "deterministic-authority-1"

#: Intenciones de query que EXIGEN una decisión determinista. Es el vocabulario
#: del clasificador (query_semantics), no operaciones de dominio.
DETERMINISTIC_DECISION_INTENTS: frozenset[str] = frozenset(
    {
        "APPLY_RULE",
        "VALIDATE",
        "COMPARE",
        "CALCULATE",
        "TRANSFORM",
        "INFER",
    }
)

#: Nombres de operación/evaluación que también exigen decisión determinista.
#: Se aceptan como entrada de `requires_deterministic_decision` para que otros
#: componentes (routers, gates, tests cross-domain) hablen el mismo contrato.
DETERMINISTIC_OPERATION_NAMES: frozenset[str] = frozenset(
    {
        "MATCH",
        "ELIGIBILITY",
        "RANGE_CHECK",
        "ENUM_CHECK",
        "DATE_RULE",
        "FORMULA",
        "BOOLEAN_RULE",
        "POSITIONAL_MATCH",
        "SET_MEMBERSHIP",
        "COMPARISON",
        "FORMULA_EVALUATION",
        "ARITHMETIC",
    }
)

#: Fases deterministas (telemetría obligatoria, incluso al fallar).
STAGE_QUERY_SEMANTICS = "query_semantics"
STAGE_RULE_RETRIEVAL = "rule_retrieval"
STAGE_RULE_EVALUATION = "rule_evaluation"
STAGE_GROUNDING = "grounding"
STAGE_DERIVATION = "derivation"
STAGE_DECISION_ENVELOPE = "decision_envelope"

#: Códigos de error explícitos (operativo vs documental).
ERROR_RULE_RETRIEVAL_UNAVAILABLE = "RULE_RETRIEVAL_UNAVAILABLE"
ERROR_RULE_EVALUATION_FAILED = "RULE_EVALUATION_FAILED"
ERROR_GROUNDING_ENGINE_FAILED = "GROUNDING_ENGINE_FAILED"
ERROR_DERIVATION_FAILED = "DERIVATION_FAILED"
ERROR_UNDETERMINED_RULE = "UNDETERMINED_RULE"
ERROR_CONFLICTING_RULE = "CONFLICTING_RULE"
ERROR_DERIVED_RESULT = "DERIVED_RESULT"

#: stage -> answer_state (el vocabulario que ve «Ver flujo»).
_STATE_BY_STAGE: dict[str, str] = {
    STAGE_RULE_RETRIEVAL: ANSWER_STATE_RULE_RETRIEVAL_UNAVAILABLE,
    STAGE_RULE_EVALUATION: ANSWER_STATE_RULE_EVALUATION_FAILED,
    STAGE_GROUNDING: ANSWER_STATE_GROUNDING_ENGINE_FAILED,
    STAGE_DERIVATION: ANSWER_STATE_DERIVATION_FAILED,
    STAGE_DECISION_ENVELOPE: ANSWER_STATE_DERIVATION_FAILED,
}

#: Intenciones donde un patrón de runtime (máscara/símbolo) NO es aplicación
#: de regla sino consulta sobre el patrón: no fuerzan decisión determinista.
_PATTERN_LOOKUP_INTENTS = frozenset(
    {"DEFINITION", "EXPLAIN", "SOURCE_LOOKUP", "SUMMARIZE", "TRACE"}
)

#: Verbos de comprobación (ES/EN). Genéricos, sin vocabulario de dominio.
_DECISION_VERB_RE = re.compile(
    r"\b(?:cumpl\w*|valid\w*|verific\w*|comprob\w*|chequ\w*|check\w*|confirm\w*|"
    r"satisfac\w*|satisface\w*|acept\w*|matche\w*|coincid\w*|aplic\w*|pasa\b|"
    r"pass\w*|aprob\w*|calific\w*|califica\b)\b",
    re.IGNORECASE,
)
_ELIGIBILITY_RE = re.compile(
    r"\b(?:elegible|elegibilidad|eligibility|eligible|califica|apto|"
    r"qualifies|qualify)\b",
    re.IGNORECASE,
)
_RANGE_RE = re.compile(
    r"\b(?:rango|range|umbral|threshold|m[ií]nim\w*|m[aá]xim\w*|\bmin\b|\bmax\b|"
    r"at\s+least|at\s+most|greater\s+than|less\s+than|\bentre\b|\bbetween\b|"
    r"no\s+m[aá]s\s+de|al\s+menos|como\s+m[aá]ximo)\b",
    re.IGNORECASE,
)
_ENUM_RE = re.compile(
    r"\b(?:enum|estados?\s+(?:permitidos?|v[aá]lidos?)|"
    r"valores?\s+(?:permitidos?|v[aá]lidos?)|allowed\s+(?:values|statuses)|"
    r"one\s+of|uno\s+de\s+los)\b",
    re.IGNORECASE,
)
_PERMIT_RE = re.compile(r"\b(?:permitid\w*|allowed|prohibid\w*|forbidden)\b", re.IGNORECASE)
_DATE_RULE_RE = re.compile(
    r"\b(?:vigente|effective|v[aá]lid[ao]\s+(?:en|desde|hasta|from|until)|"
    r"fecha\s+de\s+(?:vigencia|aplicaci[oó]n)|date\s+of\s+effect|"
    r"a\s+partir\s+de\s+la\s+fecha)\b",
    re.IGNORECASE,
)
_BOOLEAN_RULE_RE = re.compile(
    r"\b(?:si\s+.{2,80}\s+entonces|if\s+.{2,80}\s+then|"
    r"cuando\s+.{2,80}\s+(?:aplica|se\s+cumple)|"
    r"condiciones?\s+(?:se\s+cumplen|se\s+verifican))\b",
    re.IGNORECASE,
)
_NUMERIC_TOKEN_RE = re.compile(r"\d")
_UPPER_TOKEN_RE = re.compile(r"\b[A-Z][A-Z0-9_-]{1,}\b")
_LIST_QUESTION_RE = re.compile(
    r"\b(?:qu[eé]|cu[aá]les|cu[aá]l|lista|listar|enumera|muestra|dime\s+cu[aá]les|"
    r"what|which|list)\b",
    re.IGNORECASE,
)
#: Preguntas de DATO (temporal/ubicación/autor): piden información, no una
#: aplicación de regla. «¿desde cuándo aplica el cambio?» no exige decidir.
_LOOKUP_OVERRIDE_RE = re.compile(
    r"\b(?:desde\s+cu[aá]ndo|hasta\s+cu[aá]ndo|cu[aá]ndo|d[oó]nde|qui[eé]n(?:es)?|"
    r"what\s+is\s+the\s+(?:date|effective|start|end)|when\s+(?:does|is|was))\b",
    re.IGNORECASE,
)
#: Señal FUERTE de comprobación: anula el override de lookup.
_STRONG_DECISION_RE = re.compile(
    r"\b(?:cumpl\w*|valid\w*|verific\w*|coincid\w*|matche\w*|elegib\w*|eligible\b|"
    r"permitid\w*|allowed|prohibid\w*|forbidden|aprob\w*)\b",
    re.IGNORECASE,
)

#: Conclusión binaria (para diagnóstico/observabilidad; el bloqueo real no
#: depende del texto: sin envelope, una consulta ejecutable SIEMPRE se bloquea).
_BINARY_CONCLUSION_RE = re.compile(
    r"\b(?:no\s+)?(?:cumple|cumplir[ií]a|no\s+cumple|coincide|coincidir[ií]a)\b|"
    r"\b(?:no\s+)?(?:v[aá]lid[oa]s?|inv[aá]lid[oa]s?)\b|"
    r"\b(?:true|false|verdadero|falso)\b|"
    r"\b(?:no\s+)?(?:elegibles?|eligible)\b|"
    r"\b(?:no\s+)?(?:permitid[oa]s?)\b|"
    r"\b(?:correct[oa]s?|incorrect[oa]s?)\b|"
    r"\bMATCH\b|\bNO_MATCH\b",
    re.IGNORECASE,
)


def contains_binary_conclusion(text: str) -> bool:
    """¿El texto afirma una conclusión binaria? Sólo diagnóstico/observabilidad."""
    return bool(_BINARY_CONCLUSION_RE.search(str(text or "")))


def undetermined_authoritative_answer(reason: str = "") -> str:
    """Respuesta construida por código cuando el pipeline determinista falla.

    NO es «no cumple»: es un estado no concluyente explícito.
    """
    message = (
        "En esta ejecución no pude completar la evaluación determinista de la "
        "regla. No voy a afirmar si cumple o no cumple sin completar esa "
        "comprobación."
    )
    if reason:
        message += f" Causa: {str(reason).strip()[:160]}."
    return message


def answer_state_for_stage(stage: str) -> str:
    return _STATE_BY_STAGE.get(str(stage or ""), ANSWER_STATE_UNDETERMINED)


def _normalized_intent(subject: Any) -> str:
    """Intención normalizada de un string (pregunta o código) u objeto semántico."""
    if subject is None:
        return ""
    if isinstance(subject, str):
        text = subject.strip()
        if not text:
            return ""
        upper = text.upper()
        if (
            upper in DETERMINISTIC_DECISION_INTENTS
            or upper in DETERMINISTIC_OPERATION_NAMES
        ):
            return upper
        try:
            from src.intelligence.query_semantics import classify_query_semantics

            return str(
                getattr(classify_query_semantics(text), "intent", "") or ""
            ).upper()
        except Exception:  # noqa: BLE001 — sin semántica no se fuerza el gate
            return ""
    intent = str(getattr(subject, "intent", "") or "")
    return intent.upper()


def _heuristic_executable(question: str) -> bool:
    """Señales generales de operación que el clasificador pudo dejar en LOOKUP.

    Sin dominio: verbos de comprobación + rangos/elegibilidad/enum/fechas/boolean.
    """
    text = str(question or "")
    if not text.strip():
        return False
    if _ELIGIBILITY_RE.search(text):
        return True
    if _DATE_RULE_RE.search(text):
        return True
    if _BOOLEAN_RULE_RE.search(text):
        return True
    if _RANGE_RE.search(text) and (
        _DECISION_VERB_RE.search(text) or _NUMERIC_TOKEN_RE.search(text)
    ):
        return True
    if _ENUM_RE.search(text) and _DECISION_VERB_RE.search(text):
        return True
    # Membresía sobre un valor concreto («¿el estado ACTIVE está permitido?»):
    # hace falta un valor (token en mayúsculas), no una pregunta de listado.
    if (
        _PERMIT_RE.search(text)
        and _UPPER_TOKEN_RE.search(text)
        and not _LIST_QUESTION_RE.search(text)
    ):
        return True
    return False


def requires_deterministic_decision(subject: Any) -> bool:
    """¿La consulta exige una decisión determinista (no una explicación)?

    Única fuente de verdad, genérica. Acepta pregunta (str), intención u
    operación (str) o `QuerySemantics`.
    """
    intent = _normalized_intent(subject)
    text = (
        subject
        if isinstance(subject, str)
        else str(getattr(subject, "question", "") or "")
    )
    # Pregunta de DATO (temporal/ubicación/autor): no es una comprobación, por
    # más que el verbo «aplica» haya disparado el clasificador.
    if (
        text
        and _LOOKUP_OVERRIDE_RE.search(text)
        and not _STRONG_DECISION_RE.search(text)
    ):
        return False
    if intent in DETERMINISTIC_DECISION_INTENTS or intent in DETERMINISTIC_OPERATION_NAMES:
        return True
    if isinstance(subject, str) and not intent:
        # Sin clasificación disponible: heurística genérica sobre el texto.
        return _heuristic_executable(subject)
    if isinstance(subject, str):
        # El clasificador devolvió LOOKUP/DEFINITION: los patrones de runtime
        # (máscaras) aplicados sobre un valor también exigen decisión.
        if intent not in _PATTERN_LOOKUP_INTENTS:
            try:
                from src.intelligence.query_semantics import classify_query_semantics

                semantics = classify_query_semantics(subject)
                if tuple(getattr(semantics, "runtime_patterns", ()) or ()):
                    return True
            except Exception:  # noqa: BLE001
                pass
        return _heuristic_executable(subject)
    # Objeto semántico: patrón de runtime sobre un valor => aplicación.
    if intent not in _PATTERN_LOOKUP_INTENTS:
        try:
            if tuple(getattr(subject, "runtime_patterns", ()) or ()):
                return True
        except Exception:  # noqa: BLE001
            pass
    return False


def stage_step(stage: str, status: str, **fields: Any) -> dict[str, Any]:
    """Step de telemetría de una fase determinista (nunca se omite)."""
    payload: dict[str, Any] = {"type": stage, "status": status}
    for key, value in fields.items():
        if value is None:
            continue
        if isinstance(value, tuple):
            value = list(value)
        payload[key] = value
    return payload


def executable_gate_action(
    *,
    verdict: str,
    has_authority: bool,
    rounds_left: int,
    final: bool,
    exhausted: bool,
) -> str:
    """Compone la acción del gate para consultas ejecutables.

    Con autoridad determinista manda JEV (el guard no deja invertir el resultado).
    Sin autoridad: buscar más si hay presupuesto; si no, estado no concluyente.
    NUNCA revise/answer_with_limits con una decisión binaria libre.
    """
    if has_authority:
        return str(verdict or "")
    if not final and int(rounds_left or 0) > 0 and not exhausted:
        return "retrieve_more"
    return "abstain"


@dataclass(kw_only=True)
class DerivedPreparationResult:
    """Resultado estructurado de preparar la autoridad determinista de un run."""

    status: str = "ok"  # ok | degraded | error | skipped
    question: str = ""
    requires_deterministic_decision: bool = False
    rule_retrieval: Any = None
    grounded_reasoning: Any = None
    derived_claims: list[Any] = field(default_factory=list)
    authoritative_envelope: Any = None
    retrieval_unavailable: bool = False
    retrieval_error: str = ""
    error_stage: str = ""
    error_code: str = ""
    error_message: str = ""
    missing_premises: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    steps: list[dict] = field(default_factory=list)
    duration_ms: float = 0.0
    version: str = DETERMINISTIC_AUTHORITY_VERSION

    @property
    def has_authority(self) -> bool:
        envelope = self.authoritative_envelope
        if envelope is not None and bool(getattr(envelope, "authoritative", True)):
            return True
        return any(
            bool(getattr(claim, "deterministic", False))
            and str(getattr(claim, "verification_status", "")) == "SUPPORTED"
            for claim in self.derived_claims
        )

    def answer_state(self) -> tuple[str, str]:
        """(estado, mensaje) construidos por código cuando no hay autoridad."""
        if self.has_authority:
            return ANSWER_STATE_DERIVED, ""
        if self.error_stage:
            state = answer_state_for_stage(self.error_stage)
            if state == ANSWER_STATE_UNDETERMINED and self.error_code:
                state = str(self.error_code)
            return state, undetermined_authoritative_answer(self.error_message)
        if self.retrieval_unavailable:
            return (
                ANSWER_STATE_RULE_RETRIEVAL_UNAVAILABLE,
                undetermined_authoritative_answer(
                    self.retrieval_error
                    or "el retrieval de reglas canónicas no está disponible"
                ),
            )
        if self.conflicts:
            return ANSWER_STATE_CONFLICTING_RULE, (
                "Las reglas recuperadas se contradicen entre sí para esta "
                "consulta, así que no hay una única conclusión respaldada."
            )
        if self.missing_premises:
            # La abstención humanizada del motor grounded (nombra la premisa
            # faltante) manda sobre el volcado técnico de claves.
            human = str(
                getattr(self.grounded_reasoning, "abstention_message", "") or ""
            ).strip()
            if human:
                return (
                    ANSWER_STATE_UNDETERMINED,
                    f"No puedo determinarlo porque {human}.",
                )
            return ANSWER_STATE_UNDETERMINED, undetermined_answer(self.missing_premises)
        return ANSWER_STATE_UNDETERMINED, undetermined_authoritative_answer()

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "status": self.status,
            "requires_deterministic_decision": bool(
                self.requires_deterministic_decision
            ),
            "has_authority": self.has_authority,
            "retrieval_unavailable": bool(self.retrieval_unavailable),
            "error_stage": self.error_stage,
            "error_code": self.error_code,
            "error_message": self.error_message[:240],
            "missing_premises": list(self.missing_premises[:12]),
            "conflicts": list(self.conflicts[:8]),
            "steps": list(self.steps),
            "duration_ms": round(float(self.duration_ms or 0.0), 2),
        }


def _rules_for_grounding(retrieval: Any) -> list[Any]:
    if retrieval is None:
        return []
    supported = list(getattr(retrieval, "supported_rules", ()) or ())
    if supported:
        return supported
    return list(getattr(retrieval, "candidate_rules", ()) or ())


def _first_deterministic_claim(grounded: Any) -> dict[str, Any] | None:
    derivations = getattr(grounded, "derivations", None)
    for claim in getattr(derivations, "claims", ()) or ():
        if (
            bool(getattr(claim, "deterministic", False))
            and str(getattr(claim, "verification_status", "")) == "SUPPORTED"
        ):
            payload = (
                claim.to_public_dict()
                if hasattr(claim, "to_public_dict")
                else {}
            )
            return dict(payload) if isinstance(payload, dict) else None
    return None


async def prepare_derived_authority(
    *,
    organization_id: Any,
    question: str,
    evidence_items: Sequence[Any] = (),
    semantics: Any = None,
    retrieval_fn: Callable[..., Any] | None = None,
    reason_fn: Callable[..., Any] | None = None,
    envelope_fn: Callable[..., Any] | None = None,
) -> DerivedPreparationResult:
    """Ejecuta la cadena determinista por FASES con telemetría fail-closed.

    Cada fase emite su step ANTES de la siguiente. Un fallo posterior jamás
    borra la telemetría anterior (rule_retrieval sobrevive a grounding).
    """
    started = time.perf_counter()
    text_question = str(question or "")
    sem = semantics if semantics is not None and not isinstance(semantics, str) else None
    prep = DerivedPreparationResult(question=text_question)
    prep.requires_deterministic_decision = requires_deterministic_decision(
        sem if sem is not None else text_question
    )

    # --- query semantics (observabilidad obligatoria) -----------------------
    if sem is None:
        try:
            from src.intelligence.query_semantics import classify_query_semantics

            sem = classify_query_semantics(text_question)
        except Exception as exc:  # noqa: BLE001 — la semántica nunca rompe la cadena
            logger.warning("query semantics failed", error=str(exc)[:160])
            sem = None
    if sem is not None:
        try:
            from src.intelligence.query_semantics import intent_category

            category = intent_category(str(getattr(sem, "intent", "") or ""))
        except Exception:  # noqa: BLE001
            category = ""
        to_public = getattr(sem, "to_public_dict", None)
        prep.steps.append(
            stage_step(
                STAGE_QUERY_SEMANTICS,
                "ok",
                intent=str(getattr(sem, "intent", "") or ""),
                intent_category=category,
                semantics=to_public() if callable(to_public) else None,
            )
        )

    # --- RULE RETRIEVAL ------------------------------------------------------
    retrieval_started = time.perf_counter()
    retrieval: Any = None
    try:
        retrieve = retrieval_fn
        if retrieve is None:
            from src.runtime.rule_retrieval import retrieve_canonical_rules

            retrieve = retrieve_canonical_rules
        retrieval = await retrieve(
            organization_id, text_question, evidence_items=list(evidence_items)
        )
    except Exception as exc:  # noqa: BLE001 — fallo operativo explícito, no silencio
        prep.retrieval_unavailable = True
        prep.retrieval_error = str(exc)[:300]
        prep.steps.append(
            stage_step(
                STAGE_RULE_RETRIEVAL,
                "error",
                error_code=ERROR_RULE_RETRIEVAL_UNAVAILABLE,
                error=prep.retrieval_error,
                strategy="unavailable",
                duration_ms=round(
                    (time.perf_counter() - retrieval_started) * 1000, 2
                ),
            )
        )
    else:
        prep.rule_retrieval = retrieval
        supported = list(getattr(retrieval, "supported_rules", ()) or ())
        candidates = list(getattr(retrieval, "candidate_rules", ()) or ())
        errors = [str(item) for item in (getattr(retrieval, "errors", ()) or ())][:4]
        reasons = [str(item) for item in (getattr(retrieval, "reasons", ()) or ())]
        operational_failure = not supported and (
            bool(errors) or "retrieval_failure" in reasons
        )
        if operational_failure:
            prep.retrieval_unavailable = True
            prep.retrieval_error = ", ".join(errors) or "retrieval_failure"
        step = stage_step(
            STAGE_RULE_RETRIEVAL,
            "error" if operational_failure else "ok",
            strategy=str(getattr(retrieval, "strategy", "none") or "none"),
            candidates_found=len(candidates),
            supported_rules=len(supported),
            rule_ids=list(getattr(retrieval, "supported_ids", []) or [])
            [:12]
            or list(getattr(retrieval, "candidate_ids", []) or [])[:12],
            errors=errors,
            duration_ms=round((time.perf_counter() - retrieval_started) * 1000, 2),
            canonical=True,
        )
        if operational_failure:
            step["error_code"] = ERROR_RULE_RETRIEVAL_UNAVAILABLE
        if not supported:
            to_public = getattr(retrieval, "to_public_dict", None)
            if callable(to_public):
                public = to_public() or {}
                step["why_no_rule"] = list(public.get("why_no_rule") or [])[:4]
        prep.steps.append(step)

    rules = _rules_for_grounding(retrieval)

    # --- GROUNDING (incluye rule evaluation + derivation) --------------------
    grounding_started = time.perf_counter()
    try:
        reason = reason_fn
        if reason is None:
            from src.intelligence.reasoning.grounded_engine import (
                reason_over_evidence,
            )

            reason = reason_over_evidence
        grounded = reason(
            question=text_question,
            evidence_items=list(evidence_items),
            canonical_rules=rules or None,
        )
    except Exception as exc:  # noqa: BLE001 — fallo explícito y fail-closed
        prep.status = "error"
        prep.error_stage = STAGE_GROUNDING
        prep.error_code = ERROR_GROUNDING_ENGINE_FAILED
        prep.error_message = str(exc)[:300]
        prep.steps.append(
            stage_step(
                STAGE_GROUNDING,
                "error",
                error_code=ERROR_GROUNDING_ENGINE_FAILED,
                error=prep.error_message,
                duration_ms=round((time.perf_counter() - grounding_started) * 1000, 2),
            )
        )
        prep.steps.append(
            stage_step(
                STAGE_RULE_EVALUATION,
                "not_run",
                error_code=ERROR_GROUNDING_ENGINE_FAILED,
            )
        )
        prep.steps.append(
            stage_step(STAGE_DERIVATION, "not_created", error_code=ERROR_GROUNDING_ENGINE_FAILED)
        )
        prep.steps.append(stage_step(STAGE_DECISION_ENVELOPE, "not_created"))
        prep.duration_ms = (time.perf_counter() - started) * 1000
        return prep

    prep.grounded_reasoning = grounded
    premisas = tuple(str(item) for item in (getattr(grounded, "missing_premises", ()) or ()))
    conflicts = tuple(str(item) for item in (getattr(grounded, "conflicts", ()) or ()))
    derivations = getattr(grounded, "derivations", None)
    claims = list(getattr(derivations, "claims", ()) or ())
    deterministic_claims = [
        claim
        for claim in claims
        if bool(getattr(claim, "deterministic", False))
        and str(getattr(claim, "verification_status", "")) == "SUPPORTED"
    ]
    prep.derived_claims = claims
    prep.missing_premises = premisas
    prep.conflicts = conflicts
    answerability = str(getattr(grounded, "answerability", "") or "")
    evaluations = list(getattr(grounded, "rule_evaluations", ()) or ())
    credible = [
        evaluation
        for evaluation in evaluations
        if str(getattr(evaluation, "status", "") or "") in ("MATCH", "NO_MATCH")
    ]
    prep.steps.append(
        stage_step(
            STAGE_GROUNDING,
            "warn" if (premisas or conflicts) else "ok",
            answerability=answerability,
            deterministic=bool(deterministic_claims),
            missing_premises=list(premisas[:12]),
            conflicts=list(conflicts[:8]),
            duration_ms=round((time.perf_counter() - grounding_started) * 1000, 2),
        )
    )
    prep.steps.append(
        stage_step(
            STAGE_RULE_EVALUATION,
            "conflict"
            if conflicts
            else ("warn" if premisas else "ok"),
            executable_rules=len(credible),
            missing_requirements=list(premisas[:12]),
            conflicts=list(conflicts[:8]),
        )
    )
    primary = deterministic_claims[0] if deterministic_claims else None
    prep.steps.append(
        stage_step(
            STAGE_DERIVATION,
            "ok" if primary is not None else "not_created",
            deterministic=bool(deterministic_claims),
            result=getattr(primary, "result", None) if primary is not None else None,
            operation=getattr(primary, "operation", "") if primary is not None else "",
            claims=len(claims),
        )
    )

    # --- DECISION ENVELOPE ---------------------------------------------------
    try:
        builder = envelope_fn
        if builder is None:
            from src.runtime.decision_envelope import build_decision_envelope

            builder = build_decision_envelope
        envelope = builder(grounded)
    except Exception as exc:  # noqa: BLE001 — fallo explícito, fail-closed
        prep.status = "error"
        prep.error_stage = STAGE_DERIVATION
        prep.error_code = ERROR_DERIVATION_FAILED
        prep.error_message = str(exc)[:300]
        prep.steps.append(
            stage_step(
                STAGE_DECISION_ENVELOPE,
                "error",
                error_code=ERROR_DERIVATION_FAILED,
                error=prep.error_message,
            )
        )
        prep.duration_ms = (time.perf_counter() - started) * 1000
        return prep

    if envelope is not None:
        prep.authoritative_envelope = envelope
        prep.steps.append(
            stage_step(
                STAGE_DECISION_ENVELOPE,
                "ok",
                authoritative=bool(getattr(envelope, "authoritative", True)),
                operation=str(getattr(envelope, "operation", "") or ""),
                result=getattr(envelope, "normalized_result", None),
            )
        )
        prep.status = "degraded" if prep.retrieval_unavailable else "ok"
    else:
        prep.steps.append(
            stage_step(
                STAGE_DECISION_ENVELOPE,
                "not_created",
                detail="sin DerivedClaim determinista SUPPORTED",
            )
        )
        prep.status = "error" if prep.retrieval_unavailable else "ok"
    prep.duration_ms = (time.perf_counter() - started) * 1000
    return prep


__all__ = [
    "DETERMINISTIC_AUTHORITY_VERSION",
    "DETERMINISTIC_DECISION_INTENTS",
    "DETERMINISTIC_OPERATION_NAMES",
    "DerivedPreparationResult",
    "ERROR_CONFLICTING_RULE",
    "ERROR_DERIVATION_FAILED",
    "ERROR_DERIVED_RESULT",
    "ERROR_GROUNDING_ENGINE_FAILED",
    "ERROR_RULE_EVALUATION_FAILED",
    "ERROR_RULE_RETRIEVAL_UNAVAILABLE",
    "ERROR_UNDETERMINED_RULE",
    "STAGE_DECISION_ENVELOPE",
    "STAGE_DERIVATION",
    "STAGE_GROUNDING",
    "STAGE_QUERY_SEMANTICS",
    "STAGE_RULE_EVALUATION",
    "STAGE_RULE_RETRIEVAL",
    "answer_state_for_stage",
    "contains_binary_conclusion",
    "executable_gate_action",
    "prepare_derived_authority",
    "requires_deterministic_decision",
    "stage_step",
    "undetermined_authoritative_answer",
]
