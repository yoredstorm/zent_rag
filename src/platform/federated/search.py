# =============================================================================
# Federated Search — búsqueda cross-knowledge-base con ranking unificado.
# Consulta cada KB (scoping estricto por organización) y fusiona resultados
# con scores normalizados por KB + dedupe por documento.
# =============================================================================
from __future__ import annotations

import asyncio
import hashlib
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)


async def _resolve_kbs(
    organization_id: UUID,
    knowledge_base_ids: list[UUID] | None,
    workspace_ids: list[UUID] | None,
) -> list[dict]:
    session = await get_async_session()
    try:
        if knowledge_base_ids:
            sql = (
                "SELECT kb.id, kb.name, kb.workspace_id, COALESCE(w.name, 'sin workspace') AS workspace_name "
                "FROM knowledge_bases kb LEFT JOIN workspaces w ON w.id = kb.workspace_id "
                "WHERE kb.organization_id = :oid AND kb.id = ANY(:ids)"
            )
            rows = (await session.execute(text(sql), {"oid": organization_id, "ids": knowledge_base_ids})).fetchall()
        elif workspace_ids:
            sql = (
                "SELECT kb.id, kb.name, kb.workspace_id, COALESCE(w.name, 'sin workspace') AS workspace_name "
                "FROM knowledge_bases kb LEFT JOIN workspaces w ON w.id = kb.workspace_id "
                "WHERE kb.organization_id = :oid AND kb.workspace_id = ANY(:ids)"
            )
            rows = (await session.execute(text(sql), {"oid": organization_id, "ids": workspace_ids})).fetchall()
        else:
            sql = (
                "SELECT kb.id, kb.name, kb.workspace_id, COALESCE(w.name, 'sin workspace') AS workspace_name "
                "FROM knowledge_bases kb LEFT JOIN workspaces w ON w.id = kb.workspace_id "
                "WHERE kb.organization_id = :oid"
            )
            rows = (await session.execute(text(sql), {"oid": organization_id})).fetchall()
    finally:
        await session.close()
    return [
        {
            "id": r.id,
            "name": r.name,
            "workspace_id": r.workspace_id,
            "workspace_name": r.workspace_name,
        }
        for r in rows
    ]


def _chunk_key(chunk) -> str:
    raw = chunk.payload.get("content") or chunk.payload.get("document_id") or chunk.id
    return hashlib.sha256(str(raw).encode()).hexdigest()


async def federated_search(
    *,
    organization_id: UUID,
    query: str,
    vector_store,
    embedding_provider,
    knowledge_base_ids: list[UUID] | None = None,
    workspace_ids: list[UUID] | None = None,
    top_k: int = 10,
    per_kb_top: int = 10,
) -> dict:
    kbs = await _resolve_kbs(organization_id, knowledge_base_ids, workspace_ids)
    if not kbs:
        return {"query": query, "results": [], "sources": [], "kb_count": 0}

    query_embedding = await embedding_provider.embed(query)

    async def _search_kb(kb: dict) -> list[dict]:
        try:
            ctx = await vector_store.search_hybrid(
                organization_id,
                query,
                query_embedding,
                top_k=per_kb_top,
                knowledge_base_id=kb["id"],
                role="admin",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Federated KB search failed", kb=str(kb["id"]), error=str(exc)[:150])
            return []
        chunks = ctx.chunks if hasattr(ctx, "chunks") else ctx
        if not chunks:
            return []
        max_score = max((c.score or 0.0) for c in chunks) or 1.0
        return [
            {
                "chunk": c,
                "score": (c.score or 0.0) / max_score,
                "kb_id": kb["id"],
                "kb_name": kb["name"],
                "workspace_id": kb["workspace_id"],
                "workspace_name": kb["workspace_name"],
            }
            for c in chunks
        ]

    per_kb_results = await asyncio.gather(*[_search_kb(kb) for kb in kbs])
    merged: dict[str, dict] = {}
    for results in per_kb_results:
        for item in results:
            key = _chunk_key(item["chunk"])
            if key in merged:
                # Mantener el mejor score entre KBs.
                if item["score"] > merged[key]["score"]:
                    merged[key] = item
            else:
                merged[key] = item

    ranked = sorted(merged.values(), key=lambda x: -x["score"])[:top_k]
    return {
        "query": query,
        "kb_count": len(kbs),
        "sources": [
            {
                "kb_id": str(item["kb_id"]),
                "kb_name": item["kb_name"],
                "workspace_id": str(item["workspace_id"]) if item["workspace_id"] else None,
                "workspace_name": item["workspace_name"],
                "score": round(item["score"], 4),
                "content": item["chunk"].payload.get("content", "") if item["chunk"].payload else "",
                "document_id": str(item["chunk"].id) if item["chunk"].id else None,
            }
            for item in ranked
        ],
        "results": [
            {
                "score": round(item["score"], 4),
                "content": item["chunk"].payload.get("content", "") if item["chunk"].payload else "",
                "metadata": {
                    k: v
                    for k, v in (item["chunk"].payload or {}).items()
                    if k not in ("content",)
                },
            }
            for item in ranked
        ],
    }
