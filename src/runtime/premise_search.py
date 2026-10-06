# =============================================================================
# Premise Search adapters — búsqueda dirigida sobre Rule Index y evidencia
# =============================================================================
# Implementaciones concretas del puerto `PremiseSearchPort`:
#
#   RuleIndexPremiseSearch   consultas pequeñas -> Rule Index (léxico/símbolo)
#                            + lane de evidencia opcional (inyectada)
#   source_local_expander    reglas del MISMO documento/sección antes de saltar
#                            a contenido global
#   fabric_expander          vecinos conocidos del grafo (USES_SYMBOL,
#                            DEPENDS_ON, DEFINES, SUPPORTED_BY, HAS_*)
#
# Sin scope cerrado no hay búsqueda: una premisa no justifica escanear todo el
# tenant. Todo es fail-soft: un error de índice se reporta y el loop decide.
# =============================================================================
from __future__ import annotations

from typing import Any, Awaitable, Callable, Sequence
from uuid import UUID

from src.infrastructure.observability.logging_config import get_logger
from src.knowledge.rule_compiler.index import (
    merge_rule_candidates,
    query_tokens,
)
from src.knowledge.rule_compiler.model import CanonicalRule

from .premise_closure import (
    LANE_EXACT,
    LANE_SYMBOL,
    EvidenceHit,
    PlannedPremiseQuery,
    PremiseClosureRequest,
    PremiseSearchOutcome,
    SourceScope,
    premises_covered_by_text,
)
from .rule_retrieval import (
    RULE_OBJECT_KIND,
    RuleSearchRequest,
    _rule_from_row,
)

logger = get_logger(__name__)

PREMISE_SEARCH_VERSION = "premise-search-1"

MAX_RULES_PER_QUERY = 8
MAX_EVIDENCE_PER_QUERY = 6

EvidenceSearchFn = Callable[[str, SourceScope, int], Awaitable[Sequence[Any]]]


def _as_uuid(value: Any) -> UUID | None:
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _scope_from(scope: SourceScope) -> dict[str, Any]:
    return {
        "workspace_id": _as_uuid(scope.workspace_id),
        "source_ids": tuple(
            value for value in (_as_uuid(item) for item in scope.source_ids) if value
        ),
        "document_ids": tuple(
            value for value in (_as_uuid(item) for item in scope.document_ids) if value
        ),
    }


class RuleIndexPremiseSearch:
    """Premise-directed search: Rule Index por consulta + evidencia opcional."""

    def __init__(
        self,
        *,
        index: Any,
        organization_id: UUID | str,
        evidence_search: EvidenceSearchFn | None = None,
        operation_intent: str = "",
        max_results_per_query: int = MAX_RULES_PER_QUERY,
        max_evidence_per_query: int = MAX_EVIDENCE_PER_QUERY,
        model_hits_extra: Callable[[Sequence[Any]], Sequence[Any]] | None = None,
    ) -> None:
        self._index = index
        self._organization_id = organization_id
        self._evidence_search = evidence_search
        self._operation_intent = operation_intent
        self._max_results = max(1, int(max_results_per_query))
        self._max_evidence = max(1, int(max_evidence_per_query))
        self._model_hits_extra = model_hits_extra

    async def search(
        self,
        request: PremiseClosureRequest,
        queries: Sequence[PlannedPremiseQuery],
        *,
        round_index: int,
        focus: SourceScope | None = None,
    ) -> PremiseSearchOutcome:
        del round_index
        scope = focus or request.source_scope
        scope_args = _scope_from(scope)
        scored_hits: list[tuple[Any, float, str]] = []
        evidence: list[EvidenceHit] = []
        exact_hits: list[str] = []
        errors: list[str] = []

        for query in queries:
            symbols = ()
            symbol = query.symbol
            if symbol:
                symbols = (symbol,)
            search_request = RuleSearchRequest(
                organization_id=_as_uuid(self._organization_id)
                or UUID(int=0),
                query=query.query,
                workspace_id=scope_args["workspace_id"],
                source_ids=scope_args["source_ids"],
                document_ids=scope_args["document_ids"],
                tokens=query_tokens(query.query, [*query.terms, *request.field_context])[:16],
                anchors=tuple(
                    dict.fromkeys(
                        [
                            *((request.runtime_pattern,) if request.runtime_pattern else ()),
                            *query.terms[:2],
                        ]
                    )
                )[:6],
                entities=tuple(str(value) for value in request.domain_entities[:6]),
                concepts=tuple(str(value) for value in request.field_context[:6]),
                symbols=symbols,
                operation_intent=self._operation_intent,
                max_results=self._max_results,
            )
            try:
                index_hits = await self._index.search(search_request)
            except Exception as exc:  # noqa: BLE001 — índice fail-soft
                errors.append(f"index:{type(exc).__name__}")
                index_hits = []
            for hit in index_hits:
                score = float(getattr(hit, "score", 0.0))
                if symbol and symbol in _rule_symbols(getattr(hit, "rule", None)):
                    score += 10.0
                if query.lane == LANE_EXACT:
                    score += 4.0
                elif query.lane == LANE_SYMBOL:
                    score += 2.0
                scored_hits.append((hit.rule, score, query.lane))

            if self._evidence_search is None:
                continue
            try:
                raw_items = await self._evidence_search(
                    query.query, scope, self._max_evidence
                )
            except Exception as exc:  # noqa: BLE001 — evidencia fail-soft
                errors.append(f"evidence:{type(exc).__name__}")
                continue
            for item in raw_items or ():
                hit = _evidence_hit(item, request, query)
                if hit is None:
                    continue
                if symbol and symbol in hit.content and query.lane == LANE_EXACT:
                    exact_hits.append(symbol)
                    hit.score += 2.0
                evidence.append(hit)

        rules = merge_rule_candidates(
            scored_hits, max_rules=request.max_new_rules_per_round
        )
        if self._model_hits_extra is not None:
            extra = self._model_hits_extra(rules)
            if extra:
                rules = merge_rule_candidates(
                    [
                        *((rule, 1.0, "extra") for rule in rules),
                        *((rule, 0.5, "extra") for rule in extra),
                    ],
                    max_rules=request.max_new_rules_per_round,
                )
        evidence = _dedupe_evidence(evidence)[: request.max_new_evidence_per_round]
        return PremiseSearchOutcome(
            rules=tuple(rules),
            evidence=tuple(evidence),
            queries=tuple(queries),
            exact_symbol_hits=tuple(dict.fromkeys(exact_hits)),
            errors=tuple(errors),
        )


def _rule_symbols(rule: Any) -> tuple[str, ...]:
    try:
        from src.knowledge.rule_compiler.index import rule_symbols

        return tuple(rule_symbols(rule))
    except Exception:  # noqa: BLE001
        return ()


def _evidence_hit(
    item: Any,
    request: PremiseClosureRequest,
    query: PlannedPremiseQuery,
) -> EvidenceHit | None:
    content = ""
    for attribute in ("content", "text", "statement", "excerpt"):
        value = getattr(item, attribute, None)
        if value:
            content = str(value)
            break
    if not content and isinstance(item, dict):
        for key in ("content", "text", "statement", "excerpt"):
            if item.get(key):
                content = str(item[key])
                break
    content = " ".join(content.split())
    if not content:
        return None
    metadata = getattr(item, "metadata", None)
    if not isinstance(metadata, dict):
        metadata = item.get("metadata") if isinstance(item, dict) else None
    metadata = metadata if isinstance(metadata, dict) else {}
    matched = tuple(
        premise
        for premise in request.normalized_missing()
        if premises_covered_by_text(premise, content)
    )
    section_path = (
        getattr(item, "section_path", None) or metadata.get("section_path") or ()
    )
    evidence_id = str(
        getattr(item, "evidence_id", None)
        or metadata.get("evidence_id")
        or metadata.get("chunk_id")
        or ""
    )
    return EvidenceHit(
        evidence_id=evidence_id,
        content=content[:4000],
        document_id=str(
            getattr(item, "document_id", None) or metadata.get("document_id") or ""
        ),
        source_id=str(
            getattr(item, "source_id", None) or metadata.get("source_id") or ""
        ),
        page=getattr(item, "page", None) or metadata.get("page"),
        section_path=tuple(str(part) for part in section_path or ()),
        score=1.0,
        matched_premises=tuple(dict.fromkeys([query.premise, *matched])),
    )


def _dedupe_evidence(evidence: Sequence[EvidenceHit]) -> list[EvidenceHit]:
    best: dict[str, EvidenceHit] = {}
    for hit in evidence:
        identity = hit.identity
        current = best.get(identity)
        if current is None or hit.score > current.score:
            best[identity] = hit
    return [best[key] for key in sorted(best)]


# -----------------------------------------------------------------------------
# Expansión source-local: mismo documento/sección antes que búsqueda global
# -----------------------------------------------------------------------------


def make_source_local_expander(
    organization_id: UUID | str,
    *,
    max_rules_per_document: int = 60,
) -> Callable[[Sequence[Any], PremiseClosureRequest], Awaitable[list[CanonicalRule]]]:
    async def expand(
        rules: Sequence[Any], request: PremiseClosureRequest
    ) -> list[CanonicalRule]:
        document_ids: list[str] = []
        for rule in rules or ():
            scope = getattr(rule, "scope", None)
            document_id = str(getattr(scope, "document_id", "") or "")
            if document_id and document_id not in document_ids:
                document_ids.append(document_id)
        for value in request.source_scope.document_ids:
            if value and value not in document_ids:
                document_ids.append(value)
        if not document_ids:
            return []
        known = {
            str(getattr(rule, "rule_id", "") or "") for rule in rules or ()
        }
        expanded: list[CanonicalRule] = []
        for document_id in document_ids[:4]:
            for rule in await load_document_rules(
                organization_id,
                document_id,
                limit=max_rules_per_document,
            ):
                if str(getattr(rule, "rule_id", "")) in known:
                    continue
                expanded.append(rule)
        return expanded

    return expand


async def load_document_rules(
    organization_id: UUID | str,
    document_id: str,
    *,
    limit: int = 60,
) -> list[CanonicalRule]:
    """Reglas canónicas del mismo documento (source-local expansion)."""
    org = _as_uuid(organization_id)
    if org is None or not document_id:
        return []
    from sqlalchemy import text as sql_text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                sql_text(
                    "SELECT id, name, description, confidence, metadata "
                    "FROM knowledge_canonical_objects "
                    "WHERE organization_id = :org AND LOWER(kind) = :kind "
                    "AND metadata->>'document_id' = :document "
                    "ORDER BY updated_at DESC, id ASC LIMIT :limit"
                ),
                {
                    "org": org,
                    "kind": RULE_OBJECT_KIND,
                    "document": str(document_id),
                    "limit": max(1, min(int(limit), 200)),
                },
            )
        ).all()
    except Exception as exc:  # noqa: BLE001 — expansión fail-soft
        logger.warning("source-local expansion failed", error=str(exc)[:160])
        return []
    finally:
        await session.close()
    rules: list[CanonicalRule] = []
    for row in rows:
        rule = _rule_from_row(row)
        if rule is not None:
            rules.append(rule)
    return rules


# -----------------------------------------------------------------------------
# Expansión por grafo de reglas (Knowledge Fabric proyectado)
# -----------------------------------------------------------------------------

_FABRIC_RELATIONS = (
    "USES_SYMBOL",
    "DEPENDS_ON",
    "DEFINES",
    "CONSTRAINS",
    "APPLIES_TO",
    "SUPPORTED_BY",
    "HAS_CONDITION",
    "HAS_EXCEPTION",
    "HAS_CONSEQUENCE",
    "REFERENCES",
    "SAME_SECTION",
)


def make_fabric_expander(
    organization_id: UUID | str,
    *,
    max_neighbors: int = 24,
) -> Callable[[Sequence[Any], PremiseClosureRequest], Awaitable[list[CanonicalRule]]]:
    """Vecinos del grafo: si el Fabric ya conoce la relación, no hay vector search."""

    async def expand(
        rules: Sequence[Any], request: PremiseClosureRequest
    ) -> list[CanonicalRule]:
        org = _as_uuid(organization_id)
        rule_ids = [
            str(value)
            for value in (
                _fabric_rule_key(rule) for rule in rules or ()
            )
            if value
        ]
        if org is None or not rule_ids:
            return []
        from sqlalchemy import text as sql_text

        from src.infrastructure.postgres.session import get_async_session

        session = await get_async_session()
        try:
            rows = (
                await session.execute(
                    sql_text(
                        "SELECT DISTINCT e2.subject_key "
                        "FROM knowledge_fabric_edges e1 "
                        "JOIN knowledge_fabric_edges e2 "
                        "  ON e2.organization_id = e1.organization_id "
                        " AND (e2.object_id = e1.object_id "
                        "      OR e2.subject_id = e1.object_id "
                        "      OR e2.subject_id = e1.subject_id) "
                        "WHERE e1.organization_id = :org "
                        "AND e1.relation_type = ANY(CAST(:relations AS text[])) "
                        "AND e1.subject_key = ANY(CAST(:rule_keys AS text[])) "
                        "AND e2.subject_key LIKE 'rule:%' "
                        "LIMIT :limit"
                    ),
                    {
                        "org": org,
                        "relations": list(_FABRIC_RELATIONS),
                        "rule_keys": list(dict.fromkeys(rule_ids))[:24],
                        "limit": max(1, min(int(max_neighbors), 64)),
                    },
                )
            ).all()
        except Exception as exc:  # noqa: BLE001 — fabric ausente no rompe el loop
            logger.debug("fabric expansion skipped", error=str(exc)[:160])
            return []
        finally:
            await session.close()

        neighbor_keys = [str(row.subject_key) for row in rows if row.subject_key]
        return await _load_rules_by_fabric_keys(
            org,
            neighbor_keys,
            exclude={str(getattr(rule, "rule_id", "")) for rule in rules or ()},
        )

    return expand


def _fabric_rule_key(rule: Any) -> str:
    rule_id = str(getattr(rule, "rule_id", "") or "")
    if not rule_id:
        return ""
    return rule_id if rule_id.startswith("rule:") else f"rule:{rule_id}"


async def _load_rules_by_fabric_keys(
    organization_id: UUID,
    keys: Sequence[str],
    *,
    exclude: set[str],
) -> list[CanonicalRule]:
    if not keys:
        return []
    from sqlalchemy import text as sql_text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                sql_text(
                    "SELECT id, name, description, confidence, metadata "
                    "FROM knowledge_canonical_objects "
                    "WHERE organization_id = :org AND LOWER(kind) = :kind "
                    "AND (natural_key = ANY(CAST(:keys AS text[])) "
                    "     OR metadata->>'canonical_rule_id' = ANY(CAST(:rule_ids AS text[]))) "
                    "LIMIT 64"
                ),
                {
                    "org": organization_id,
                    "kind": RULE_OBJECT_KIND,
                    "keys": [key for key in keys if key.startswith("rule:")][:48],
                    "rule_ids": [key.split("rule:", 1)[-1] for key in keys][:48],
                },
            )
        ).all()
    except Exception as exc:  # noqa: BLE001
        logger.debug("fabric neighbor load skipped", error=str(exc)[:160])
        return []
    finally:
        await session.close()
    rules: list[CanonicalRule] = []
    for row in rows:
        rule = _rule_from_row(row)
        if rule is not None and str(rule.rule_id) not in exclude:
            rules.append(rule)
    return rules


__all__ = [
    "EvidenceSearchFn",
    "PREMISE_SEARCH_VERSION",
    "RuleIndexPremiseSearch",
    "load_document_rules",
    "make_fabric_expander",
    "make_source_local_expander",
]
