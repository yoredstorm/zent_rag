# =============================================================================
# KnowledgeCorpus Repository — Postgres (Knowledge V2, Phase D slice 2)
# =============================================================================
# knowledge_corpora + kb_sources.corpus_id / knowledge_bases.corpus_id.
# Scoped estricto por organization_id; workspace opcional.
# =============================================================================
from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import text

from src.core.domain.knowledge_v2 import KnowledgeCorpus
from src.core.ports.knowledge_corpus import KnowledgeCorpusRepository
from src.infrastructure.postgres.session import get_async_session

_COLUMNS = (
    "id, organization_id, workspace_id, name, slug, description, "
    "knowledge_base_id, status, metadata, created_at, updated_at"
)


class PostgresKnowledgeCorpusRepository(KnowledgeCorpusRepository):

    async def create_corpus(self, corpus: KnowledgeCorpus) -> KnowledgeCorpus:
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    f"""
                    INSERT INTO knowledge_corpora ({_COLUMNS})
                    VALUES (
                        :id, :organization_id, :workspace_id, :name, :slug,
                        :description, :knowledge_base_id, :status,
                        CAST(:metadata AS jsonb), now(), now()
                    )
                    ON CONFLICT (organization_id, workspace_id, slug)
                    DO UPDATE SET name = EXCLUDED.name, updated_at = now()
                    """
                ),
                {
                    "id": str(corpus.id),
                    "organization_id": str(corpus.organization_id),
                    "workspace_id": str(corpus.workspace_id),
                    "name": corpus.name,
                    "slug": corpus.slug,
                    "description": corpus.description or "",
                    "knowledge_base_id": str(corpus.knowledge_base_id)
                    if corpus.knowledge_base_id
                    else None,
                    "status": corpus.status.value,
                    "metadata": json.dumps(corpus.metadata, default=str),
                },
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
        return corpus

    async def get_corpus(
        self, organization_id: UUID, corpus_id: UUID
    ) -> dict | None:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    f"SELECT {_COLUMNS} FROM knowledge_corpora "
                    "WHERE id = :cid AND organization_id = :oid"
                ),
                {"cid": str(corpus_id), "oid": str(organization_id)},
            )
            row = result.fetchone()
            return _row_to_dict(row) if row is not None else None
        finally:
            await session.close()

    async def get_corpus_by_slug(
        self, organization_id: UUID, workspace_id: UUID, slug: str
    ) -> dict | None:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    f"SELECT {_COLUMNS} FROM knowledge_corpora "
                    "WHERE organization_id = :oid AND workspace_id = :wid "
                    "AND slug = :slug"
                ),
                {"oid": str(organization_id), "wid": str(workspace_id), "slug": slug},
            )
            row = result.fetchone()
            return _row_to_dict(row) if row is not None else None
        finally:
            await session.close()

    async def list_corpora(
        self,
        organization_id: UUID,
        workspace_id: UUID | None = None,
        limit: int = 100,
    ) -> list[dict]:
        session = await get_async_session()
        try:
            query = (
                f"SELECT {_COLUMNS} FROM knowledge_corpora "
                "WHERE organization_id = :oid "
            )
            params: dict = {"oid": str(organization_id), "limit": limit}
            if workspace_id is not None:
                query += "AND workspace_id = :wid "
                params["wid"] = str(workspace_id)
            query += "ORDER BY created_at DESC LIMIT :limit"
            result = await session.execute(text(query), params)
            return [_row_to_dict(row) for row in result.fetchall()]
        finally:
            await session.close()

    async def attach_source(
        self, organization_id: UUID, source_id: UUID, corpus_id: UUID
    ) -> None:
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    "UPDATE kb_sources SET corpus_id = :cid, updated_at = now() "
                    "WHERE id = :sid AND organization_id = :oid"
                ),
                {
                    "cid": str(corpus_id),
                    "sid": str(source_id),
                    "oid": str(organization_id),
                },
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def detach_source(
        self, organization_id: UUID, source_id: UUID
    ) -> None:
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    "UPDATE kb_sources SET corpus_id = NULL, updated_at = now() "
                    "WHERE id = :sid AND organization_id = :oid"
                ),
                {"sid": str(source_id), "oid": str(organization_id)},
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


def _row_to_dict(row) -> dict:
    return {
        "id": str(row.id),
        "organization_id": str(row.organization_id),
        "workspace_id": str(row.workspace_id),
        "name": row.name,
        "slug": row.slug,
        "description": row.description or "",
        "knowledge_base_id": str(row.knowledge_base_id) if row.knowledge_base_id else None,
        "status": row.status,
        "metadata": row.metadata if isinstance(row.metadata, dict) else {},
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }
