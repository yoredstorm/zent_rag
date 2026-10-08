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
STAGE_OPERATION_COMPATIBILITY = "operation_compatibility"
STAGE_RULE_EVALUATION = "rule_evaluation"
STAGE_GROUNDING = "grounding"
STAGE_DERIVATION = "derivation"
STAGE_DECISION_ENVELOPE = "decision_envelope"
STAGE_REQUIREMENT_GRAPH = "requirement_graph"
STAGE_PREMISE_CLOSURE = "premise_closure"

#: Códigos de error explícitos (operativo vs documental).
ERROR_RULE_RETRIEVAL_UNAVAILABLE = "RULE_RETRIEVAL_UNAVAILABLE"
ERROR_RULE_EVALUATION_FAILED = "RULE_EVALUATION_FAILED"
ERROR_GROUNDING_ENGINE_FAILED = "GROUNDING_ENGINE_FAILED"
ERROR_DERIVATION_FAILED = "DERIVATION_FAILED"
ERROR_UNDETERMINED_RULE = "UNDETERMINED_RULE"
ERROR_OPERATION_MISMATCH = "UNDETERMINED_OPERATION_MISMATCH"
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

#: Operadores de matching de MÁSCARA (patrón posicional), no de comparación.
_MASK_MATCH_OPERATORS = frozenset({"POSITIONAL", "FIXED_POSITION", "PREFIX", "SUFFIX"})

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
    premise_closure: Any = None
    evidence_counters: dict = field(default_factory=dict)
    #: Reglas excluidas por scope autorizado / provenance mezclada (auditable).
    scope_excluded_rules: list[dict] = field(default_factory=list)
    #: Scope autorizado publicado (sin secretos) para «Ver flujo».
    authorized_scope: dict = field(default_factory=dict)
    #: Gate OPERACIÓN↔QUERY: vistas públicas (conteos, rechazos, ganador).
    operation_compatibility: dict = field(default_factory=dict)
    #: True cuando existían reglas soportadas pero NINGUNA compatible con la
    #: operación que exige la consulta (fail closed: UNDETERMINED_OPERATION_MISMATCH).
    operation_mismatch: bool = False
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
        if self.operation_mismatch:
            return ERROR_OPERATION_MISMATCH, (
                "Las reglas recuperadas existen, pero ninguna ejecuta la "
                "operación que exige esta consulta (máscara/patrón posicional "
                "vs comparación, rango u otra familia). No se eligió «la más "
                "cercana»: el resultado queda indeterminado."
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
            "operation_mismatch": bool(self.operation_mismatch),
            "operation_compatibility": dict(self.operation_compatibility),
            "steps": list(self.steps),
            "premise_closure": (
                self.premise_closure.to_public_dict()
                if hasattr(self.premise_closure, "to_public_dict")
                else self.premise_closure
            ),
            "evidence_counters": dict(self.evidence_counters),
            "duration_ms": round(float(self.duration_ms or 0.0), 2),
        }


def _rules_for_grounding(retrieval: Any) -> list[Any]:
    """Reglas que pueden entrar al grounded engine.

    Con el gate aplicado solo entran compatibles (+ diferidas por capacidad
    incompleta: el merge distribuido/closure puede completarlas). Sin gate
    (dobles de test) se conserva el comportamiento histórico.
    """
    if retrieval is None:
        return []
    if bool(getattr(retrieval, "compatibility_applied", False)):
        compatible = list(getattr(retrieval, "compatible_rules", ()) or ())
        supported = [rule for rule in compatible if _is_supported(rule)]
        deferred = list(getattr(retrieval, "deferred_rules", ()) or ())
        if supported:
            return [*supported, *deferred]
        return [*compatible, *deferred]
    supported = list(getattr(retrieval, "supported_rules", ()) or ())
    if supported:
        return supported
    return list(getattr(retrieval, "candidate_rules", ()) or ())


def _is_supported(rule: Any) -> bool:
    try:
        return bool(getattr(rule, "supported", False))
    except Exception:  # noqa: BLE001
        return str(getattr(rule, "verification_state", "")) == "SUPPORTED"


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


def _has_deterministic_claim(grounded: Any) -> bool:
    """¿El grounded trae al menos un DerivedClaim determinista SUPPORTED?"""
    if grounded is None:
        return False
    derivations = getattr(grounded, "derivations", None)
    return any(
        bool(getattr(claim, "deterministic", False))
        and str(getattr(claim, "verification_status", "")) == "SUPPORTED"
        for claim in (getattr(derivations, "claims", ()) or ())
    )


class _ClosureEvidenceItem:
    """Evidencia recuperada -> item consumible por el grounded engine."""

    def __init__(self, hit: Any) -> None:
        self.content = str(getattr(hit, "content", "") or "")
        self.evidence_id = str(getattr(hit, "evidence_id", "") or "")
        self.source_id = str(getattr(hit, "source_id", "") or "")
        self.document_id = str(getattr(hit, "document_id", "") or "")
        self.page = getattr(hit, "page", None)
        self.section_path = tuple(getattr(hit, "section_path", ()) or ())
        self.metadata = {
            "document_id": self.document_id,
            "source_id": self.source_id,
            "page": self.page,
            "section_path": list(self.section_path),
            "evidence_id": self.evidence_id,
        }


def _evidence_identity(item: Any) -> str:
    metadata = getattr(item, "metadata", None)
    metadata = metadata if isinstance(metadata, dict) else {}
    for attribute in ("evidence_id", "chunk_id"):
        value = getattr(item, attribute, None) or metadata.get(attribute)
        if value:
            return str(value)
    return ""


def _scope_retrieval_args(
    authorized_scope: Any,
) -> tuple[Any, tuple[Any, ...], tuple[Any, ...]]:
    """(workspace_id, source_ids, document_ids) UUID para Rule Lane.

    Sin scope explícito devuelve vacíos: el caller conserva la herencia desde
    la evidencia (comportamiento histórico). Nunca amplía nada.
    """
    if authorized_scope is None:
        return None, (), ()
    if not bool(getattr(authorized_scope, "is_explicit", False)):
        return None, (), ()

    def _uuid(value: Any) -> Any:
        try:
            from uuid import UUID

            return UUID(str(value))
        except (TypeError, ValueError):
            return None

    workspace = _uuid(getattr(authorized_scope, "workspace_id", ""))
    sources = tuple(
        value
        for value in (
            _uuid(item) for item in getattr(authorized_scope, "source_ids", ()) or ()
        )
        if value is not None
    )
    documents = tuple(
        value
        for value in (
            _uuid(item) for item in getattr(authorized_scope, "document_ids", ()) or ()
        )
        if value is not None
    )
    return workspace, sources, documents


def _source_scope_for_closure(
    *,
    organization_id: Any,
    evidence_items: Sequence[Any],
    authorized_scope: Any = None,
) -> Any:
    """SourceScope de Premise Closure: autorizado ∩ evidencia, sin ampliar.

    Con scope explícito, las fuentes autorizadas mandan aunque no haya
    evidencia recuperada (fast path): la closure busca DENTRO de ellas, nunca
    en toda la organización.
    """
    from src.runtime.premise_closure import SourceScope

    documents: list[str] = []
    sources: list[str] = []
    for item in evidence_items or ():
        metadata = getattr(item, "metadata", None)
        metadata = metadata if isinstance(metadata, dict) else {}
        document = str(
            getattr(item, "document_id", None) or metadata.get("document_id") or ""
        )
        source = str(
            getattr(item, "source_id", None) or metadata.get("source_id") or ""
        )
        if document and document not in documents:
            documents.append(document)
        if source and source not in sources:
            sources.append(source)

    workspace = ""
    if authorized_scope is not None and bool(
        getattr(authorized_scope, "is_explicit", False)
    ):
        workspace = str(getattr(authorized_scope, "workspace_id", "") or "")
        allowed_sources = [
            str(value)
            for value in getattr(authorized_scope, "source_ids", ()) or ()
            if str(value or "").strip()
        ]
        allowed_documents = [
            str(value)
            for value in getattr(authorized_scope, "document_ids", ()) or ()
            if str(value or "").strip()
        ]
        if allowed_sources:
            sources = [value for value in sources if value in allowed_sources]
            if not sources:
                sources = list(allowed_sources)
        if allowed_documents:
            documents = [value for value in documents if value in allowed_documents]
            if not documents:
                documents = list(allowed_documents)
    return SourceScope(
        organization_id=str(organization_id),
        workspace_id=workspace,
        document_ids=tuple(documents[:12]),
        source_ids=tuple(sources[:12]),
    )


def _split_searchable_premises(
    premises: Sequence[str],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Separa premisas buscables (retrieval) de diagnósticos del compiler.

    `executable_semantics`, `rule:*` y similares NO son buscables: no deben
    disparar otra búsqueda documental inútil (§7). El cierre y el rule
    assembly los resuelven.
    """
    try:
        from src.runtime.premise_closure import _is_searchable_premise
    except Exception:  # noqa: BLE001 — sin motor, todo es diagnóstico
        return (), tuple(str(item) for item in premises)
    searchable: list[str] = []
    diagnostics: list[str] = []
    for premise in premises:
        text = str(premise or "")
        (searchable if _is_searchable_premise(text) else diagnostics).append(text)
    return tuple(searchable), tuple(diagnostics)


async def _run_premise_closure_stage(
    *,
    organization_id: Any,
    question: str,
    evidence_items: Sequence[Any],
    grounded: Any,
    rules: Sequence[Any],
    semantics: Any,
    rounds_left: int,
    evidence_search: Callable[..., Any] | None,
    reason_fn: Callable[..., Any] | None,
    authorized_scope: Any = None,
) -> tuple[Any, Any]:
    """Ejecuta premise closure si hay puerto disponible. Fail-soft total."""
    try:
        from src.runtime.premise_closure import (
            PremiseClosureRequest,
            PremiseEvaluation,
            normalize_premises,
            run_premise_closure,
        )
        from src.runtime.premise_search import (
            RuleIndexPremiseSearch,
            make_fabric_expander,
            make_source_local_expander,
        )
        from src.runtime.query_local_rules import compile_query_local_rules
    except Exception as exc:  # noqa: BLE001 — sin motor no hay fase
        logger.warning("premise closure unavailable", error=str(exc)[:160])
        return None, grounded, {}

    missing = normalize_premises(getattr(grounded, "missing_premises", ()) or ())

    runtime_pattern = ""
    for pattern in getattr(semantics, "runtime_patterns", ()) or ():
        value = str(getattr(pattern, "value", "") or "")
        if value:
            runtime_pattern = value
            break
    domain_entities = tuple(
        str(getattr(obj, "value", "") or "")
        for obj in (getattr(semantics, "objects", ()) or ())
        if str(getattr(obj, "semantic_role", "")) == "DOMAIN_ENTITY"
    )
    field_context = tuple(
        str(getattr(obj, "value", "") or "")
        for obj in (getattr(semantics, "field_requirements", ()) or ())
    )

    source_scope = _source_scope_for_closure(
        organization_id=organization_id,
        evidence_items=evidence_items,
        authorized_scope=authorized_scope,
    )
    document_ids = list(source_scope.document_ids)
    source_ids = list(source_scope.source_ids)
    seen_evidence: list[str] = []
    for item in evidence_items:
        identity = _evidence_identity(item)
        if identity:
            seen_evidence.append(identity)
    document_id = document_ids[0] if document_ids else ""

    # Compilación provisional de la evidencia YA recuperada: si la ingesta no
    # compiló la premisa, la consulta no queda inútil. Corre SIEMPRE (con o sin
    # closure): una consulta ejecutable con evidencia suficiente no debe quedar
    # UNDETERMINED solo porque no había premisas "faltantes" que buscar.
    local_stats: dict[str, Any] = {"runs": 0, "candidates": 0, "supported": 0, "executable": 0}
    initial_local = compile_query_local_rules(
        evidence_items,
        document_id=document_id,
        document_title=str(getattr(grounded, "document_title", "") or ""),
        organization_id=str(organization_id),
    )
    local_stats["runs"] += 1
    local_stats["candidates"] += int(initial_local.candidates or 0)
    local_stats["supported"] += int(initial_local.supported or 0)
    local_stats["executable"] += int(initial_local.executable or 0)

    # 1) Si la evidencia ya contiene gramática query-local, evaluarla PRIMERO:
    #    las reglas persistidas pueden ser no ejecutables (kind=EXAMPLE) y el
    #    missing REAL de esa evaluación (p.ej. length_semantics) es el que la
    #    closure dirigida debe buscar. El diagnóstico `rule:*` no es buscable.
    if initial_local.rules:
        try:
            reground = reason_fn
            if reground is None:
                from src.intelligence.reasoning.grounded_engine import (
                    reason_over_evidence,
                )

                reground = reason_over_evidence
            regrounded = reground(
                question=question,
                evidence_items=list(evidence_items),
                canonical_rules=list(initial_local.rules),
            )
            if _has_deterministic_claim(regrounded):
                return None, regrounded, local_stats
            regrounded_missing = normalize_premises(
                getattr(regrounded, "missing_premises", ()) or ()
            )
            if not regrounded_missing or rounds_left <= 0:
                return None, regrounded, local_stats
            grounded = regrounded
            missing = regrounded_missing
        except Exception as exc:  # noqa: BLE001 — fail-soft
            logger.warning("query-local authority failed", error=str(exc)[:160])
            if not missing or rounds_left <= 0:
                return None, grounded, local_stats
    elif not missing or rounds_left <= 0:
        return None, grounded, local_stats

    # La cobertura estructural NO debe contar reglas de ingesta que no deciden
    # (PARTIALLY_SUPPORTED / missing premises): si cubrieran, la closure se
    # declararía satisfecha sin buscar la evidencia y el caso quedaría
    # UNDETERMINED. Solo las decisorias cubren premisas.
    decisive = [
        rule
        for rule in rules
        if str(getattr(rule, "verification_state", "")) == "SUPPORTED"
        and not getattr(rule, "missing_premises", None)
    ]
    candidates = [*decisive, *initial_local.rules]

    request = PremiseClosureRequest(
        original_query=question,
        canonical_rule_candidates=tuple(candidates),
        missing_premises=missing,
        runtime_pattern=runtime_pattern,
        domain_entities=domain_entities,
        field_context=field_context,
        source_scope=source_scope,
        already_seen_evidence=tuple(seen_evidence),
        already_seen_rule_ids=tuple(
            str(getattr(rule, "rule_id", "") or "") for rule in candidates
        ),
        rounds_left=max(1, min(int(rounds_left), 4)),
    )

    final_grounded: dict[str, Any] = {"value": grounded}

    def _decisive_pass(items: Sequence[Any], rules_list: Sequence[Any]) -> Any | None:
        """Pass decisivo: la mejor regla query-local COMPATIBLE y EJECUTABLE decide.

        El re-merge global del engine puede contaminar una regla autocontenida
        con reglas ruidosas de otras secciones. Si una regla query-local ya
        ejecutable declara los símbolos del patrón, se evalúa SOLA y su claim
        determinista manda. Prioridad: capacidad exacta de operación > símbolos
        ejecutables > gramática ejecutable > verificada > provenance > léxico.
        Una regla incompatible NO entra al pass decisivo (jamás «la más cercana»).
        """
        try:
            from src.runtime.operation_compatibility import (
                FAMILY_MATCHING,
                derive_query_operation_requirements,
                evaluate_operation_compatibility,
            )
            from src.runtime.query_local_rules import rules_are_query_local

            requirements = derive_query_operation_requirements(
                question=question,
                semantics=semantics,
                runtime_patterns=(runtime_pattern,) if runtime_pattern else (),
            )
            if not requirements.symbols:
                # El pass decisivo aplica a patrones/máscaras aplicados a valores.
                return None
            decisive: list[tuple[tuple[int, ...], Any]] = []
            for rule in rules_list or ():
                if not rules_are_query_local([rule]):
                    continue
                if not getattr(rule, "executable", False):
                    continue
                compatibility = evaluate_operation_compatibility(
                    rule, requirements
                )
                if not compatibility.compatible:
                    continue
                if requirements.operation_family != FAMILY_MATCHING:
                    continue
                # Una regla sin la definición de los símbolos del patrón no puede
                # decidir el match: jamás un NO_MATCH incidental sin semántica.
                if not (
                    compatibility.symbol_executable
                    or compatibility.symbol_defined
                ):
                    continue
                properties = getattr(rule, "properties", {}) or {}
                operator_prop = properties.get("matching.operator")
                operator = (
                    str(getattr(operator_prop, "value", "") or "").upper()
                    if operator_prop is not None
                    else ""
                )
                capability_rank = (
                    1 if compatibility.symbol_executable else 0,
                    1 if operator in _MASK_MATCH_OPERATORS else 0,
                    1 if operator else 0,
                    1 if getattr(rule, "supported", False) else 0,
                    1 if getattr(rule, "provenance", ()) else 0,
                    len(properties),
                )
                decisive.append((capability_rank, rule))
            if not decisive:
                return None

            reason = reason_fn
            if reason is None:
                from src.intelligence.reasoning.grounded_engine import (
                    reason_over_evidence,
                )

                reason = reason_over_evidence
            # La mejor regla por score puede no poder decidir (p.ej. un modo de
            # matching que exige datos ausentes). Se prueban en orden: la
            # primera que produzca un claim determinista SUPPORTED manda.
            ordered = sorted(
                decisive,
                key=lambda item: (
                    item[0],
                    str(getattr(item[1], "rule_id", "") or ""),
                ),
                reverse=True,
            )
            for _rank, best in ordered:
                grounded_now = reason(
                    question=question,
                    evidence_items=list(items),
                    canonical_rules=[best],
                )
                claims_now = list(getattr(grounded_now.derivations, "claims", ()) or ())
                if any(
                    bool(getattr(claim, "deterministic", False))
                    and str(getattr(claim, "verification_status", "")) == "SUPPORTED"
                    for claim in claims_now
                ):
                    return grounded_now
        except Exception:  # noqa: BLE001 — pass decisivo fail-soft
            return None
        return None

    async def _evaluate(closure_rules: Sequence[Any], hits: Sequence[Any]) -> Any:
        items = [*evidence_items, *[_ClosureEvidenceItem(hit) for hit in hits]]
        reason = reason_fn
        if reason is None:
            from src.intelligence.reasoning.grounded_engine import reason_over_evidence

            reason = reason_over_evidence
        try:
            grounded_now = reason(
                question=question,
                evidence_items=items,
                canonical_rules=list(closure_rules) or None,
            )
        except Exception as exc:  # noqa: BLE001 — evaluación fail-soft
            logger.warning("premise closure evaluation failed", error=str(exc)[:160])
            return PremiseEvaluation(missing_premises=missing, conflicts=())
        decisive_grounded = _decisive_pass(items, list(closure_rules))
        if decisive_grounded is not None:
            grounded_now = decisive_grounded
        final_grounded["value"] = grounded_now
        derivations = getattr(grounded_now, "derivations", None)
        return PremiseEvaluation(
            missing_premises=tuple(
                str(item) for item in (getattr(grounded_now, "missing_premises", ()) or ())
            ),
            conflicts=tuple(
                str(item) for item in (getattr(grounded_now, "conflicts", ()) or ())
            ),
            claims=tuple(getattr(derivations, "claims", ()) or ()),
            canonical_rules=tuple(
                getattr(grounded_now, "canonical_rules", ()) or closure_rules
            ),
        )

    def _compile_new(hits: Sequence[Any], _request: Any) -> list[Any]:
        # Compila TODA la evidencia acumulada + la nueva (deduplicada por
        # identity): la regla provisional no depende de qué ronda trajo cada
        # pieza y no se pierde evidencia de rondas anteriores (§8).
        deduped: list[Any] = []
        seen_ids: set[str] = set()
        for hit in hits:
            identity = str(getattr(hit, "identity", "") or "")
            if not identity:
                identity = _evidence_identity(hit)
            if identity and identity in seen_ids:
                continue
            if identity:
                seen_ids.add(identity)
            deduped.append(hit)
        compilation = compile_query_local_rules(
            [*evidence_items, *deduped],
            document_id=document_id,
            organization_id=str(organization_id),
        )
        local_stats["runs"] += 1
        local_stats["candidates"] += int(compilation.candidates or 0)
        local_stats["supported"] += int(compilation.supported or 0)
        local_stats["executable"] += int(compilation.executable or 0)
        return compilation.rules

    source_local = make_source_local_expander(organization_id)
    fabric = make_fabric_expander(organization_id)

    async def _expand(closure_rules: Sequence[Any], closure_request: Any) -> list[Any]:
        expanded = list(await source_local(closure_rules, closure_request))
        expanded.extend(await fabric(closure_rules, closure_request))
        return expanded

    async def _evidence_search(query: str, scope: Any, limit: int) -> list[Any]:
        if evidence_search is None:
            return []
        return list(await evidence_search(query, scope, limit))

    try:
        from src.runtime.rule_retrieval import PostgresRuleIndex

        search_port = RuleIndexPremiseSearch(
            index=PostgresRuleIndex(),
            organization_id=organization_id,
            evidence_search=_evidence_search if evidence_search is not None else None,
            operation_intent=str(getattr(semantics, "intent", "") or ""),
        )
        closure = await run_premise_closure(
            request,
            search=search_port,
            evaluate=_evaluate,
            expand=_expand,
            compile_evidence=_compile_new,
        )
    except Exception as exc:  # noqa: BLE001 — la fase jamás rompe el run
        logger.warning("premise closure stage failed", error=str(exc)[:200])
        return None, grounded, local_stats

    if closure is None:
        return None, grounded, local_stats
    return closure, final_grounded["value"], local_stats


async def prepare_derived_authority(
    *,
    organization_id: Any,
    question: str,
    evidence_items: Sequence[Any] = (),
    semantics: Any = None,
    retrieval_fn: Callable[..., Any] | None = None,
    reason_fn: Callable[..., Any] | None = None,
    envelope_fn: Callable[..., Any] | None = None,
    enable_premise_closure: bool = False,
    premise_evidence_search: Callable[..., Any] | None = None,
    premise_retriever_status: dict[str, Any] | None = None,
    premise_closure_rounds: int = 2,
    authorized_scope: Any = None,
) -> DerivedPreparationResult:
    """Ejecuta la cadena determinista por FASES con telemetría fail-closed.

    Cada fase emite su step ANTES de la siguiente. Un fallo posterior jamás
    borra la telemetría anterior (rule_retrieval sobrevive a grounding).

    `authorized_scope` (AuthorizedKnowledgeScope) restringe Rule Lane y Premise
    Closure a las fuentes/KB autorizadas del agente: el fast path corre antes
    del retrieval principal y no puede ampliar el universo en silencio.
    """
    started = time.perf_counter()
    text_question = str(question or "")
    sem = semantics if semantics is not None and not isinstance(semantics, str) else None
    prep = DerivedPreparationResult(question=text_question)
    prep.requires_deterministic_decision = requires_deterministic_decision(
        sem if sem is not None else text_question
    )
    try:
        from src.runtime.runtime_identity import runtime_identity

        prep.steps.append(stage_step("runtime_identity", "ok", **runtime_identity()))
    except Exception:  # noqa: BLE001 — la identidad nunca rompe el run
        pass

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
    scope_workspace, scope_sources, scope_documents = _scope_retrieval_args(
        authorized_scope
    )
    try:
        retrieve = retrieval_fn
        if retrieve is None:
            from src.runtime.rule_retrieval import retrieve_canonical_rules

            retrieve = retrieve_canonical_rules
        retrieval = await retrieve(
            organization_id,
            text_question,
            evidence_items=list(evidence_items),
            workspace_id=scope_workspace,
            source_ids=scope_sources,
            document_ids=scope_documents,
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
        # P0.2: provenance de las candidatas (fuente, documento, páginas) para
        # «Ver flujo». No sólo el conteo.
        try:
            from src.runtime.authorized_scope import rule_provenance

            step["rules"] = [
                rule_provenance(rule) for rule in supported[:6]
            ] or [rule_provenance(rule) for rule in candidates[:6]]
        except Exception:  # noqa: BLE001 — la provenance no rompe el retrieval
            pass
        if operational_failure:
            step["error_code"] = ERROR_RULE_RETRIEVAL_UNAVAILABLE
        if not supported:
            to_public = getattr(retrieval, "to_public_dict", None)
            if callable(to_public):
                public = to_public() or {}
                step["why_no_rule"] = list(public.get("why_no_rule") or [])[:4]
        prep.steps.append(step)

        # Gate OPERACIÓN↔QUERY: telemetría del score ANTES y DESPUÉS del gate.
        compatibility = dict(
            getattr(retrieval, "operation_compatibility", {}) or {}
        )
        if compatibility:
            prep.operation_compatibility = compatibility
            compatible_count = int(compatibility.get("compatible") or 0)
            rejected_count = int(compatibility.get("rejected") or 0)
            mismatch = bool(
                compatibility.get("applied")
                and compatible_count == 0
                and rejected_count > 0
            ) or "operation_mismatch" in reasons
            if mismatch:
                prep.operation_mismatch = True
            prep.steps.append(
                stage_step(
                    STAGE_OPERATION_COMPATIBILITY,
                    "warn" if mismatch else "ok",
                    query_operation=compatibility.get("query_operation"),
                    expected_operations=compatibility.get("expected_operations"),
                    candidates=compatibility.get("candidates"),
                    compatible=compatible_count,
                    rejected=rejected_count,
                    top_rejected_reasons=compatibility.get("top_rejected_reasons"),
                    winner_rule_id=compatibility.get("winner_rule_id"),
                    scores=compatibility.get("scores"),
                )
            )

    rules = _rules_for_grounding(retrieval)
    # P0.2/P0.3: provenance de la regla candidata DENTRO del scope autorizado y
    # sin mezclar reingestas. La exclusión es auditable en `scope_filter`.
    if authorized_scope is not None:
        from src.runtime.authorized_scope import filter_rules_for_scope

        prep.authorized_scope = (
            authorized_scope.to_public_dict()
            if hasattr(authorized_scope, "to_public_dict")
            else {}
        )
        kept_rules, excluded_rules = filter_rules_for_scope(rules, authorized_scope)
        if excluded_rules:
            prep.scope_excluded_rules = list(excluded_rules)
            prep.steps.append(
                stage_step(
                    "scope_filter",
                    "warn",
                    excluded=len(excluded_rules),
                    kept=len(kept_rules),
                    rules=excluded_rules[:8],
                )
            )
        rules = kept_rules

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

    # --- PREMISE CLOSURE: retrieval dirigido por premisas faltantes ----------
    # JEV/answer gate decide "necesitamos más"; ESTA fase decide exactamente
    # qué buscar. No repite la búsqueda semántica de la pregunta original.
    if enable_premise_closure and prep.requires_deterministic_decision and premisas:
        health = dict(premise_retriever_status or {})
        if premise_evidence_search is None:
            # Sin retriever NO se puede afirmar que la fuente carezca de la
            # premisa: el diagnóstico es operacional, no documental.
            health.setdefault("available", False)
            health.setdefault("error_code", "PREMISE_RETRIEVER_FACTORY_FAILED")
            prep.steps.append(
                stage_step("premise_retriever_health", "error", **health)
            )
            prep.status = "degraded"
            prep.error_stage = "premise_retrieval"
            prep.error_code = "PREMISE_RETRIEVER_UNAVAILABLE"
            prep.error_message = (
                "No se pudo completar la búsqueda de premisas: el retriever de "
                "evidencia no está disponible. No se comprobó que la fuente "
                "carezca de la premisa."
            )
        else:
            health.setdefault("available", True)
            prep.steps.append(
                stage_step("premise_retriever_health", "ok", **health)
            )
    if (
        enable_premise_closure
        and prep.requires_deterministic_decision
        and premisas
        and prep.grounded_reasoning is not None
        and premise_evidence_search is not None
    ):
        closure, grounded_final, local_stats = await _run_premise_closure_stage(
            organization_id=organization_id,
            question=text_question,
            evidence_items=list(evidence_items),
            grounded=prep.grounded_reasoning,
            rules=rules,
            semantics=sem,
            rounds_left=max(0, int(premise_closure_rounds)),
            evidence_search=premise_evidence_search,
            reason_fn=reason_fn,
            authorized_scope=authorized_scope,
        )
        if closure is not None:
            prep.premise_closure = closure
            searchable_missing, diagnostics = _split_searchable_premises(premisas)
            prep.steps.append(
                stage_step(
                    STAGE_REQUIREMENT_GRAPH,
                    "warn" if premisas else "ok",
                    missing_premises=list(premisas[:12]),
                    searchable_missing=list(searchable_missing[:12]),
                    non_searchable_diagnostics=list(diagnostics[:12]),
                    canonical_rules=len(list(getattr(prep.rule_retrieval, "supported_rules", ()) or ())),
                )
            )
            prep.steps.append(
                stage_step(
                    STAGE_PREMISE_CLOSURE,
                    "ok" if closure.satisfied else "warn",
                    termination=closure.termination,
                    rounds=len(closure.rounds),
                    information_gain=closure.total_information_gain,
                    missing_before=list(closure.missing_before[:12]),
                    missing_after=list(closure.missing_after[:12]),
                    compilation_gaps=len(closure.compilation_gaps),
                    rules_added=len(closure.rules),
                    evidence_added=len(closure.evidence),
                    detail=closure.to_public_dict(),
                )
            )
            if grounded_final is not None:
                prep.grounded_reasoning = grounded_final
                grounded = grounded_final
                derivations = getattr(grounded_final, "derivations", None)
                claims = list(getattr(derivations, "claims", ()) or ())
                deterministic_claims = [
                    claim
                    for claim in claims
                    if bool(getattr(claim, "deterministic", False))
                    and str(getattr(claim, "verification_status", "")) == "SUPPORTED"
                ]
                premisas = tuple(
                    str(item)
                    for item in (getattr(grounded_final, "missing_premises", ()) or ())
                )
                conflicts = tuple(
                    str(item)
                    for item in (getattr(grounded_final, "conflicts", ()) or ())
                )
                prep.derived_claims = claims
                prep.missing_premises = premisas
                prep.conflicts = conflicts
                credible = [
                    evaluation
                    for evaluation in (
                        getattr(grounded_final, "rule_evaluations", ()) or ()
                    )
                    if str(getattr(evaluation, "status", "") or "")
                    in ("MATCH", "NO_MATCH")
                ]
            # Contadores de evidencia: una evidencia usada para CERRAR una
            # premisa cuenta como used_for_reasoning aunque la respuesta final
            # (p. ej. abstención) no la cite.
            unique_initial = {
                _evidence_identity(item)
                for item in evidence_items
                if _evidence_identity(item)
            }
            decision_refs = {
                str(ref)
                for claim in deterministic_claims
                for ref in (getattr(claim, "evidence_refs", ()) or ())
                if ref
            }
            prep.evidence_counters = {
                "retrieved": len(evidence_items),
                "unique": len(unique_initial),
                "used_for_reasoning": len(unique_initial) + len(closure.evidence),
                "used_for_decision": len(decision_refs),
            }
        elif grounded_final is not None and grounded_final is not prep.grounded_reasoning:
            # Query-local compilation decidió sin closure (no había premisas
            # buscables): la regla local re-evaluó la evidencia recuperada y
            # debe reemplazar al grounding previo.
            prep.grounded_reasoning = grounded_final
            grounded = grounded_final
            derivations = getattr(grounded_final, "derivations", None)
            claims = list(getattr(derivations, "claims", ()) or ())
            deterministic_claims = [
                claim
                for claim in claims
                if bool(getattr(claim, "deterministic", False))
                and str(getattr(claim, "verification_status", "")) == "SUPPORTED"
            ]
            premisas = tuple(
                str(item)
                for item in (getattr(grounded_final, "missing_premises", ()) or ())
            )
            conflicts = tuple(
                str(item)
                for item in (getattr(grounded_final, "conflicts", ()) or ())
            )
            prep.derived_claims = claims
            prep.missing_premises = premisas
            prep.conflicts = conflicts
            searchable_missing, diagnostics = _split_searchable_premises(premisas)
            prep.steps.append(
                stage_step(
                    STAGE_REQUIREMENT_GRAPH,
                    "ok" if not searchable_missing else "warn",
                    missing_premises=list(premisas[:12]),
                    searchable_missing=list(searchable_missing[:12]),
                    non_searchable_diagnostics=list(diagnostics[:12]),
                )
            )
        prep.steps.append(
            stage_step(
                "query_local_compilation",
                "ok" if local_stats.get("executable") else "warn",
                runs=local_stats.get("runs", 0),
                candidates=local_stats.get("candidates", 0),
                supported=local_stats.get("supported", 0),
                executable=local_stats.get("executable", 0),
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
    "ERROR_OPERATION_MISMATCH",
    "ERROR_GROUNDING_ENGINE_FAILED",
    "ERROR_RULE_EVALUATION_FAILED",
    "ERROR_RULE_RETRIEVAL_UNAVAILABLE",
    "ERROR_UNDETERMINED_RULE",
    "STAGE_DECISION_ENVELOPE",
    "STAGE_DERIVATION",
    "STAGE_GROUNDING",
    "STAGE_OPERATION_COMPATIBILITY",
    "STAGE_PREMISE_CLOSURE",
    "STAGE_QUERY_SEMANTICS",
    "STAGE_REQUIREMENT_GRAPH",
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
