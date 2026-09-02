# =============================================================================
# Index Versions — snapshot del estado del índice por knowledge base
# =============================================================================
from __future__ import annotations

from uuid import UUID

from sqlalchemy import text

from src.infrastructure.postgres.session import get_async_session


async def record_index_version(
    organization_id: UUID,
    knowledge_base_id: UUID,
    *,
    embedding_model: str | None,
    chunk_size: int | None,
    chunk_overlap: int | None,
    vector_count: int,
) -> dict:
    """Registra una versión del índice tras un sync completado."""
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO index_versions (id, organization_id, knowledge_base_id, "
                    "embedding_model, chunk_size, chunk_overlap, vector_count, source_version) "
                    "SELECT uuid_generate_v4(), :oid, :kid, :em, :cs, :co, :vc, "
                    "COALESCE(MAX(source_version), 0) + 1 "
                    "FROM index_versions WHERE knowledge_base_id = :kid "
                    "RETURNING id, source_version, vector_count, created_at"
                ),
                {
                    "oid": organization_id,
                    "kid": knowledge_base_id,
                    "em": embedding_model,
                    "cs": chunk_size,
                    "co": chunk_overlap,
                    "vc": max(int(vector_count), 0),
                },
            )
        ).fetchone()
        await session.commit()
        return {
            "id": str(row.id),
            "source_version": int(row.source_version),
            "vector_count": int(row.vector_count),
            "created_at": row.created_at.isoformat(),
        }
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def list_index_versions(
    organization_id: UUID, knowledge_base_id: UUID, limit: int = 50
) -> list[dict]:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT id, embedding_model, chunk_size, chunk_overlap, "
                    "vector_count, source_version, created_at "
                    "FROM index_versions "
                    "WHERE organization_id = :oid AND knowledge_base_id = :kid "
                    "ORDER BY created_at DESC LIMIT :limit"
                ),
                {"oid": organization_id, "kid": knowledge_base_id, "limit": limit},
            )
        ).fetchall()
    finally:
        await session.close()
    return [
        {
            "id": str(r.id),
            "embedding_model": r.embedding_model,
            "chunk_size": r.chunk_size,
            "chunk_overlap": r.chunk_overlap,
            "vector_count": int(r.vector_count),
            "source_version": int(r.source_version),
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]
