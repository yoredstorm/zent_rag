# =============================================================================
# Adaptive RAG domain — plans, evidence, traces. No infrastructure.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import UUID

POLICY_VERSION = "adaptive-v1"


class AdaptiveMode(StrEnum):
    OFF = "off"
    SHADOW = "shadow"
    ACTIVE = "active"
    CANARY = "canary"


class DataModality(StrEnum):
    DOCUMENTS = "documents"
    STRUCTURED_DATA = "structured_data"
    MIXED = "mixed"
    TOOL = "tool"
    WORKFLOW = "workflow"
    CONVERSATIONAL = "conversational"


class RetrievalStrategyName(StrEnum):
    EXACT = "exact"
    LEXICAL = "lexical"
    VECTOR = "vector"
    HYBRID = "hybrid"
    STRUCTURED = "structured"
    MIXED = "mixed"


class AdaptivePath(StrEnum):
    FAST = "fast"
    STANDARD = "standard"
    COMPLEX = "complex"


class SourceRoute(StrEnum):
    KNOWLEDGE_SEARCH = "knowledge.search"
    DATABASE_QUERY = "database.query"
    MIXED = "mixed"
    DIRECT = "direct"
    TOOL = "tool"
    WORKFLOW = "workflow"
    AGENT = "agent"


@dataclass(kw_only=True)
class AdaptivePlan:
    """Retrieval/generation plan. Orchestrator executes; this never runs tools."""

    mode: str = AdaptiveMode.OFF.value
    apply: bool = False
    intent: str = "general"
    modality: str = DataModality.DOCUMENTS.value
    retrieval_requirement: str = "semantic"
    reasoning_requirement: str = "none"
    source_route: str = SourceRoute.KNOWLEDGE_SEARCH.value
    retrieval_strategy: str = RetrievalStrategyName.HYBRID.value
    engine_strategy: str = "hybrid"
    lexical_weight: float = 0.3
    top_k: int = 8
    search_top_k: int | None = None
    path: str = AdaptivePath.STANDARD.value
    skip_retrieval: bool = False
    skip_sql: bool = False
    prefer_sql: bool = False
    rewrite_needed: bool = False
    rewritten_query: str | None = None
    complexity: str = "bounded"
    confidence: float = 0.0
    provider: str = "rules"
    classification_kind: str = "semantic"
    classification_lexical_ratio: float = 0.2
    jev_answers: dict[str, Any] = field(default_factory=dict)
    cache_hit: bool = False

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "apply": self.apply,
            "intent": self.intent,
            "modality": self.modality,
            "retrieval_requirement": self.retrieval_requirement,
            "reasoning_requirement": self.reasoning_requirement,
            "source_route": self.source_route,
            "retrieval_strategy": self.retrieval_strategy,
            "engine_strategy": self.engine_strategy,
            "lexical_weight": round(self.lexical_weight, 3),
            "top_k": self.top_k,
            "path": self.path,
            "skip_retrieval": self.skip_retrieval,
            "skip_sql": self.skip_sql,
            "prefer_sql": self.prefer_sql,
            "rewrite_needed": self.rewrite_needed,
            "complexity": self.complexity,
            "confidence": round(self.confidence, 4),
            "provider": self.provider,
            "classification_kind": self.classification_kind,
            "cache_hit": self.cache_hit,
        }


@dataclass(kw_only=True)
class EvidenceItem:
    """Normalized evidence from any source. Tenant isolation stays in the caller."""

    source_type: str
    content: str
    score: float = 0.0
    rerank_score: float | None = None
    source_id: str | None = None
    document_id: str | None = None
    chunk_id: str | None = None
    table: str | None = None
    row_ref: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    freshness: str | None = None
    citation: str | None = None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "source_type": self.source_type,
            "source_id": self.source_id,
            "document_id": self.document_id,
            "chunk_id": self.chunk_id,
            "table": self.table,
            "row_ref": self.row_ref,
            "score": round(self.score, 4),
            "rerank_score": None if self.rerank_score is None else round(self.rerank_score, 4),
            "freshness": self.freshness,
            "citation": self.citation,
            "chars": len(self.content or ""),
        }


@dataclass(kw_only=True)
class EvidenceSet:
    items: list[EvidenceItem] = field(default_factory=list)
    query: str = ""

    @property
    def size(self) -> int:
        return len(self.items)

    def preview(self, max_chars: int = 1500) -> str:
        parts: list[str] = []
        used = 0
        for item in self.items[:8]:
            snippet = " ".join((item.content or "").split())[:240]
            if not snippet:
                continue
            piece = f"[{item.source_type}] {snippet}"
            if used + len(piece) > max_chars:
                break
            parts.append(piece)
            used += len(piece)
        return "\n".join(parts)


@dataclass(kw_only=True)
class EvidenceQuality:
    sufficient: bool
    score: float
    max_retrieval_score: float = 0.0
    mean_retrieval_score: float = 0.0
    coverage: float = 0.0
    source_diversity: int = 0
    exact_match: bool = False
    reason: str = ""
    jev_used: bool = False
    jev_answers: dict[str, Any] = field(default_factory=dict)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "sufficient": self.sufficient,
            "score": round(self.score, 4),
            "max_retrieval_score": round(self.max_retrieval_score, 4),
            "mean_retrieval_score": round(self.mean_retrieval_score, 4),
            "coverage": round(self.coverage, 4),
            "source_diversity": self.source_diversity,
            "exact_match": self.exact_match,
            "reason": self.reason,
            "jev_used": self.jev_used,
        }


@dataclass(kw_only=True)
class RetrievalAttempt:
    attempt: int
    strategy: str
    source_route: str
    query: str
    sufficient: bool
    quality_score: float
    n_items: int = 0

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "attempt": self.attempt,
            "strategy": self.strategy,
            "source_route": self.source_route,
            "sufficient": self.sufficient,
            "quality_score": round(self.quality_score, 4),
            "n_items": self.n_items,
            "query_chars": len(self.query or ""),
        }


@dataclass(kw_only=True)
class GroundingResult:
    grounded: bool
    score: float
    citation_coverage: float = 0.0
    reason: str = ""
    jev_used: bool = False

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "grounded": self.grounded,
            "score": round(self.score, 4),
            "citation_coverage": round(self.citation_coverage, 4),
            "reason": self.reason,
            "jev_used": self.jev_used,
        }


@dataclass(kw_only=True)
class AdaptiveTrace:
    """Inspectable RAG trace. No secrets, no full document bodies."""

    organization_id: UUID
    request_id: UUID
    intent: str = ""
    decision_capability: str | None = None
    plan: dict[str, Any] = field(default_factory=dict)
    source_route: str = ""
    retrieval_strategy: str = ""
    retrieved: list[dict[str, Any]] = field(default_factory=list)
    evidence_evaluation: dict[str, Any] = field(default_factory=dict)
    attempts: list[dict[str, Any]] = field(default_factory=list)
    rewrite: str | None = None
    generator_model: str | None = None
    llm_skipped: bool = False
    grounding: dict[str, Any] | None = None
    jev_decisions: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    top_k: int = 0
    context_tokens_before: int = 0
    context_tokens_after: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_cost: float = 0.0
    latency_ms: float = 0.0
    fallbacks: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "request_id": str(self.request_id),
            "intent": self.intent,
            "decision": self.decision_capability,
            "plan": self.plan,
            "source_route": self.source_route,
            "retrieval_strategy": self.retrieval_strategy,
            "retrieved": self.retrieved[:12],
            "evidence_evaluation": self.evidence_evaluation,
            "attempts": self.attempts,
            "rewrite": bool(self.rewrite),
            "generator": self.generator_model,
            "llm_skipped": self.llm_skipped,
            "grounding": self.grounding,
            "jev_decisions": self.jev_decisions,
            "confidence": round(self.confidence, 4),
            "top_k": self.top_k,
            "context_tokens_before": self.context_tokens_before,
            "context_tokens_after": self.context_tokens_after,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_cost": round(self.total_cost, 6),
            "latency_ms": round(self.latency_ms, 2),
            "fallbacks": self.fallbacks,
        }
