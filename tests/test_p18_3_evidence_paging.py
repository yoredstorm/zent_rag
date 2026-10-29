# =============================================================================
# P18.3-06 - Paginación determinista de evidence_ledger
# =============================================================================
# Orden observable: strength DESC NULLS LAST, created_at DESC, id ASC.
# El cursor debe reproducir exactamente ese orden, incluidos empates y NULL.
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from src.infrastructure.postgres.relational_db import PostgresOrganizationRepository
from src.infrastructure.postgres.session import get_async_session
from src.knowledge.evidence_paging import (
    EvidenceCursor,
    decode_evidence_cursor,
    encode_evidence_cursor,
    fetch_evidence_page,
)

UTC = timezone.utc


async def _org(label: str) -> UUID:
    org = await PostgresOrganizationRepository().create_organization(
        uuid4(), f"P18.3 Paging {label} {uuid4().hex[:6]}"
    )
    return org.id


async def _insert(
    session,
    *,
    organization_id: UUID,
    source_id: UUID,
    rows: list[tuple[str, float | None, datetime, UUID]],
) -> None:
    for excerpt, strength, created_at, evidence_id in rows:
        await session.execute(
            text(
                "INSERT INTO evidence_ledger "
                "(id, organization_id, source_id, excerpt, content_hash, strength, created_at) "
                "VALUES (:id, :oid, :sid, :excerpt, :hash, :strength, :created_at)"
            ),
            {
                "id": str(evidence_id),
                "oid": str(organization_id),
                "sid": str(source_id),
                "excerpt": excerpt,
                "hash": f"hash-{evidence_id}",
                "strength": strength,
                "created_at": created_at,
            },
        )
    await session.commit()


async def _delete_org(organization_id: UUID) -> None:
    session = await get_async_session()
    try:
        await session.execute(
            text("DELETE FROM organizations WHERE id = :oid"),
            {"oid": str(organization_id)},
        )
        await session.commit()
    finally:
        await session.close()


async def _fetch(
    organization_id: UUID,
    source_id: UUID,
    *,
    cursor: EvidenceCursor | None = None,
    limit: int,
):
    session = await get_async_session()
    try:
        return await fetch_evidence_page(
            session,
            organization_id=organization_id,
            source_id=source_id,
            cursor=cursor,
            limit=limit,
        )
    finally:
        await session.close()


async def _walk(
    organization_id: UUID,
    source_id: UUID,
    *,
    page_size: int,
) -> tuple[list[dict], int]:
    pages = 0
    collected: list[dict] = []
    cursor = None
    while True:
        page = await _fetch(
            organization_id, source_id, cursor=cursor, limit=page_size
        )
        pages += 1
        collected.extend(page.rows)
        if not page.has_more:
            break
        cursor = page.next_cursor
        assert cursor is not None
        assert pages < 100, "la paginación no terminó"
    return collected, pages


@pytest.mark.asyncio
async def test_tied_strength_and_timestamp_reach_every_row_exactly_once() -> None:
    org = await _org("empates")
    source_id = uuid4()
    created_at = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    ids = sorted(uuid4() for _ in range(3))
    session = await get_async_session()
    try:
        await _insert(
            session,
            organization_id=org,
            source_id=source_id,
            rows=[
                (f"pasaje {index}", 0.5, created_at, evidence_id)
                for index, evidence_id in enumerate(ids)
            ],
        )
    finally:
        await session.close()

    try:
        collected, pages = await _walk(org, source_id, page_size=1)
        observed = [str(item["id"]) for item in collected]
        assert pages == 3
        assert observed == [str(item) for item in ids]
        assert len(set(observed)) == 3
    finally:
        await _delete_org(org)


@pytest.mark.asyncio
async def test_null_strength_stays_last_and_is_paginated_without_loss() -> None:
    org = await _org("nulls")
    source_id = uuid4()
    created_at = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)
    rows: list[tuple[str, float | None, datetime, UUID]] = [
        ("fuerte", 0.9, created_at, uuid4()),
        ("nulo-a", None, created_at, uuid4()),
        ("nulo-b", None, created_at, uuid4()),
        ("medio", 0.4, created_at, uuid4()),
        ("nulo-c", None, created_at, uuid4()),
    ]
    session = await get_async_session()
    try:
        await _insert(session, organization_id=org, source_id=source_id, rows=rows)
    finally:
        await session.close()

    try:
        collected, _ = await _walk(org, source_id, page_size=1)
        observed = [str(item["id"]) for item in collected]
        expected_non_null = [str(rows[0][3]), str(rows[3][3])]
        expected_null = sorted(str(row[3]) for row in rows if row[1] is None)
        assert observed == expected_non_null + expected_null
    finally:
        await _delete_org(org)


@pytest.mark.asyncio
@pytest.mark.parametrize("total", [1001, 10001])
async def test_full_read_of_large_ledger_has_no_duplicates_or_omissions(total: int) -> None:
    org = await _org(f"grande-{total}")
    source_id = uuid4()
    created_at = datetime(2026, 1, 3, 12, 0, tzinfo=UTC)
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO evidence_ledger "
                "(id, organization_id, source_id, excerpt, content_hash, strength, created_at) "
                "SELECT gen_random_uuid(), :oid, :sid, 'pasaje ' || g, "
                "       md5(g::text), (g % 7)::double precision / 10.0, :created_at "
                "FROM generate_series(1, :total) AS g"
            ),
            {
                "oid": str(org),
                "sid": str(source_id),
                "created_at": created_at,
                "total": total,
            },
        )
        await session.commit()
    finally:
        await session.close()

    try:
        collected, pages = await _walk(org, source_id, page_size=1000)
        observed = [str(item["id"]) for item in collected]
        assert len(observed) == total
        assert len(set(observed)) == total
        assert pages == (total + 999) // 1000
    finally:
        await _delete_org(org)


@pytest.mark.asyncio
async def test_cursor_never_crosses_tenant_or_source_boundary() -> None:
    org_a = await _org("tenant-a")
    org_b = await _org("tenant-b")
    source_id = uuid4()  # mismo source_id lógico en ambos tenants
    created_at = datetime(2026, 1, 4, 12, 0, tzinfo=UTC)
    session = await get_async_session()
    try:
        await _insert(
            session,
            organization_id=org_a,
            source_id=source_id,
            rows=[("solo-a", 1.0, created_at, uuid4())],
        )
        await _insert(
            session,
            organization_id=org_b,
            source_id=source_id,
            rows=[("solo-b", 1.0, created_at, uuid4())],
        )
    finally:
        await session.close()

    try:
        page = await _fetch(org_a, source_id, limit=10)
        assert len(page.rows) == 1
        assert page.rows[0]["excerpt"] == "solo-a"
    finally:
        await _delete_org(org_a)
        await _delete_org(org_b)


@pytest.mark.asyncio
async def test_deleted_row_between_pages_is_reported_as_snapshot_drift() -> None:
    org = await _org("borrado")
    source_id = uuid4()
    created_at = datetime(2026, 1, 5, 12, 0, tzinfo=UTC)
    ids = sorted(uuid4() for _ in range(5))
    session = await get_async_session()
    try:
        await _insert(
            session,
            organization_id=org,
            source_id=source_id,
            rows=[(f"pasaje {index}", 1.0, created_at, eid) for index, eid in enumerate(ids)],
        )
    finally:
        await session.close()

    try:
        first = await _fetch(org, source_id, limit=2)
        assert [str(row["id"]) for row in first.rows] == [str(ids[0]), str(ids[1])]
        assert first.has_more is True

        session = await get_async_session()
        try:
            await session.execute(
                text("DELETE FROM evidence_ledger WHERE id = :eid"),
                {"eid": str(ids[2])},
            )
            await session.commit()
        finally:
            await session.close()

        second = await _fetch(
            org, source_id, cursor=first.next_cursor, limit=10
        )
        observed = [str(row["id"]) for row in second.rows]
        assert observed == [str(ids[3]), str(ids[4])]
        assert str(ids[2]) not in observed
    finally:
        await _delete_org(org)


def test_cursor_is_typed_versioned_and_rejects_tampering() -> None:
    cursor = EvidenceCursor(
        strength=None,
        created_at=datetime(2026, 1, 6, tzinfo=UTC),
        evidence_id=uuid4(),
    )
    token = encode_evidence_cursor(cursor)
    decoded = decode_evidence_cursor(token)
    assert decoded == cursor

    with pytest.raises(ValueError):
        decode_evidence_cursor("not-a-cursor")
    with pytest.raises(ValueError):
        decode_evidence_cursor(token[:-2])


@pytest.mark.asyncio
async def test_cursor_is_stable_across_equal_timestamps_with_different_strength() -> None:
    org = await _org("mixto")
    source_id = uuid4()
    created_at = datetime(2026, 1, 7, 12, 0, tzinfo=UTC)
    rows = [
        ("alta", 0.8, created_at, uuid4()),
        ("media", 0.8, created_at + timedelta(seconds=1), uuid4()),
        ("baja", 0.2, created_at, uuid4()),
        ("nula", None, created_at, uuid4()),
    ]
    session = await get_async_session()
    try:
        await _insert(session, organization_id=org, source_id=source_id, rows=rows)
    finally:
        await session.close()

    try:
        collected, _ = await _walk(org, source_id, page_size=1)
        assert [str(row["id"]) for row in collected] == [
            str(rows[1][3]),
            str(rows[0][3]),
            str(rows[2][3]),
            str(rows[3][3]),
        ]
    finally:
        await _delete_org(org)
