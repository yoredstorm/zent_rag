# =============================================================================
# RegionalSemanticModel — comprensión regional (§18)
# =============================================================================
# Cuando varias ventanas pertenecen a una región lógica (capítulo, sección,
# hoja, grupo de API, schema, thread, cluster de tópicos), se consolidan:
#
#   definitions, rules, concepts, entities, exceptions, relationships,
#   unresolved dependencies
#
# La región NO sustituye evidencia: cada item conserva unit_key, block_ids y
# ventanas. Determinista; la Fase 7 (global) consume estos modelos.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from uuid import UUID, uuid5

from src.knowledge.compiler.model import normalize_term

from .contracts import SemanticWindowPlan, SemanticWindowResult
from .stitcher import StitchedUnit, StitchRelation
from .threads import SemanticThread

REGIONAL_VERSION = "regional-model-1"

REGION_NS = UUID("f6c9d3e5-2b8a-4e4c-9f7d-8b5a9c3e2d64")

#: Categorías consolidadas por región (kinds del stitcher).
_REGION_CATEGORIES: dict[str, str] = {
    "definitions": "definition",
    "rules": "rule",
    "concepts": "concept",
    "entities": "entity",
    "exceptions": "exception",
    "procedures": "procedure",
    "conditions": "condition",
    "symbols": "symbol",
    "claims": "claim",
    "tables": "table",
    "conflicts": "conflict",
}

_DOCUMENT_REGION = "document"


@dataclass(frozen=True, kw_only=True)
class RegionalSemanticModel:
    """Consolidación regional de unidades/relaciones (no evidencia cruda)."""

    id: UUID
    region_id: str
    label: str
    organization_id: UUID
    source_id: UUID | None = None
    workspace_id: UUID | None = None
    document_id: UUID | None = None
    window_start: int = 0
    window_end: int = 0
    window_indexes: tuple[int, ...] = ()
    definitions: tuple[dict, ...] = ()
    rules: tuple[dict, ...] = ()
    concepts: tuple[dict, ...] = ()
    entities: tuple[dict, ...] = ()
    exceptions: tuple[dict, ...] = ()
    procedures: tuple[dict, ...] = ()
    conditions: tuple[dict, ...] = ()
    symbols: tuple[dict, ...] = ()
    claims: tuple[dict, ...] = ()
    tables: tuple[dict, ...] = ()
    conflicts: tuple[dict, ...] = ()
    relationships: tuple[dict, ...] = ()
    unresolved_dependencies: tuple[dict, ...] = ()
    stats: dict = field(default_factory=dict)
    version: str = REGIONAL_VERSION

    @property
    def fingerprint(self) -> str:
        material = {
            "version": self.version,
            "region_id": self.region_id,
            "document_id": str(self.document_id) if self.document_id else None,
            "window_indexes": list(self.window_indexes),
            "definitions": [item.get("unit_key") for item in self.definitions],
            "rules": [item.get("unit_key") for item in self.rules],
            "concepts": [item.get("unit_key") for item in self.concepts],
            "entities": [item.get("unit_key") for item in self.entities],
            "exceptions": [item.get("unit_key") for item in self.exceptions],
            "procedures": [item.get("unit_key") for item in self.procedures],
            "conditions": [item.get("unit_key") for item in self.conditions],
            "symbols": [item.get("unit_key") for item in self.symbols],
            "claims": [item.get("unit_key") for item in self.claims],
            "tables": [item.get("unit_key") for item in self.tables],
            "conflicts": [item.get("unit_key") for item in self.conflicts],
            "relationships": [item.get("relation_key") for item in self.relationships],
            "unresolved": [
                item.get("thread_key") for item in self.unresolved_dependencies
            ],
        }
        import json

        raw = json.dumps(material, sort_keys=True, separators=(",", ":"), default=str)
        return sha256(raw.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "region_id": self.region_id,
            "label": self.label,
            "organization_id": str(self.organization_id),
            "source_id": str(self.source_id) if self.source_id else None,
            "workspace_id": str(self.workspace_id) if self.workspace_id else None,
            "document_id": str(self.document_id) if self.document_id else None,
            "window_start": int(self.window_start),
            "window_end": int(self.window_end),
            "window_indexes": list(self.window_indexes),
            "definitions": list(self.definitions),
            "rules": list(self.rules),
            "concepts": list(self.concepts),
            "entities": list(self.entities),
            "exceptions": list(self.exceptions),
            "procedures": list(self.procedures),
            "conditions": list(self.conditions),
            "symbols": list(self.symbols),
            "claims": list(self.claims),
            "tables": list(self.tables),
            "conflicts": list(self.conflicts),
            "relationships": list(self.relationships),
            "unresolved_dependencies": list(self.unresolved_dependencies),
            "stats": dict(self.stats),
            "fingerprint": self.fingerprint,
            "version": self.version,
        }


class RegionalModelBuilder:
    """Agrupa ventanas en regiones y consolida unidades/relaciones."""

    version = REGIONAL_VERSION

    def __init__(
        self,
        *,
        max_items_per_category: int = 2000,
        max_relations: int = 4000,
        max_unresolved: int = 500,
    ) -> None:
        self._max_items = max(1, int(max_items_per_category))
        self._max_relations = max(1, int(max_relations))
        self._max_unresolved = max(1, int(max_unresolved))

    def build(
        self,
        *,
        document,
        plan: SemanticWindowPlan | None,
        results: list[SemanticWindowResult],
        units: list[StitchedUnit],
        relations: list[StitchRelation],
        threads: list[SemanticThread],
    ) -> list[RegionalSemanticModel]:
        if not results:
            return []
        region_windows, region_labels = self._detect_regions(document, plan, results)
        models: list[RegionalSemanticModel] = []
        for region_id, windows in region_windows.items():
            window_set = set(windows)
            region_units = [
                unit
                for unit in units
                if window_set.intersection(unit.source_windows)
            ]
            region_relations = [
                relation
                for relation in relations
                if window_set.intersection(relation.windows)
                and _relation_in_region(relation, region_units)
            ]
            region_threads = [
                thread
                for thread in threads
                if thread.is_open
                and (
                    window_set.intersection(thread.source_windows)
                    or int(thread.opened_at_window) in window_set
                )
            ]
            categories: dict[str, tuple[dict, ...]] = {
                name: tuple(
                    _unit_summary(unit)
                    for unit in region_units
                    if unit.unit_kind == kind
                )[: self._max_items]
                for name, kind in _REGION_CATEGORIES.items()
            }
            models.append(
                RegionalSemanticModel(
                    id=uuid5(
                        REGION_NS,
                        f"{getattr(document, 'id', None)}|{region_id}",
                    ),
                    region_id=region_id,
                    label=region_labels.get(region_id, region_id),
                    organization_id=document.organization_id,
                    source_id=document.source_id,
                    workspace_id=document.workspace_id,
                    document_id=document.id,
                    window_start=min(windows),
                    window_end=max(windows),
                    window_indexes=tuple(windows),
                    definitions=categories["definitions"],
                    rules=categories["rules"],
                    concepts=categories["concepts"],
                    entities=categories["entities"],
                    exceptions=categories["exceptions"],
                    procedures=categories["procedures"],
                    conditions=categories["conditions"],
                    symbols=categories["symbols"],
                    claims=categories["claims"],
                    tables=categories["tables"],
                    conflicts=categories["conflicts"],
                    relationships=tuple(
                        _relation_summary(relation)
                        for relation in region_relations
                    )[: self._max_relations],
                    unresolved_dependencies=tuple(
                        _thread_summary(thread) for thread in region_threads
                    )[: self._max_unresolved],
                    stats={
                        "windows": len(windows),
                        "units": len(region_units),
                        "relations": len(region_relations),
                        "unresolved": len(region_threads),
                        "coverage": round(
                            len(
                                {
                                    result.window_index
                                    for result in results
                                    if result.window_index in window_set
                                    and result.status in ("complete", "partial")
                                }
                            )
                            / max(1, len(windows)),
                            4,
                        ),
                    },
                )
            )
        return models

    # ------------------------------------------------------------------
    def _detect_regions(
        self,
        document,
        plan: SemanticWindowPlan | None,
        results: list[SemanticWindowResult],
    ) -> tuple[dict[str, list[int]], dict[str, str]]:
        """Ventana -> región lógica (capítulo/sección de primer nivel)."""
        regions: dict[str, list[int]] = {}
        labels: dict[str, str] = {}
        blocks = [block for block in document.blocks if _indexable(block)]
        section_by_id = {section.id: section for section in document.sections}
        section_by_block = {}
        for section in document.sections:
            for block_id in section.block_ids:
                section_by_block[block_id] = section
        specs = {spec.window_index: spec for spec in (plan.windows if plan else ())}
        for result in sorted(results, key=lambda item: item.window_index):
            region_id, label = _DOCUMENT_REGION, "Documento"
            spec = specs.get(result.window_index)
            if spec is not None and blocks:
                window_blocks = blocks[spec.unit_start : spec.unit_end + 1]
                for block in window_blocks:
                    section = section_by_block.get(block.id)
                    if section is None:
                        section = section_by_id.get(
                            _as_uuid(block.metadata.get("parent_section_id"))
                        )
                    if section is None:
                        continue
                    path = [part for part in (section.section_path or ()) if part]
                    top = path[0] if path else (section.heading or "")
                    if top:
                        region_id = f"section:{normalize_term(top)}"
                        label = str(top)[:160]
                        break
            regions.setdefault(region_id, []).append(int(result.window_index))
            labels.setdefault(region_id, label)
        return regions, labels


def _indexable(block) -> bool:
    from .planner import is_indexable_block

    return is_indexable_block(block)


def _as_uuid(value):
    from uuid import UUID

    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _unit_summary(unit: StitchedUnit) -> dict:
    return {
        "unit_key": unit.unit_key,
        "unit_kind": unit.unit_kind,
        "label": unit.label[:300],
        "text": unit.text[:300],
        "confidence": round(float(unit.confidence), 4),
        "source_windows": list(unit.source_windows),
        "block_ids": list(unit.block_ids)[:16],
    }


def _relation_summary(relation: StitchRelation) -> dict:
    return {
        "relation_key": relation.relation_key,
        "relation_type": relation.relation_type,
        "subject_key": relation.subject_key,
        "object_key": relation.object_key,
        "confidence": round(float(relation.confidence), 4),
        "windows": list(relation.windows),
    }


def _thread_summary(thread: SemanticThread) -> dict:
    return {
        "thread_key": thread.thread_key,
        "thread_type": thread.thread_type,
        "status": thread.status,
        "target_hint": thread.target_hint[:200],
        "opened_at_window": int(thread.opened_at_window),
        "confidence": round(float(thread.confidence), 4),
    }


def _relation_in_region(
    relation: StitchRelation, region_units: list[StitchedUnit]
) -> bool:
    """La relación toca al menos una unidad de la región (no solo ventana)."""
    if not region_units:
        return False
    keys = {unit.unit_key for unit in region_units}
    return relation.subject_key in keys or relation.object_key in keys


__all__ = [
    "REGIONAL_VERSION",
    "REGION_NS",
    "RegionalModelBuilder",
    "RegionalSemanticModel",
]
