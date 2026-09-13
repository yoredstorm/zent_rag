# =============================================================================
# Grounding → Evidence Ledger producer (Phase 2 slice 2)
# =============================================================================
# Cada GroundedAnswer persiste sus citas como evidencia append-only, con
# locators (documento/página/sección/chunk) y metadata de la cita.
# =============================================================================
from __future__ import annotations

import hashlib
from uuid import uuid4

import pytest

from src.rag.grounding.models import Citation, GroundedAnswer
from src.rag.grounding.recorder import GroundingLedgerRecorder


class _FakeEvidenceRepo:
    def __init__(self) -> None:
        self.records: list = []

    async def append(self, evidence):
        self.records.append(evidence)
        return evidence

    async def get(self, organization_id, evidence_id):
        return None

    async def list_for_document(self, organization_id, document_id, limit=100):
        return []


def _citation(**overrides) -> Citation:
    base = dict(
        source_id=uuid4(),
        document_id=uuid4(),
        document_name="Contrato ACME.pdf",
        page=18,
        section_path=("5", "5.2"),
        chunk_id=uuid4(),
        excerpt="La penalidad es 7%.",
        relevance=0.91,
    )
    base.update(overrides)
    return Citation(**base)


@pytest.mark.asyncio
async def test_recorder_persists_citations_as_evidence() -> None:
    repo = _FakeEvidenceRepo()
    org, workspace_id, agent_id, task_id = uuid4(), uuid4(), uuid4(), uuid4()
    citation = _citation()
    answer = GroundedAnswer(answer="respuesta", citations=(citation,), confidence=0.8)

    ids = await GroundingLedgerRecorder(repo).record_evidence(
        organization_id=org,
        answer=answer,
        workspace_id=workspace_id,
        agent_id=agent_id,
        task_id=task_id,
    )

    assert len(ids) == 1
    record = repo.records[0]
    assert record.organization_id == org
    assert record.workspace_id == workspace_id
    assert record.agent_id == agent_id
    assert record.task_id == task_id
    assert record.document_id == citation.document_id
    assert record.chunk_id == citation.chunk_id
    assert record.page == 18
    assert record.section_path == ("5", "5.2")
    assert record.content_hash == hashlib.sha256(
        citation.excerpt.encode("utf-8")
    ).hexdigest()
    assert record.retrieval_score == citation.relevance
    assert record.metadata["document_name"] == "Contrato ACME.pdf"


@pytest.mark.asyncio
async def test_recorder_skips_empty_excerpts() -> None:
    repo = _FakeEvidenceRepo()
    answer = GroundedAnswer(answer="x", citations=(_citation(excerpt="   "),))
    ids = await GroundingLedgerRecorder(repo).record_evidence(
        organization_id=uuid4(), answer=answer
    )
    assert ids == []
    assert repo.records == []


@pytest.mark.asyncio
async def test_recorder_db_roundtrip() -> None:
    from src.infrastructure.postgres.evidence_ledger import (
        PostgresEvidenceLedgerRepository,
    )
    from src.infrastructure.postgres.relational_db import PostgresOrganizationRepository

    org = await PostgresOrganizationRepository().create_organization(
        uuid4(), f"Grounding Ledger {uuid4().hex[:6]}"
    )
    repo = PostgresEvidenceLedgerRepository()
    citation = _citation()
    answer = GroundedAnswer(answer="respuesta", citations=(citation,))

    ids = await GroundingLedgerRecorder(repo).record_evidence(
        organization_id=org.id, answer=answer
    )
    assert len(ids) == 1
    fetched = await repo.get(org.id, ids[0])
    assert fetched is not None
    assert fetched.excerpt == citation.excerpt
    assert fetched.section_path == ("5", "5.2")
    listed = await repo.list_for_document(org.id, citation.document_id)
    assert [r.id for r in listed] == ids
