# =============================================================================
# P18.2-02 — Sello durable, attach atómico e idempotencia del lote
# =============================================================================
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.core.domain.knowledge_session import SessionSealedError
from src.infrastructure.postgres.relational_db import PostgresOrganizationRepository
from src.platform.knowledge_sessions.repository import (
    PostgresKnowledgeSessionRepository,
)
from src.platform.knowledge_sessions.service import LearningSessionService


async def _service_and_session(title: str):
    org = await PostgresOrganizationRepository().create_organization(uuid4(), f"P18.2 Sessions {uuid4().hex[:6]}")
    repo = PostgresKnowledgeSessionRepository()
    await repo.ensure_tables()
    service = LearningSessionService(repo)
    session = await service.start_session(org.id, title=title, origin="test")
    return org, repo, service, session


@pytest.mark.asyncio
async def test_sealed_session_rejects_new_source() -> None:
    _org, repo, service, session = await _service_and_session("Sellada")
    await service.seal_session(session.organization_id, session.id)

    with pytest.raises(SessionSealedError):
        await service.attach_source(
            session,
            source_id=uuid4(),
            job_id=uuid4(),
            name="tarde.pdf",
            source_type="file",
        )

    detail = await service.get_session_detail(session.organization_id, session.id)
    assert detail is not None
    assert detail["sources"] == []
    assert detail["source_count"] == 0


@pytest.mark.asyncio
async def test_attach_is_idempotent_by_key() -> None:
    _org, _repo, service, session = await _service_and_session("Idempotente")
    source_id = uuid4()
    job_id = uuid4()

    first = await service.attach_source(
        session,
        source_id=source_id,
        job_id=job_id,
        name="uno.pdf",
        source_type="file",
        idempotency_key="file:one:123",
    )
    second = await service.attach_source(
        session,
        source_id=source_id,
        job_id=job_id,
        name="uno.pdf",
        source_type="file",
        idempotency_key="file:one:123",
    )

    detail = await service.get_session_detail(session.organization_id, session.id)
    assert first.id == second.id
    assert detail is not None
    assert detail["source_count"] == 1
    assert len(detail["sources"]) == 1


@pytest.mark.asyncio
async def test_seal_and_attach_race_never_leaves_source_in_sealed_batch() -> None:
    _org, _repo, service, session = await _service_and_session("Carrera")

    async def attach() -> str:
        try:
            await service.attach_source(
                session,
                source_id=uuid4(),
                job_id=uuid4(),
                name="carrera.pdf",
                source_type="file",
            )
            return "attached"
        except SessionSealedError:
            return "sealed"

    attached, _ = await asyncio.gather(attach(), service.seal_session(session.organization_id, session.id))

    detail = await service.get_session_detail(session.organization_id, session.id)
    assert detail is not None
    assert detail["sealed_at"] is not None
    assert detail["source_count"] == (1 if attached == "attached" else 0)
    assert len(detail["sources"]) == detail["source_count"]


@pytest.mark.asyncio
async def test_upload_helper_opens_derived_batch_instead_of_reusing_sealed() -> None:
    from src.api.routes.sources import _open_learning_session

    org, _repo, service, session = await _service_and_session("Original")
    await service.seal_session(org.id, session.id)
    ctx = SimpleNamespace(organization_id=org.id)

    opened = await _open_learning_session(
        ctx,
        service,
        session_id=session.id,
        title="Reintento",
        origin="upload_retry",
        workspace_id=None,
    )

    assert opened is not None
    assert opened.id != session.id
    assert opened.sealed_at is None
    original = await service.get_session_detail(org.id, session.id)
    assert original is not None and original["sealed_at"] is not None


@pytest.mark.asyncio
async def test_strict_attach_does_not_enqueue_job_for_sealed_session() -> None:
    from src.knowledge.uploads import enqueue_source_sync

    class Jobs:
        def __init__(self) -> None:
            self.updated: list[dict] = []

        async def create_job(self, organization_id, **kwargs):
            return SimpleNamespace(id=uuid4(), status=SimpleNamespace(value="created"))

        async def update_job(self, job_id, **fields):
            self.updated.append({"job_id": job_id, **fields})
            return None

    class Source:
        id = uuid4()
        type = "file"
        name = "sellada.pdf"
        knowledge_base_id = None

    jobs = Jobs()

    async def _sealed(_job):
        raise SessionSealedError(uuid4())

    with pytest.raises(SessionSealedError):
        await enqueue_source_sync(
            SimpleNamespace(organization_id=uuid4()),
            jobs,
            Source(),
            on_created=_sealed,
            strict_attach=True,
        )

    assert jobs.updated and jobs.updated[0]["status"] == "failed"
