# =============================================================================
# Company Discovery — fuentes de uso real (§7/§8/§9/§13)
# =============================================================================
# Estas fuentes son INTERPRETATIVAS: describen cómo trabaja la organización a
# partir de la ejecución observada, no de una declaración. Por eso nunca
# alcanzan CONFIRMED solas: acumulan soporte (runs exitosos, actores distintos,
# corroboración entre fuentes) y quedan en SUGGESTED para revisión humana.
#
# - SqlUsageSource: diccionario de negocio (término -> mapeo técnico).
# - ObservedProcessSource: proceso real (secuencia de pasos observada).
# - AuthorityCandidateSource: candidato a fuente de verdad.
# =============================================================================
from __future__ import annotations

import re
import unicodedata
from uuid import UUID

from src.company.discovery.source_base import DiscoverySource
from src.company.discovery.source_loaders import (
    load_authoritative_sql_signals,
    load_successful_sql,
    load_verified_queries,
    load_workflow_run_steps,
)
from src.company.discovery.sources_structured import _support
from src.core.domain.company_discovery import (
    AuthorityCandidatePayload,
    CandidateKind,
    DiscoveryCandidate,
    DiscoveryEvidence,
    DiscoverySourceKind,
    EntityRef,
    GapKind,
    KnowledgeGapPayload,
    MappingCandidatePayload,
    ProcessCandidatePayload,
    ProcessMode,
    ProcessStep,
    TermCandidatePayload,
)
from src.core.domain.company_graph import SourceAuthorityLevel

# Predicados físicos: COL = 'lit'  |  COL IN ('a','b',...)
_PREDICATE_RE = re.compile(
    r"(?P<col>[A-Za-z_][\w$]*(?:\.[A-Za-z_][\w$]*)?)\s*"
    r"(?P<op>=|\bin\b)\s*"
    r"(?P<vals>\([^()]{0,240}\)|'[^']{0,60}')",
    re.IGNORECASE,
)
_LITERAL_RE = re.compile(r"'([^']{0,60})'")
_TOKEN_RE = re.compile(r"[A-Za-zÁÉÍÓÚÑÜáéíóúñü][A-Za-zÁÉÍÓÚÑÜáéíóúñü0-9_]{3,}")

# Palabras que no son términos de negocio.
_STOPWORDS = frozenset(
    {
        "select", "from", "where", "group", "order", "having", "join", "left",
        "right", "inner", "outer", "count", "sum", "avg", "min", "max", "case",
        "when", "then", "else", "end", "null", "true", "false", "limit", "offset",
        "distinct", "union", "total", "todos", "todas", "cuantos", "cuantas",
        "cuales", "what", "which", "that", "this", "with", "without", "last",
        "first", "into", "over", "between", "como", "cuando", "donde", "para",
        "porque", "sobre", "entre", "desde", "hasta", "lista", "listar", "dame",
        "muestra", "mostrar", "year", "month", "day", "date",
    }
)

# Términos que no deben volverse conceptos por sí solos.
_GENERIC_TOKENS = frozenset(
    {"pending", "status", "total", "amount", "value", "code", "date", "type"}
) | _STOPWORDS


def normalize_term(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.lower().split())


def extract_predicates(sql: str) -> list[tuple[str, tuple[str, ...]]]:
    """Predicados físicos (columna, valores) presentes en un SQL.

    Solo lee igualdades y listas IN con literales: es observación, no
    generación de SQL. Nunca se construye ni se ejecuta SQL desde aquí.
    """
    found: list[tuple[str, tuple[str, ...]]] = []
    for match in _PREDICATE_RE.finditer(sql or ""):
        column = match.group("col")
        if "." in column:
            column = column.rsplit(".", 1)[-1]
        values = tuple(
            value.strip() for value in _LITERAL_RE.findall(match.group("vals") or "")
        )
        if not values:
            continue
        found.append((column.strip(), values[:8]))
    return found


def extract_terms(question: str) -> list[str]:
    """Términos de negocio candidatos en la pregunta del usuario."""
    terms: list[str] = []
    for raw in _TOKEN_RE.findall(question or ""):
        term = normalize_term(raw)
        if len(term) < 4 or term.isdigit():
            continue
        if term in _STOPWORDS:
            continue
        if term not in terms:
            terms.append(term)
    return terms[:12]


class SqlUsageSource(DiscoverySource):
    """Diccionario de negocio desde consultas exitosas (§7).

    El ejemplo del spec: los usuarios dicen "pending" y el SQL exitoso filtra
    repetidamente `A1672STO0 IN ('0','')`. El candidato es
    Concept Pending Transaction MAPS_TO A1672STO0 con valores 0 y blank — con
    evidencia acumulada, no por una ocurrencia.
    """

    source_kind = DiscoverySourceKind.SQL_QUERY
    name = "sql_usage"

    def __init__(
        self,
        *,
        loader_sql=load_successful_sql,
        loader_verified=load_verified_queries,
        min_runs: int = 3,
        max_items: int | None = None,
    ) -> None:
        super().__init__(max_items=max_items)
        self._load_sql = loader_sql
        self._load_verified = loader_verified
        self.min_runs = min_runs

    async def discover(
        self, organization_id: UUID, *, workspace_id: UUID | None = None
    ) -> list[DiscoveryCandidate]:
        rows = await self._load_sql(organization_id, self.max_items)
        verified = await self._load_verified(organization_id, self.max_items)

        pairs: dict[tuple[str, str], dict] = {}
        term_stats: dict[str, dict] = {}
        for row in rows:
            question = str(row.get("question") or "")
            sql = str(row.get("generated_sql") or "")
            actor = str(row.get("user_id") or "")
            predicates = extract_predicates(sql)
            terms = extract_terms(question)
            for term in terms:
                stat = term_stats.setdefault(term, {"occurrences": 0, "actors": set(), "mapped": False, "refs": []})
                stat["occurrences"] += 1
                if actor:
                    stat["actors"].add(actor)
                if len(stat["refs"]) < 3:
                    stat["refs"].append(str(row.get("id")))
                if predicates:
                    stat["mapped"] = True
            for term in terms:
                for column, values in predicates:
                    key = (term, column)
                    entry = pairs.setdefault(
                        key,
                        {
                            "runs": 0,
                            "actors": set(),
                            "values": {},
                            "refs": [],
                            "questions": [],
                        },
                    )
                    entry["runs"] += 1
                    if actor:
                        entry["actors"].add(actor)
                    for value in values:
                        entry["values"][value] = entry["values"].get(value, 0) + 1
                    if len(entry["refs"]) < 5:
                        entry["refs"].append(str(row.get("id")))
                    if len(entry["questions"]) < 3:
                        entry["questions"].append(question[:200])

        verified_columns: set[str] = set()
        for row in verified:
            sql = str(row.get("verified_sql") or "")
            for column, _values in extract_predicates(sql):
                verified_columns.add(column.lower())

        candidates: list[DiscoveryCandidate] = []
        for (term, column), entry in pairs.items():
            if entry["runs"] < self.min_runs:
                continue
            values = tuple(
                value
                for value, _count in sorted(
                    entry["values"].items(), key=lambda kv: kv[1], reverse=True
                )[:4]
            )
            distinct_sources = 1 + (1 if column.lower() in verified_columns else 0)
            actors = len(entry["actors"])
            payload = MappingCandidatePayload(
                concept_ref=EntityRef("concept", term),
                target_ref=EntityRef("field", column),
                values=values,
                predicate=f"{column} IN ({', '.join(repr(v) for v in values)})",
            )
            candidates.append(
                self.build_candidate(
                    organization_id=organization_id,
                    kind=CandidateKind.MAPPING,
                    payload=payload.to_dict(),
                    title=f"{term} MAPS_TO {column}",
                    summary=(
                        f"{entry['runs']} successful queries pair the term with "
                        f"{column}"
                    ),
                    support=_support(
                        structural=False,
                        observations=entry["runs"],
                        distinct_sources=distinct_sources,
                        distinct_actors=actors,
                        successful_runs=entry["runs"],
                    ),
                    evidence=DiscoveryEvidence(
                        source_kind=self.source_kind,
                        ref=entry["refs"][0] if entry["refs"] else term,
                        detail={
                            "column": column,
                            "values": list(values),
                            "runs": entry["runs"],
                            "distinct_actors": actors,
                            "questions": entry["questions"],
                        },
                        excerpt=entry["questions"][0] if entry["questions"] else "",
                    ),
                    workspace_id=workspace_id,
                )
            )

        # Términos frecuentes sin mapeo técnico -> hueco de conocimiento (§11).
        for term, stat in term_stats.items():
            if stat["occurrences"] < self.min_runs or stat["mapped"]:
                continue
            if term in _GENERIC_TOKENS:
                continue
            gap = KnowledgeGapPayload(
                gap_kind=GapKind.MISSING_TECHNICAL_MAPPING,
                subject=term,
                detail=(
                    f"business term used in {stat['occurrences']} successful "
                    "queries without a technical mapping"
                ),
                observed_runs=stat["occurrences"],
                evidence_summary=tuple(stat["refs"][:3]),
            )
            candidates.append(
                self.build_candidate(
                    organization_id=organization_id,
                    kind=CandidateKind.KNOWLEDGE_GAP,
                    payload=gap.to_dict(),
                    title=f"Gap: {term} has no technical mapping",
                    summary=gap.summary(),
                    support=_support(
                        structural=False,
                        observations=stat["occurrences"],
                        distinct_sources=1,
                        distinct_actors=len(stat["actors"]),
                        successful_runs=stat["occurrences"],
                    ),
                    evidence=DiscoveryEvidence(
                        source_kind=self.source_kind,
                        ref=stat["refs"][0] if stat["refs"] else term,
                        detail={"occurrences": stat["occurrences"]},
                    ),
                    workspace_id=workspace_id,
                )
            )

        # Diccionario de negocio: terminología observada (§7).
        for term, stat in term_stats.items():
            if stat["occurrences"] < self.min_runs or term in _GENERIC_TOKENS:
                continue
            payload = TermCandidatePayload(
                term=term,
                aliases=(term,),
                proposed_concept=term,
                domain="business",
            )
            candidates.append(
                self.build_candidate(
                    organization_id=organization_id,
                    kind=CandidateKind.TERM,
                    payload=payload.to_dict(),
                    title=f"Business term: {term}",
                    summary=f"observed in {stat['occurrences']} successful queries",
                    support=_support(
                        structural=False,
                        observations=stat["occurrences"],
                        distinct_sources=1,
                        distinct_actors=len(stat["actors"]),
                        successful_runs=stat["occurrences"],
                    ),
                    evidence=DiscoveryEvidence(
                        source_kind=self.source_kind,
                        ref=stat["refs"][0] if stat["refs"] else term,
                        detail={"mapped": stat["mapped"]},
                    ),
                    workspace_id=workspace_id,
                )
            )
        return candidates


class ObservedProcessSource(DiscoverySource):
    """Proceso OBSERVED: lo que realmente corre (§9/§10)."""

    source_kind = DiscoverySourceKind.EVENT
    name = "observed_process"

    def __init__(self, *, loader=load_workflow_run_steps, max_items: int | None = None) -> None:
        super().__init__(max_items=max_items)
        self._load = loader

    async def discover(
        self, organization_id: UUID, *, workspace_id: UUID | None = None
    ) -> list[DiscoveryCandidate]:
        rows = await self._load(organization_id, self.max_items * 3)
        runs: dict[str, list[dict]] = {}
        meta: dict[str, dict] = {}
        for row in rows:
            run_id = str(row.get("run_id") or "")
            if not run_id:
                continue
            runs.setdefault(run_id, []).append(row)
            workflow_id = str(row.get("workflow_id") or "")
            if workflow_id:
                meta.setdefault(
                    workflow_id,
                    {
                        "workflow_id": workflow_id,
                        "workflow_name": str(row.get("workflow_name") or ""),
                    },
                )

        per_workflow: dict[str, dict] = {}
        for run_id, steps in runs.items():
            ordered = sorted(steps, key=lambda item: int(item.get("step_index") or 0))
            workflow_id = str(ordered[0].get("workflow_id") or "")
            if not workflow_id:
                continue
            entry = per_workflow.setdefault(
                workflow_id,
                {"runs": 0, "steps": {}, "order": {}, "run_ids": []},
            )
            entry["runs"] += 1
            if len(entry["run_ids"]) < 5:
                entry["run_ids"].append(run_id)
            for position, step in enumerate(ordered):
                node = str(step.get("node_id") or "").strip()
                if not node:
                    continue
                entry["steps"][node] = entry["steps"].get(node, 0) + 1
                entry["order"].setdefault(node, position)

        candidates: list[DiscoveryCandidate] = []
        for workflow_id, entry in per_workflow.items():
            runs_count = max(1, entry["runs"])
            name = (
                meta.get(workflow_id, {}).get("workflow_name")
                or f"workflow:{workflow_id}"
            )
            steps = tuple(
                ProcessStep(
                    name=node,
                    order=entry["order"].get(node, 0),
                    frequency=count / runs_count,
                    runs=count,
                    documented=False,
                )
                for node, count in sorted(
                    entry["steps"].items(), key=lambda kv: (-kv[1], kv[0])
                )
            )
            payload = ProcessCandidatePayload(
                name=name,
                mode=ProcessMode.OBSERVED,
                steps=steps,
                runs_observed=entry["runs"],
                workflow_id=workflow_id,
            )
            candidates.append(
                self.build_candidate(
                    organization_id=organization_id,
                    kind=CandidateKind.PROCESS,
                    payload=payload.to_dict(),
                    title=f"OBSERVED process: {name}",
                    summary=f"{entry['runs']} observed runs, {len(steps)} distinct steps",
                    support=_support(
                        structural=False,
                        observations=entry["runs"],
                        distinct_sources=1,
                        successful_runs=entry["runs"],
                    ),
                    evidence=DiscoveryEvidence(
                        source_kind=self.source_kind,
                        ref=str(entry["run_ids"][0]) if entry["run_ids"] else workflow_id,
                        detail={
                            "runs": entry["runs"],
                            "workflow_id": workflow_id,
                            "steps": {node: count for node, count in entry["steps"].items()},
                        },
                    ),
                    workspace_id=workspace_id,
                )
            )
        return candidates


class AuthorityCandidateSource(DiscoverySource):
    """Candidato a fuente de verdad desde ejecución consistente (§13).

    Propone, no decide: la confirmación es administrativa (o por la regla de
    authority ya configurada en Fase 5A).
    """

    source_kind = DiscoverySourceKind.VERIFIED_QUERY
    name = "source_authority_candidate"

    def __init__(
        self, *, loader=load_authoritative_sql_signals, max_items: int | None = None
    ) -> None:
        super().__init__(max_items=max_items)
        self._load = loader

    async def discover(
        self, organization_id: UUID, *, workspace_id: UUID | None = None
    ) -> list[DiscoveryCandidate]:
        rows = await self._load(organization_id, self.max_items)
        candidates: list[DiscoveryCandidate] = []
        for row in rows:
            concept = str(row.get("concept") or row.get("column_name") or "").strip()
            table = str(row.get("table_name") or "").strip()
            column = str(row.get("column_name") or "").strip()
            if not concept or not table:
                continue
            runs = int(row.get("runs") or 0)
            actors = int(row.get("actors") or 0)
            payload = AuthorityCandidatePayload(
                domain="data",
                concept=concept.lower(),
                source_name=table,
                proposed_level=SourceAuthorityLevel.PRIMARY,
                rationale=(
                    f"{runs} verified queries across {actors} users resolve "
                    f"'{concept}' through {table}.{column}"
                ),
                source_type="database",
            )
            candidates.append(
                self.build_candidate(
                    organization_id=organization_id,
                    kind=CandidateKind.SOURCE_AUTHORITY,
                    payload=payload.to_dict(),
                    title=f"{table} as authority for {concept}",
                    summary=payload.rationale,
                    support=_support(
                        structural=False,
                        observations=runs,
                        distinct_sources=1,
                        distinct_actors=actors,
                        successful_runs=runs,
                    ),
                    evidence=DiscoveryEvidence(
                        source_kind=self.source_kind,
                        ref=f"{table}.{column}",
                        detail={"runs": runs, "actors": actors},
                    ),
                    workspace_id=workspace_id,
                )
            )
        return candidates


__all__ = [
    "AuthorityCandidateSource",
    "ObservedProcessSource",
    "SqlUsageSource",
    "extract_predicates",
    "extract_terms",
    "normalize_term",
]
