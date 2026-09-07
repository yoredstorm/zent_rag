# =============================================================================
# Domain Layer — Zent Intelligence Layer (Answerability Engine)
# =============================================================================
# Entidades puras del motor de answerability. Sin dependencias externas.
# La decisión de responder o abstenerse combina señales objetivas del sistema;
# el LLM nunca es la única señal.
# =============================================================================
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4


class AnswerabilityStatus(StrEnum):
    """Estados formales de answerability (Zent nunca se siente obligado a responder)."""

    ANSWERABLE = "ANSWERABLE"
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"
    CONTEXT_MISSING = "CONTEXT_MISSING"
    DATA_MISSING = "DATA_MISSING"
    DATA_QUALITY_LOW = "DATA_QUALITY_LOW"
    AMBIGUOUS = "AMBIGUOUS"
    ACCESS_BLOCKED = "ACCESS_BLOCKED"
    SOURCE_CONFLICT = "SOURCE_CONFLICT"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"


class ConfidenceLevel(StrEnum):
    """Niveles de confianza discretos — nunca falsa precisión."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INSUFFICIENT = "insufficient"


class PlanStrategy(StrEnum):
    """Estrategias del Query Planner (Text-to-SQL NO es siempre la primera opción)."""

    SQL = "sql"
    RAG = "rag"
    SQL_RAG = "sql_rag"
    API_TOOL = "api_tool"
    MULTI_SOURCE = "multi_source"
    CLARIFICATION = "clarification"
    ABSTAIN = "abstain"


class EvidenceType(StrEnum):
    """Tipos de evidencia estructurada (nunca mezclar con reasoning del LLM)."""

    DOCUMENT_CHUNK = "document_chunk"
    SQL_RESULT = "sql_result"
    API_RESPONSE = "api_response"
    TOOL_RESULT = "tool_result"
    SEMANTIC_DEFINITION = "semantic_definition"
    APPROVED_METRIC = "approved_metric"
    HUMAN_VERIFIED_CONTEXT = "human_verified_context"


@dataclass(kw_only=True)
class QueryUnderstanding:
    """Resultado de la capa de comprensión de la consulta."""

    intent: str = "general"  # business_metric | document_policy | operational_status | concept_definition | general
    entities: list[str] = field(default_factory=list)
    concepts: list[str] = field(default_factory=list)
    requires_definition: list[str] = field(default_factory=list)
    resolved_concepts: dict[str, bool] = field(default_factory=dict)
    time_scope: str | None = None  # current | past | period | range
    requires_structured_data: bool = False
    requires_documents: bool = False
    requires_tools: bool = False
    ambiguity: bool = False
    clarifying_question: str | None = None
    dependencies: list[str] = field(default_factory=list)
    extraction_source: str = "deterministic"  # llm | deterministic | none
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "intent": self.intent,
            "entities": self.entities,
            "concepts": self.concepts,
            "requires_definition": self.requires_definition,
            "resolved_concepts": self.resolved_concepts,
            "time_scope": self.time_scope,
            "requires_structured_data": self.requires_structured_data,
            "requires_documents": self.requires_documents,
            "requires_tools": self.requires_tools,
            "ambiguity": self.ambiguity,
            "clarifying_question": self.clarifying_question,
            "dependencies": self.dependencies,
            "extraction_source": self.extraction_source,
        }


@dataclass(kw_only=True)
class QueryPlan:
    """Plan estructurado producido ANTES de ejecutar herramientas."""

    strategy: PlanStrategy = PlanStrategy.RAG
    steps: list[str] = field(default_factory=list)
    needs_sql: bool = False
    needs_retrieval: bool = False
    needs_tools: bool = False
    needs_semantic_resolution: bool = False
    rationale: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "strategy": self.strategy.value,
            "steps": self.steps,
            "needs_sql": self.needs_sql,
            "needs_retrieval": self.needs_retrieval,
            "needs_tools": self.needs_tools,
            "needs_semantic_resolution": self.needs_semantic_resolution,
            "rationale": self.rationale,
            "limitations": self.limitations,
        }


@dataclass(kw_only=True)
class EvidenceObject:
    """Evidencia estructurada de una fuente. Nunca mezcla reasoning generado."""

    evidence_id: str = field(default_factory=lambda: str(uuid4()))
    type: EvidenceType
    source_id: str | None = None
    source_name: str = ""
    authority_level: str = "informational"  # authoritative | approved | informational | external
    query: str | None = None
    content: str | None = None
    executed_at: datetime | None = None
    freshness: str | None = None
    row_count: int | None = None
    validation_status: str = "valid"  # valid | invalid | unvalidated
    access_verified: bool = False
    value: Any = None
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "evidence_id": self.evidence_id,
            "type": self.type.value,
            "source_id": self.source_id,
            "source_name": self.source_name,
            "authority_level": self.authority_level,
            "query": self.query,
            "executed_at": self.executed_at.isoformat() if self.executed_at else None,
            "freshness": self.freshness,
            "row_count": self.row_count,
            "validation_status": self.validation_status,
            "access_verified": self.access_verified,
            "metadata": self.metadata,
        }


@dataclass(kw_only=True)
class BusinessDefinition:
    """Definición empresarial aprobada (única fuente de verdad de conceptos).

    FASE 24: extendido con gobernanza de glosario (synonyms, owner, version,
    fechas de vigencia, approved_by, provenance).
    """

    id: UUID
    organization_id: UUID
    concept: str
    definition: str
    expression: str | None = None
    data_type: str = "concept"  # metric | dimension | concept | status_value
    status: str = "approved"  # draft | approved | deprecated
    authoritative_source_id: str | None = None
    created_by: UUID | None = None
    synonyms: list[str] = field(default_factory=list)
    owner: str | None = None
    version: int = 1
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    approved_by: UUID | None = None
    provenance: str = "APPROVED"  # OBSERVED | INFERRED | APPROVED | REJECTED | DEPRECATED
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(kw_only=True)
class AnswerabilityDecision:
    """Salida estructurada del Answerability Gate."""

    status: AnswerabilityStatus = AnswerabilityStatus.ANSWERABLE
    answerable: bool = True
    confidence_level: ConfidenceLevel = ConfidenceLevel.INSUFFICIENT
    score: float = 0.0
    reason_codes: list[str] = field(default_factory=list)
    missing_context: list[str] = field(default_factory=list)
    missing_data: list[str] = field(default_factory=list)
    conflicting_sources: list[dict] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    recommended_actions: list[str] = field(default_factory=list)
    clarifying_question: str | None = None
    message: str | None = None
    found: list[str] = field(default_factory=list)
    llm_critic: dict | None = None
    evidence_summaries: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "answerable": self.answerable,
            "confidence_level": self.confidence_level.value,
            "score": self.score,
            "reason_codes": self.reason_codes,
            "missing_context": self.missing_context,
            "missing_data": self.missing_data,
            "conflicting_sources": self.conflicting_sources,
            "evidence_ids": self.evidence_ids,
            "recommended_actions": self.recommended_actions,
            "clarifying_question": self.clarifying_question,
            "message": self.message,
            "found": self.found,
            "evidence_summaries": self.evidence_summaries,
        }


@dataclass(kw_only=True)
class BudgetLimits:
    """Límites duros por ejecución (integrados con la infraestructura existente)."""

    max_plan_attempts: int = 2
    max_sql_repair_attempts: int = 3
    max_retrieval_rounds: int = 2
    max_tool_calls: int = 8
    max_llm_calls: int = 10
    max_execution_seconds: float = 45.0
    max_total_tokens: int = 6000
    max_cost_usd: float = 0.10

    def to_dict(self) -> dict:
        return {
            "max_plan_attempts": self.max_plan_attempts,
            "max_sql_repair_attempts": self.max_sql_repair_attempts,
            "max_retrieval_rounds": self.max_retrieval_rounds,
            "max_tool_calls": self.max_tool_calls,
            "max_llm_calls": self.max_llm_calls,
            "max_execution_seconds": self.max_execution_seconds,
            "max_total_tokens": self.max_total_tokens,
            "max_cost_usd": self.max_cost_usd,
        }


@dataclass(kw_only=True)
class Budget:
    """Contadores de presupuesto por ejecución (Finite State Machine)."""

    limits: BudgetLimits
    llm_calls: int = 0
    tool_calls: int = 0
    retrieval_rounds: int = 0
    plan_attempts: int = 0
    sql_repair_attempts: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def record_llm_call(self, tokens: int = 0, cost: float = 0.0) -> None:
        self.llm_calls += 1
        self.total_tokens += tokens
        self.cost_usd += cost

    def record_tool_call(self) -> None:
        self.tool_calls += 1

    def record_retrieval(self) -> None:
        self.retrieval_rounds += 1

    def record_plan_attempt(self) -> None:
        self.plan_attempts += 1

    def record_sql_repair(self) -> None:
        self.sql_repair_attempts += 1

    @property
    def elapsed_seconds(self) -> float:
        return (datetime.now(timezone.utc) - self.started_at).total_seconds()

    @property
    def exceeded(self) -> str | None:
        """Retorna el límite excedido (o None si el presupuesto es válido)."""
        if self.llm_calls > self.limits.max_llm_calls:
            return "max_llm_calls"
        if self.tool_calls > self.limits.max_tool_calls:
            return "max_tool_calls"
        if self.retrieval_rounds > self.limits.max_retrieval_rounds:
            return "max_retrieval_rounds"
        if self.plan_attempts > self.limits.max_plan_attempts:
            return "max_plan_attempts"
        if self.sql_repair_attempts > self.limits.max_sql_repair_attempts:
            return "max_sql_repair_attempts"
        if self.total_tokens > self.limits.max_total_tokens:
            return "max_total_tokens"
        if self.cost_usd > self.limits.max_cost_usd:
            return "max_cost_usd"
        if self.elapsed_seconds > self.limits.max_execution_seconds:
            return "max_execution_seconds"
        return None

    def to_dict(self) -> dict:
        return {
            "llm_calls": self.llm_calls,
            "tool_calls": self.tool_calls,
            "retrieval_rounds": self.retrieval_rounds,
            "plan_attempts": self.plan_attempts,
            "sql_repair_attempts": self.sql_repair_attempts,
            "total_tokens": self.total_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "elapsed_seconds": round(self.elapsed_seconds, 3),
        }


@dataclass(kw_only=True, frozen=True)
class ToolFingerprint:
    """Fingerprint determinista de una operación (loop prevention)."""

    tool: str
    source: str | None
    normalized_arguments: str
    normalized_query: str
    agent_id: str | None
    organization_id: str
    digest: str

    @staticmethod
    def compute(
        *,
        tool: str,
        source: str | None,
        arguments: dict | None,
        query: str,
        agent_id: str | None,
        organization_id: str,
    ) -> ToolFingerprint:
        normalized_args = json.dumps(arguments or {}, sort_keys=True, default=str)
        normalized_query = " ".join((query or "").lower().split())
        payload = "|".join(
            [
                tool.lower().strip(),
                (source or "").lower().strip(),
                normalized_args,
                normalized_query,
                (agent_id or "").lower().strip(),
                organization_id.lower().strip(),
            ]
        )
        return ToolFingerprint(
            tool=tool,
            source=source,
            normalized_arguments=normalized_args,
            normalized_query=normalized_query,
            agent_id=agent_id,
            organization_id=organization_id,
            digest=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        )


@dataclass(kw_only=True)
class IntelligenceTrace:
    """Traza completa de una ejecución del Intelligence Layer (traceability)."""

    trace_id: str = field(default_factory=lambda: str(uuid4()))
    organization_id: UUID
    query_id: UUID | None = None
    user_id: UUID | None = None
    user_query: str = ""
    role: str = "admin"
    understanding: dict = field(default_factory=dict)
    query_plan: dict = field(default_factory=dict)
    evidence: list[dict] = field(default_factory=list)
    decision: dict = field(default_factory=dict)
    status: str = AnswerabilityStatus.ANSWERABLE.value
    answer: str | None = None
    method: str = "rag"
    model: str | None = None
    budget: dict = field(default_factory=dict)
    latency_ms: float = 0.0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "trace_id": self.trace_id,
            "organization_id": str(self.organization_id),
            "query_id": str(self.query_id) if self.query_id else None,
            "user_id": str(self.user_id) if self.user_id else None,
            "user_query": self.user_query,
            "role": self.role,
            "understanding": self.understanding,
            "query_plan": self.query_plan,
            "evidence": self.evidence,
            "decision": self.decision,
            "status": self.status,
            "answer": self.answer,
            "method": self.method,
            "model": self.model,
            "budget": self.budget,
            "latency_ms": self.latency_ms,
            "created_at": self.created_at.isoformat(),
        }
