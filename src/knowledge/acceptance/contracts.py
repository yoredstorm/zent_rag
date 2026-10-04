# =============================================================================
# Acceptance — contratos
# =============================================================================
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID, uuid5

PROBE_POLICY_VERSION = "probe-policy-1"
GENERATOR_VERSION = "probe-generator-1"

PROBE_TYPES = (
    "exact_identifier",
    "alias",
    "semantic_paraphrase",
    "section_question",
    "relation_question",
    "table_lookup",
    "temporal_question",
    "definition",
    # Fase 14 (Retrieval Acceptance V2): probes derivados del Semantic Fabric.
    "knowledge_definition",
    "knowledge_rule",
    "knowledge_exception",
    "knowledge_symbol",
    "knowledge_condition",
    "knowledge_procedure",
    "knowledge_claim",
    "knowledge_dependency",
)

_PROBE_NS = UUID("3d8b2f41-7c6a-4e2d-9f10-5a6c7e8d9b21")


def probe_id_for(document_id, query: str, query_type: str) -> str:
    return str(uuid5(_PROBE_NS, f"{document_id}:{query_type}:{query.strip().casefold()}"))


class AcceptanceMode(StrEnum):
    OFF = "off"
    OBSERVE = "observe"
    WARN = "warn"
    QUARANTINE = "quarantine"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, kw_only=True)
class RetrievalProbe:
    """Pregunta de evaluación con evidencia esperada (versionada, re-ejecutable)."""

    probe_id: str
    organization_id: UUID
    document_id: UUID
    query: str
    query_type: str = "semantic_paraphrase"
    workspace_id: UUID | None = None
    source_id: UUID | None = None
    semantic_unit_id: str | None = None
    expected_document_id: str = ""
    expected_section_id: str | None = None
    expected_unit_id: str | None = None
    expected_entity_ids: tuple[str, ...] = ()
    generated_by: str = "semantic_enrichment"
    generator_version: str = GENERATOR_VERSION
    policy_version: str = PROBE_POLICY_VERSION
    active: bool = True
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.query.strip():
            raise ValueError("RetrievalProbe.query must not be empty")
        if self.query_type not in PROBE_TYPES:
            raise ValueError(f"RetrievalProbe.query_type must be one of {PROBE_TYPES}")

    def to_dict(self) -> dict:
        return {
            "probe_id": self.probe_id,
            "organization_id": str(self.organization_id),
            "workspace_id": str(self.workspace_id) if self.workspace_id else None,
            "source_id": str(self.source_id) if self.source_id else None,
            "document_id": str(self.document_id),
            "semantic_unit_id": self.semantic_unit_id,
            "query": self.query,
            "query_type": self.query_type,
            "expected_document_id": self.expected_document_id,
            "expected_section_id": self.expected_section_id,
            "expected_unit_id": self.expected_unit_id,
            "expected_entity_ids": list(self.expected_entity_ids),
            "generated_by": self.generated_by,
            "generator_version": self.generator_version,
            "policy_version": self.policy_version,
            "active": bool(self.active),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, kw_only=True)
class ProbeOutcome:
    """Resultado de un probe: rank real + evidencias encontradas."""

    probe_id: str
    query: str
    query_type: str
    passed: bool
    rank: int | None = None
    document_rank: int | None = None
    hit_document: bool = False
    hit_section: bool = False
    hit_unit: bool = False
    semantic_hit: bool = False
    lexical_hit: bool | None = None
    top_score: float | None = None
    retrieved_document_ids: tuple[str, ...] = ()
    error: str | None = None

    def to_dict(self) -> dict:
        data = asdict(self)
        data["retrieved_document_ids"] = list(self.retrieved_document_ids)
        return data


@dataclass(frozen=True, kw_only=True)
class AcceptanceReport:
    """Resultado completo de una corrida de acceptance sobre un documento."""

    organization_id: UUID
    document_id: UUID
    mode: str = AcceptanceMode.WARN.value
    source_id: UUID | None = None
    workspace_id: UUID | None = None
    accepted: bool = False
    retrievable: bool = False
    probes_total: int = 0
    probes_passed: int = 0
    probes_failed: int = 0
    recall_at_1: float | None = None
    recall_at_3: float | None = None
    recall_at_5: float | None = None
    mrr: float | None = None
    correct_document_rate: float | None = None
    correct_section_rate: float | None = None
    evidence_hit_rate: float | None = None
    semantic_hit_rate: float | None = None
    lexical_hit_rate: float | None = None
    top_score: float | None = None
    min_recall_at_5: float = 0.6
    failed_probes: tuple[ProbeOutcome, ...] = ()
    outcomes: tuple[ProbeOutcome, ...] = ()
    duration_ms: float = 0.0
    evaluated_at: datetime = field(default_factory=_utcnow)
    generator_version: str = GENERATOR_VERSION
    policy_version: str = PROBE_POLICY_VERSION
    details: dict = field(default_factory=dict)

    def to_dict(self, *, include_outcomes: bool = False) -> dict:
        data = {
            "organization_id": str(self.organization_id),
            "document_id": str(self.document_id),
            "source_id": str(self.source_id) if self.source_id else None,
            "workspace_id": str(self.workspace_id) if self.workspace_id else None,
            "mode": self.mode,
            "state": self.gate_state,
            "accepted": bool(self.accepted),
            "retrievable": bool(self.retrievable),
            "probes_total": self.probes_total,
            "probes_passed": self.probes_passed,
            "probes_failed": self.probes_failed,
            "recall_at_1": self.recall_at_1,
            "recall_at_3": self.recall_at_3,
            "recall_at_5": self.recall_at_5,
            "mrr": self.mrr,
            "correct_document_rate": self.correct_document_rate,
            "correct_section_rate": self.correct_section_rate,
            "evidence_hit_rate": self.evidence_hit_rate,
            "semantic_hit_rate": self.semantic_hit_rate,
            "lexical_hit_rate": self.lexical_hit_rate,
            "top_score": self.top_score,
            "min_recall_at_5": self.min_recall_at_5,
            "failed_probes": [outcome.to_dict() for outcome in self.failed_probes],
            "duration_ms": self.duration_ms,
            "evaluated_at": self.evaluated_at.isoformat(),
            "generator_version": self.generator_version,
            "policy_version": self.policy_version,
            "details": dict(self.details),
        }
        if include_outcomes:
            data["outcomes"] = [outcome.to_dict() for outcome in self.outcomes]
        return data

    @property
    def quality_status(self) -> str:
        if not self.probes_total:
            return "UNKNOWN"
        if self.retrievable:
            return "RETRIEVABLE"
        if self.recall_at_5 is not None and self.recall_at_5 >= 0.8:
            return "INDEXED"
        if self.recall_at_5 is not None and self.recall_at_5 >= 0.3:
            return "ENRICHED"
        return "NOT_RETRIEVABLE"

    @property
    def gate_state(self) -> str:
        """PASS / DEGRADED / FAIL / UNKNOWN. No necesariamente tumba el job."""
        if not self.probes_total:
            return "UNKNOWN"
        if self.accepted:
            return "PASS"
        if self.probes_passed > 0:
            return "DEGRADED"
        return "FAIL"
