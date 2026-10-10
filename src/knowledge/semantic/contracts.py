# =============================================================================
# Progressive Semantic Ingestion — contratos
# =============================================================================
# La fuente completa pertenece a UNA ingesta lógica. Su comprensión puede
# ocurrir en N ventanas semánticas con continuidad (SemanticState/Threads),
# pero la cobertura de lectura se mide siempre:
#
#   GLOBAL INGESTION != SINGLE LLM CALL
#
# Este módulo define el manifiesto por fuente (¿ZENT procesó toda la fuente?)
# y el plan de ventanas semánticas (soft boundaries + hard safety limit).
# Puro: sin I/O, sin LLM, testeable.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import StrEnum
from hashlib import sha256
from uuid import UUID

SEMANTIC_INGESTION_VERSION = "semantic-ingestion-1"
WINDOW_PLAN_VERSION = "semantic-window-plan-1"
WINDOW_UNDERSTANDING_VERSION = "semantic-window-understanding-2"
SEMANTIC_STATE_VERSION = "semantic-state-1"
STATE_SELECTOR_VERSION = "semantic-state-selector-1"

#: Pesos de cobertura por etapa. La cobertura nunca se redondea a 100% si una
#: etapa requerida no terminó; una etapa no requerida no penaliza. La lista de
#: etapas requeridas vive en `manifest.versions["required_stages"]` (Fase 3:
#: parsing + indexing + semantic_windows; Fase 5 agrega stitching; Fase 7 global).
COVERAGE_WEIGHTS: dict[str, float] = {
    "parsing_complete": 0.40,
    "indexing_complete": 0.15,
    "semantic_complete": 0.20,
    "stitching_complete": 0.15,
    "global_synthesis_complete": 0.10,
}

#: Etapa requerida -> flag del manifiesto que la representa.
STAGE_FLAGS: dict[str, str] = {
    "parsing": "parsing_complete",
    "indexing": "indexing_complete",
    "semantic_windows": "semantic_complete",
    "stitching": "stitching_complete",
    "global": "global_synthesis_complete",
}

#: Kinds de item de una ventana semántica (Fase 3, §9 de la misión).
WINDOW_ITEM_KINDS: tuple[str, ...] = (
    "concept",
    "entity",
    "definition",
    "symbol",
    "alias",
    "claim",
    "rule",
    "condition",
    "exception",
    "procedure",
    "temporal",
    "reference",
    "unresolved_reference",
    "table",
    "relationship",
    "continuation",
    "topic",
    "note",
    "conflict",
)

WINDOW_RESULT_STATUSES: tuple[str, ...] = (
    "complete",
    "partial",
    "retryable",
    "failed",
    "quarantined",
)


class IngestionStage(StrEnum):
    """Etapas de la ingesta progresiva (una fila de manifiesto por etapa)."""

    PARSING = "parsing"
    UNDERSTANDING = "understanding"
    SEMANTIC_WINDOWS = "semantic_windows"
    STITCHING = "stitching"
    REGIONAL = "regional"
    GLOBAL = "global"
    INDEXING = "indexing"
    COMPILING = "compiling"
    ACCEPTANCE = "acceptance"
    NUTRITION = "nutrition"


class StageStatus(StrEnum):
    """Estado de una etapa/unidad. Un fallo no invalida la fuente completa."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    PARTIAL = "partial"
    RETRYABLE = "retryable"
    FAILED = "failed"
    QUARANTINED = "quarantined"
    SKIPPED = "skipped"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(kw_only=True)
class SourceIngestionManifest:
    """Manifiesto por (organización, fuente, external_id).

    Responde la pregunta central de Fase 1: «¿ZENT procesó realmente toda esta
    fuente?». Los flags describen etapas REALES; un flag en False nunca se
    presenta como cobertura completa.
    """

    organization_id: UUID
    source_id: UUID | None
    external_id: str
    document_id: UUID | None = None
    workspace_id: UUID | None = None
    source_type: str = ""

    #: Hash de los bytes crudos de la fuente (antes de parsear). Permite
    #: reanudar sin re-parsear cuando el archivo no cambió.
    raw_fingerprint: str = ""
    #: Hash del contenido estructurado/entendido (el que usa el índice).
    content_hash: str = ""

    total_bytes: int = 0
    estimated_tokens: int = 0
    structural_units: int = 0
    processed_units: int = 0
    semantic_units: int = 0
    unresolved_units: int = 0
    failed_units: int = 0
    windows_total: int = 0
    windows_processed: int = 0

    parsing_complete: bool = False
    semantic_complete: bool = False
    stitching_complete: bool = False
    global_synthesis_complete: bool = False
    indexing_complete: bool = False
    #: True solo cuando TODAS las etapas requeridas por la versión activa
    #: terminaron. Es la condición de reanudación/selectivo.
    pipeline_complete: bool = False

    stages: dict = field(default_factory=dict)
    versions: dict = field(default_factory=dict)
    details: dict = field(default_factory=dict)
    started_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)
    completed_at: datetime | None = None

    @property
    def coverage_ratio(self) -> float:
        """Cobertura ponderada por etapas REQUERIDAS (nunca > 1.0).

        `versions["required_stages"]` define qué etapas exige la versión activa
        del pipeline. Compatibilidad: manifiestos viejos con
        `versions["semantic_required"]=true` y sin `required_stages` exigen
        semantic/stitching/global.
        """
        required = self.versions.get("required_stages")
        if required is None:
            required = ["parsing", "indexing"]
            if self.versions.get("semantic_required"):
                required += ["semantic_windows", "stitching", "global"]
        required = [str(stage) for stage in required]
        weights = {
            flag: weight
            for stage, flag in STAGE_FLAGS.items()
            if stage in required
            for weight in (COVERAGE_WEIGHTS.get(flag, 0.0),)
            if weight > 0
        }
        total = sum(weights.values())
        if total <= 0:
            return 0.0
        achieved = 0.0
        for flag, weight in weights.items():
            if bool(getattr(self, flag, False)):
                achieved += weight
        return round(min(1.0, achieved / total), 4)

    def stage(self, stage: IngestionStage | str) -> str:
        return str(self.stages.get(str(stage)) or StageStatus.PENDING.value)

    def to_dict(self) -> dict:
        payload = {
            "organization_id": str(self.organization_id),
            "source_id": str(self.source_id) if self.source_id else None,
            "document_id": str(self.document_id) if self.document_id else None,
            "workspace_id": str(self.workspace_id) if self.workspace_id else None,
            "external_id": self.external_id,
            "source_type": self.source_type,
            "raw_fingerprint": self.raw_fingerprint,
            "content_hash": self.content_hash,
            "total_bytes": int(self.total_bytes),
            "estimated_tokens": int(self.estimated_tokens),
            "structural_units": int(self.structural_units),
            "processed_units": int(self.processed_units),
            "semantic_units": int(self.semantic_units),
            "unresolved_units": int(self.unresolved_units),
            "failed_units": int(self.failed_units),
            "windows_total": int(self.windows_total),
            "windows_processed": int(self.windows_processed),
            "parsing_complete": bool(self.parsing_complete),
            "semantic_complete": bool(self.semantic_complete),
            "stitching_complete": bool(self.stitching_complete),
            "global_synthesis_complete": bool(self.global_synthesis_complete),
            "indexing_complete": bool(self.indexing_complete),
            "pipeline_complete": bool(self.pipeline_complete),
            "coverage_ratio": self.coverage_ratio,
            "stages": dict(self.stages),
            "versions": dict(self.versions),
            "details": dict(self.details),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }
        return payload


def manifest_with(manifest: SourceIngestionManifest, **changes) -> SourceIngestionManifest:
    """Copia inmutable con `updated_at` renovado (única vía de mutación)."""
    return replace(manifest, updated_at=_utcnow(), **changes)


def set_stage(
    manifest: SourceIngestionManifest,
    stage: IngestionStage | str,
    status: StageStatus | str,
) -> SourceIngestionManifest:
    stages = dict(manifest.stages)
    stages[str(stage)] = str(status)
    return manifest_with(manifest, stages=stages)


# ---------------------------------------------------------------------------
# Plan de ventanas semánticas
# ---------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class SemanticWindowSpec:
    """Ventana contigua sobre el orden de lectura de los bloques.

    `unit_start`/`unit_end` son índices inclusivos de bloque en el orden de
    lectura indexable. Los límites son SOFT: una unidad semántica completa se
    extiende dentro del headroom antes que cortarse.
    """

    window_index: int
    unit_start: int
    unit_end: int
    estimated_tokens: int
    target_tokens: int
    hard_limit_tokens: int
    first_block_id: UUID | None = None
    last_block_id: UUID | None = None
    #: Offsets dentro del bloque cuando la ventana usa una pieza partida.
    char_start: int | None = None
    char_end: int | None = None
    preserved_units: int = 0
    split_units: int = 0
    status: str = "planned"
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "window_index": int(self.window_index),
            "unit_start": int(self.unit_start),
            "unit_end": int(self.unit_end),
            "estimated_tokens": int(self.estimated_tokens),
            "target_tokens": int(self.target_tokens),
            "hard_limit_tokens": int(self.hard_limit_tokens),
            "first_block_id": str(self.first_block_id) if self.first_block_id else None,
            "last_block_id": str(self.last_block_id) if self.last_block_id else None,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "preserved_units": int(self.preserved_units),
            "split_units": int(self.split_units),
            "status": self.status,
            "reason": self.reason,
        }


@dataclass(frozen=True, kw_only=True)
class SemanticWindowPlan:
    """Plan completo de ventanas para un documento."""

    document_id: str = ""
    model: str = ""
    model_source: str = "default"
    profile: str = "balanced"
    hard_limit_tokens: int = 0
    target_tokens: int = 0
    total_units: int = 0
    total_tokens: int = 0
    soft_extensions: int = 0
    split_units: int = 0
    windows: tuple[SemanticWindowSpec, ...] = ()
    version: str = WINDOW_PLAN_VERSION
    notes: dict = field(default_factory=dict)

    @property
    def window_count(self) -> int:
        return len(self.windows)

    @property
    def fingerprint(self) -> str:
        material = {
            "version": self.version,
            "model": self.model,
            "profile": self.profile,
            "hard_limit_tokens": self.hard_limit_tokens,
            "target_tokens": self.target_tokens,
            "total_units": self.total_units,
            "windows": [
                [w.window_index, w.unit_start, w.unit_end, w.estimated_tokens]
                for w in self.windows
            ],
        }
        import json

        raw = json.dumps(material, sort_keys=True, separators=(",", ":"), default=str)
        return sha256(raw.encode("utf-8")).hexdigest()

    def to_dict(self, *, include_windows: bool = True) -> dict:
        payload = {
            "document_id": self.document_id,
            "model": self.model,
            "model_source": self.model_source,
            "profile": self.profile,
            "hard_limit_tokens": int(self.hard_limit_tokens),
            "target_tokens": int(self.target_tokens),
            "total_units": int(self.total_units),
            "total_tokens": int(self.total_tokens),
            "soft_extensions": int(self.soft_extensions),
            "split_units": int(self.split_units),
            "window_count": self.window_count,
            "version": self.version,
            "fingerprint": self.fingerprint,
            "notes": dict(self.notes),
        }
        if include_windows:
            payload["windows"] = [window.to_dict() for window in self.windows]
        return payload


# ---------------------------------------------------------------------------
# Fase 3 — comprensión local por ventana + estado semántico
# ---------------------------------------------------------------------------


def _canonical_hash(payload: dict) -> str:
    import json

    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True, kw_only=True)
class WindowItem:
    """Item semántico extraído de UNA ventana.

    `derived=true` y `canonical=false` por ley: la comprensión por ventana es
    señal, no conocimiento canónico (eso lo decide el compiler/stitcher).
    """

    kind: str
    key: str
    label: str
    text: str = ""
    confidence: float = 0.6
    method: str = "deterministic"
    block_ids: tuple[str, ...] = ()
    attributes: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "key": self.key,
            "label": self.label,
            "text": self.text[:600],
            "confidence": round(float(self.confidence), 4),
            "method": self.method,
            "derived": True,
            "canonical": False,
            "block_ids": list(self.block_ids),
            "attributes": dict(self.attributes),
        }


@dataclass(frozen=True, kw_only=True)
class SemanticWindowResult:
    """Resultado estructurado de la comprensión local de una ventana (§9)."""

    window_index: int
    organization_id: UUID
    source_id: UUID | None = None
    workspace_id: UUID | None = None
    document_id: UUID | None = None
    status: str = "complete"
    items: tuple[WindowItem, ...] = ()
    block_ids: tuple[str, ...] = ()
    char_start: int | None = None
    char_end: int | None = None
    tokens_estimated: int = 0
    fingerprint: str = ""
    carry_fingerprint: str = ""
    version: str = WINDOW_UNDERSTANDING_VERSION
    provenance: dict = field(default_factory=dict)
    quality: dict = field(default_factory=dict)
    error: str | None = None

    def by_kind(self, kind: str) -> tuple[WindowItem, ...]:
        return tuple(item for item in self.items if item.kind == kind)

    @property
    def counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.items:
            counts[item.kind] = counts.get(item.kind, 0) + 1
        return counts

    @property
    def concepts(self) -> tuple[WindowItem, ...]:
        return self.by_kind("concept")

    @property
    def entities(self) -> tuple[WindowItem, ...]:
        return self.by_kind("entity")

    @property
    def definitions(self) -> tuple[WindowItem, ...]:
        return self.by_kind("definition")

    @property
    def symbols(self) -> tuple[WindowItem, ...]:
        return self.by_kind("symbol")

    @property
    def aliases(self) -> tuple[WindowItem, ...]:
        return self.by_kind("alias")

    @property
    def claims(self) -> tuple[WindowItem, ...]:
        return self.by_kind("claim")

    @property
    def rules(self) -> tuple[WindowItem, ...]:
        return self.by_kind("rule")

    @property
    def conditions(self) -> tuple[WindowItem, ...]:
        return self.by_kind("condition")

    @property
    def exceptions(self) -> tuple[WindowItem, ...]:
        return self.by_kind("exception")

    @property
    def procedures(self) -> tuple[WindowItem, ...]:
        return self.by_kind("procedure")

    @property
    def temporal_statements(self) -> tuple[WindowItem, ...]:
        return self.by_kind("temporal")

    @property
    def references(self) -> tuple[WindowItem, ...]:
        return self.by_kind("reference")

    @property
    def unresolved_references(self) -> tuple[WindowItem, ...]:
        return self.by_kind("unresolved_reference")

    @property
    def tables(self) -> tuple[WindowItem, ...]:
        return self.by_kind("table")

    @property
    def relationships(self) -> tuple[WindowItem, ...]:
        return self.by_kind("relationship")

    @property
    def continuation_candidates(self) -> tuple[WindowItem, ...]:
        return self.by_kind("continuation")

    @property
    def topic_signals(self) -> tuple[WindowItem, ...]:
        return self.by_kind("topic")

    def to_dict(self, *, include_items: bool = True) -> dict:
        payload = {
            "window_index": int(self.window_index),
            "organization_id": str(self.organization_id),
            "source_id": str(self.source_id) if self.source_id else None,
            "workspace_id": str(self.workspace_id) if self.workspace_id else None,
            "document_id": str(self.document_id) if self.document_id else None,
            "status": self.status,
            "block_ids": list(self.block_ids),
            "char_start": self.char_start,
            "char_end": self.char_end,
            "tokens_estimated": int(self.tokens_estimated),
            "fingerprint": self.fingerprint,
            "carry_fingerprint": self.carry_fingerprint,
            "version": self.version,
            "provenance": dict(self.provenance),
            "quality": dict(self.quality),
            "counts": self.counts,
            "error": self.error,
        }
        if include_items:
            payload["items"] = [item.to_dict() for item in self.items]
        return payload


@dataclass(frozen=True, kw_only=True)
class SemanticState:
    """Estado compacto y verificable de lo aprendido hasta una ventana (§10).

    Sin chain-of-thought: solo conocimiento verificable con provenance.
    """

    organization_id: UUID
    source_id: UUID | None = None
    workspace_id: UUID | None = None
    document_id: UUID | None = None
    window_index: int = -1
    version: str = SEMANTIC_STATE_VERSION
    active_concepts: tuple[dict, ...] = ()
    known_entities: tuple[dict, ...] = ()
    glossary: tuple[dict, ...] = ()
    symbol_definitions: tuple[dict, ...] = ()
    active_rules: tuple[dict, ...] = ()
    unresolved_references: tuple[dict, ...] = ()
    resolved_references: tuple[dict, ...] = ()
    open_continuations: tuple[dict, ...] = ()
    current_topics: tuple[str, ...] = ()
    temporal_context: tuple[str, ...] = ()
    detected_aliases: tuple[dict, ...] = ()
    pending_relationships: tuple[dict, ...] = ()
    conflicts: tuple[dict, ...] = ()
    stats: dict = field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        return _canonical_hash(
            {
                "version": self.version,
                "document_id": str(self.document_id) if self.document_id else None,
                "window_index": int(self.window_index),
                "active_concepts": list(self.active_concepts),
                "known_entities": list(self.known_entities),
                "glossary": list(self.glossary),
                "symbol_definitions": list(self.symbol_definitions),
                "active_rules": list(self.active_rules),
                "unresolved_references": list(self.unresolved_references),
                "resolved_references": list(self.resolved_references),
                "open_continuations": list(self.open_continuations),
                "current_topics": list(self.current_topics),
                "temporal_context": list(self.temporal_context),
                "detected_aliases": list(self.detected_aliases),
                "pending_relationships": list(self.pending_relationships),
                "conflicts": list(self.conflicts),
            }
        )

    @property
    def counts(self) -> dict[str, int]:
        return {
            "active_concepts": len(self.active_concepts),
            "known_entities": len(self.known_entities),
            "glossary": len(self.glossary),
            "symbol_definitions": len(self.symbol_definitions),
            "active_rules": len(self.active_rules),
            "unresolved_references": len(self.unresolved_references),
            "resolved_references": len(self.resolved_references),
            "open_continuations": len(self.open_continuations),
            "current_topics": len(self.current_topics),
            "temporal_context": len(self.temporal_context),
            "detected_aliases": len(self.detected_aliases),
            "pending_relationships": len(self.pending_relationships),
            "conflicts": len(self.conflicts),
        }

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "organization_id": str(self.organization_id),
            "source_id": str(self.source_id) if self.source_id else None,
            "workspace_id": str(self.workspace_id) if self.workspace_id else None,
            "document_id": str(self.document_id) if self.document_id else None,
            "window_index": int(self.window_index),
            "fingerprint": self.fingerprint,
            "counts": self.counts,
            "active_concepts": list(self.active_concepts),
            "known_entities": list(self.known_entities),
            "glossary": list(self.glossary),
            "symbol_definitions": list(self.symbol_definitions),
            "active_rules": list(self.active_rules),
            "unresolved_references": list(self.unresolved_references),
            "resolved_references": list(self.resolved_references),
            "open_continuations": list(self.open_continuations),
            "current_topics": list(self.current_topics),
            "temporal_context": list(self.temporal_context),
            "detected_aliases": list(self.detected_aliases),
            "pending_relationships": list(self.pending_relationships),
            "conflicts": list(self.conflicts),
            "stats": dict(self.stats),
        }


@dataclass(frozen=True, kw_only=True)
class SemanticStateSlice:
    """Recorte relevante del estado para la ventana siguiente (§11)."""

    window_index: int = -1
    source_window_index: int = -1
    version: str = STATE_SELECTOR_VERSION
    active_concepts: tuple[dict, ...] = ()
    known_entities: tuple[dict, ...] = ()
    glossary: tuple[dict, ...] = ()
    symbol_definitions: tuple[dict, ...] = ()
    active_rules: tuple[dict, ...] = ()
    unresolved_references: tuple[dict, ...] = ()
    open_continuations: tuple[dict, ...] = ()
    current_topics: tuple[str, ...] = ()
    temporal_context: tuple[str, ...] = ()
    detected_aliases: tuple[dict, ...] = ()
    pending_relationships: tuple[dict, ...] = ()
    stats: dict = field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        return _canonical_hash(
            {
                "version": self.version,
                "source_window_index": int(self.source_window_index),
                "active_concepts": list(self.active_concepts),
                "known_entities": list(self.known_entities),
                "glossary": list(self.glossary),
                "symbol_definitions": list(self.symbol_definitions),
                "active_rules": list(self.active_rules),
                "unresolved_references": list(self.unresolved_references),
                "open_continuations": list(self.open_continuations),
                "current_topics": list(self.current_topics),
                "temporal_context": list(self.temporal_context),
                "detected_aliases": list(self.detected_aliases),
                "pending_relationships": list(self.pending_relationships),
            }
        )

    @property
    def total(self) -> int:
        return sum(
            len(value)
            for value in (
                self.active_concepts,
                self.known_entities,
                self.glossary,
                self.symbol_definitions,
                self.active_rules,
                self.unresolved_references,
                self.open_continuations,
                self.current_topics,
                self.temporal_context,
                self.detected_aliases,
                self.pending_relationships,
            )
        )

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "window_index": int(self.window_index),
            "source_window_index": int(self.source_window_index),
            "fingerprint": self.fingerprint,
            "total": self.total,
            "stats": dict(self.stats),
            "active_concepts": list(self.active_concepts),
            "known_entities": list(self.known_entities),
            "glossary": list(self.glossary),
            "symbol_definitions": list(self.symbol_definitions),
            "active_rules": list(self.active_rules),
            "unresolved_references": list(self.unresolved_references),
            "open_continuations": list(self.open_continuations),
            "current_topics": list(self.current_topics),
            "temporal_context": list(self.temporal_context),
            "detected_aliases": list(self.detected_aliases),
            "pending_relationships": list(self.pending_relationships),
        }


def window_result_from_dict(payload: dict) -> SemanticWindowResult:
    """Reconstruye un `SemanticWindowResult` desde el JSONB del store."""

    def _uuid(value) -> UUID | None:
        if not value:
            return None
        try:
            return UUID(str(value))
        except (TypeError, ValueError):
            return None

    items = tuple(
        WindowItem(
            kind=str(entry.get("kind") or ""),
            key=str(entry.get("key") or ""),
            label=str(entry.get("label") or ""),
            text=str(entry.get("text") or ""),
            confidence=float(entry.get("confidence") or 0.0),
            method=str(entry.get("method") or "deterministic"),
            block_ids=tuple(str(value) for value in entry.get("block_ids") or ()),
            attributes=dict(entry.get("attributes") or {}),
        )
        for entry in payload.get("items") or ()
        if isinstance(entry, dict)
    )
    return SemanticWindowResult(
        window_index=int(payload.get("window_index") or 0),
        organization_id=_uuid(payload.get("organization_id")) or UUID(int=0),
        source_id=_uuid(payload.get("source_id")),
        workspace_id=_uuid(payload.get("workspace_id")),
        document_id=_uuid(payload.get("document_id")),
        status=str(payload.get("status") or "complete"),
        items=items,
        block_ids=tuple(str(value) for value in payload.get("block_ids") or ()),
        char_start=payload.get("char_start"),
        char_end=payload.get("char_end"),
        tokens_estimated=int(payload.get("tokens_estimated") or 0),
        fingerprint=str(payload.get("fingerprint") or ""),
        carry_fingerprint=str(payload.get("carry_fingerprint") or ""),
        version=str(payload.get("version") or WINDOW_UNDERSTANDING_VERSION),
        provenance=dict(payload.get("provenance") or {}),
        quality=dict(payload.get("quality") or {}),
        error=payload.get("error"),
    )


__all__ = [
    "COVERAGE_WEIGHTS",
    "SEMANTIC_INGESTION_VERSION",
    "SEMANTIC_STATE_VERSION",
    "STAGE_FLAGS",
    "STATE_SELECTOR_VERSION",
    "WINDOW_ITEM_KINDS",
    "WINDOW_PLAN_VERSION",
    "WINDOW_RESULT_STATUSES",
    "WINDOW_UNDERSTANDING_VERSION",
    "IngestionStage",
    "SemanticState",
    "SemanticStateSlice",
    "SemanticWindowPlan",
    "SemanticWindowResult",
    "SemanticWindowSpec",
    "SourceIngestionManifest",
    "StageStatus",
    "WindowItem",
    "manifest_with",
    "set_stage",
    "window_result_from_dict",
]
