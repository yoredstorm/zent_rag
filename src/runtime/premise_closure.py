# =============================================================================
# Premise Closure — retrieval dirigido por premisas faltantes
# =============================================================================
# PROBLEMA QUE RESUELVE
#
# Cuando el Requirement Graph sabe EXACTAMENTE qué premisas faltan
# (`definition:symbol:&`, `matching:positional`, `matching:literal`,
# `length_policy`), una segunda búsqueda semántica de la pregunta original es
# ruido: repite la misma distribución y no cierra nada.
#
# Este módulo convierte `missing_premises` en un plan de consultas pequeñas,
# busca por premisa (exacto/simbólico ANTES de dense), expande el grafo de
# reglas conocido, prioriza la localidad de la fuente y mide gain real por
# ronda. Si una ronda no cierra ninguna premisa, termina: no hay loops ciegos.
#
# SEPARACIÓN DE RESPONSABILIDADES
#
#   JEV / answer gate   -> "necesitamos más" (decisión)
#   Premise Closure     -> "exactamente qué necesitamos buscar" (contenido)
#
# DOMAIN-AGNOSTIC: la ontología de consulta es lingüística (posición, literal,
# longitud, definición de símbolo). No contiene vocabulario de ningún manual.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Iterable, Protocol, Sequence

from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)

PREMISE_CLOSURE_VERSION = "premise-closure-1"

# --- Claves canónicas de premisa -------------------------------------------
PREMISE_SYMBOL_PREFIX = "definition:symbol:"
PREMISE_MATCHING_POSITIONAL = "matching:positional"
PREMISE_MATCHING_LITERAL = "matching:literal"
PREMISE_LENGTH_POLICY = "length_policy"
PREMISE_DEFINITION_UNKNOWN = "definition:unknown"

#: Terminación explícita del loop.
TERMINATION_SATISFIED = "SATISFIED"
TERMINATION_CONFLICTING = "CONFLICTING"
TERMINATION_NO_INFORMATION_GAIN = "NO_INFORMATION_GAIN"
TERMINATION_BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
TERMINATION_NO_SEARCH = "NO_SEARCH_PORT"

#: Carriles en orden de prioridad: exacto/lexical antes que dense.
LANE_EXACT = "exact"
LANE_LEXICAL = "lexical"
LANE_RULE_INDEX = "rule_index"
LANE_SYMBOL = "symbol"
LANE_DENSE = "dense"

# -----------------------------------------------------------------------------
# Normalización de premisas
# -----------------------------------------------------------------------------
# El vocabulario viene de fuentes distintas (grounded engine, rule evaluation,
# query semantics). Se normaliza a claves canónicas para planificar sin repetir
# la misma búsqueda con tres nombres.

_PREMISE_ALIASES: dict[str, str] = {
    "matching_policy": PREMISE_MATCHING_POSITIONAL,
    "matching.operator": PREMISE_MATCHING_POSITIONAL,
    "matching_semantics": PREMISE_MATCHING_POSITIONAL,
    "positional_semantics": PREMISE_MATCHING_POSITIONAL,
    "matching:positional": PREMISE_MATCHING_POSITIONAL,
    "literal_semantics": PREMISE_MATCHING_LITERAL,
    "matching.literal": PREMISE_MATCHING_LITERAL,
    "matching.fixed_position": PREMISE_MATCHING_LITERAL,
    "matching:literal": PREMISE_MATCHING_LITERAL,
    "length_semantics": PREMISE_LENGTH_POLICY,
    "length.policy": PREMISE_LENGTH_POLICY,
    "length_policy": PREMISE_LENGTH_POLICY,
    "length_policy:unknown": PREMISE_LENGTH_POLICY,
    "operand:value": "input:value",
    "operand:pattern": "input:pattern",
    "input:pattern": "input:pattern",
    "input:value": "input:value",
}


def normalize_premise(premise: str) -> str:
    """Premisa cruda -> clave canónica (símbolo con identidad preservada)."""
    text = str(premise or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    if lowered.startswith(PREMISE_SYMBOL_PREFIX):
        symbol = text[len(PREMISE_SYMBOL_PREFIX) :].strip()
        return f"{PREMISE_SYMBOL_PREFIX}{symbol}" if symbol else PREMISE_DEFINITION_UNKNOWN
    if lowered.startswith("symbol:"):
        symbol = text.split(":", 1)[1].strip()
        return f"{PREMISE_SYMBOL_PREFIX}{symbol}" if symbol else PREMISE_DEFINITION_UNKNOWN
    if lowered.startswith("definition:"):
        return lowered
    if lowered.startswith("rule:") or lowered.startswith("no_rule_valid_at:"):
        # Diagnóstico de regla ausente: NO es una premisa buscable por sí misma.
        return ""
    return _PREMISE_ALIASES.get(lowered, lowered)


def normalize_premises(premises: Iterable[str]) -> tuple[str, ...]:
    """Normaliza, deduplica y ordena por prioridad de resolución."""
    normalized: list[str] = []
    for premise in premises or ():
        key = normalize_premise(premise)
        if key and key not in normalized:
            normalized.append(key)
    return tuple(sorted(normalized, key=_premise_priority))


def _premise_priority(premise: str) -> tuple[int, str]:
    if premise.startswith(PREMISE_SYMBOL_PREFIX):
        return (0, premise)
    return (
        {
            PREMISE_MATCHING_POSITIONAL: 1,
            PREMISE_MATCHING_LITERAL: 2,
            PREMISE_LENGTH_POLICY: 3,
        }.get(premise, 4),
        premise,
    )


def symbol_from_premise(premise: str) -> str:
    text = str(premise or "")
    if text.startswith(PREMISE_SYMBOL_PREFIX):
        return text[len(PREMISE_SYMBOL_PREFIX) :]
    return ""


# -----------------------------------------------------------------------------
# Ontología de consulta por tipo de premisa (lingüística, genérica)
# -----------------------------------------------------------------------------
# Términos intencionalmente generales. PROHIBIDO meter vocabulario de dominio
# (ATPCO/FCLAS/Record 2/Fare Basis); un test lo verifica.

_PREMISE_ONTOLOGY: dict[str, tuple[str, ...]] = {
    PREMISE_MATCHING_POSITIONAL: (
        "position",
        "positional",
        "same position",
        "left to right",
        "ordered comparison",
        "by position",
        "positionally match",
        "posición",
        "posicional",
        "misma posición",
        "de izquierda a derecha",
    ),
    PREMISE_MATCHING_LITERAL: (
        "literal",
        "exact character",
        "fixed position",
        "exact match",
        "literal character",
        "specified character",
        "carácter literal",
        "coincidencia exacta",
        "carácter fijo",
        "misma posición exacta",
    ),
    PREMISE_LENGTH_POLICY: (
        "length",
        "number of characters",
        "additional characters",
        "extra characters",
        "longer",
        "shorter",
        "exact length",
        "minimum length",
        "maximum length",
        "trailing",
        "remaining characters",
        "may follow",
        "longitud",
        "número de caracteres",
        "caracteres adicionales",
        "caracteres extra",
        "más largo",
        "más corto",
        "longitud exacta",
        "longitud mínima",
        "longitud máxima",
        "caracteres restantes",
        "pueden seguir",
    ),
}

#: Verbos de definición genéricos (ES/EN) para `definition:symbol:X`.
_DEFINITION_VERBS: tuple[str, ...] = (
    "definition",
    "defined as",
    "means",
    "represents",
    "stands for",
    "indicates",
    "matches",
    "used to indicate",
    "used to represent",
    "definición",
    "significa",
    "representa",
    "indica",
    "se usa para",
)


def premise_ontology(premise: str) -> tuple[str, ...]:
    """Conceptos de búsqueda generales para una premisa."""
    key = normalize_premise(premise)
    if key.startswith(PREMISE_SYMBOL_PREFIX):
        return _DEFINITION_VERBS
    return _PREMISE_ONTOLOGY.get(key, ())


# -----------------------------------------------------------------------------
# Request / plan / resultados
# -----------------------------------------------------------------------------


@dataclass(kw_only=True)
class SourceScope:
    """Alcance de fuente del retrieval (vacío = sin scope)."""

    organization_id: str = ""
    workspace_id: str = ""
    document_ids: tuple[str, ...] = ()
    source_ids: tuple[str, ...] = ()
    document_id: str = ""
    section_path: tuple[str, ...] = ()

    def focused(self, *, document_id: str, section_path: Sequence[str] = ()) -> "SourceScope":
        return SourceScope(
            organization_id=self.organization_id,
            workspace_id=self.workspace_id,
            document_ids=tuple(dict.fromkeys([document_id, *self.document_ids])),
            source_ids=self.source_ids,
            document_id=document_id,
            section_path=tuple(section_path),
        )


@dataclass(kw_only=True)
class PremiseClosureRequest:
    """Driver de retrieval: la pregunta original ya NO decide las rondas."""

    original_query: str
    canonical_rule_candidates: tuple[Any, ...] = ()
    missing_premises: tuple[str, ...] = ()
    runtime_pattern: str = ""
    domain_entities: tuple[str, ...] = ()
    field_context: tuple[str, ...] = ()
    source_scope: SourceScope = field(default_factory=SourceScope)
    already_seen_evidence: tuple[str, ...] = ()
    already_seen_rule_ids: tuple[str, ...] = ()
    rounds_left: int = 2
    max_queries_per_round: int = 6
    max_queries_per_premise: int = 3
    max_new_evidence_per_round: int = 24
    max_new_rules_per_round: int = 24

    def normalized_missing(self) -> tuple[str, ...]:
        return normalize_premises(self.missing_premises)


@dataclass(frozen=True, kw_only=True)
class PlannedPremiseQuery:
    """Consulta pequeña y determinista para UNA premisa."""

    premise: str
    query: str
    lane: str = LANE_LEXICAL
    terms: tuple[str, ...] = ()
    symbol: str = ""

    def to_public_dict(self) -> dict:
        return {
            "premise": self.premise,
            "query": self.query[:240],
            "lane": self.lane,
            "terms": list(self.terms[:8]),
            "symbol": self.symbol,
        }


@dataclass(kw_only=True)
class EvidenceHit:
    """Evidencia nueva recuperada (chunk/unit), con su procedencia."""

    evidence_id: str = ""
    content: str = ""
    document_id: str = ""
    source_id: str = ""
    page: int | None = None
    section_path: tuple[str, ...] = ()
    score: float = 0.0
    matched_premises: tuple[str, ...] = ()
    lane: str = ""

    @property
    def identity(self) -> str:
        return self.evidence_id or str(hash(self.content[:400]))


@dataclass(kw_only=True)
class PremiseSearchOutcome:
    """Resultado de UNA ronda de búsqueda dirigida."""

    rules: tuple[Any, ...] = ()
    evidence: tuple[EvidenceHit, ...] = ()
    queries: tuple[PlannedPremiseQuery, ...] = ()
    exact_symbol_hits: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


@dataclass(kw_only=True)
class PremiseEvaluation:
    """Estado del Requirement Graph después de evaluar reglas + evidencia."""

    missing_premises: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    claims: tuple[Any, ...] = ()
    canonical_rules: tuple[Any, ...] = ()

    @property
    def satisfied(self) -> bool:
        return not self.missing_premises and not self.conflicts


@dataclass(kw_only=True)
class CompilationGap:
    """La evidencia contiene la premisa pero no existe regla equivalente."""

    premise: str
    evidence_ref: str
    excerpt: str = ""
    expected_semantic_dimension: str = ""
    compiler_version: str = ""
    document_id: str = ""
    page: int | None = None
    section_path: tuple[str, ...] = ()

    def to_public_dict(self) -> dict:
        return {
            "premise": self.premise,
            "evidence_ref": self.evidence_ref,
            "excerpt": self.excerpt[:240],
            "expected_semantic_dimension": self.expected_semantic_dimension,
            "compiler_version": self.compiler_version,
            "document_id": self.document_id,
            "page": self.page,
            "section_path": list(self.section_path[:6]),
        }


@dataclass(kw_only=True)
class RuleCompilerMissedEvidence:
    """Señal de calidad para el compiler (backfill/recompilación)."""

    semantic_dimension: str
    document_id: str = ""
    source_id: str = ""
    page: int | None = None
    section_path: tuple[str, ...] = ()
    semantic_unit: str = ""
    evidence_ref: str = ""
    frequency: int = 1
    compiler_version: str = ""

    def to_public_dict(self) -> dict:
        return {
            "semantic_dimension": self.semantic_dimension,
            "document_id": self.document_id,
            "source_id": self.source_id,
            "page": self.page,
            "section_path": list(self.section_path[:6]),
            "semantic_unit": self.semantic_unit[:240],
            "evidence_ref": self.evidence_ref,
            "frequency": int(self.frequency),
            "compiler_version": self.compiler_version,
        }


@dataclass(kw_only=True)
class PremiseClosureRound:
    """Cada ronda con su ganancia REAL (no intención de buscar)."""

    index: int
    missing_before: tuple[str, ...]
    missing_after: tuple[str, ...]
    premises_closed: tuple[str, ...] = ()
    queries: tuple[PlannedPremiseQuery, ...] = ()
    new_rule_ids: tuple[str, ...] = ()
    new_evidence_refs: tuple[str, ...] = ()
    new_semantic_dimensions: tuple[str, ...] = ()
    information_gain: int = 0
    stop_reason: str = ""

    def to_public_dict(self) -> dict:
        return {
            "round": self.index,
            "missing_before": list(self.missing_before[:12]),
            "missing_after": list(self.missing_after[:12]),
            "premises_closed": list(self.premises_closed[:12]),
            "queries": [query.to_public_dict() for query in self.queries],
            "new_rule_ids": list(self.new_rule_ids[:12]),
            "new_evidence_refs": list(self.new_evidence_refs[:12]),
            "new_semantic_dimensions": list(self.new_semantic_dimensions[:12]),
            "information_gain": int(self.information_gain),
            "stop_reason": self.stop_reason,
        }


@dataclass(kw_only=True)
class PremiseClosureResult:
    """Salida completa y auditable del loop."""

    termination: str = TERMINATION_NO_INFORMATION_GAIN
    rounds: list[PremiseClosureRound] = field(default_factory=list)
    missing_before: tuple[str, ...] = ()
    missing_after: tuple[str, ...] = ()
    rules: tuple[Any, ...] = ()
    evidence: tuple[EvidenceHit, ...] = ()
    compilation_gaps: list[CompilationGap] = field(default_factory=list)
    feedback: list[RuleCompilerMissedEvidence] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    version: str = PREMISE_CLOSURE_VERSION

    @property
    def satisfied(self) -> bool:
        return self.termination == TERMINATION_SATISFIED

    @property
    def total_information_gain(self) -> int:
        return sum(round_.information_gain for round_ in self.rounds)

    def to_public_dict(self) -> dict:
        return {
            "version": self.version,
            "termination": self.termination,
            "missing_before": list(self.missing_before[:12]),
            "missing_after": list(self.missing_after[:12]),
            "rounds": [round_.to_public_dict() for round_ in self.rounds],
            "information_gain": self.total_information_gain,
            "rules_added": len(self.rules),
            "evidence_added": len(self.evidence),
            "compilation_gaps": [gap.to_public_dict() for gap in self.compilation_gaps[:12]],
            "compiler_feedback": [item.to_public_dict() for item in self.feedback[:12]],
            "errors": list(self.errors[:6]),
        }


# -----------------------------------------------------------------------------
# Planner determinista
# -----------------------------------------------------------------------------

#: Premisa -> dimensión semántica esperada en el compilador (para gaps).
_PREMISE_EXPECTED_DIMENSION: dict[str, str] = {
    PREMISE_MATCHING_POSITIONAL: "matching.operator",
    PREMISE_MATCHING_LITERAL: "matching.literal",
    PREMISE_LENGTH_POLICY: "length.policy",
}


def expected_semantic_dimension(premise: str) -> str:
    key = normalize_premise(premise)
    if key.startswith(PREMISE_SYMBOL_PREFIX):
        symbol = symbol_from_premise(key)
        return f"matching.symbol.{symbol}"
    return _PREMISE_EXPECTED_DIMENSION.get(key, "")


class PremiseQueryPlanner:
    """Convierte premisas faltantes en consultas pequeñas (jamás una gigante)."""

    def __init__(
        self,
        *,
        max_queries_per_premise: int = 3,
        max_queries_per_round: int = 6,
    ) -> None:
        self._max_per_premise = max(1, int(max_queries_per_premise))
        self._max_per_round = max(1, int(max_queries_per_round))

    def plan(self, request: PremiseClosureRequest) -> tuple[PlannedPremiseQuery, ...]:
        missing = request.normalized_missing()
        context = self._context_terms(request)
        context_suffix = f" {' '.join(context)}" if context else ""
        queries: list[PlannedPremiseQuery] = []
        seen: set[str] = set()

        def build(premise: str) -> list[PlannedPremiseQuery]:
            symbol = symbol_from_premise(premise)
            built: list[PlannedPremiseQuery] = []
            if symbol:
                for lane, query in (
                    (LANE_EXACT, f'"{symbol}"'),
                    (LANE_SYMBOL, f"{symbol} symbol definition represents indicates"),
                    (
                        LANE_RULE_INDEX,
                        f"definition symbol {symbol} meaning position match{context_suffix}",
                    ),
                ):
                    built.append(
                        PlannedPremiseQuery(
                            premise=premise,
                            query=" ".join(query.split())[:240],
                            lane=lane,
                            terms=tuple(_DEFINITION_VERBS[:4]),
                            symbol=symbol,
                        )
                    )
                return built
            ontology = premise_ontology(premise)
            if not ontology:
                return built
            step = max(1, len(ontology) // 2)
            chunks = [
                ontology[index : index + step]
                for index in range(0, len(ontology), step)
            ][:2]
            for index, terms in enumerate(chunks):
                lane = LANE_LEXICAL if index == 0 else LANE_RULE_INDEX
                term_text = " ".join(dict.fromkeys(terms))
                built.append(
                    PlannedPremiseQuery(
                        premise=premise,
                        query=" ".join(f"{term_text}{context_suffix}".split())[:240],
                        lane=lane,
                        terms=tuple(terms),
                    )
                )
            return built

        # Round-robin: TODA premisa recibe al menos una consulta antes de que el
        # presupuesto se gaste en consultas extra de otra.
        buckets = [build(premise) for premise in missing]
        for index in range(self._max_per_premise):
            for bucket in buckets:
                if len(queries) >= self._max_per_round:
                    return tuple(queries)
                if index >= len(bucket):
                    continue
                candidate = bucket[index]
                if not candidate.query or candidate.query in seen:
                    continue
                seen.add(candidate.query)
                queries.append(candidate)
        return tuple(queries)

    @staticmethod
    def _context_terms(request: PremiseClosureRequest) -> list[str]:
        """Contexto combinado: entidades + campo + símbolos del patrón."""
        context: list[str] = []
        for value in (
            *request.field_context,
            *request.domain_entities,
        ):
            text = " ".join(str(value or "").split())
            if text and text not in context:
                context.append(text[:48])
        pattern = str(request.runtime_pattern or "")
        if pattern:
            for char in pattern:
                if not char.isalnum() and char not in context:
                    context.append(char)
        return context[:4]


# -----------------------------------------------------------------------------
# Puertos
# -----------------------------------------------------------------------------


class PremiseSearchPort(Protocol):
    """Búsqueda dirigida por consultas de premisa (Rule Index + evidencia)."""

    async def search(
        self,
        request: PremiseClosureRequest,
        queries: Sequence[PlannedPremiseQuery],
        *,
        round_index: int,
        focus: SourceScope | None = None,
    ) -> PremiseSearchOutcome: ...


PremiseEvaluateFn = Callable[
    [Sequence[Any], Sequence[EvidenceHit]],
    Awaitable[PremiseEvaluation] | PremiseEvaluation,
]
PremiseExpandFn = Callable[
    [Sequence[Any], PremiseClosureRequest],
    Awaitable[Sequence[Any]] | Sequence[Any],
]
PremiseCompileFn = Callable[
    [Sequence[EvidenceHit], PremiseClosureRequest],
    Awaitable[Sequence[Any]] | Sequence[Any],
]


# -----------------------------------------------------------------------------
# Filtro exacto de símbolo (sin embedding)
# -----------------------------------------------------------------------------


def _symbol_in_text(symbol: str, text: str) -> bool:
    if not symbol:
        return False
    return symbol in str(text or "")


def premises_covered_by_text(premise: str, text: str) -> bool:
    """¿El texto de la evidencia cubre conceptualmente la premisa?

    Es una señal para distinguir COMPILATION_GAP de retrieval miss: la
    evidencia habla de la premisa (símbolo o concepto de la ontología) aunque
    el compilador no la haya convertido en regla.
    """
    key = normalize_premise(premise)
    lowered = " ".join(str(text or "").lower().split())
    symbol = symbol_from_premise(key)
    if symbol:
        if not _symbol_in_text(symbol, text):
            return False
        # El símbolo en el texto tiene que estar en contexto de definición.
        return any(verb in lowered for verb in _DEFINITION_VERBS) or any(
            marker in lowered
            for marker in ("indicate", "represents", "means", "match", "position")
        )
    return any(term.lower() in lowered for term in premise_ontology(key))


def _new_semantic_dimensions(rules: Sequence[Any]) -> tuple[str, ...]:
    dimensions: list[str] = []
    for rule in rules:
        for name, prop in (getattr(rule, "properties", {}) or {}).items():
            if not getattr(prop, "known", False):
                continue
            base = ".".join(str(name).split(".")[:2]) if name.startswith("matching.symbol.") else str(name)
            if name.startswith("matching.symbol."):
                base = str(name)
            if base not in dimensions:
                dimensions.append(base)
    return tuple(sorted(dimensions))


def premise_covered_by_rules(premise: str, rules: Sequence[Any]) -> bool:
    """¿Alguna regla REPRESENTA la premisa (dimensión semántica declarada)?

    No alcanza con que la evaluación no la pida: la premisa se cierra cuando
    una regla la representa o cuando es dato runtime del escenario
    (`input:value`/`input:pattern`), nunca por silencio.
    """
    key = normalize_premise(premise)
    if not key:
        return True
    if key.startswith("input:"):
        return True
    symbol = symbol_from_premise(key)
    for rule in rules or ():
        properties = getattr(rule, "properties", {}) or {}
        known = {
            name: prop
            for name, prop in properties.items()
            if getattr(prop, "known", False)
        }
        if symbol:
            if f"matching.symbol.{symbol}" in known:
                return True
            continue
        if key == PREMISE_MATCHING_POSITIONAL:
            if "matching.operator" in known:
                return True
        elif key == PREMISE_MATCHING_LITERAL:
            if "matching.literal" in known:
                return True
            # Un operador posicional con símbolos definidos implica que los
            # caracteres no-símbolo se comparan literalmente en su posición.
            if "matching.operator" in known and any(
                name.startswith("matching.symbol.") and not name.endswith(".alphabet")
                for name in known
            ):
                return True
        elif key == PREMISE_LENGTH_POLICY:
            if "length.policy" in known:
                return True
    return False


# -----------------------------------------------------------------------------
# Loop de coverage con información ganada
# -----------------------------------------------------------------------------


def _is_searchable_premise(premise: str) -> bool:
    """¿La premisa se puede cerrar con retrieval (ontología o símbolo)?

    Diagnósticos como `executable_semantics` o `rule:*` no son premisas
    buscables: ningún retrieval los cierra. No deben bloquear el cierre ni
    contarse como gain.
    """
    key = normalize_premise(premise)
    if not key:
        return False
    if key.startswith("input:"):
        return False
    return bool(symbol_from_premise(key) or premise_ontology(key))


async def run_premise_closure(
    request: PremiseClosureRequest,
    *,
    search: PremiseSearchPort | None,
    evaluate: PremiseEvaluateFn,
    expand: PremiseExpandFn | None = None,
    compile_evidence: PremiseCompileFn | None = None,
) -> PremiseClosureResult:
    """Loop dirigido por premisas. Nunca repite una ronda sin gain."""
    missing_before = request.normalized_missing()
    result = PremiseClosureResult(missing_before=missing_before, missing_after=missing_before)
    if not missing_before:
        result.termination = TERMINATION_SATISFIED
        return result
    if search is None:
        result.termination = TERMINATION_NO_SEARCH
        return result

    planner = PremiseQueryPlanner(
        max_queries_per_premise=request.max_queries_per_premise,
        max_queries_per_round=request.max_queries_per_round,
    )
    rounds_left = max(0, int(request.rounds_left))

    rules_by_id: dict[str, Any] = {
        str(getattr(rule, "rule_id", "") or id(rule)): rule
        for rule in request.canonical_rule_candidates
    }
    evidence_by_id: dict[str, EvidenceHit] = {}
    seen_evidence: set[str] = set(str(value) for value in request.already_seen_evidence)
    seen_premises: set[tuple[str, ...]] = set()
    focus: SourceScope | None = None

    # Ronda 0: reevaluar con lo que YA se tiene (candidatas + evidencia inicial
    # compilada). Sin esto, una regla query-local ya compilada no se aplicaría
    # hasta que una búsqueda nueva devolviera algo, y el loop terminaría antes.
    if rules_by_id:
        try:
            initial_evaluation = await _maybe_await(
                evaluate(list(rules_by_id.values()), list(evidence_by_id.values()))
            )
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"evaluate_error:{type(exc).__name__}")
            initial_evaluation = None
        if initial_evaluation is not None:
            initial_missing = normalize_premises(initial_evaluation.missing_premises)
            structural_initial = tuple(
                premise
                for premise in missing_before
                if _is_searchable_premise(premise)
                and not premise_covered_by_rules(premise, list(rules_by_id.values()))
            )
            initial_missing = normalize_premises(
                [*initial_missing, *structural_initial]
            )
            missing_before = initial_missing
            result.missing_after = initial_missing
            if not any(_is_searchable_premise(item) for item in initial_missing):
                has_supported = any(
                    str(getattr(claim, "verification_status", "")) == "SUPPORTED"
                    for claim in (initial_evaluation.claims or ())
                )
                result.termination = (
                    TERMINATION_CONFLICTING
                    if initial_evaluation.conflicts
                    else TERMINATION_SATISFIED
                    if has_supported
                    else TERMINATION_NO_INFORMATION_GAIN
                )
                result.rules = tuple(rules_by_id.values())
                result.evidence = tuple(evidence_by_id.values())
                return result
            if not missing_before:
                result.termination = (
                    TERMINATION_CONFLICTING
                    if initial_evaluation.conflicts
                    else TERMINATION_SATISFIED
                )
                result.rules = tuple(rules_by_id.values())
                result.evidence = tuple(evidence_by_id.values())
                return result

    for round_index in range(1, rounds_left + 1):
        plan_request = PremiseClosureRequest(
            **{
                **request.__dict__,
                "missing_premises": missing_before,
                "canonical_rule_candidates": tuple(rules_by_id.values()),
                "already_seen_evidence": tuple(seen_evidence),
                "already_seen_rule_ids": tuple(rules_by_id.keys()),
            }
        )
        queries = planner.plan(plan_request)
        round_ = PremiseClosureRound(
            index=round_index,
            missing_before=missing_before,
            missing_after=missing_before,
            queries=queries,
        )
        if not queries:
            round_.stop_reason = TERMINATION_NO_INFORMATION_GAIN
            result.rounds.append(round_)
            result.termination = TERMINATION_NO_INFORMATION_GAIN
            break
        if missing_before in seen_premises:
            round_.stop_reason = TERMINATION_NO_INFORMATION_GAIN
            result.rounds.append(round_)
            result.termination = TERMINATION_NO_INFORMATION_GAIN
            break
        seen_premises.add(missing_before)

        try:
            outcome = await search.search(
                plan_request,
                queries,
                round_index=round_index,
                focus=focus,
            )
        except Exception as exc:  # noqa: BLE001 — el loop nunca rompe la query
            message = f"search_error:{type(exc).__name__}"
            result.errors.append(message)
            round_.stop_reason = "SEARCH_ERROR"
            result.rounds.append(round_)
            result.termination = TERMINATION_NO_INFORMATION_GAIN
            break

        new_rules: list[Any] = []
        for rule in outcome.rules or ():
            rule_id = str(getattr(rule, "rule_id", "") or id(rule))
            if rule_id in rules_by_id:
                continue
            rules_by_id[rule_id] = rule
            new_rules.append(rule)

        new_evidence: list[EvidenceHit] = []
        for hit in outcome.evidence or ():
            identity = hit.identity
            if identity in seen_evidence or identity in evidence_by_id:
                continue
            seen_evidence.add(identity)
            evidence_by_id[identity] = hit
            new_evidence.append(hit)
        new_evidence = new_evidence[: request.max_new_evidence_per_round]

        # Expansión por grafo conocido (USES_SYMBOL/DEPENDS_ON/...) ANTES de
        # volver a búsqueda global. Solo cuando la ronda encontró algo nuevo.
        if expand is not None and new_rules:
            try:
                expanded = list(await _maybe_await(expand(list(rules_by_id.values()), plan_request)))
            except Exception as exc:  # noqa: BLE001 — best-effort
                result.errors.append(f"expand_error:{type(exc).__name__}")
                expanded = []
            for rule in expanded:
                rule_id = str(getattr(rule, "rule_id", "") or id(rule))
                if rule_id in rules_by_id:
                    continue
                rules_by_id[rule_id] = rule
                new_rules.append(rule)

        # Compilación provisional desde evidencia (PROPOSED -> verificado
        # contra la evidencia; NUNCA se persiste aquí). La compilación recibe
        # TODA la evidencia acumulada hasta la ronda (§8): base + A + B + C,
        # no solo la nueva. Deduplicada por identity.
        if compile_evidence is not None and new_evidence:
            try:
                accumulated = list(evidence_by_id.values())
                compiled = list(
                    await _maybe_await(compile_evidence(accumulated, plan_request))
                )
            except Exception as exc:  # noqa: BLE001 — best-effort
                result.errors.append(f"compile_error:{type(exc).__name__}")
                compiled = []
            for rule in compiled:
                rule_id = str(getattr(rule, "rule_id", "") or id(rule))
                if rule_id in rules_by_id:
                    continue
                rules_by_id[rule_id] = rule
                new_rules.append(rule)

        if not new_rules and not new_evidence:
            round_.stop_reason = TERMINATION_NO_INFORMATION_GAIN
            result.rounds.append(round_)
            result.termination = TERMINATION_NO_INFORMATION_GAIN
            break

        try:
            evaluation = await _maybe_await(
                evaluate(list(rules_by_id.values()), list(evidence_by_id.values()))
            )
        except Exception as exc:  # noqa: BLE001 — evaluación falló: no inventar
            result.errors.append(f"evaluate_error:{type(exc).__name__}")
            round_.stop_reason = "EVALUATE_ERROR"
            result.rounds.append(round_)
            result.termination = TERMINATION_NO_INFORMATION_GAIN
            break

        # Las reglas FUSIONADAS que devuelve la evaluación (p. ej. símbolo +
        # operador + longitud unidas por el motor) son producto legítimo del
        # cierre: entran al pool para la siguiente ronda.
        for rule in getattr(evaluation, "canonical_rules", ()) or ():
            rule_id = str(getattr(rule, "rule_id", "") or id(rule))
            if rule_id not in rules_by_id:
                rules_by_id[rule_id] = rule
                new_rules.append(rule)

        missing_after = normalize_premises(evaluation.missing_premises)
        searchable_before = tuple(
            item for item in missing_before if _is_searchable_premise(item)
        )
        # Cobertura ESTRUCTURAL: una premisa solo se cierra si alguna regla la
        # representa (o es dato runtime). La evaluación puede dejar de pedirla
        # por una dimensión distinta; eso no la cierra por silencio.
        structural_unresolved = tuple(
            premise
            for premise in searchable_before
            if not premise_covered_by_rules(premise, list(rules_by_id.values()))
        )
        searchable_after = normalize_premises(
            [
                *[item for item in missing_after if _is_searchable_premise(item)],
                *structural_unresolved,
            ]
        )
        missing_after = normalize_premises([*missing_after, *structural_unresolved])
        closed = tuple(item for item in missing_before if item not in missing_after)
        gain = max(0, len(searchable_before) - len(searchable_after))
        round_.missing_after = missing_after
        round_.premises_closed = closed
        round_.new_rule_ids = tuple(
            str(getattr(rule, "rule_id", "") or "") for rule in new_rules if getattr(rule, "rule_id", "")
        )[:12]
        round_.new_evidence_refs = tuple(hit.evidence_id or hit.identity for hit in new_evidence)[:12]
        round_.new_semantic_dimensions = _new_semantic_dimensions(new_rules)
        round_.information_gain = gain

        # COMPILATION_GAP: la evidencia cubre la premisa que sigue faltando.
        for premise in missing_after:
            for hit in new_evidence:
                if premises_covered_by_text(premise, hit.content):
                    gap = CompilationGap(
                        premise=premise,
                        evidence_ref=hit.evidence_id or hit.identity,
                        excerpt=hit.content[:400],
                        expected_semantic_dimension=expected_semantic_dimension(premise),
                        compiler_version=_compiler_version(),
                        document_id=hit.document_id,
                        page=hit.page,
                        section_path=hit.section_path,
                    )
                    result.compilation_gaps.append(gap)
                    result.feedback.append(
                        RuleCompilerMissedEvidence(
                            semantic_dimension=gap.expected_semantic_dimension,
                            document_id=hit.document_id,
                            source_id=hit.source_id,
                            page=hit.page,
                            section_path=hit.section_path,
                            semantic_unit=hit.content[:240],
                            evidence_ref=gap.evidence_ref,
                            compiler_version=gap.compiler_version,
                        )
                    )
                    break

        # Localidad de fuente: una evidencia que matchea exacto el símbolo es
        # foco fuerte; la siguiente ronda prioriza ese documento/sección.
        if round_index < rounds_left:
            focus = _focus_from(outcome, new_evidence, plan_request.source_scope)

        missing_before = missing_after
        if evaluation.conflicts:
            round_.stop_reason = TERMINATION_CONFLICTING
            result.rounds.append(round_)
            result.termination = TERMINATION_CONFLICTING
            break
        if not searchable_after:
            # Premisas buscables cerradas: el Requirement Graph quedó satisfecho
            # aunque queden diagnósticos no buscables (executable_semantics).
            round_.stop_reason = TERMINATION_SATISFIED
            result.rounds.append(round_)
            result.termination = TERMINATION_SATISFIED
            break
        if gain <= 0:
            round_.stop_reason = TERMINATION_NO_INFORMATION_GAIN
            result.rounds.append(round_)
            result.termination = TERMINATION_NO_INFORMATION_GAIN
            break
        result.rounds.append(round_)

    else:
        result.termination = TERMINATION_BUDGET_EXHAUSTED

    result.missing_after = missing_before
    result.rules = tuple(rules_by_id.values())
    result.evidence = tuple(evidence_by_id.values())
    result.feedback = _merge_feedback(result.feedback)
    return result


async def _maybe_await(value: Any) -> Any:
    if hasattr(value, "__await__"):
        return await value
    return value


def _focus_from(
    outcome: PremiseSearchOutcome,
    new_evidence: Sequence[EvidenceHit],
    current: SourceScope,
) -> SourceScope | None:
    """Foco source-local: documento de la evidencia más fuerte con símbolo."""
    candidates = [hit for hit in new_evidence if hit.document_id or hit.section_path]
    if not candidates:
        return None
    if outcome.exact_symbol_hits:
        for hit in candidates:
            if any(_symbol_in_text(symbol, hit.content) for symbol in outcome.exact_symbol_hits):
                return current.focused(document_id=hit.document_id, section_path=hit.section_path)
    best = max(candidates, key=lambda hit: (hit.score, hit.evidence_id))
    return current.focused(document_id=best.document_id, section_path=best.section_path)


def _merge_feedback(
    feedback: Sequence[RuleCompilerMissedEvidence],
) -> list[RuleCompilerMissedEvidence]:
    """Agrega frecuencia por (documento, dimensión) sin perder provenance."""
    merged: dict[tuple[str, str, str], RuleCompilerMissedEvidence] = {}
    for item in feedback:
        key = (item.document_id, item.semantic_dimension, item.evidence_ref)
        current = merged.get(key)
        if current is None:
            merged[key] = item
        else:
            current.frequency += item.frequency
    return [merged[key] for key in sorted(merged)]


def _compiler_version() -> str:
    try:
        from src.knowledge.rule_compiler.model import RULE_COMPILER_VERSION

        return RULE_COMPILER_VERSION
    except Exception:  # noqa: BLE001
        return ""


__all__ = [
    "CompilationGap",
    "EvidenceHit",
    "LANE_DENSE",
    "LANE_EXACT",
    "LANE_LEXICAL",
    "LANE_RULE_INDEX",
    "LANE_SYMBOL",
    "PREMISE_MATCHING_LITERAL",
    "PREMISE_MATCHING_POSITIONAL",
    "PREMISE_LENGTH_POLICY",
    "PREMISE_SYMBOL_PREFIX",
    "PREMISE_CLOSURE_VERSION",
    "PlannedPremiseQuery",
    "PremiseClosureRequest",
    "PremiseClosureResult",
    "PremiseClosureRound",
    "PremiseEvaluateFn",
    "PremiseEvaluation",
    "PremiseQueryPlanner",
    "PremiseSearchPort",
    "PremiseSearchOutcome",
    "RuleCompilerMissedEvidence",
    "SourceScope",
    "TERMINATION_BUDGET_EXHAUSTED",
    "TERMINATION_CONFLICTING",
    "TERMINATION_NO_INFORMATION_GAIN",
    "TERMINATION_NO_SEARCH",
    "TERMINATION_SATISFIED",
    "expected_semantic_dimension",
    "normalize_premise",
    "normalize_premises",
    "premise_ontology",
    "premises_covered_by_text",
    "premise_covered_by_rules",
    "run_premise_closure",
    "symbol_from_premise",
]
