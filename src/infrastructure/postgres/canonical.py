# =============================================================================
# Canonical Knowledge Repository — Postgres (Phase 1)
# =============================================================================
# Identidad canónica (knowledge_canonical_objects) + mapping a objetos físicos
# (knowledge_canonical_links). Scoped estricto por organization_id; nunca
# resuelve ni enlaza objetos de otro tenant.
# =============================================================================
from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import text

from src.core.domain.canonical import (
    CanonicalKind,
    CanonicalLink,
    CanonicalObject,
    CanonicalRef,
    CanonicalSystem,
)
from src.core.domain.catalog import CatalogProvenance
from src.core.domain.knowledge_v2 import KnowledgeObjectStatus
from src.core.ports.canonical import CanonicalKnowledgeRepository
from src.infrastructure.postgres.session import get_async_session

_OBJECT_COLUMNS = (
    "id, organization_id, workspace_id, kind, natural_key, title, provenance, "
    "status, confidence, authority_level, valid_from, valid_to, metadata, "
    "created_at, updated_at"
)

_LINK_COLUMNS = (
    "id, canonical_id, organization_id, workspace_id, system, object_type, "
    "object_ref, is_primary, metadata, created_at"
)


class PostgresCanonicalKnowledgeRepository(CanonicalKnowledgeRepository):

    # ------------------------------------------------------------------
    # Objects
    # ------------------------------------------------------------------
    async def upsert_object(self, obj: CanonicalObject) -> CanonicalObject:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    f"""
                    INSERT INTO knowledge_canonical_objects ({_OBJECT_COLUMNS})
                    VALUES (
                        :id, :organization_id, :workspace_id, :kind, :natural_key,
                        :title, :provenance, :status, :confidence,
                        :authority_level, :valid_from, :valid_to,
                        CAST(:metadata AS jsonb), now(), now()
                    )
                    ON CONFLICT (organization_id, kind, natural_key)
                    DO UPDATE SET
                        workspace_id = EXCLUDED.workspace_id,
                        title = EXCLUDED.title,
                        provenance = EXCLUDED.provenance,
                        status = EXCLUDED.status,
                        confidence = EXCLUDED.confidence,
                        authority_level = EXCLUDED.authority_level,
                        valid_from = EXCLUDED.valid_from,
                        valid_to = EXCLUDED.valid_to,
                        metadata = EXCLUDED.metadata,
                        updated_at = now()
                    RETURNING {_OBJECT_COLUMNS}
                    """
                ),
                {
                    "id": str(obj.canonical_id),
                    "organization_id": str(obj.organization_id),
                    "workspace_id": _uuid_or_none(obj.workspace_id),
                    "kind": obj.kind.value,
                    "natural_key": obj.natural_key,
                    "title": obj.title,
                    "provenance": obj.provenance.value,
                    "status": obj.status.value,
                    "confidence": obj.confidence,
                    "authority_level": obj.authority_level,
                    "valid_from": obj.valid_from,
                    "valid_to": obj.valid_to,
                    "metadata": json.dumps(obj.metadata, default=str),
                },
            )
            row = result.fetchone()
            await session.commit()
            return _row_to_object(row)
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def get_object(
        self, organization_id: UUID, canonical_id: UUID
    ) -> CanonicalObject | None:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    f"SELECT {_OBJECT_COLUMNS} FROM knowledge_canonical_objects "
                    "WHERE id = :id AND organization_id = :oid"
                ),
                {"id": str(canonical_id), "oid": str(organization_id)},
            )
            row = result.fetchone()
            return _row_to_object(row) if row is not None else None
        finally:
            await session.close()

    async def get_by_natural_key(
        self, organization_id: UUID, kind: CanonicalKind, natural_key: str
    ) -> CanonicalObject | None:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    f"SELECT {_OBJECT_COLUMNS} FROM knowledge_canonical_objects "
                    "WHERE organization_id = :oid AND kind = :kind "
                    "AND natural_key = :natural_key"
                ),
                {
                    "oid": str(organization_id),
                    "kind": kind.value,
                    "natural_key": natural_key,
                },
            )
            row = result.fetchone()
            return _row_to_object(row) if row is not None else None
        finally:
            await session.close()

    # ------------------------------------------------------------------
    # Links
    # ------------------------------------------------------------------
    async def link(
        self,
        organization_id: UUID,
        canonical_id: UUID,
        ref: CanonicalRef,
        *,
        workspace_id: UUID | None = None,
        is_primary: bool = False,
        metadata: dict | None = None,
    ) -> CanonicalLink:
        session = await get_async_session()
        try:
            owner = await session.execute(
                text(
                    "SELECT 1 FROM knowledge_canonical_objects "
                    "WHERE id = :id AND organization_id = :oid"
                ),
                {"id": str(canonical_id), "oid": str(organization_id)},
            )
            if owner.fetchone() is None:
                raise ValueError(
                    "canonical object not found for this organization"
                )
            result = await session.execute(
                text(
                    f"""
                    INSERT INTO knowledge_canonical_links ({_LINK_COLUMNS})
                    VALUES (
                        gen_random_uuid(), :canonical_id, :organization_id,
                        :workspace_id, :system, :object_type, :object_ref,
                        :is_primary, CAST(:metadata AS jsonb), now()
                    )
                    ON CONFLICT (organization_id, system, object_type, object_ref)
                    DO UPDATE SET
                        canonical_id = EXCLUDED.canonical_id,
                        workspace_id = EXCLUDED.workspace_id,
                        is_primary = EXCLUDED.is_primary,
                        metadata = EXCLUDED.metadata
                    RETURNING {_LINK_COLUMNS}
                    """
                ),
                {
                    "canonical_id": str(canonical_id),
                    "organization_id": str(organization_id),
                    "workspace_id": _uuid_or_none(workspace_id),
                    "system": ref.system.value,
                    "object_type": ref.object_type,
                    "object_ref": ref.object_ref,
                    "is_primary": is_primary,
                    "metadata": json.dumps(metadata or {}, default=str),
                },
            )
            row = result.fetchone()
            await session.commit()
            return _row_to_link(row)
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def unlink(self, organization_id: UUID, ref: CanonicalRef) -> None:
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    "DELETE FROM knowledge_canonical_links "
                    "WHERE organization_id = :oid AND system = :system "
                    "AND object_type = :object_type AND object_ref = :object_ref"
                ),
                {
                    "oid": str(organization_id),
                    "system": ref.system.value,
                    "object_type": ref.object_type,
                    "object_ref": ref.object_ref,
                },
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def list_links(
        self, organization_id: UUID, canonical_id: UUID
    ) -> list[CanonicalLink]:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    f"SELECT {_LINK_COLUMNS} FROM knowledge_canonical_links "
                    "WHERE organization_id = :oid AND canonical_id = :cid "
                    "ORDER BY created_at, id"
                ),
                {"oid": str(organization_id), "cid": str(canonical_id)},
            )
            return [_row_to_link(row) for row in result.fetchall()]
        finally:
            await session.close()

    async def resolve(
        self, organization_id: UUID, ref: CanonicalRef
    ) -> CanonicalObject | None:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    f"""
                    SELECT {", ".join("o." + c for c in _OBJECT_COLUMNS.split(", "))}
                    FROM knowledge_canonical_links l
                    JOIN knowledge_canonical_objects o
                      ON o.id = l.canonical_id
                     AND o.organization_id = l.organization_id
                    WHERE l.organization_id = :oid
                      AND l.system = :system
                      AND l.object_type = :object_type
                      AND l.object_ref = :object_ref
                    """
                ),
                {
                    "oid": str(organization_id),
                    "system": ref.system.value,
                    "object_type": ref.object_type,
                    "object_ref": ref.object_ref,
                },
            )
            row = result.fetchone()
            return _row_to_object(row) if row is not None else None
        finally:
            await session.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uuid_or_none(value: UUID | None) -> str | None:
    return str(value) if value is not None else None


def _row_to_object(row) -> CanonicalObject:
    return CanonicalObject(
        organization_id=row.organization_id,
        kind=CanonicalKind(row.kind),
        natural_key=row.natural_key,
        title=row.title or "",
        workspace_id=row.workspace_id,
        provenance=CatalogProvenance(row.provenance),
        status=KnowledgeObjectStatus(row.status),
        confidence=row.confidence,
        authority_level=row.authority_level,
        valid_from=row.valid_from,
        valid_to=row.valid_to,
        metadata=row.metadata if isinstance(row.metadata, dict) else {},
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _row_to_link(row) -> CanonicalLink:
    return CanonicalLink(
        canonical_id=row.canonical_id,
        organization_id=row.organization_id,
        ref=CanonicalRef(
            system=CanonicalSystem(row.system),
            object_type=row.object_type,
            object_ref=row.object_ref,
        ),
        workspace_id=row.workspace_id,
        is_primary=bool(row.is_primary),
        metadata=row.metadata if isinstance(row.metadata, dict) else {},
        created_at=row.created_at,
    )
