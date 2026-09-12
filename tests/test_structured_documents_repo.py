# =============================================================================
# Knowledge V2 — Structured Document repository (Phase B, Postgres real)
# =============================================================================
# Roundtrip del árbol StructuredDocument + aislamiento escricto por
# organization_id (nunca expone documentos de otro tenant).
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text

from src.infrastructure.postgres.relational_db import PostgresOrganizationRepository
from src.infrastructure.postgres.session import get_async_session
from src.infrastructure.postgres.structured_documents import (
    PostgresStructuredDocumentRepository,
)
from src.knowledge.structure import TextParser

_PARSER = TextParser()


async def _build_document(
    organization_id,
    external_id: str,
    *,
    source_id=None,
    markdown: str | None = None,
):
    md = markdown or "# Manual\n\nComisión 5%.\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n"
    doc = _PARSER.parse(
        md.encode("utf-8"),
        organization_id=organization_id,
        external_id=external_id,
        source_id=source_id or uuid4(),
        workspace_id=uuid4(),
    )
    doc.check_consistency()
    return doc


@pytest.fixture
async def org():
    repo = PostgresOrganizationRepository()
    return await repo.create_organization(uuid4(), f"Structured Org {uuid4().hex[:6]}")


@pytest.mark.asyncio
async def test_structured_document_repo_roundtrip_and_isolation(org) -> None:
    repo = PostgresStructuredDocumentRepository()
    source_id = uuid4()
    doc = await _build_document(org.id, "manual.md", source_id=source_id)
    first = await repo.upsert_document(doc)
    assert first == "created"

    meta = await repo.get_document(org.id, doc.id)
    assert meta is not None
    assert meta["title"] == "Manual"
    assert meta["block_count"] == doc.block_count
    assert meta["section_count"] == 1
    assert meta["table_count"] == 1

    # otro tenant nunca ve el documento
    foreign = await repo.get_document(uuid4(), doc.id)
    assert foreign is None

    listed = await repo.list_documents(org.id, doc.source_id)
    assert len(listed) == 1

    # mismo hash → unchanged; contenido distinto (mismo source+external) → updated
    same = await repo.upsert_document(doc)
    assert same == "unchanged"
    changed = await _build_document(
        org.id,
        "manual.md",
        source_id=source_id,
        markdown="# Manual\n\nComisión 7%.\n",
    )
    assert changed.id == doc.id
    changed_kind = await repo.upsert_document(changed)
    assert changed_kind == "updated"
    listed = await repo.list_documents(org.id, doc.source_id)
    assert len(listed) == 1

    # versiones registradas (1 created + 1 unchanged + 1 updated)
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT version, change_kind FROM structured_document_versions "
                    "WHERE document_id = :did AND organization_id = :oid "
                    "ORDER BY version"
                ),
                {"did": doc.id, "oid": org.id},
            )
        ).fetchall()
        assert [(r.version, r.change_kind) for r in rows] == [
            (1, "created"),
            (2, "unchanged"),
            (3, "updated"),
        ]
    finally:
        await session.close()

    await repo.delete_for_source(org.id, doc.source_id)
    remaining = await repo.list_documents(org.id, doc.source_id)
    assert remaining == []
    assert await repo.get_document(org.id, doc.id) is None
