# =============================================================================
# Verified Query Service — search + AST-aware matching (Phase 26C)
# =============================================================================
# Never reuse a verified query only because text is similar. Prefer semantic AST
# overlap (metrics, entities, segments, time structure, dialect).
# Adaptation changes time filters on AST metadata — never unsafe string replace
# of arbitrary SQL.
# =============================================================================
from __future__ import annotations

import hashlib
import re
from typing import Any
from uuid import UUID

from src.core.domain.semantic import SemanticCompileResult
from src.core.domain.verified_query import (
    MappingSuggestion,
    MappingSuggestionStatus,
    VerifiedQuery,
    VerifiedQueryMatch,
    VerifiedQueryStatus,
)
from src.intelligence.verified_query_store import PostgresVerifiedQueryStore

_TOKEN_RE = re.compile(r"[a-záéíóúñü0-9_]+", re.IGNORECASE)
_EQ_LITERAL_RE = re.compile(
    r"(?i)\b([a-z_][a-z0-9_]*)\s*=\s*'([^']+)'"
)


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(text or "") if len(t) > 1}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _ast_metrics(ast: dict[str, Any]) -> set[str]:
    return {
        str(m.get("name", "")).lower()
        for m in (ast.get("metrics") or [])
        if m.get("name")
    }


def _ast_segments(ast: dict[str, Any]) -> set[str]:
    return {str(s).lower() for s in (ast.get("segments") or [])}


def _ast_entity_values(ast: dict[str, Any]) -> set[str]:
    return {
        str(e.get("value", "")).lower()
        for e in (ast.get("entities") or [])
        if e.get("value")
    }


def _time_structure(ast: dict[str, Any]) -> str:
    time = ast.get("time") or {}
    if time.get("from") or time.get("to"):
        return "range"
    return str(time.get("scope") or "none")


class VerifiedQueryService:
    """CRUD helpers + semantic search over verified queries."""

    def __init__(self, store: PostgresVerifiedQueryStore | None = None) -> None:
        self._store = store or PostgresVerifiedQueryStore()

    @property
    def store(self) -> PostgresVerifiedQueryStore:
        return self._store

    async def create(
        self,
        organization_id: UUID,
        *,
        name: str,
        canonical_question: str,
        verified_sql: str,
        semantic_ast: dict[str, Any] | None = None,
        question_variants: list[str] | None = None,
        dialect: str = "postgres",
        status: VerifiedQueryStatus = VerifiedQueryStatus.DRAFT,
        metric_dependencies: list[str] | None = None,
        concept_dependencies: list[str] | None = None,
        table_dependencies: list[str] | None = None,
        approved_by: UUID | None = None,
    ) -> VerifiedQuery:
        fingerprint = hashlib.sha256(
            verified_sql.strip().encode("utf-8")
        ).hexdigest()[:32]
        item = VerifiedQuery(
            organization_id=organization_id,
            name=name,
            canonical_question=canonical_question,
            verified_sql=verified_sql,
            semantic_ast=semantic_ast or {},
            question_variants=question_variants or [],
            dialect=dialect,
            status=status,
            metric_dependencies=metric_dependencies or [],
            concept_dependencies=concept_dependencies or [],
            table_dependencies=table_dependencies or [],
            approved_by=approved_by,
            execution_fingerprint=fingerprint,
        )
        if status == VerifiedQueryStatus.VERIFIED:
            from datetime import datetime, timezone

            item.approved_at = datetime.now(timezone.utc)
            item.last_verified_at = item.approved_at
        return await self._store.upsert(item)

    async def search(
        self,
        organization_id: UUID,
        *,
        question: str,
        compile_result: SemanticCompileResult | None = None,
        dialect: str = "postgres",
        min_score: float = 0.35,
        limit: int = 5,
    ) -> list[VerifiedQueryMatch]:
        candidates = await self._store.list_verified(
            organization_id, dialect=dialect
        )
        target_ast = (
            compile_result.semantic_ast.to_dict()
            if compile_result is not None
            else {}
        )
        q_tokens = _tokens(question)
        target_metrics = _ast_metrics(target_ast)
        target_segments = _ast_segments(target_ast)
        target_entities = _ast_entity_values(target_ast)
        target_time = _time_structure(target_ast)

        matches: list[VerifiedQueryMatch] = []
        for cand in candidates:
            cand_ast = cand.semantic_ast or {}
            cand_metrics = _ast_metrics(cand_ast)
            cand_segments = _ast_segments(cand_ast)
            cand_entities = _ast_entity_values(cand_ast)
            text_score = max(
                _jaccard(q_tokens, _tokens(cand.canonical_question)),
                max(
                    (
                        _jaccard(q_tokens, _tokens(v))
                        for v in (cand.question_variants or [])
                    ),
                    default=0.0,
                ),
            )
            metric_score = (
                1.0
                if not target_metrics and not cand_metrics
                else _jaccard(target_metrics, cand_metrics)
            )
            segment_score = (
                1.0
                if not target_segments and not cand_segments
                else _jaccard(target_segments, cand_segments)
            )
            entity_score = (
                1.0
                if not target_entities and not cand_entities
                else _jaccard(target_entities, cand_entities)
            )
            time_score = (
                1.0
                if target_time != "none"
                and _time_structure(cand_ast) == target_time
                else (
                    0.5
                    if target_time != "none"
                    and _time_structure(cand_ast) != "none"
                    else 0.0
                )
            )
            dialect_ok = 1.0 if cand.dialect == dialect else 0.0

            # Require non-vacuous semantic overlap — text alone is never enough
            semantic_signals = []
            if target_metrics or cand_metrics:
                semantic_signals.append(metric_score)
            if target_segments or cand_segments:
                semantic_signals.append(segment_score)
            if target_entities or cand_entities:
                semantic_signals.append(entity_score)
            semantic_core = max(semantic_signals) if semantic_signals else 0.0
            if semantic_core < 0.01 and text_score < 0.85:
                if text_score < 0.5:
                    continue

            score = (
                0.20 * text_score
                + 0.30 * metric_score
                + 0.15 * segment_score
                + 0.15 * entity_score
                + 0.10 * time_score
                + 0.10 * dialect_ok
            )
            if score < min_score:
                continue

            adaptable = False
            notes: list[str] = []
            if (
                metric_score >= 0.99
                and segment_score >= 0.99
                and time_score < 1.0
                and target_time != "none"
            ):
                adaptable = True
                notes.append("reuse joins/metrics/filters; adapt time range only")

            matches.append(
                VerifiedQueryMatch(
                    query=cand,
                    score=round(score, 4),
                    signals={
                        "text": round(text_score, 4),
                        "metrics": round(metric_score, 4),
                        "segments": round(segment_score, 4),
                        "entities": round(entity_score, 4),
                        "time": round(time_score, 4),
                        "dialect": dialect_ok,
                    },
                    adaptable=adaptable,
                    adaptation_notes=notes,
                )
            )

        matches.sort(key=lambda m: m.score, reverse=True)
        return matches[:limit]

    def adapt_time_only(
        self,
        verified: VerifiedQuery,
        *,
        new_time: dict[str, Any],
    ) -> dict[str, Any]:
        """Return adapted AST + original SQL (SQL unchanged — caller must recompile).

        Never mutates verified SQL via string replacement.
        """
        ast = dict(verified.semantic_ast or {})
        ast["time"] = dict(new_time)
        return {
            "semantic_ast": ast,
            "verified_sql": verified.verified_sql,
            "adaptation": "time_only",
            "note": "SQL reused only when planner revalidates AST equivalence",
        }

    async def suggest_mappings_from_sql_history(
        self,
        organization_id: UUID,
        *,
        concept: str,
        successful_sql: list[str],
        min_evidence: int = 3,
    ) -> MappingSuggestion | None:
        """Infer physical predicates from repeated equality filters — INFERRED only."""
        counts: dict[str, int] = {}
        samples: dict[str, list[str]] = {}
        for sql in successful_sql:
            for col, lit in _EQ_LITERAL_RE.findall(sql or ""):
                pred = f"{col} = '{lit}'"
                counts[pred] = counts.get(pred, 0) + 1
                samples.setdefault(pred, [])
                if len(samples[pred]) < 3:
                    samples[pred].append(sql[:240])
        if not counts:
            return None
        pred, n = max(counts.items(), key=lambda kv: kv[1])
        if n < min_evidence:
            return None
        suggestion = MappingSuggestion(
            organization_id=organization_id,
            concept=concept.strip().lower(),
            physical_predicate=pred,
            evidence_count=n,
            evidence_sample=samples.get(pred, []),
            status=MappingSuggestionStatus.INFERRED,
        )
        return await self._store.upsert_mapping_suggestion(suggestion)
