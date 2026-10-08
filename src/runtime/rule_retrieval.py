# =============================================================================
# Rule Retrieval — reglas canónicas como conocimiento de primera clase
# =============================================================================
# Query-time NO reparsea regex sobre texto bruto para reinterpretar semántica:
# recupera la CanonicalRule compilada (con scope, operator, conditions,
# exceptions, parámetros, evidence refs, verification state, confidence y
# vigencia) y RECIÉN DESPUÉS la evidencia de soporte para citas/auditoría.
#
# DOS CARRILES (nunca uno solo):
#
#   RULE LANE      búsqueda por semántica de la QUERY (tokens, anchors,
#                  entidades, conceptos, símbolos, operador) sobre el índice de
#                  reglas canónicas. Independiente del top-k de raw chunks.
#   EVIDENCE LANE  chunks recuperados: `canonical_rule_ids` /
#                  `canonical_rule_objects` son un SHORTCUT/BOOST/direct
#                  evidence relation, nunca el único camino.
#
# Se fusionan DESPUÉS de encontrar candidatos de regla, con orden determinista
# (score, rule_id): misma query + misma fuente => mismos candidatos, siempre.
#
# Sin reglas soportadas no se inventa nada: el grounded engine conserva el
# camino histórico (y lo bloquea cuando la pregunta exige una operación).
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Protocol, Sequence
from uuid import UUID

from src.core.domain.canonical import CanonicalKind
from src.infrastructure.observability.logging_config import get_logger
from src.knowledge.rule_compiler.index import (
    merge_rule_candidates,
    query_symbols,
    query_tokens,
    rank_rule,
)
from src.knowledge.rule_compiler.model import CanonicalRule
from src.runtime.operation_compatibility import (
    MISSING_RUNTIME_SYMBOL_SEMANTICS,
    QueryOperationRequirements,
    derive_query_operation_requirements,
    gate_rules_for_requirements,
)

logger = get_logger(__name__)

RULE_RETRIEVAL_VERSION = "rule-retrieval-4"
#: Kind REAL con el que el compilador persiste las reglas canónicas.
#: El Rule Lane DEBE usar este valor: persistir `business_rule` y consultar
#: `BUSINESS_RULE` fue un miss total de retrieval (0 candidatas siempre).
RULE_OBJECT_KIND = CanonicalKind.BUSINESS_RULE.value
#: Comparación case-insensitive para tolerar datos históricos con otro casing.
_RULE_KIND_CLAUSE = "LOWER(kind) = :rule_kind"
#: Consulta de reglas por id: solo se interpola la cláusula constante de kind.
_LOOKUP_BY_IDS_SQL = (
    "SELECT id, name, description, confidence, metadata "  # noqa: S608 — cláusula constante
    "FROM knowledge_canonical_objects "
    "WHERE organization_id = :org AND "
    f"{_RULE_KIND_CLAUSE} "
    "AND id::text IN :ids"
)
MAX_RULES_PER_QUERY = 24
#: Score mínimo para que una regla entre al motor desde la Rule Lane.
MIN_RULE_SCORE = 2.0
#: Techo de filas que el índice Postgres trae para re-ranking determinista.
_MAX_INDEX_FETCH = 200

#: Motivos por los que una consulta ejecutable quedó sin regla soportada.
WHY_NO_RULE: dict[str, str] = {
    "no_candidate": "no hay candidatos de regla en el índice para esta consulta",
    "out_of_scope": "los candidatos existen pero quedan fuera del scope autorizado",
    "unsupported": "hay reglas candidatas pero ninguna está verificada/ejecutable",
    "index_missing": "la evidencia referencia reglas pero el índice de reglas no las expone (requiere backfill)",
    "stale_document": "el documento fue compilado antes del Semantic Rule Compiler (requiere backfill)",
    "retrieval_failure": "el retrieval de reglas falló (operativo)",
    "conflict": "las reglas candidatas están en conflicto y no hay una soportada",
    "operation_mismatch": (
        "hay reglas soportadas pero ninguna es semánticamente compatible con la "
        "operación que exige la consulta"
    ),
}


class RuleLookupPort(Protocol):
    """Puerto de carga de reglas canónicas por id (tenant-scoped)."""

    async def load_rules(
        self, organization_id: UUID, rule_ids: Sequence[UUID]
    ) -> list[CanonicalRule]: ...


class RuleIndexPort(Protocol):
    """Puerto de búsqueda de reglas canónicas por semántica de la query."""

    async def search(self, request: "RuleSearchRequest") -> list["RuleSearchHit"]: ...


def _as_uuid(value: Any) -> UUID | None:
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def collect_rule_ids(items: Sequence[Any]) -> list[UUID]:
    """Ids de reglas canónicas declarados por los chunks recuperados."""
    ids: list[UUID] = []
    seen: set[str] = set()
    for item in items or ():
        metadata = getattr(item, "metadata", None) or {}
        if not isinstance(metadata, dict):
            continue
        for meta_field in ("canonical_rule_ids", "canonical_rule_objects"):
            values = metadata.get(meta_field)
            if isinstance(values, dict):
                values = list(values.values())
            elif isinstance(values, str):
                values = [values]
            elif values is None:
                continue
            for value in values or ():
                parsed = _as_uuid(value)
                if parsed is None:
                    continue
                key = str(parsed)
                if key in seen:
                    continue
                seen.add(key)
                ids.append(parsed)
    return ids[:MAX_RULES_PER_QUERY]


def rule_signal_from_evidence(items: Sequence[Any]) -> str:
    """¿La evidencia indica que existe una regla documental relevante?

    Devuelve '' si no hay señal. Códigos:
      rule_ids_present    el chunk referencia una regla canónica (shortcut)
      rule_index_missing  hay artefactos de regla (fabric/rule_semantics) sin ids
      rule_fragment_present  hay fragmentos de condiciones/excepciones
      normative_evidence  el texto recuperado parece normativo (compilable)
    """
    normative = False
    for item in items or ():
        metadata = getattr(item, "metadata", None) or {}
        if not isinstance(metadata, dict):
            continue
        if metadata.get("canonical_rule_ids") or metadata.get("canonical_rule_objects"):
            return "rule_ids_present"
        if (
            metadata.get("rule_semantics")
            or metadata.get("rule_provenance")
            or metadata.get("rule_ids")
        ):
            return "rule_index_missing"
        if (
            metadata.get("exception_ids")
            or metadata.get("condition_ids")
            or metadata.get("definition_ids")
        ):
            return "rule_fragment_present"
        content = str(getattr(item, "content", "") or "")
        if content and _looks_normative(content):
            normative = True
    if normative:
        return "normative_evidence"
    return ""


_NORMATIVE_MARKERS = (
    "must",
    "shall",
    "may not",
    "only if",
    "unless",
    "required",
    "eligible",
    "must be",
    "debe",
    "deberá",
    "debera",
    "no podrá",
    "no podra",
    "solo si",
    "sólo si",
    "salvo",
    "excepto",
    "requiere",
    "obligatorio",
    "permitido",
)


def _looks_normative(text: str) -> bool:
    lowered = " ".join(text.lower().split())
    return any(marker in lowered for marker in _NORMATIVE_MARKERS)


# -----------------------------------------------------------------------------
# Lookup por id (shortcut de la Evidence Lane)
# -----------------------------------------------------------------------------


def _rule_from_row(row: Any) -> CanonicalRule | None:
    metadata = dict(row.metadata or {}) if isinstance(row.metadata, dict) else {}
    payload = metadata.get("semantics")
    if not isinstance(payload, dict):
        payload = {}
    payload = dict(payload)
    payload.setdefault("rule_id", str(metadata.get("canonical_rule_id") or row.id))
    payload.setdefault("subject", str(row.name or ""))
    payload.setdefault("statement", str(row.description or ""))
    payload.setdefault("confidence", float(row.confidence or 0.7))
    if metadata.get("verification_state"):
        payload.setdefault("verification_state", metadata["verification_state"])
    provenance = metadata.get("rule_provenance")
    if isinstance(provenance, list):
        payload["provenance"] = provenance
    try:
        rule = CanonicalRule.from_dict(payload)
    except Exception as exc:  # noqa: BLE001 — payload ajeno no rompe la query
        logger.warning(
            "Canonical rule payload invalid",
            rule_id=str(getattr(row, "id", "")),
            error=str(exc)[:160],
        )
        return None
    return rule if rule.rule_id else None


class PostgresRuleLookup:
    """Carga reglas desde knowledge_canonical_objects (semántica en metadata)."""

    async def load_rules(
        self, organization_id: UUID, rule_ids: Sequence[UUID]
    ) -> list[CanonicalRule]:
        ids = [str(value) for value in rule_ids if value]
        if not ids:
            return []
        from sqlalchemy import bindparam
        from sqlalchemy import text as sql_text

        from src.infrastructure.postgres.session import get_async_session

        session = await get_async_session()
        try:
            stmt = sql_text(_LOOKUP_BY_IDS_SQL).bindparams(
                bindparam("ids", expanding=True)
            )
            rows = (
                await session.execute(
                    stmt,
                    {
                        "org": organization_id,
                        "rule_kind": RULE_OBJECT_KIND,
                        "ids": ids,
                    },
                )
            ).all()
        finally:
            await session.close()

        rules: list[CanonicalRule] = []
        for row in rows:
            rule = _rule_from_row(row)
            if rule is not None:
                rules.append(rule)
        return rules


class InMemoryRuleLookup:
    """Lookup para tests y runtimes embebidos (sin DB)."""

    def __init__(self, rules: Iterable[CanonicalRule] = ()) -> None:
        self._rules: dict[str, CanonicalRule] = {
            str(rule.rule_id): rule for rule in rules
        }

    async def load_rules(
        self, organization_id: UUID, rule_ids: Sequence[UUID]
    ) -> list[CanonicalRule]:
        del organization_id
        found: list[CanonicalRule] = []
        for value in rule_ids:
            rule = self._rules.get(str(value))
            if rule is None:
                continue
            if rule.rule_id not in {item.rule_id for item in found}:
                found.append(rule)
        return found


async def load_rules_for_evidence(
    organization_id: UUID,
    items: Sequence[Any],
    *,
    lookup: RuleLookupPort | None = None,
    max_rules: int = MAX_RULES_PER_QUERY,
) -> list[CanonicalRule]:
    """Fail-soft: sin ids o sin lookup devuelve [] (shortcut, no camino único)."""
    rule_ids = collect_rule_ids(items)
    if not rule_ids:
        return []
    resolved = lookup or PostgresRuleLookup()
    try:
        rules = await resolved.load_rules(organization_id, rule_ids[:max_rules])
    except Exception as exc:  # noqa: BLE001 — retrieval de reglas nunca frena el run
        logger.warning(
            "Canonical rule retrieval failed",
            organization_id=str(organization_id),
            error=str(exc)[:200],
        )
        return []
    return [rule for rule in rules if rule.rule_id][:max_rules]


# -----------------------------------------------------------------------------
# Rule Lane — búsqueda por semántica de la query
# -----------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class RuleSearchRequest:
    """Inputs mínimos del Rule Lane (independiente de los raw chunks)."""

    organization_id: UUID
    query: str = ""
    workspace_id: UUID | None = None
    source_ids: tuple[UUID, ...] = ()
    document_ids: tuple[UUID, ...] = ()
    tokens: tuple[str, ...] = ()
    anchors: tuple[str, ...] = ()
    entities: tuple[str, ...] = ()
    concepts: tuple[str, ...] = ()
    symbols: tuple[str, ...] = ()
    required_semantics: tuple[str, ...] = ()
    operation_intent: str = ""
    #: Requisitos de operación derivados de QuerySemantics (gate de compatibilidad).
    operation_requirements: QueryOperationRequirements | None = None
    max_results: int = MAX_RULES_PER_QUERY

    def to_public_dict(self) -> dict:
        return {
            "tokens": list(self.tokens[:16]),
            "anchors": list(self.anchors[:8]),
            "entities": list(self.entities[:8]),
            "concepts": list(self.concepts[:8]),
            "symbols": list(self.symbols[:8]),
            "operation_intent": self.operation_intent,
            "required_semantics": list(self.required_semantics[:12]),
            "scoped": bool(self.workspace_id or self.source_ids or self.document_ids),
            "operation_requirements": (
                self.operation_requirements.to_public_dict()
                if self.operation_requirements is not None
                else None
            ),
        }


@dataclass(frozen=True, kw_only=True)
class RuleSearchHit:
    rule: CanonicalRule
    score: float
    source: str = "lexical"  # lexical | anchor | symbol | semantic | chunk_association
    reasons: tuple[str, ...] = ()


class InMemoryRuleIndex:
    """Índice determinista en memoria (tests, runtimes embebidos)."""

    def __init__(self, rules: Iterable[CanonicalRule] = ()) -> None:
        self._rules: tuple[CanonicalRule, ...] = tuple(rules)

    @property
    def rules(self) -> tuple[CanonicalRule, ...]:
        return self._rules

    async def search(self, request: RuleSearchRequest) -> list[RuleSearchHit]:
        hits: list[RuleSearchHit] = []
        for rule in self._rules:
            score, reasons = rank_rule(
                rule,
                tokens=request.tokens,
                anchors=request.anchors,
                entities=request.entities,
                concepts=request.concepts,
                symbols=request.symbols,
                intent=request.operation_intent,
            )
            if score <= 0:
                continue
            source = _hit_source(reasons)
            hits.append(
                RuleSearchHit(rule=rule, score=score, source=source, reasons=reasons)
            )
        hits.sort(key=lambda hit: (-hit.score, str(hit.rule.rule_id)))
        return hits[: request.max_results]


class PostgresRuleIndex:
    """Rule Lane sobre knowledge_canonical_objects (tenant/scope acotado).

    El ranking determinista se hace en Python sobre un fetch acotado; el SQL
    solo aplica scope + preselección léxica para no escanear la tabla entera.
    """

    def __init__(self, *, fetch_limit: int = _MAX_INDEX_FETCH) -> None:
        self._fetch_limit = max(20, int(fetch_limit))

    async def search(self, request: RuleSearchRequest) -> list[RuleSearchHit]:
        patterns = _search_patterns(request)
        if not patterns:
            return []
        from sqlalchemy import text as sql_text

        from src.infrastructure.postgres.session import get_async_session

        clause = (
            "name ILIKE ANY(CAST(:patterns AS text[])) "
            "OR description ILIKE ANY(CAST(:patterns AS text[])) "
            "OR metadata::text ILIKE ANY(CAST(:patterns AS text[]))"
        )
        params: dict[str, Any] = {
            "org": request.organization_id,
            "patterns": patterns,
            "limit": self._fetch_limit,
            "rule_kind": RULE_OBJECT_KIND,
        }
        scope = _scope_clause(request, params)
        session = await get_async_session()
        try:
            rows = (
                await session.execute(
                    sql_text(
                        "SELECT id, name, description, confidence, metadata "  # noqa: S608
                        "FROM knowledge_canonical_objects "
                        "WHERE organization_id = :org AND "
                        f"{_RULE_KIND_CLAUSE} "
                        f"AND ({clause}) {scope} "  # fragmentos constantes del módulo
                        "ORDER BY updated_at DESC, id ASC LIMIT :limit"
                    ),
                    params,
                )
            ).all()
        finally:
            await session.close()

        hits: list[RuleSearchHit] = []
        for row in rows:
            rule = _rule_from_row(row)
            if rule is None:
                continue
            score, reasons = rank_rule(
                rule,
                tokens=request.tokens,
                anchors=request.anchors,
                entities=request.entities,
                concepts=request.concepts,
                symbols=request.symbols,
                intent=request.operation_intent,
            )
            if score <= 0:
                continue
            hits.append(
                RuleSearchHit(
                    rule=rule,
                    score=score,
                    source=_hit_source(reasons),
                    reasons=reasons,
                )
            )
        hits.sort(key=lambda hit: (-hit.score, str(hit.rule.rule_id)))
        return hits[: request.max_results]


def _search_patterns(request: RuleSearchRequest) -> list[str]:
    patterns: list[str] = []
    for value in [*request.tokens, *request.anchors, *request.entities, *request.concepts]:
        text = str(value or "").strip()
        if len(text) >= 3:
            patterns.append(f"%{text}%")
    for symbol in request.symbols:
        if symbol:
            patterns.append(f"%{symbol}%")
    # Determinista y acotado: el SQL no recibe más de 12 patrones.
    return list(dict.fromkeys(patterns))[:12]


def _scope_clause(request: RuleSearchRequest, params: dict) -> str:
    clauses: list[str] = []
    if request.workspace_id:
        params["workspace_id"] = str(request.workspace_id)
        clauses.append(
            "(metadata->>'workspace_id' IS NULL OR metadata->>'workspace_id' = :workspace_id)"
        )
    if request.document_ids:
        params["document_ids"] = [str(value) for value in request.document_ids]
        clauses.append(
            "(metadata->>'document_id' IS NULL OR metadata->>'document_id' = ANY(CAST(:document_ids AS text[])))"
        )
    if request.source_ids:
        params["source_ids"] = [str(value) for value in request.source_ids]
        clauses.append(
            "(metadata->>'source_id' IS NULL OR metadata->>'source_id' = ANY(CAST(:source_ids AS text[])))"
        )
    return ("AND " + " AND ".join(clauses)) if clauses else ""


def _hit_source(reasons: Sequence[str]) -> str:
    if any(reason.startswith("symbol:") for reason in reasons):
        return "symbol"
    if any(reason.startswith("anchor:") for reason in reasons):
        return "anchor"
    if any(
        reason.startswith(("entity:", "concept:")) for reason in reasons
    ):
        return "semantic"
    return "lexical"


# -----------------------------------------------------------------------------
# Retriever — fusión de carriles
# -----------------------------------------------------------------------------


@dataclass(kw_only=True)
class RuleRetrievalResult:
    """Resultado del retrieval de reglas + diagnóstico de «Ver flujo»."""

    strategy: str = "none"  # canonical_first | chunk_association | none
    candidates: list[RuleSearchHit] = field(default_factory=list)
    candidate_rules: list[CanonicalRule] = field(default_factory=list)
    supported_rules: list[CanonicalRule] = field(default_factory=list)
    executable_rules: list[CanonicalRule] = field(default_factory=list)
    #: Candidatas que pasaron el gate de compatibilidad OPERACIÓN↔QUERY,
    #: rankeadas DESPUÉS del gate (score_after). Es la lista que entra al
    #: pass decisivo; `candidate_rules` conserva todo para telemetría.
    compatible_rules: list[CanonicalRule] = field(default_factory=list)
    #: Familia compatible pero capacidad incompleta (p.ej. matching sin la
    #: definición del símbolo): Premise Closure / el merge distribuido puede
    #: completarla. No entra directamente al pass decisivo.
    deferred_rules: list[CanonicalRule] = field(default_factory=list)
    #: True cuando el retriever aplicó el gate (no cuando un doble de test
    #: construyó el resultado a mano).
    compatibility_applied: bool = False
    #: Vista pública del stage `operation_compatibility` (conteos, rechazos,
    #: score antes/después, ganador).
    operation_compatibility: dict = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    evidence_signal: str = ""
    errors: list[str] = field(default_factory=list)
    request: RuleSearchRequest | None = None
    version: str = RULE_RETRIEVAL_VERSION

    @property
    def candidate_ids(self) -> list[str]:
        return [str(rule.rule_id) for rule in self.candidate_rules]

    @property
    def supported_ids(self) -> list[str]:
        return [str(rule.rule_id) for rule in self.supported_rules]

    @property
    def compatible_ids(self) -> list[str]:
        return [str(rule.rule_id) for rule in self.compatible_rules]

    @property
    def deferred_ids(self) -> list[str]:
        return [str(rule.rule_id) for rule in self.deferred_rules]

    def to_public_dict(self) -> dict:
        why = [WHY_NO_RULE.get(reason, reason) for reason in self.reasons]
        if self.evidence_signal in ("rule_index_missing", "stale_document") and not self.supported_rules:
            why.append(WHY_NO_RULE["stale_document"])
        return {
            "version": self.version,
            "strategy": self.strategy,
            "candidates_found": len(self.candidates),
            "supported_rules": len(self.supported_rules),
            "compatible_rules": len(self.compatible_rules),
            "deferred_rules": len(self.deferred_rules),
            "rule_ids": self.supported_ids[:12] or self.candidate_ids[:12],
            "supported_rule_ids": self.supported_ids[:12],
            "candidate_rule_ids": self.candidate_ids[:12],
            "compatible_rule_ids": self.compatible_ids[:12],
            "deferred_rule_ids": self.deferred_ids[:12],
            "reasons": list(dict.fromkeys(self.reasons))[:6],
            "why_no_rule": why[:4],
            "evidence_signal": self.evidence_signal,
            "errors": list(self.errors[:4]),
            "operation_compatibility": dict(self.operation_compatibility),
            "request": self.request.to_public_dict() if self.request else None,
        }


class CanonicalRuleRetriever:
    """Rule-first retrieval: Rule Lane + Evidence Lane (chunk ids como boost)."""

    def __init__(
        self,
        *,
        index: RuleIndexPort | None = None,
        lookup: RuleLookupPort | None = None,
        max_rules: int = MAX_RULES_PER_QUERY,
        min_rule_score: float = MIN_RULE_SCORE,
    ) -> None:
        self._index = index
        self._lookup = lookup
        self._max_rules = max_rules
        self._min_rule_score = min_rule_score

    async def retrieve(
        self,
        request: RuleSearchRequest,
        *,
        chunk_rule_ids: Sequence[UUID] = (),
    ) -> RuleRetrievalResult:
        result = RuleRetrievalResult(request=request)
        hits: list[tuple[CanonicalRule, float, str]] = []

        # Evidence Lane: shortcut por ids declarados en los chunks.
        if chunk_rule_ids:
            lookup = self._lookup or PostgresRuleLookup()
            try:
                chunk_rules = await lookup.load_rules(
                    request.organization_id, list(chunk_rule_ids)[: self._max_rules]
                )
                for rule in chunk_rules:
                    hits.append((rule, 100.0, "chunk_association"))
            except Exception as exc:  # noqa: BLE001
                result.errors.append("chunk_lookup_failed")
                logger.warning(
                    "Canonical rule chunk lookup failed",
                    organization_id=str(request.organization_id),
                    error=str(exc)[:200],
                )

        # Rule Lane: búsqueda por semántica de la query.
        rule_lane_found = False
        if self._index is not None:
            try:
                index_hits = await self._index.search(request)
                for hit in index_hits:
                    hits.append((hit.rule, hit.score, hit.source))
                rule_lane_found = bool(index_hits)
            except Exception as exc:  # noqa: BLE001
                result.errors.append("index_search_failed")
                logger.warning(
                    "Canonical rule index search failed",
                    organization_id=str(request.organization_id),
                    error=str(exc)[:200],
                )

        merged_rules = merge_rule_candidates(hits, max_rules=self._max_rules)
        result.candidate_rules = merged_rules
        result.candidates = self._hits_for_rules(merged_rules, hits)

        # Gate de compatibilidad OPERACIÓN↔QUERY ANTES del ranking decisivo:
        # las incompatibles quedan excluidas con razón auditable; solo las
        # compatibles se rankean (score_after) y alimentan el pass decisivo.
        requirements = _requirements_for_request(request)
        scores = _best_scores(hits)
        gate = gate_rules_for_requirements(merged_rules, requirements, scores=scores)
        result.compatibility_applied = True
        result.operation_compatibility = gate.to_public_dict()
        result.compatible_rules = gate.ranked_compatible()
        result.deferred_rules = [
            rule
            for rule in gate.rejected
            if (result_for := gate.result_for(rule)) is not None
            and result_for.eligibility == MISSING_RUNTIME_SYMBOL_SEMANTICS
        ]
        result.supported_rules = [
            rule for rule in result.compatible_rules if _is_supported(rule)
        ]
        result.executable_rules = [
            rule for rule in result.supported_rules if _is_executable(rule)
        ]

        if rule_lane_found:
            result.strategy = "canonical_first"
        elif hits:
            result.strategy = "chunk_association"
        else:
            result.strategy = "none"

        if not result.candidates:
            result.reasons.append(
                "retrieval_failure" if result.errors else "no_candidate"
            )
        elif not result.compatible_rules and gate.rejected:
            # Candidatas existentes pero NINGUNA compatible: no es un conflicto
            # documental ni un «casi match»; es incompatibilidad de operación.
            result.reasons.append("operation_mismatch")
            if not any(_is_supported(rule) for rule in result.candidate_rules):
                result.reasons.append("unsupported")
        elif not result.supported_rules:
            if any(_is_conflicting(rule) for rule in result.candidate_rules):
                result.reasons.append("conflict")
            else:
                result.reasons.append("unsupported")
        return result

    @staticmethod
    def _hits_for_rules(
        rules: Sequence[CanonicalRule],
        hits: Sequence[tuple[CanonicalRule, float, str]],
    ) -> list[RuleSearchHit]:
        by_id: dict[str, RuleSearchHit] = {}
        for rule, score, source in hits:
            rule_id = str(getattr(rule, "rule_id", "") or "")
            if not rule_id:
                continue
            current = by_id.get(rule_id)
            if current is None or score > current.score:
                by_id[rule_id] = RuleSearchHit(
                    rule=rule, score=float(score), source=source
                )
        return [by_id[str(rule.rule_id)] for rule in rules if str(rule.rule_id) in by_id]


def _best_scores(hits: Sequence[tuple[CanonicalRule, float, str]]) -> dict[str, float]:
    """Mejor score por regla (antes del gate), determinista."""
    scores: dict[str, float] = {}
    for rule, score, _source in hits or ():
        rule_id = str(getattr(rule, "rule_id", "") or "")
        if not rule_id:
            continue
        current = scores.get(rule_id)
        if current is None or float(score) > current:
            scores[rule_id] = float(score)
    return scores


def _requirements_for_request(
    request: RuleSearchRequest,
) -> QueryOperationRequirements:
    """Requisitos de operación: los del request o derivados de sus señales."""
    if request.operation_requirements is not None:
        return request.operation_requirements
    return derive_query_operation_requirements(
        question=request.query,
        symbols=request.symbols,
        runtime_patterns=request.anchors,
        intent=request.operation_intent,
        required_semantics=request.required_semantics,
    )


def _is_supported(rule: CanonicalRule) -> bool:
    try:
        return bool(rule.supported)
    except Exception:  # noqa: BLE001
        return str(getattr(rule, "verification_state", "")) == "SUPPORTED"


def _is_executable(rule: CanonicalRule) -> bool:
    return bool(getattr(rule, "executable", False))


def _is_conflicting(rule: CanonicalRule) -> bool:
    return str(getattr(rule, "verification_state", "")) == "CONFLICTING" or bool(
        getattr(rule, "conflicts_with", ())
    )


# -----------------------------------------------------------------------------
# Construcción del request + entry point
# -----------------------------------------------------------------------------


def build_rule_search_request(
    organization_id: UUID,
    question: str,
    *,
    semantics: Any | None = None,
    evidence_items: Sequence[Any] = (),
    workspace_id: UUID | None = None,
    source_ids: Sequence[UUID] = (),
    document_ids: Sequence[UUID] = (),
    operation_intent: str = "",
    max_results: int = MAX_RULES_PER_QUERY,
) -> RuleSearchRequest:
    """Deriva los inputs del Rule Lane desde Query Semantics + evidencia.

    Scope: si el caller no lo fija, se hereda de la evidencia recuperada
    (document_id/source_id) para no buscar fuera del material del run.
    """
    sem = semantics
    if sem is None:
        try:
            from src.intelligence.query_semantics import classify_query_semantics

            sem = classify_query_semantics(question)
        except Exception:  # noqa: BLE001 — sin semántica, búsqueda léxica
            sem = None

    patterns: list[str] = []
    objects: list[Any] = []
    required_semantics: tuple[str, ...] = ()
    intent = operation_intent
    if sem is not None:
        objects = list(getattr(sem, "objects", ()) or ())
        patterns = [str(obj.value) for obj in getattr(sem, "runtime_patterns", ())]
        intent = intent or str(getattr(sem, "intent", "") or "")
        try:
            from src.intelligence.query_semantics import pattern_semantic_requirements

            for pattern in patterns:
                required_semantics = tuple(
                    dict.fromkeys(
                        [*required_semantics, *pattern_semantic_requirements(pattern)]
                    )
                )
        except Exception:  # noqa: BLE001
            required_semantics = ()

    tokens = query_tokens(
        question,
        [
            getattr(obj, "value", "")
            for obj in objects
            if getattr(obj, "documentable", False)
        ],
    )
    symbols = query_symbols(question, patterns)
    anchors = tuple(dict.fromkeys([*patterns, *[
        str(getattr(obj, "value", ""))
        for obj in objects
        if str(getattr(obj, "semantic_role", "")) == "RUNTIME_PATTERN"
    ]]))
    entities = tuple(
        dict.fromkeys(
            str(getattr(obj, "value", ""))
            for obj in objects
            if str(getattr(obj, "semantic_role", "")) == "DOMAIN_ENTITY"
        )
    )
    concepts = tuple(
        dict.fromkeys(
            str(getattr(obj, "value", ""))
            for obj in objects
            if str(getattr(obj, "semantic_role", ""))
            in ("RULE_REQUIREMENT", "DEFINITION_REQUIREMENT", "FIELD_REQUIREMENT", "REFERENCE")
        )
    )

    if not document_ids and not source_ids:
        derived_docs, derived_sources = _scope_from_evidence(evidence_items)
        document_ids = derived_docs
        source_ids = derived_sources

    operation_requirements = derive_query_operation_requirements(
        question=question,
        semantics=sem,
        symbols=tuple(symbols),
        runtime_patterns=tuple(patterns),
        intent=intent,
        required_semantics=required_semantics,
    )

    return RuleSearchRequest(
        organization_id=organization_id,
        query=question,
        workspace_id=workspace_id,
        source_ids=tuple(source_ids)[:24],
        document_ids=tuple(document_ids)[:24],
        tokens=tokens[:24],
        anchors=anchors[:8],
        entities=entities[:8],
        concepts=concepts[:8],
        symbols=symbols[:8],
        required_semantics=required_semantics,
        operation_intent=intent,
        operation_requirements=operation_requirements,
        max_results=max_results,
    )


def _scope_from_evidence(
    items: Sequence[Any],
) -> tuple[tuple[UUID, ...], tuple[UUID, ...]]:
    documents: list[UUID] = []
    sources: list[UUID] = []
    for item in items or ():
        metadata = getattr(item, "metadata", None) or {}
        if not isinstance(metadata, dict):
            continue
        for meta_field, target in (("document_id", documents), ("source_id", sources)):
            parsed = _as_uuid(metadata.get(meta_field))
            if parsed is not None and parsed not in target:
                target.append(parsed)
    return tuple(documents[:24]), tuple(sources[:24])


async def retrieve_canonical_rules(
    organization_id: UUID,
    question: str,
    *,
    evidence_items: Sequence[Any] = (),
    semantics: Any | None = None,
    lookup: RuleLookupPort | None = None,
    index: RuleIndexPort | None = None,
    workspace_id: UUID | None = None,
    source_ids: Sequence[UUID] = (),
    document_ids: Sequence[UUID] = (),
    max_rules: int = MAX_RULES_PER_QUERY,
) -> RuleRetrievalResult:
    """Entry point productivo: Rule Lane + chunk shortcut, fail-soft.

    Nunca lanza: un fallo operativo del índice se refleja en `errors`/`reasons`
    y el llamado conserva el camino determinista disponible.
    """
    request = build_rule_search_request(
        organization_id,
        question,
        semantics=semantics,
        evidence_items=evidence_items,
        workspace_id=workspace_id,
        source_ids=source_ids,
        document_ids=document_ids,
        max_results=max_rules,
    )
    retriever = CanonicalRuleRetriever(
        index=index if index is not None else PostgresRuleIndex(),
        lookup=lookup if lookup is not None else PostgresRuleLookup(),
        max_rules=max_rules,
    )
    try:
        result = await retriever.retrieve(
            request, chunk_rule_ids=collect_rule_ids(evidence_items)
        )
    except Exception as exc:  # noqa: BLE001 — nunca frena la query
        logger.warning(
            "Canonical rule retrieval failed",
            organization_id=str(organization_id),
            error=str(exc)[:200],
        )
        result = RuleRetrievalResult(
            strategy="none", reasons=["retrieval_failure"], errors=[type(exc).__name__]
        )
    result.evidence_signal = rule_signal_from_evidence(evidence_items)
    if (
        not result.supported_rules
        and result.evidence_signal in ("rule_index_missing", "rule_fragment_present")
        and "index_missing" not in result.reasons
    ):
        result.reasons.append("index_missing")
    return result


def rules_metadata(rules: Sequence[CanonicalRule]) -> dict:
    return {
        "canonical_rules": [rule.to_dict() for rule in rules],
        "rule_retrieval_version": RULE_RETRIEVAL_VERSION,
    }


def attach_rules_to_items(items: Sequence[Any], rules: Sequence[CanonicalRule]) -> int:
    """Anota metadata de los items con las reglas cargadas (best-effort).

    El grounded engine puede consumir `canonical_rules=` directo; esto existe
    para caminos que solo transportan items (context compiler, auditoría).
    """
    if not rules:
        return 0
    payload = rules_metadata(rules)
    attached = 0
    for item in items or ():
        metadata = getattr(item, "metadata", None)
        if not isinstance(metadata, dict):
            continue
        try:
            item.metadata = {**metadata, **payload}
            attached += 1
        except Exception:  # noqa: BLE001, S112 — item inmutable: no se toca
            continue
    return attached


__all__ = [
    "CanonicalRuleRetriever",
    "InMemoryRuleIndex",
    "InMemoryRuleLookup",
    "MAX_RULES_PER_QUERY",
    "MIN_RULE_SCORE",
    "PostgresRuleIndex",
    "PostgresRuleLookup",
    "RULE_OBJECT_KIND",
    "RULE_RETRIEVAL_VERSION",
    "RuleIndexPort",
    "RuleLookupPort",
    "RuleRetrievalResult",
    "RuleSearchHit",
    "RuleSearchRequest",
    "WHY_NO_RULE",
    "attach_rules_to_items",
    "build_rule_search_request",
    "collect_rule_ids",
    "load_rules_for_evidence",
    "retrieve_canonical_rules",
    "rule_signal_from_evidence",
    "rules_metadata",
]
