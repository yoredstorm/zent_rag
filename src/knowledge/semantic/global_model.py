# =============================================================================
# GlobalSemanticModel — síntesis global estructurada (§19-20, §48)
# =============================================================================
# MAP (ventanas) -> REDUCE (regiones) -> RECONCILE (links globales)
# -> GLOBAL (modelo estructurado).
#
# El modelo global NO es un resumen. Contiene:
#   glossary, concepts, entities, rules, relationships, dependencies,
#   symbols, exceptions, procedures, conditions, claims, tables, conflicts,
#   unresolved items, temporal model, reference graph y semantic clusters.
#
# Cada item conserva unit_key + regiones + evidencia (block_ids) + ventanas.
# Determinista; la Fase 8 (Semantic Fabric) lo proyecta a nodos/relaciones.
# =============================================================================
from __future__ import annotations

import json
from dataclasses import dataclass, field
from hashlib import sha256
from uuid import UUID, uuid5

from src.knowledge.compiler.model import normalize_term

from .regional import RegionalSemanticModel
from .stitcher import StitchedUnit, StitchRelation
from .threads import SemanticThread

GLOBAL_MODEL_VERSION = "global-model-1"

GLOBAL_NS = UUID("a7d1e4f6-3c9b-4f5d-8a2e-9c6b1d4f7e85")

#: Tipos de relación que cuentan como dependencia semántica global.
DEPENDENCY_TYPES: tuple[str, ...] = (
    "DEFINES",
    "USES",
    "HAS_ATTRIBUTE",
    "HAS_CONDITION",
    "HAS_EXCEPTION",
    "PART_OF",
    "DERIVED_FROM",
)

_CATEGORY_KINDS: dict[str, str] = {
    "concepts": "concept",
    "entities": "entity",
    "rules": "rule",
    "symbols": "symbol",
    "exceptions": "exception",
    "procedures": "procedure",
    "conditions": "condition",
    "claims": "claim",
    "tables": "table",
    "conflicts": "conflict",
}


@dataclass(frozen=True, kw_only=True)
class GlobalSemanticModel:
    """Síntesis global estructurada de un documento (no un resumen)."""

    id: UUID
    organization_id: UUID
    source_id: UUID | None = None
    workspace_id: UUID | None = None
    document_id: UUID | None = None
    regions: tuple[str, ...] = ()
    glossary: tuple[dict, ...] = ()
    concepts: tuple[dict, ...] = ()
    entities: tuple[dict, ...] = ()
    rules: tuple[dict, ...] = ()
    symbols: tuple[dict, ...] = ()
    exceptions: tuple[dict, ...] = ()
    procedures: tuple[dict, ...] = ()
    conditions: tuple[dict, ...] = ()
    claims: tuple[dict, ...] = ()
    tables: tuple[dict, ...] = ()
    conflicts: tuple[dict, ...] = ()
    relationships: tuple[dict, ...] = ()
    dependencies: tuple[dict, ...] = ()
    unresolved_items: tuple[dict, ...] = ()
    temporal_model: dict = field(default_factory=dict)
    reference_graph: tuple[dict, ...] = ()
    semantic_clusters: tuple[dict, ...] = ()
    stats: dict = field(default_factory=dict)
    version: str = GLOBAL_MODEL_VERSION

    @property
    def fingerprint(self) -> str:
        material = {
            "version": self.version,
            "document_id": str(self.document_id) if self.document_id else None,
            "regions": list(self.regions),
            "glossary": [item.get("term") for item in self.glossary],
            "concepts": [item.get("unit_key") for item in self.concepts],
            "entities": [item.get("unit_key") for item in self.entities],
            "rules": [item.get("unit_key") for item in self.rules],
            "symbols": [item.get("unit_key") for item in self.symbols],
            "exceptions": [item.get("unit_key") for item in self.exceptions],
            "procedures": [item.get("unit_key") for item in self.procedures],
            "conditions": [item.get("unit_key") for item in self.conditions],
            "claims": [item.get("unit_key") for item in self.claims],
            "tables": [item.get("unit_key") for item in self.tables],
            "conflicts": [item.get("unit_key") for item in self.conflicts],
            "relationships": [
                item.get("relation_key") for item in self.relationships
            ],
            "dependencies": [item.get("relation_key") for item in self.dependencies],
            "unresolved": [
                item.get("thread_key") for item in self.unresolved_items
            ],
            "clusters": [item.get("cluster_id") for item in self.semantic_clusters],
        }
        raw = json.dumps(material, sort_keys=True, separators=(",", ":"), default=str)
        return sha256(raw.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "organization_id": str(self.organization_id),
            "source_id": str(self.source_id) if self.source_id else None,
            "workspace_id": str(self.workspace_id) if self.workspace_id else None,
            "document_id": str(self.document_id) if self.document_id else None,
            "regions": list(self.regions),
            "glossary": list(self.glossary),
            "concepts": list(self.concepts),
            "entities": list(self.entities),
            "rules": list(self.rules),
            "symbols": list(self.symbols),
            "exceptions": list(self.exceptions),
            "procedures": list(self.procedures),
            "conditions": list(self.conditions),
            "claims": list(self.claims),
            "tables": list(self.tables),
            "conflicts": list(self.conflicts),
            "relationships": list(self.relationships),
            "dependencies": list(self.dependencies),
            "unresolved_items": list(self.unresolved_items),
            "temporal_model": dict(self.temporal_model),
            "reference_graph": list(self.reference_graph),
            "semantic_clusters": list(self.semantic_clusters),
            "stats": dict(self.stats),
            "fingerprint": self.fingerprint,
            "version": self.version,
        }


class GlobalModelBuilder:
    """RECONCILE + GLOBAL: sintetiza regiones/unidades/relaciones."""

    version = GLOBAL_MODEL_VERSION

    def __init__(
        self,
        *,
        max_items_per_category: int = 5000,
        max_relationships: int = 20000,
        max_clusters: int = 500,
        max_units_per_cluster: int = 40,
        max_unresolved: int = 500,
    ) -> None:
        self._max_items = max(1, int(max_items_per_category))
        self._max_relations = max(1, int(max_relationships))
        self._max_clusters = max(1, int(max_clusters))
        self._max_cluster_units = max(1, int(max_units_per_cluster))
        self._max_unresolved = max(1, int(max_unresolved))

    def build(
        self,
        *,
        document,
        regions: list[RegionalSemanticModel],
        units: list[StitchedUnit],
        relations: list[StitchRelation],
        threads: list[SemanticThread],
    ) -> GlobalSemanticModel:
        unit_by_key = {unit.unit_key: unit for unit in units}
        region_by_window: dict[int, str] = {}
        for region in regions:
            for window in region.window_indexes:
                region_by_window.setdefault(int(window), region.region_id)
        unit_regions = self._unit_regions(units, regions, region_by_window)

        glossary = self._glossary(units, unit_regions)
        categories = {
            name: tuple(
                self._category_summary(unit, unit_regions)
                for unit in units
                if unit.unit_kind == kind
            )[: self._max_items]
            for name, kind in _CATEGORY_KINDS.items()
        }
        relation_summaries = tuple(
            self._relation_summary(relation, region_by_window)
            for relation in relations
        )[: self._max_relations]
        dependencies = tuple(
            summary
            for summary in relation_summaries
            if summary["relation_type"] in DEPENDENCY_TYPES
        )
        reference_graph = tuple(
            {
                "from": relation.subject_key,
                "to": relation.object_key,
                "confidence": round(float(relation.confidence), 4),
                "windows": list(relation.windows),
            }
            for relation in relations
            if relation.relation_type == "REFERENCES"
        )
        temporal_units = [unit for unit in units if unit.unit_kind == "temporal"]
        supersessions = [
            self._relation_summary(relation, region_by_window)
            for relation in relations
            if relation.relation_type == "SUPERSEDES"
        ]
        clusters = self._clusters(
            units=units,
            relations=relations,
            unit_regions=unit_regions,
            document_id=getattr(document, "id", None),
        )
        unresolved = tuple(
            self._thread_summary(thread)
            for thread in threads
            if thread.is_open
        )[: self._max_unresolved]
        cross_region = sum(
            1 for summary in relation_summaries if summary.get("cross_region")
        )

        return GlobalSemanticModel(
            id=uuid5(GLOBAL_NS, f"{getattr(document, 'id', None)}|global"),
            organization_id=document.organization_id,
            source_id=document.source_id,
            workspace_id=document.workspace_id,
            document_id=document.id,
            regions=tuple(region.region_id for region in regions),
            glossary=glossary,
            concepts=categories["concepts"],
            entities=categories["entities"],
            rules=categories["rules"],
            symbols=categories["symbols"],
            exceptions=categories["exceptions"],
            procedures=categories["procedures"],
            conditions=categories["conditions"],
            claims=categories["claims"],
            tables=categories["tables"],
            conflicts=categories["conflicts"],
            relationships=relation_summaries,
            dependencies=dependencies,
            unresolved_items=unresolved,
            temporal_model={
                "dates": [
                    {
                        "label": unit.label[:120],
                        "unit_key": unit.unit_key,
                        "windows": list(unit.source_windows),
                    }
                    for unit in temporal_units[:200]
                ],
                "supersessions": supersessions[:200],
                "windows_with_temporal": sorted(
                    {window for unit in temporal_units for window in unit.source_windows}
                ),
            },
            reference_graph=reference_graph,
            semantic_clusters=clusters,
            stats={
                "regions": len(regions),
                "units": len(units),
                "relations": len(relations),
                "dependencies": len(dependencies),
                "clusters": len(clusters),
                "unresolved": len(unresolved),
                "glossary": len(glossary),
                "cross_region_relations": cross_region,
                "unit_by_key": len(unit_by_key),
            },
        )

    # ------------------------------------------------------------------
    def _unit_regions(
        self,
        units: list[StitchedUnit],
        regions: list[RegionalSemanticModel],
        region_by_window: dict[int, str],
    ) -> dict[str, list[str]]:
        mapping: dict[str, list[str]] = {}
        for unit in units:
            found: list[str] = []
            for window in unit.source_windows:
                region_id = region_by_window.get(int(window))
                if region_id and region_id not in found:
                    found.append(region_id)
            mapping[unit.unit_key] = found
        return mapping

    def _glossary(
        self, units: list[StitchedUnit], unit_regions: dict[str, list[str]]
    ) -> tuple[dict, ...]:
        merged: dict[str, dict] = {}
        for unit in units:
            if unit.unit_kind != "definition" or not unit.label:
                continue
            term = normalize_term(unit.label)
            if not term:
                continue
            entry = {
                "term": unit.label[:200],
                "definition": unit.text[:400],
                "unit_key": unit.unit_key,
                "regions": unit_regions.get(unit.unit_key, []),
                "windows": list(unit.source_windows),
                "block_ids": list(unit.block_ids)[:8],
                "confidence": round(float(unit.confidence), 4),
            }
            existing = merged.get(term)
            if existing is None or len(entry["definition"]) > len(existing["definition"]):
                merged[term] = entry
        return tuple(
            merged[key] for key in sorted(merged)
        )[: self._max_items]

    def _category_summary(
        self, unit: StitchedUnit, unit_regions: dict[str, list[str]]
    ) -> dict:
        return {
            "unit_key": unit.unit_key,
            "unit_kind": unit.unit_kind,
            "label": unit.label[:200],
            "text": unit.text[:200],
            "confidence": round(float(unit.confidence), 4),
            "regions": unit_regions.get(unit.unit_key, []),
            "windows": list(unit.source_windows),
            "block_ids": list(unit.block_ids)[:8],
        }

    def _relation_summary(
        self, relation: StitchRelation, region_by_window: dict[int, str]
    ) -> dict:
        regions = sorted(
            {
                region_by_window[window]
                for window in relation.windows
                if window in region_by_window
            }
        )
        return {
            "relation_key": relation.relation_key,
            "relation_type": relation.relation_type,
            "subject_key": relation.subject_key,
            "object_key": relation.object_key,
            "subject_label": relation.subject_label[:200],
            "object_label": relation.object_label[:200],
            "confidence": round(float(relation.confidence), 4),
            "windows": list(relation.windows),
            "regions": regions,
            "cross_region": len(regions) > 1,
        }

    def _thread_summary(self, thread: SemanticThread) -> dict:
        return {
            "thread_key": thread.thread_key,
            "thread_type": thread.thread_type,
            "status": thread.status,
            "target_hint": thread.target_hint[:200],
            "opened_at_window": int(thread.opened_at_window),
            "confidence": round(float(thread.confidence), 4),
        }

    def _clusters(
        self,
        *,
        units: list[StitchedUnit],
        relations: list[StitchRelation],
        unit_regions: dict[str, list[str]],
        document_id,
    ) -> tuple[dict, ...]:
        parent: dict[str, str] = {}

        def find(key: str) -> str:
            parent.setdefault(key, key)
            while parent[key] != key:
                parent[key] = parent[parent[key]]
                key = parent[key]
            return key

        def union(left: str, right: str) -> None:
            root_left, root_right = find(left), find(right)
            if root_left != root_right:
                parent[root_right] = root_left

        unit_by_key = {unit.unit_key: unit for unit in units}
        for relation in relations:
            if relation.subject_key in unit_by_key and relation.object_key in unit_by_key:
                union(relation.subject_key, relation.object_key)

        groups: dict[str, list[str]] = {}
        for key in parent:
            groups.setdefault(find(key), []).append(key)

        clusters: list[dict] = []
        for members in groups.values():
            if len(members) < 2:
                continue
            member_units = [unit_by_key[key] for key in members if key in unit_by_key]
            if not member_units:
                continue
            best = max(member_units, key=lambda unit: unit.confidence)
            regions = sorted(
                {
                    region
                    for unit in member_units
                    for region in unit_regions.get(unit.unit_key, [])
                }
            )
            windows = sorted(
                {window for unit in member_units for window in unit.source_windows}
            )
            kinds: dict[str, int] = {}
            for unit in member_units:
                kinds[unit.unit_kind] = kinds.get(unit.unit_kind, 0) + 1
            clusters.append(
                {
                    "cluster_id": str(
                        uuid5(GLOBAL_NS, f"{document_id}|cluster:{best.unit_key}")
                    ),
                    "label": best.label[:200],
                    "unit_keys": [unit.unit_key for unit in member_units][
                        : self._max_cluster_units
                    ],
                    "unit_kinds": kinds,
                    "regions": regions,
                    "windows": windows,
                    "size": len(member_units),
                    "confidence": round(float(best.confidence), 4),
                }
            )
        clusters.sort(key=lambda item: (-item["size"], item["cluster_id"]))
        return tuple(clusters[: self._max_clusters])


__all__ = [
    "DEPENDENCY_TYPES",
    "GLOBAL_MODEL_VERSION",
    "GLOBAL_NS",
    "GlobalModelBuilder",
    "GlobalSemanticModel",
]
