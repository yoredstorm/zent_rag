# =============================================================================
# Knowledge V2 — usage & cost tracker (brief §41)
# =============================================================================
# Registra por org/workspace/corpus/source y categoría:
#   embedding | llm | rerank | storage | query
# con tokens y costo estimado. Scoped estricto por organization_id; los tokens
# de embedding se ESTIMAN desde token_count de los chunks (documentado), los
# de LLM son los reales reportados por el provider.
# =============================================================================
from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.postgres.session import get_async_session

_INSERT = text(
    """
    INSERT INTO knowledge_usage
        (organization_id, workspace_id, corpus_id, source_id, category,
         tokens, cost_usd, metadata, created_at)
    VALUES
        (:oid, :wid, :cid, :sid, :category, :tokens, :cost_usd,
         CAST(:metadata AS jsonb), now())
    """
)


class KnowledgeUsageTracker:
    """Tracker idempotente de costos del pipeline V2 (registra, no modela)."""

    async def record(
        self,
        organization_id: UUID,
        *,
        category: str,
        tokens: int = 0,
        cost_usd: float = 0.0,
        workspace_id: UUID | None = None,
        corpus_id: UUID | None = None,
        source_id: UUID | None = None,
        metadata: dict | None = None,
    ) -> None:
        if category not in {"embedding", "llm", "rerank", "storage", "query"}:
            raise ValueError(f"unknown usage category: {category}")
        session = await get_async_session()
        try:
            await session.execute(
                _INSERT,
                {
                    "oid": str(organization_id),
                    "wid": str(workspace_id) if workspace_id else None,
                    "cid": str(corpus_id) if corpus_id else None,
                    "sid": str(source_id) if source_id else None,
                    "category": category,
                    "tokens": max(int(tokens), 0),
                    "cost_usd": max(float(cost_usd), 0.0),
                    "metadata": json.dumps(metadata or {}, default=str),
                },
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def record_embedding_tokens(
        self,
        organization_id: UUID,
        chunk_token_count: int,
        *,
        model: str | None = None,
        cost_usd: float = 0.0,
        workspace_id: UUID | None = None,
        corpus_id: UUID | None = None,
        source_id: UUID | None = None,
    ) -> None:
        """Estima tokens de embedding desde el token_count de los chunks."""
        metadata = {"method": "token_count_estimate"}
        if model:
            metadata["model"] = model
        await self.record(
            organization_id,
            category="embedding",
            tokens=chunk_token_count,
            cost_usd=cost_usd,
            workspace_id=workspace_id,
            corpus_id=corpus_id,
            source_id=source_id,
            metadata=metadata,
        )

    async def record_llm_tokens(
        self,
        organization_id: UUID,
        *,
        prompt_tokens: int,
        completion_tokens: int,
        cost_usd: float = 0.0,
        model: str | None = None,
        purpose: str = "",
        workspace_id: UUID | None = None,
        source_id: UUID | None = None,
        metadata: dict | None = None,
    ) -> None:
        """Uso real de LLM durante la ingesta (hoy: resúmenes en shadow)."""
        payload = dict(metadata or {})
        if model:
            payload["model"] = model
        if purpose:
            payload["purpose"] = purpose
        payload["prompt_tokens"] = int(prompt_tokens)
        payload["completion_tokens"] = int(completion_tokens)
        await self.record(
            organization_id,
            category="llm",
            tokens=int(prompt_tokens) + int(completion_tokens),
            cost_usd=cost_usd,
            workspace_id=workspace_id,
            source_id=source_id,
            metadata=payload,
        )

    async def summary(
        self,
        organization_id: UUID,
        corpus_id: UUID | None = None,
    ) -> dict:
        """Totales por categoría (scoped por org, opcional corpus)."""
        session = await get_async_session()
        try:
            query = (
                "SELECT category, SUM(tokens)::bigint AS tokens, "
                "SUM(cost_usd) AS cost_usd "
                "FROM knowledge_usage WHERE organization_id = :oid "
            )
            params: dict = {"oid": str(organization_id)}
            if corpus_id is not None:
                query += "AND corpus_id = :cid "
                params["cid"] = str(corpus_id)
            query += "GROUP BY category"
            rows = (
                await session.execute(text(query), params)
            ).fetchall()
            return {
                str(row.category): {
                    "tokens": int(row.tokens or 0),
                    "cost_usd": round(float(row.cost_usd or 0), 6),
                }
                for row in rows
            }
        finally:
            await session.close()
