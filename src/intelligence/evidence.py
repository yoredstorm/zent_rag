# =============================================================================
# Evidence Collector — toda fuente se transforma en evidencia estructurada
# =============================================================================
# Nunca mezcla evidencia con reasoning del LLM. Tipos: document_chunk,
# sql_result, api_response, tool_result, semantic_definition, approved_metric,
# human_verified_context.
# =============================================================================
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.core.domain.entities import RetrievalContext
from src.core.domain.intelligence import (
    BusinessDefinition,
    EvidenceObject,
    EvidenceType,
)
from src.core.ports.sql_expert import SqlQueryResult


class EvidenceCollector:
    """Convierte salidas de fuentes en objetos de evidencia estructurados."""

    @staticmethod
    def from_sql_result(
        sql_result: SqlQueryResult,
        *,
        source_id: str | None = None,
        source_name: str = "SQL",
        authority_level: str = "authoritative",
    ) -> EvidenceObject:
        return EvidenceObject(
            type=EvidenceType.SQL_RESULT,
            source_id=source_id,
            source_name=source_name,
            authority_level=authority_level,
            query=sql_result.sql or None,
            executed_at=datetime.now(timezone.utc),
            freshness="live",
            row_count=sql_result.row_count,
            validation_status="valid" if not sql_result.error else "invalid",
            access_verified=True,
            metadata={
                "error": sql_result.error[:300] if sql_result.error else None,
                "truncated": bool(sql_result.truncated),
                "cost": sql_result.cost,
            },
        )

    @staticmethod
    def from_retrieval_chunks(
        retrieval_context: RetrievalContext,
        *,
        source_name: str = "Knowledge Base",
        authority_level: str = "informational",
        freshness: str | None = None,
        min_score: float = 0.0,
        limit: int = 8,
    ) -> list[EvidenceObject]:
        evidences: list[EvidenceObject] = []
        for chunk in retrieval_context.chunks:
            if chunk.score < min_score:
                continue
            evidences.append(
                EvidenceObject(
                    type=EvidenceType.DOCUMENT_CHUNK,
                    source_id=str(chunk.document_id),
                    source_name=source_name,
                    authority_level=authority_level,
                    content=chunk.content[:4000],
                    executed_at=datetime.now(timezone.utc),
                    freshness=freshness,
                    validation_status="unvalidated",
                    access_verified=True,
                    metadata={
                        "score": chunk.score,
                        "document_id": str(chunk.document_id),
                    },
                )
            )
            if len(evidences) >= limit:
                break
        return evidences

    @staticmethod
    def from_definition(
        definition: BusinessDefinition,
    ) -> EvidenceObject:
        return EvidenceObject(
            type=EvidenceType.APPROVED_METRIC,
            source_id=str(definition.id),
            source_name="Business Definitions",
            authority_level="authoritative",
            content=definition.definition,
            freshness="approved",
            validation_status="valid",
            access_verified=True,
            metadata={
                "concept": definition.concept,
                "data_type": definition.data_type,
                "status": definition.status,
            },
        )

    @staticmethod
    def from_semantic_definition(
        *,
        concept: str,
        definition_text: str,
        source_id: str | None = None,
        source_name: str = "Knowledge Base",
        score: float = 0.0,
    ) -> EvidenceObject:
        return EvidenceObject(
            type=EvidenceType.SEMANTIC_DEFINITION,
            source_id=source_id,
            source_name=source_name,
            authority_level="informational",
            content=definition_text[:4000],
            freshness="unvalidated",
            validation_status="unvalidated",
            access_verified=True,
            metadata={"concept": concept, "score": score},
        )

    @staticmethod
    def from_tool_result(
        tool_name: str,
        output: str,
        *,
        source_id: str | None = None,
        source_name: str | None = None,
        error: str | None = None,
    ) -> EvidenceObject:
        return EvidenceObject(
            type=EvidenceType.TOOL_RESULT,
            source_id=source_id,
            source_name=source_name or tool_name,
            authority_level="informational",
            content=output[:4000],
            executed_at=datetime.now(timezone.utc),
            freshness="live",
            validation_status="valid" if not error else "invalid",
            access_verified=True,
            metadata={"tool": tool_name, "error": error[:300] if error else None},
        )

    @staticmethod
    def to_serializable(evidence: EvidenceObject) -> dict[str, Any]:
        return evidence.to_dict()
