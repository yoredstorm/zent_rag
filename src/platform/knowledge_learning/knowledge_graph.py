# =============================================================================
# Knowledge Graph & Gaps — representación visual del negocio aprendido (F33C)
# =============================================================================
# PostgreSQL es suficiente (sin Neo4j): nodos y aristas se derivan de tablas
# reales del catálogo, con confidence, provenance, status, source y validación.
#
# Nodos: Entity, Field, Metric, Dimension, Business Rule, Synonym,
#        Verified Question, Data Source.
# Aristas: relaciones entity-entity (con evidencia), entity-field,
#        metric-field, rule-entity/field, synonym-entity, source-entity.
# =============================================================================
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from src.catalog.store import PostgresCatalogStore
from src.infrastructure.observability.logging_config import get_logger
from src.intelligence.store import PostgresIntelligenceStore

logger = get_logger(__name__)

_CONFIDENCE_SCORE = {"high": 0.9, "medium": 0.65, "low": 0.4}
_STALE_DAYS = 14.0
_LOW_COVERAGE = 60.0

_NODE_PRIORITY = {
    "datasource": 0,
    "entity": 1,
    "metric": 2,
    "rule": 3,
    "dimension": 4,
    "verified_question": 5,
    "synonym": 6,
    "field": 7,
}


def _score_from_confidence(value: str | float | None) -> float:
    if isinstance(value, (int, float)):
        return round(max(0.0, min(1.0, float(value))), 4)
    return _CONFIDENCE_SCORE.get(str(value or "low"), 0.4)


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()
    return f"{prefix}:{digest[:16]}"


def _normalize(text: str) -> str:
    return " ".join((text or "").lower().replace("_", " ").split())


@dataclass
class GraphNode:
    id: str
    type: str
    label: str
    description: str = ""
    confidence: float = 0.0
    provenance: str = "INFERRED"
    status: str = "draft"
    source_id: str | None = None
    source_name: str | None = None
    last_learned_at: str | None = None
    validation_state: str = "unvalidated"
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "label": self.label,
            "description": self.description,
            "confidence": self.confidence,
            "provenance": self.provenance,
            "status": self.status,
            "source_id": self.source_id,
            "source_name": self.source_name,
            "last_learned_at": self.last_learned_at,
            "validation_state": self.validation_state,
            "metadata": self.metadata,
        }


@dataclass
class GraphEdge:
    id: str
    type: str
    from_node_id: str
    to_node_id: str
    label: str
    confidence: float = 0.0
    provenance: str = "INFERRED"
    status: str = "suggested"
    cardinality: str | None = None
    evidence: list[str] = field(default_factory=list)
    evidence_detail: list[dict] = field(default_factory=list)
    source_id: str | None = None
    last_learned_at: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "from": self.from_node_id,
            "to": self.to_node_id,
            "label": self.label,
            "confidence": self.confidence,
            "provenance": self.provenance,
            "status": self.status,
            "cardinality": self.cardinality,
            "evidence": self.evidence,
            "evidence_detail": self.evidence_detail,
            "source_id": self.source_id,
            "last_learned_at": self.last_learned_at,
        }


class KnowledgeGraphService:
    """Construye el Knowledge Map y los gaps accionables desde datos reales."""

    def __init__(
        self,
        catalog_store: PostgresCatalogStore,
        *,
        intelligence_store: PostgresIntelligenceStore | None = None,
        repository: Any | None = None,
    ) -> None:
        self._store = catalog_store
        self._intel = intelligence_store or PostgresIntelligenceStore()
        self._repo = repository

    # ------------------------------------------------------------------ graph
    async def build(
        self,
        organization_id: UUID,
        *,
        source_id: UUID | None = None,
        node_types: set[str] | None = None,
        q: str | None = None,
        limit_nodes: int = 300,
        limit_edges: int = 600,
    ) -> dict:
        sources = await self._store.list_sources(organization_id)
        if source_id is not None:
            sources = [s for s in sources if s["id"] == str(source_id)]
        source_by_id = {s["id"]: s for s in sources}

        tables: list[dict] = []
        relationships: list[dict] = []
        for source in sources:
            source_tables = await self._store.list_tables(
                organization_id, UUID(source["id"]), limit=5000
            )
            tables.extend(source_tables)
            relationships.extend(
                await self._store.list_relationships(
                    organization_id, UUID(source["id"]), limit=5000
                )
            )
        tables_by_id = {t["id"]: t for t in tables}

        entities = await self._store.list_entities(organization_id, limit=2000)
        entities = [
            e
            for e in entities
            if e.get("mapped_table_id") in tables_by_id
            or e.get("mapped_table_id") is None
        ]
        entity_by_table = {
            e["mapped_table_id"]: e
            for e in entities
            if e.get("mapped_table_id") and e.get("mapped_table_id") in tables_by_id
        }
        fields_all = await self._store.list_fields_all(organization_id, limit=5000)
        fields_by_entity: dict[str, list[dict]] = {}
        for fld in fields_all:
            fields_by_entity.setdefault(fld["entity_id"], []).append(fld)
        field_ids = {f["id"]: f for f in fields_all}

        try:
            metrics = await self._store.list_metrics(organization_id, limit=1000)
        except Exception:  # noqa: BLE001
            metrics = []
        try:
            definitions = await self._intel.list_definitions(organization_id)
        except Exception:  # noqa: BLE001
            definitions = []
        rules = []
        if self._repo is not None:
            try:
                rules = await self._repo.list_business_rules(
                    organization_id, limit=500
                )
            except Exception:  # noqa: BLE001
                rules = []
        try:
            lexicon = await self._store.list_lexicon(organization_id)
        except Exception:  # noqa: BLE001
            lexicon = []
        try:
            from src.intelligence.verified_query_store import (
                PostgresVerifiedQueryStore,
            )

            verified = await PostgresVerifiedQueryStore().list_verified(organization_id)
        except Exception:  # noqa: BLE001
            verified = []
        if source_id is not None:
            verified = [
                v
                for v in verified
                if str(source_id) in {str(s) for s in (v.source_ids or [])}
            ]

        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []

        # ---------------------------------------------------------- datasources
        for source in sources:
            node = GraphNode(
                id=f"datasource:{source['id']}",
                type="datasource",
                label=f"{(source.get('engine') or 'Source')} · {source['id'][:8]}",
                description="Fuente de datos conectada.",
                confidence=0.9 if source.get("phase") in ("COMPLETED", "WAITING_REVIEW") else 0.5,
                provenance="OBSERVED",
                status="active",
                source_id=source["id"],
                source_name=source.get("engine"),
                last_learned_at=source.get("last_scan_at"),
                validation_state="validated",
                metadata={
                    "phase": source.get("phase"),
                    "connector_id": source.get("connector_id"),
                    "scan_error": source.get("scan_error"),
                },
            )
            nodes.append(node)

        # ------------------------------------------------------------- entities
        for entity in entities:
            table = tables_by_id.get(entity.get("mapped_table_id") or "")
            entity_fields = fields_by_entity.get(entity["id"], [])
            entity_rels = [
                r
                for r in relationships
                if r.get("from_table_id") == entity.get("mapped_table_id")
                or r.get("to_table_id") == entity.get("mapped_table_id")
            ]
            last_learned = max(
                (
                    r.get("last_learned_at")
                    for r in entity_rels
                    if r.get("last_learned_at")
                ),
                default=None,
            ) or (table.get("detected_at") if table else None)
            node = GraphNode(
                id=f"entity:{entity['id']}",
                type="entity",
                label=entity.get("display_name") or entity.get("name"),
                description=entity.get("description") or "",
                confidence=_score_from_confidence(entity.get("confidence")),
                provenance=entity.get("provenance") or "INFERRED",
                status=entity.get("status") or "draft",
                source_id=table.get("source_id") if table else None,
                source_name=(
                    source_by_id.get(table.get("source_id"), {}).get("engine")
                    if table
                    else None
                ),
                last_learned_at=last_learned,
                validation_state="validated"
                if entity.get("status") == "approved"
                else "unvalidated",
                metadata={
                    "name": entity.get("name"),
                    "table": table.get("qualified_name") if table else None,
                    "fields_total": len(entity_fields),
                    "fields_approved": sum(
                        1 for f in entity_fields if f.get("status") == "approved"
                    ),
                    "relationships_total": len(entity_rels),
                    "relationships_confirmed": sum(
                        1 for r in entity_rels if r.get("status") == "confirmed"
                    ),
                },
            )
            nodes.append(node)
            if table is not None:
                edges.append(
                    GraphEdge(
                        id=_stable_id("edge", "source-entity", table.get("source_id", ""), entity["id"]),
                        type="contains",
                        from_node_id=f"datasource:{table['source_id']}",
                        to_node_id=node.id,
                        label="contains",
                        confidence=0.9,
                        provenance="OBSERVED",
                        status="confirmed",
                        source_id=table.get("source_id"),
                    )
                )

        # --------------------------------------------------------------- fields
        for fld in fields_all:
            if fld["entity_id"] not in {e["id"] for e in entities}:
                continue
            node = GraphNode(
                id=f"field:{fld['id']}",
                type="field",
                label=fld.get("name") or "",
                description=fld.get("description") or "",
                confidence=_score_from_confidence(fld.get("confidence")),
                provenance=fld.get("provenance") or "INFERRED",
                status=fld.get("status") or "draft",
                last_learned_at=None,
                validation_state="validated"
                if fld.get("status") == "approved"
                else "unvalidated",
                metadata={
                    "role": fld.get("role"),
                    "mapped_column_id": fld.get("mapped_column_id"),
                    "synonyms": fld.get("synonyms") or [],
                },
            )
            nodes.append(node)
            edges.append(
                GraphEdge(
                    id=_stable_id("edge", "has-field", fld["entity_id"], fld["id"]),
                    type="has_field",
                    from_node_id=f"entity:{fld['entity_id']}",
                    to_node_id=node.id,
                    label="has field",
                    confidence=_score_from_confidence(fld.get("confidence")),
                    provenance=fld.get("provenance") or "INFERRED",
                    status="confirmed" if fld.get("status") == "approved" else "suggested",
                )
            )

        # ---------------------------------------------------------- relationships
        for rel in relationships:
            from_entity = entity_by_table.get(rel.get("from_table_id"))
            to_entity = entity_by_table.get(rel.get("to_table_id"))
            if from_entity is None or to_entity is None:
                continue  # tablas sin entidad: aparecen como gaps, no como modelo
            edges.append(
                GraphEdge(
                    id=f"relationship:{rel['id']}",
                    type="relationship",
                    from_node_id=f"entity:{from_entity['id']}",
                    to_node_id=f"entity:{to_entity['id']}",
                    label=rel.get("business_verb") or "references",
                    confidence=float(rel.get("confidence_score") or 0.0)
                    or _score_from_confidence(rel.get("confidence")),
                    provenance=rel.get("provenance") or "INFERRED",
                    status=rel.get("status") or "suggested",
                    cardinality=rel.get("cardinality"),
                    evidence=list(rel.get("evidence") or []),
                    evidence_detail=list(rel.get("evidence_detail") or []),
                    source_id=rel.get("source_id"),
                    last_learned_at=rel.get("last_learned_at"),
                )
            )

        # ---------------------------------------------------------------- others
        entity_ids = {e["id"] for e in entities}
        for metric in metrics:
            node = GraphNode(
                id=f"metric:{metric['id']}",
                type="metric",
                label=metric.get("name") or metric.get("metric_key") or "",
                description=metric.get("definition") or "",
                confidence=0.9 if metric.get("status") == "approved" else 0.55,
                provenance="APPROVED" if metric.get("status") == "approved" else "INFERRED",
                status=metric.get("status") or "draft",
                validation_state="validated"
                if metric.get("status") == "approved"
                else "unvalidated",
                metadata={
                    "metric_key": metric.get("metric_key"),
                    "formula": metric.get("formula"),
                    "version": metric.get("version"),
                },
            )
            nodes.append(node)
            self._link_metric_fields(metric, node, field_ids, fields_all, edges)

        for definition in definitions:
            data_type = getattr(definition, "data_type", "concept")
            if data_type != "dimension":
                continue
            concept = getattr(definition, "concept", "")
            node = GraphNode(
                id=f"dimension:{concept}",
                type="dimension",
                label=concept,
                description=getattr(definition, "definition", "") or "",
                confidence=0.9 if getattr(definition, "status", "") == "approved" else 0.6,
                provenance=getattr(definition, "provenance", "APPROVED"),
                status=getattr(definition, "status", "draft"),
                validation_state="validated"
                if getattr(definition, "status", "") == "approved"
                else "unvalidated",
                metadata={"expression": getattr(definition, "expression", None)},
            )
            nodes.append(node)

        for rule in rules:
            node = GraphNode(
                id=f"rule:{rule['id']}",
                type="rule",
                label=rule.get("name") or "",
                description=rule.get("definition") or "",
                confidence=_score_from_confidence(rule.get("confidence")),
                provenance=rule.get("provenance") or "INFERRED",
                status="approved"
                if rule.get("provenance") == "APPROVED"
                else "draft",
                last_learned_at=rule.get("last_learned_at"),
                validation_state="validated"
                if rule.get("provenance") == "APPROVED"
                else "unvalidated",
                metadata={"applies_to": rule.get("applies_to") or []},
            )
            nodes.append(node)
            for target in rule.get("applies_to") or []:
                entity = next(
                    (
                        e
                        for e in entities
                        if _normalize(e.get("name")) == _normalize(str(target))
                        or _normalize(e.get("display_name")) == _normalize(str(target))
                    ),
                    None,
                )
                if entity is not None:
                    edges.append(
                        GraphEdge(
                            id=_stable_id("edge", "applies-to", rule["id"], entity["id"]),
                            type="applies_to",
                            from_node_id=node.id,
                            to_node_id=f"entity:{entity['id']}",
                            label="applies to",
                            confidence=node.confidence,
                            provenance=node.provenance,
                            status="confirmed"
                            if node.provenance == "APPROVED"
                            else "suggested",
                        )
                    )

        for entry in lexicon:
            node = GraphNode(
                id=f"synonym:{entry['id']}",
                type="synonym",
                label=entry.get("token") or "",
                description=entry.get("meaning") or "",
                confidence=0.9 if entry.get("status") == "approved" else 0.6,
                provenance="APPROVED" if entry.get("status") == "approved" else "INFERRED",
                status=entry.get("status") or "signal",
                validation_state="validated"
                if entry.get("status") == "approved"
                else "unvalidated",
                metadata={"role": entry.get("role")},
            )
            nodes.append(node)
            meaning = _normalize(entry.get("meaning", ""))
            match = next(
                (
                    e
                    for e in entities
                    if meaning
                    and (
                        meaning == _normalize(e.get("name"))
                        or meaning == _normalize(e.get("display_name"))
                    )
                ),
                None,
            )
            if match is not None:
                edges.append(
                    GraphEdge(
                        id=_stable_id("edge", "synonym", entry["id"], match["id"]),
                        type="synonym_of",
                        from_node_id=node.id,
                        to_node_id=f"entity:{match['id']}",
                        label="synonym of",
                        confidence=node.confidence,
                        provenance=node.provenance,
                        status="confirmed" if node.provenance == "APPROVED" else "suggested",
                    )
                )

        for vq in verified:
            node = GraphNode(
                id=f"verified_question:{vq.id}",
                type="verified_question",
                label=vq.canonical_question,
                description=vq.description or "",
                confidence=0.95,
                provenance="APPROVED",
                status="verified",
                validation_state="validated",
                metadata={"name": vq.name, "version": vq.version},
            )
            nodes.append(node)

        # ----------------------------------------------------------- filter/caps
        if node_types:
            nodes = [n for n in nodes if n.type in node_types]
        if q:
            needle = q.strip().lower()
            nodes = [
                n
                for n in nodes
                if needle in n.label.lower()
                or needle in (n.description or "").lower()
                or needle in json.dumps(n.metadata, default=str).lower()
            ]
        nodes.sort(key=lambda n: (_NODE_PRIORITY.get(n.type, 99), -n.confidence))
        node_ids = {n.id for n in nodes}
        nodes = nodes[: max(1, min(limit_nodes, 2000))]
        node_ids = {n.id for n in nodes}
        edges = [
            e
            for e in edges
            if e.from_node_id in node_ids and e.to_node_id in node_ids
        ][: max(1, min(limit_edges, 4000))]

        counts: dict[str, int] = {}
        for node in nodes:
            counts[node.type] = counts.get(node.type, 0) + 1
        return {
            "nodes": [n.to_dict() for n in nodes],
            "edges": [e.to_dict() for e in edges],
            "counts": {"nodes": len(nodes), "edges": len(edges), "by_type": counts},
            "truncated": len(nodes) >= limit_nodes,
        }

    @staticmethod
    def _link_metric_fields(
        metric: dict,
        node: GraphNode,
        field_ids: dict[str, dict],
        fields_all: list[dict],
        edges: list[GraphEdge],
    ) -> None:
        linked: set[str] = set()
        for mapping in metric.get("physical_mappings") or []:
            if not isinstance(mapping, dict):
                continue
            column_id = mapping.get("column_id") or mapping.get("mapped_column_id")
            if not column_id:
                continue
            for fld in fields_all:
                if fld.get("mapped_column_id") == str(column_id) and fld["id"] not in linked:
                    linked.add(fld["id"])
                    edges.append(
                        GraphEdge(
                            id=_stable_id("edge", "metric-field", metric["id"], fld["id"]),
                            type="uses_field",
                            from_node_id=node.id,
                            to_node_id=f"field:{fld['id']}",
                            label="uses field",
                            confidence=node.confidence,
                            provenance=node.provenance,
                            status="confirmed"
                            if metric.get("status") == "approved"
                            else "suggested",
                        )
                    )

    # -------------------------------------------------- what zent learned
    async def learned_entities(
        self,
        organization_id: UUID,
        *,
        source_id: UUID | None = None,
        limit: int = 100,
    ) -> list[dict]:
        entities = await self._store.list_entities(organization_id, limit=2000)
        if source_id is not None:
            tables = await self._store.list_tables(
                organization_id, source_id, limit=5000
            )
            table_ids = {t["id"] for t in tables}
            entities = [
                e for e in entities if e.get("mapped_table_id") in table_ids
            ]
        relationships = []
        sources = await self._store.list_sources(organization_id)
        source_ids = (
            [source_id] if source_id is not None else [UUID(s["id"]) for s in sources]
        )
        for sid in source_ids:
            relationships.extend(
                await self._store.list_relationships(
                    organization_id, sid, limit=5000
                )
            )
        rules = []
        if self._repo is not None:
            try:
                rules = await self._repo.list_business_rules(organization_id, limit=1000)
            except Exception:  # noqa: BLE001
                rules = []
        pending_by_entity: dict[str, int] = {}
        if self._repo is not None:
            try:
                pending_by_entity = await self._repo.count_pending_questions_by_entity(
                    organization_id
                )
            except Exception:  # noqa: BLE001
                pending_by_entity = {}

        out: list[dict] = []
        fields_by_entity: dict[str, list[dict]] = {}
        try:
            all_fields = await self._store.list_fields_all(
                organization_id, limit=5000
            )
            for fld in all_fields:
                fields_by_entity.setdefault(fld["entity_id"], []).append(fld)
        except Exception:  # noqa: BLE001
            all_fields = []
        for entity in entities:
            fields = fields_by_entity.get(str(entity["id"]), [])
            rels = [
                r
                for r in relationships
                if r.get("from_table_id") == entity.get("mapped_table_id")
                or r.get("to_table_id") == entity.get("mapped_table_id")
            ]
            entity_names = {
                _normalize(entity.get("name")),
                _normalize(entity.get("display_name")),
            }
            entity_rules = [
                r
                for r in rules
                if any(
                    _normalize(str(target)) in entity_names
                    or any(
                        _normalize(str(target)) == _normalize(f.get("name"))
                        for f in fields
                    )
                    for target in (r.get("applies_to") or [])
                )
            ]
            table = None
            if entity.get("mapped_table_id"):
                try:
                    table = await self._store.get_table(
                        organization_id, UUID(entity["mapped_table_id"])
                    )
                except Exception:  # noqa: BLE001
                    table = None
            columns_total = 0
            if table is not None:
                columns_total = len(
                    await self._store.list_columns(
                        organization_id, UUID(table["id"])
                    )
                )
            mapped_fields = [f for f in fields if f.get("mapped_column_id")]
            coverage = (
                round(len(mapped_fields) / max(columns_total, 1) * 100, 1)
                if columns_total
                else None
            )
            last_learned = max(
                (
                    r.get("last_learned_at")
                    for r in rels
                    if r.get("last_learned_at")
                ),
                default=None,
            )
            out.append(
                {
                    "entity_id": entity["id"],
                    "name": entity.get("name"),
                    "display_name": entity.get("display_name"),
                    "description": entity.get("description"),
                    "confidence": _score_from_confidence(entity.get("confidence")),
                    "confidence_label": entity.get("confidence"),
                    "provenance": entity.get("provenance"),
                    "status": entity.get("status"),
                    "table": table.get("qualified_name") if table else None,
                    "source_id": table.get("source_id") if table else None,
                    "fields_total": len(fields),
                    "fields_understood": len(mapped_fields),
                    "columns_total": columns_total,
                    "coverage_pct": coverage,
                    "relationships_total": len(rels),
                    "relationships_confirmed": sum(
                        1 for r in rels if r.get("status") == "confirmed"
                    ),
                    "business_rules_total": len(entity_rules),
                    "business_rules_approved": sum(
                        1 for r in entity_rules if r.get("provenance") == "APPROVED"
                    ),
                    "open_questions": int(
                        pending_by_entity.get(str(entity["id"]), 0)
                    ),
                    "last_learned_at": last_learned,
                }
            )
        out.sort(key=lambda item: (-item["confidence"], item["name"] or ""))
        return out[: max(1, min(limit, 500))]

    # ---------------------------------------------------------------- gaps
    async def gaps(
        self,
        organization_id: UUID,
        *,
        source_id: UUID | None = None,
        limit: int = 200,
    ) -> dict:
        gaps: list[dict] = []
        now = datetime.now(timezone.utc)

        # Gaps estructurados ya persistidos (Intelligence Layer).
        try:
            stored = await self._intel.list_gaps(
                organization_id, status="open", limit=100
            )
        except Exception:  # noqa: BLE001
            stored = []
        for gap in stored:
            gaps.append(
                {
                    "id": f"context:{gap.get('id')}",
                    "gap_type": gap.get("gap_type") or "CONTEXT_MISSING",
                    "severity": "high" if int(gap.get("occurrences") or 1) >= 3 else "medium",
                    "impact": gap.get("impact") or {},
                    "suggested_action": "resolve_context_gap",
                    "concept": gap.get("concept"),
                    "related_source_id": None,
                    "evidence": gap.get("evidence_hints") or [],
                }
            )

        # Evaluación RAG (FASE 33G): sin auto-evaluación o por debajo del umbral.
        try:
            from sqlalchemy import text

            from src.infrastructure.postgres.session import get_async_session

            session = await get_async_session()
            try:
                eval_row = (
                    await session.execute(
                        text(
                            "SELECT summary FROM eval_runs "
                            "WHERE organization_id = :oid AND status = 'completed' "
                            "AND dataset_name LIKE 'knowledge-auto%' "
                            "ORDER BY created_at DESC LIMIT 1"
                        ),
                        {"oid": organization_id},
                    )
                ).fetchone()
            finally:
                await session.close()
            eval_summary = eval_row.summary if isinstance(eval_row.summary, dict) else None
            if eval_summary is None:
                gaps.append(
                    {
                        "id": _stable_id("gap", "evaluation", "none"),
                        "gap_type": "LOW_DATA_QUALITY",
                        "severity": "medium",
                        "impact": {"evaluation": "missing"},
                        "suggested_action": "run_evaluation",
                        "concept": "evaluación RAG",
                        "related_source_id": None,
                        "evidence": ["sin auto-evaluación de conocimiento (knowledge-auto)"],
                    }
                )
            else:
                quality = eval_summary.get("quality") or {}
                composite = quality.get("composite_score")
                precision = quality.get("retrieval_precision")
                recall = quality.get("retrieval_recall")
                low_retrieval = (
                    isinstance(precision, (int, float))
                    and isinstance(recall, (int, float))
                    and (precision + recall) / 2 < 0.5
                )
                if not isinstance(composite, (int, float)) or composite < 0.6 or low_retrieval:
                    gaps.append(
                        {
                            "id": _stable_id("gap", "evaluation", "low"),
                            "gap_type": "LOW_DATA_QUALITY",
                            "severity": "high"
                            if (not isinstance(composite, (int, float)) or composite < 0.4)
                            else "medium",
                            "impact": {
                                "composite_score": (
                                    round(float(composite), 4)
                                    if isinstance(composite, (int, float))
                                    else None
                                ),
                                "retrieval_precision": precision,
                                "retrieval_recall": recall,
                            },
                            "suggested_action": "improve_knowledge_or_resync",
                            "concept": "evaluación RAG",
                            "related_source_id": None,
                            "evidence": [
                                "auto-evaluación por debajo del umbral de calidad"
                            ],
                        }
                    )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Evaluation gap detection failed", error=str(exc)[:200])

        sources = await self._store.list_sources(organization_id)
        if source_id is not None:
            sources = [s for s in sources if s["id"] == str(source_id)]

        for source in sources:
            sid = UUID(source["id"])
            source_ref = source["id"]
            last_scan = source.get("last_scan_at")
            if source.get("phase") in ("FAILED", "PARTIAL"):
                gaps.append(
                    {
                        "id": _stable_id("gap", "source_conflict", source_ref),
                        "gap_type": "SOURCE_CONFLICT",
                        "severity": "critical" if source["phase"] == "FAILED" else "high",
                        "impact": {"connection": True},
                        "suggested_action": "review_source_connection",
                        "concept": source.get("engine") or source_ref[:8],
                        "related_source_id": source_ref,
                        "evidence": [f"phase={source['phase']}"],
                    }
                )
            if last_scan:
                try:
                    scanned = datetime.fromisoformat(last_scan)
                    if scanned.tzinfo is None:
                        scanned = scanned.replace(tzinfo=timezone.utc)
                    days = (now - scanned).total_seconds() / 86400
                    if days > _STALE_DAYS:
                        gaps.append(
                            {
                                "id": _stable_id("gap", "stale", source_ref),
                                "gap_type": "STALE_SOURCE",
                                "severity": "high" if days > 30 else "medium",
                                "impact": {"staleness_days": round(days, 1)},
                                "suggested_action": "run_learning_again",
                                "concept": source.get("engine") or source_ref[:8],
                                "related_source_id": source_ref,
                                "evidence": [f"last_scan hace {round(days, 1)} días"],
                            }
                        )
                except ValueError:
                    pass

            tables = await self._store.list_tables(organization_id, sid, limit=5000)
            relations = await self._store.list_relationships(
                organization_id, sid, limit=5000
            )
            entities = await self._store.list_entities(organization_id, limit=2000)
            entity_by_table = {
                e["mapped_table_id"]: e
                for e in entities
                if e.get("mapped_table_id")
            }
            for table in tables:
                if table["id"] not in entity_by_table:
                    gaps.append(
                        {
                            "id": _stable_id("gap", "table_no_entity", table["id"]),
                            "gap_type": "MISSING_TABLE",
                            "severity": "medium",
                            "impact": {"table": table.get("qualified_name")},
                            "suggested_action": "confirm_entity_mapping",
                            "concept": table.get("qualified_name"),
                            "related_source_id": source_ref,
                            "evidence": ["tabla sin entidad de negocio mapeada"],
                        }
                    )
            for rel in relations:
                if (
                    rel.get("status") == "suggested"
                    and float(rel.get("confidence_score") or 0) >= 0.5
                ):
                    gaps.append(
                        {
                            "id": _stable_id("gap", "relationship", rel["id"]),
                            "gap_type": "MISSING_RELATIONSHIP",
                            "severity": "high"
                            if float(rel.get("confidence_score") or 0) >= 0.75
                            else "medium",
                            "impact": {
                                "confidence": rel.get("confidence_score"),
                                "from": rel.get("from_column"),
                            },
                            "suggested_action": "confirm_relationship",
                            "concept": f"{rel.get('from_column')} -> {rel.get('to_column')}",
                            "related_source_id": source_ref,
                            "evidence": rel.get("evidence") or [],
                        }
                    )
            for entity in entities:
                if entity.get("mapped_table_id") not in {
                    t["id"] for t in tables
                }:
                    continue
                fields = await self._store.list_fields(
                    organization_id, UUID(entity["id"])
                )
                if not fields:
                    gaps.append(
                        {
                            "id": _stable_id("gap", "entity_no_fields", entity["id"]),
                            "gap_type": "MISSING_FIELD",
                            "severity": "high",
                            "impact": {"entity": entity.get("name")},
                            "suggested_action": "review_semantic_mapping",
                            "concept": entity.get("name"),
                            "related_entity_id": entity["id"],
                            "related_source_id": source_ref,
                            "evidence": ["entidad sin campos de negocio"],
                        }
                    )
                    continue
                columns_total = 0
                if entity.get("mapped_table_id"):
                    columns_total = len(
                        await self._store.list_columns(
                            organization_id, UUID(entity["mapped_table_id"])
                        )
                    )
                mapped = [f for f in fields if f.get("mapped_column_id")]
                if columns_total and len(mapped) / columns_total * 100 < _LOW_COVERAGE:
                    gaps.append(
                        {
                            "id": _stable_id("gap", "low_coverage", entity["id"]),
                            "gap_type": "MISSING_FIELD",
                            "severity": "medium",
                            "impact": {
                                "coverage_pct": round(
                                    len(mapped) / columns_total * 100, 1
                                )
                            },
                            "suggested_action": "map_more_fields",
                            "concept": entity.get("name"),
                            "related_entity_id": entity["id"],
                            "related_source_id": source_ref,
                            "evidence": [
                                f"{len(mapped)}/{columns_total} columnas mapeadas"
                            ],
                        }
                    )
                for fld in fields:
                    scores = fld.get("signal_scores") or {}
                    if isinstance(scores, str):
                        try:
                            scores = json.loads(scores)
                        except (TypeError, ValueError):
                            scores = {}
                    if scores.get("llm_role_conflict"):
                        gaps.append(
                            {
                                "id": _stable_id("gap", "conflict", fld["id"]),
                                "gap_type": "AMBIGUOUS_TERM",
                                "severity": "high",
                                "impact": {"llm_role": scores.get("llm_role_conflict")},
                                "suggested_action": "ask_business_question",
                                "concept": fld.get("name"),
                                "related_entity_id": entity["id"],
                                "related_source_id": source_ref,
                                "evidence": ["heurística y LLM discrepan en el rol"],
                            }
                        )

        gaps.sort(
            key=lambda g: (
                {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(
                    g.get("severity"), 4
                ),
                g.get("gap_type"),
            )
        )
        by_severity: dict[str, int] = {}
        by_type: dict[str, int] = {}
        for gap in gaps:
            by_severity[gap["severity"]] = by_severity.get(gap["severity"], 0) + 1
            by_type[gap["gap_type"]] = by_type.get(gap["gap_type"], 0) + 1
        return {
            "gaps": gaps[: max(1, min(limit, 1000))],
            "count": min(len(gaps), max(1, min(limit, 1000))),
            "total": len(gaps),
            "by_severity": by_severity,
            "by_type": by_type,
        }
