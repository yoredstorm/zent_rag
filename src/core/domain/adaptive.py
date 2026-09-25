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
    """Normalized evidence from any source. Tenant isolation stays in the caller.

    Es la MISMA evidencia que consumen el generador, JEV, el grounding, las
    citas y «Ver flujo»: `evidence_id` es el identificador estable del run y el
    contenido no se recorta acá (la selección decide después qué entra al
    prompt y con cuántos caracteres).

    SOURCE (documento disponible) != EVIDENCE (fragmento recuperado) != CLAIM
    (afirmación respaldada): este objeto es el fragmento, nunca el documento
    entero ni la afirmación.
    """

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
    #: Identificador estable dentro del run (`E1`, `E2`, …). Vacío = sin registrar.
    evidence_id: str = ""
    #: Nombre legible de la fuente (filename/título) y localización del fragmento.
    title: str | None = None
    page: int | None = None
    section_path: tuple[str, ...] = ()
    #: Cómo se recuperó: vector | lexical | hybrid | entity_lexical | entity_scan | tabular.
    retrieval_method: str = ""
    #: La recuperación vino del pin de entidades (label exacto de la pregunta).
    entity_pin: bool = False
    authority: str | None = None
    knowledge_type: str | None = None

    @property
    def label(self) -> str:
        """Etiqueta corta y honesta para trazas: título + sección, sin inventar."""
        parts = [self.title or self.document_id or self.source_id or self.source_type]
        if self.section_path:
            parts.append(".".join(str(item) for item in self.section_path))
        return " · ".join(part for part in parts if part)

    def to_public_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
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
        # UNKNOWN != ZERO: sólo se publica lo que existió.
        if self.evidence_id:
            payload["evidence_id"] = self.evidence_id
        if self.title:
            payload["title"] = self.title
        if self.page is not None:
            payload["page"] = self.page
        if self.section_path:
            payload["section_path"] = [str(item) for item in self.section_path]
        if self.retrieval_method:
            payload["retrieval"] = self.retrieval_method
        if self.entity_pin:
            payload["entity_pin"] = True
        if self.authority:
            payload["authority"] = self.authority
        if self.knowledge_type:
            payload["knowledge_type"] = self.knowledge_type
        if self.content:
            payload["excerpt"] = " ".join(self.content.split())[:400]
        return payload


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
    passage_relevance: float = 0.0
    contradictions: int = 0
    injection_suspected: int = 0
    authority: bool = False
    freshness: bool = False
    # --- Evidence Sufficiency (señales objetivas, no cuotas de LLM) ----------
    #: ¿Hay fragmentos recuperados? (medido siempre).
    has_evidence: bool = False
    #: Cobertura de las entidades que la pregunta nombra (None = no se midió).
    entity_coverage: float | None = None
    entities_asked: tuple[str, ...] = ()
    entities_covered: tuple[str, ...] = ()
    missing_entities: tuple[str, ...] = ()
    #: ¿La evidencia contiene TODAS las entidades pedidas? (None = no se midió).
    exact_entity_match: bool | None = None
    #: Fragmentos que sostienen algo de lo pedido (None = no se midió).
    supporting_chunks: int | None = None
    #: Fragmentos marcados en conflicto por el Passage Judge (None = no se midió).
    conflicting_chunks: int | None = None
    #: generate | retrieve_more | answer_with_limits | abstain.
    recommended_action: str = ""

    def to_public_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "sufficient": self.sufficient,
            "score": round(self.score, 4),
            "max_retrieval_score": round(self.max_retrieval_score, 4),
            "mean_retrieval_score": round(self.mean_retrieval_score, 4),
            "coverage": round(self.coverage, 4),
            "source_diversity": self.source_diversity,
            "exact_match": self.exact_match,
            "reason": self.reason,
            "jev_used": self.jev_used,
            "passage_relevance": round(self.passage_relevance, 4),
            "contradictions": self.contradictions,
            "injection_suspected": self.injection_suspected,
            "authority": self.authority,
            "freshness": self.freshness,
            "has_evidence": self.has_evidence,
        }
        # UNKNOWN != ZERO: lo no medido se omite, no se rellena con 0.
        if self.entity_coverage is not None:
            payload["entity_coverage"] = round(self.entity_coverage, 4)
            payload["entities_asked"] = list(self.entities_asked)[:6]
            payload["entities_covered"] = list(self.entities_covered)[:6]
            if self.missing_entities:
                payload["missing_entities"] = list(self.missing_entities)[:6]
        if self.exact_entity_match is not None:
            payload["exact_entity_match"] = self.exact_entity_match
        if self.supporting_chunks is not None:
            payload["supporting_chunks"] = self.supporting_chunks
        if self.conflicting_chunks is not None:
            payload["conflicting_chunks"] = self.conflicting_chunks
        if self.recommended_action:
            payload["recommended_action"] = self.recommended_action
        return payload


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
    claim_verdicts: list[dict[str, Any]] = field(default_factory=list)
    policy: str = ""
    claims_summary: dict[str, Any] = field(default_factory=dict)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "grounded": self.grounded,
            "score": round(self.score, 4),
            "citation_coverage": round(self.citation_coverage, 4),
            "reason": self.reason,
            "jev_used": self.jev_used,
            "policy": self.policy,
            "claims": self.claims_summary,
            "claim_verdicts": self.claim_verdicts[:12],
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
    passages: dict[str, Any] = field(default_factory=dict)
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
            "passages": self.passages,
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
