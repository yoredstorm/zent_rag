# =============================================================================
# Structured Document Repository — Postgres (Knowledge V2, Phase B)
# =============================================================================
# Persiste el árbol StructuredDocument en structured_documents +
# structured_blocks. Scoped estricto por organization_id y source_id; nunca
# expone un documento de otro tenant. node_type cubre block/page/section/
# table/figure para que la recuperación hierárquica (Phase C+) trabaje sobre
# bloques reales, no solo sobre texto aplanado.
# =============================================================================
from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import text

from src.core.domain.knowledge_v2 import (
    DocumentTable,
    StructuredDocument,
)
from src.core.ports.structured import StructuredDocumentRepository
from src.infrastructure.postgres.session import get_async_session

_DOCUMENT_COLUMNS = (
    "id, organization_id, workspace_id, source_id, knowledge_base_id, "
    "external_id, title, content_hash, mime_type, document_type, language, "
    "provenance, status, page_count, section_count, table_count, figure_count, "
    "block_count, metadata, created_at, updated_at"
)


class PostgresStructuredDocumentRepository(StructuredDocumentRepository):

    # ------------------------------------------------------------------
    # Writers
    # ------------------------------------------------------------------
    async def upsert_document(self, document: StructuredDocument) -> str:
        session = await get_async_session()
        try:
            change_kind = await self._detect_change_kind(session, document)
            await session.execute(
                text(
                    f"""
                    INSERT INTO structured_documents
                        ({_DOCUMENT_COLUMNS})
                    VALUES (
                        :id, :organization_id, :workspace_id, :source_id,
                        :knowledge_base_id, :external_id, :title,
                        :content_hash, :mime_type, :document_type, :language,
                        :provenance, :status, :page_count, :section_count,
                        :table_count, :figure_count, :block_count,
                        CAST(:metadata AS jsonb), now(), now()
                    )
                    ON CONFLICT (organization_id, source_id, external_id)
                    DO UPDATE SET
                        title = EXCLUDED.title,
                        content_hash = EXCLUDED.content_hash,
                        mime_type = EXCLUDED.mime_type,
                        document_type = EXCLUDED.document_type,
                        language = EXCLUDED.language,
                        provenance = EXCLUDED.provenance,
                        status = EXCLUDED.status,
                        page_count = EXCLUDED.page_count,
                        section_count = EXCLUDED.section_count,
                        table_count = EXCLUDED.table_count,
                        figure_count = EXCLUDED.figure_count,
                        block_count = EXCLUDED.block_count,
                        metadata = EXCLUDED.metadata,
                        updated_at = now()
                    """
                ),
                {
                    "id": str(document.id),
                    "organization_id": str(document.organization_id),
                    "workspace_id": _uuid_or_none(document.workspace_id),
                    "source_id": _uuid_or_none(document.source_id),
                    "knowledge_base_id": None,
                    "external_id": document.external_id,
                    "title": document.title,
                    "content_hash": document.content_hash,
                    "mime_type": document.mime_type,
                    "document_type": document.document_type,
                    "language": document.language,
                    "provenance": document.provenance.value,
                    "status": document.status.value,
                    "page_count": document.page_count,
                    "section_count": document.section_count,
                    "table_count": document.table_count,
                    "figure_count": document.figure_count,
                    "block_count": len(document.blocks),
                    "metadata": json.dumps(document.metadata, default=str),
                },
            )
            await self._record_version(session, document, change_kind)
            # Reemplazo del árbol: delete + insert idempotente.
            await session.execute(
                text(
                    "DELETE FROM structured_blocks "
                    "WHERE document_id = :did AND organization_id = :oid"
                ),
                {"did": str(document.id), "oid": str(document.organization_id)},
            )
            rows = _blocks_to_rows(document)
            if rows:
                columns = (
                    "id, document_id, organization_id, workspace_id, source_id, "
                    "node_type, kind, content_type, text, order_index, page_number, "
                    "section_path, parent_id, depth, heading, page_start, page_end, "
                    "char_start, char_end, bbox, language, token_count, content_hash, "
                    "metadata"
                )
                placeholders = _placeholder_sql(columns)
                await session.execute(
                    text(
                        f"INSERT INTO structured_blocks ({columns}) VALUES {placeholders}"
                    ),
                    [row for row in rows],
                )
            await session.commit()
            return change_kind
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def _detect_change_kind(self, session, document: StructuredDocument) -> str:
        from src.core.domain.knowledge_v2 import DocumentChangeKind

        result = await session.execute(
            text(
                "SELECT content_hash FROM structured_documents "
                "WHERE id = :did AND organization_id = :oid"
            ),
            {"did": str(document.id), "oid": str(document.organization_id)},
        )
        row = result.fetchone()
        if row is None:
            return DocumentChangeKind.CREATED.value
        if row.content_hash == document.content_hash:
            return DocumentChangeKind.UNCHANGED.value
        return DocumentChangeKind.UPDATED.value

    async def _record_version(self, session, document: StructuredDocument, change_kind: str) -> None:
        result = await session.execute(
            text(
                "SELECT COALESCE(MAX(version), 0) AS max_version, "
                "(SELECT id FROM structured_document_versions sv "
                " WHERE sv.document_id = :did AND sv.organization_id = :oid "
                " ORDER BY version DESC LIMIT 1) AS previous_id "
                "FROM structured_document_versions "
                "WHERE document_id = :did AND organization_id = :oid"
            ),
            {"did": str(document.id), "oid": str(document.organization_id)},
        )
        row = result.fetchone()
        next_version = int(row.max_version) + 1
        await session.execute(
            text(
                "INSERT INTO structured_document_versions "
                "(id, organization_id, document_id, workspace_id, source_id, "
                "version, content_hash, change_kind, previous_version_id, "
                "metadata, created_at) "
                "VALUES (gen_random_uuid(), :oid, :did, :wid, :sid, :version, "
                ":content_hash, :change_kind, :previous_id, CAST(:metadata AS jsonb), now())"
            ),
            {
                "oid": str(document.organization_id),
                "did": str(document.id),
                "wid": _uuid_or_none(document.workspace_id),
                "sid": _uuid_or_none(document.source_id),
                "version": next_version,
                "content_hash": document.content_hash,
                "change_kind": change_kind,
                "previous_id": str(row.previous_id) if row.previous_id else None,
                "metadata": json.dumps({"title": document.title}, default=str),
            },
        )

    # ------------------------------------------------------------------
    # Readers (todas scoped por organization_id)
    # ------------------------------------------------------------------
    async def get_document(
        self, organization_id: UUID, document_id: UUID
    ) -> dict | None:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    f"SELECT {_DOCUMENT_COLUMNS} FROM structured_documents "
                    "WHERE id = :did AND organization_id = :oid"
                ),
                {"did": str(document_id), "oid": str(organization_id)},
            )
            row = result.fetchone()
            if row is None:
                return None
            return _row_to_dict(row)
        finally:
            await session.close()

    async def list_documents(
        self,
        organization_id: UUID,
        source_id: UUID,
        limit: int = 100,
    ) -> list[dict]:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    f"SELECT {_DOCUMENT_COLUMNS} FROM structured_documents "
                    "WHERE organization_id = :oid AND source_id = :sid "
                    "ORDER BY updated_at DESC LIMIT :limit"
                ),
                {"oid": str(organization_id), "sid": str(source_id), "limit": limit},
            )
            return [_row_to_dict(row) for row in result.fetchall()]
        finally:
            await session.close()

    async def delete_for_source(self, organization_id: UUID, source_id: UUID) -> None:
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    "DELETE FROM structured_documents "
                    "WHERE organization_id = :oid AND source_id = :sid"
                ),
                {"oid": str(organization_id), "sid": str(source_id)},
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ---------------------------------------------------------------------------
# Helpers de mapeo (domain → rows)
# ---------------------------------------------------------------------------

def _uuid_or_none(value: UUID | None) -> str | None:
    return str(value) if value is not None else None


def _blocks_to_rows(document: StructuredDocument) -> list[dict]:
    rows: list[dict] = []
    for block in document.blocks:
        rows.append(
            _row(
                node_type="block",
                kind=block.kind.value,
                content_type=block.content_type.value,
                text=block.text,
                order_index=block.order,
                page_number=block.page,
                section_path=block.heading_path,
                parent_id=None,
                depth=None,
                heading=None,
                page_start=None,
                page_end=None,
                char_range=block.char_range,
                bbox=block.bbox,
                language=block.language,
                token_count=block.token_count,
                content_hash=block.content_hash,
                metadata=dict(block.metadata),
                document=document,
                block_id=block.id,
            )
        )
    for section in document.sections:
        rows.append(
            _row(
                node_type="section",
                kind="section",
                content_type="markdown",
                text=section.text,
                order_index=section.order,
                page_number=section.page_start,
                section_path=section.section_path,
                parent_id=section.parent_id,
                depth=section.depth,
                heading=section.heading,
                page_start=section.page_start,
                page_end=section.page_end,
                char_range=None,
                bbox=None,
                language=section.language,
                token_count=section.token_count,
                content_hash=section.content_hash,
                metadata=dict(section.metadata),
                document=document,
                block_id=section.id,
            )
        )
    for page in document.pages:
        rows.append(
            _row(
                node_type="page",
                kind="page",
                content_type="text",
                text=page.text,
                order_index=page.page_number,
                page_number=page.page_number,
                section_path=(),
                parent_id=None,
                depth=None,
                heading=None,
                page_start=page.page_number,
                page_end=page.page_number,
                char_range=page.char_range,
                bbox=page.bbox,
                language=page.language,
                token_count=page.token_count,
                content_hash=page.content_hash,
                metadata={"block_ids": [str(b) for b in page.block_ids], **page.metadata},
                document=document,
                block_id=page.id,
            )
        )
    for table in document.tables:
        rows.append(
            _row(
                node_type="table",
                kind="table",
                content_type="table",
                text=_render_table(table),
                order_index=0,
                page_number=table.page,
                section_path=(),
                parent_id=None,
                depth=None,
                heading=table.caption,
                page_start=table.page,
                page_end=table.page,
                char_range=table.char_range,
                bbox=table.bbox,
                language=None,
                token_count=table.token_count,
                content_hash=table.content_hash,
                metadata={
                    "headers": list(table.headers),
                    "rows": [list(r) for r in table.rows],
                    **table.metadata,
                },
                document=document,
                block_id=table.id,
            )
        )
    for figure in document.figures:
        rows.append(
            _row(
                node_type="figure",
                kind="figure",
                content_type="figure",
                text=figure.caption,
                order_index=0,
                page_number=figure.page,
                section_path=(),
                parent_id=None,
                depth=None,
                heading=figure.caption,
                page_start=figure.page,
                page_end=figure.page,
                char_range=None,
                bbox=figure.bbox,
                language=None,
                token_count=figure.token_count,
                content_hash=figure.content_hash,
                metadata={
                    "figure_type": figure.figure_type,
                    "alt_text": figure.alt_text,
                    **figure.metadata,
                },
                document=document,
                block_id=figure.id,
            )
        )
    return rows


def _row(
    *,
    node_type: str,
    kind: str,
    content_type: str,
    text: str,
    order_index: int,
    page_number: int | None,
    section_path: tuple[str, ...],
    parent_id: UUID | None,
    depth: int | None,
    heading: str | None,
    page_start: int | None,
    page_end: int | None,
    char_range: object | None,
    bbox: object | None,
    language: str | None,
    token_count: int,
    content_hash: str | None,
    metadata: dict,
    document: StructuredDocument,
    block_id: UUID,
) -> dict:
    char_start = char_end = None
    if char_range is not None:
        char_start, char_end = char_range.start, char_range.end
    return {
        "id": str(block_id),
        "document_id": str(document.id),
        "organization_id": str(document.organization_id),
        "workspace_id": _uuid_or_none(document.workspace_id),
        "source_id": _uuid_or_none(document.source_id),
        "node_type": node_type,
        "kind": kind,
        "content_type": content_type,
        "text": text,
        "order_index": order_index,
        "page_number": page_number,
        "section_path": json.dumps(list(section_path)),
        "parent_id": _uuid_or_none(parent_id),
        "depth": depth,
        "heading": heading,
        "page_start": page_start,
        "page_end": page_end,
        "char_start": char_start,
        "char_end": char_end,
        "bbox": json.dumps(_bbox_to_dict(bbox)) if bbox is not None else None,
        "language": language,
        "token_count": token_count,
        "content_hash": content_hash,
        "metadata": json.dumps(metadata, default=str),
    }


def _bbox_to_dict(bbox: object) -> dict:
    if bbox is None:
        return {}
    return {
        "page": bbox.page,
        "x0": bbox.x0,
        "y0": bbox.y0,
        "x1": bbox.x1,
        "y1": bbox.y1,
        "unit": bbox.unit,
    }


def _render_table(table: DocumentTable) -> str:
    parts = [table.caption] if table.caption else []
    parts.append(" | ".join(table.headers))
    parts.extend(" | ".join(row) for row in table.rows)
    return "\n".join(parts)


def _placeholder_sql(columns: str) -> str:
    names = [c.strip() for c in columns.split(",")]
    return "(" + ", ".join(f":{name}" for name in names) + ")"


def _row_to_dict(row) -> dict:
    return {
        "id": str(row.id),
        "organization_id": str(row.organization_id),
        "workspace_id": str(row.workspace_id) if row.workspace_id else None,
        "source_id": str(row.source_id) if row.source_id else None,
        "knowledge_base_id": str(row.knowledge_base_id) if row.knowledge_base_id else None,
        "external_id": row.external_id,
        "title": row.title,
        "content_hash": row.content_hash,
        "mime_type": row.mime_type,
        "document_type": row.document_type,
        "language": row.language,
        "provenance": row.provenance,
        "status": row.status,
        "page_count": row.page_count,
        "section_count": row.section_count,
        "table_count": row.table_count,
        "figure_count": row.figure_count,
        "block_count": row.block_count,
        "metadata": row.metadata if isinstance(row.metadata, dict) else {},
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }
