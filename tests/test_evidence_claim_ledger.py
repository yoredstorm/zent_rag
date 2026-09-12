# =============================================================================
# Evidence + Claim Ledger — Phase 2 slice 1
# =============================================================================
# Dominio puro (sin DB) + roundtrip Postgres con aislamiento estricto por
# organization_id. Tablas en la migración 103. Ledger append-only para
# evidencia; claims con estados de verificación y detección de conflicto
# estructural (mismo sujeto+predicado, objeto distinto).
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest

from src.core.domain.catalog import CatalogProvenance
from src.core.domain.evidence import (
    ClaimRecord,
    ClaimVerificationStatus,
    EvidenceRecord,
)

# ---------------------------------------------------------------------------
# Dominio puro
# ---------------------------------------------------------------------------

def test_evidence_record_requires_excerpt_and_hash() -> None:
    org = uuid4()
    with pytest.raises(ValueError):
        EvidenceRecord(organization_id=org, excerpt="   ", content_hash="abc")
    with pytest.raises(ValueError):
        EvidenceRecord(organization_id=org, excerpt="texto", content_hash="")
    record = EvidenceRecord(
        organization_id=org,
        excerpt="La penalidad es 7%.",
        content_hash="sha256:abc",
        page=3,
        section_path=("5", "5.2"),
        authority="approved",
        retrieval_score=0.83,
    )
    assert record.page == 3
    assert record.section_path == ("5", "5.2")


def test_evidence_record_rejects_invalid_locators() -> None:
    org = uuid4()
    with pytest.raises(ValueError):
        EvidenceRecord(
            organization_id=org, excerpt="x", content_hash="h", page=0
        )
    with pytest.raises(ValueError):
        EvidenceRecord(
            organization_id=org, excerpt="x", content_hash="h", version=0
        )


def test_claim_record_defaults_and_validation() -> None:
    org = uuid4()
    claim = ClaimRecord(
        organization_id=org,
        text="La penalidad actual es 7%.",
        normalized_subject="penalidad",
        normalized_predicate="es",
        normalized_object="7%",
    )
    assert claim.status is ClaimVerificationStatus.PROPOSED
    assert claim.confidence == 0.0
    assert claim.provenance is CatalogProvenance.INFERRED
    assert claim.evidence_ids == ()

    with pytest.raises(ValueError):
        ClaimRecord(
            organization_id=org,
            text=" ",
            normalized_subject="a",
            normalized_predicate="b",
        )
    with pytest.raises(ValueError):
        ClaimRecord(
            organization_id=org,
            text="x",
            normalized_subject="",
            normalized_predicate="b",
        )
    with pytest.raises(ValueError):
        ClaimRecord(
            organization_id=org,
            text="x",
            normalized_subject="a",
            normalized_predicate="",
        )
    with pytest.raises(ValueError):
        ClaimRecord(
            organization_id=org,
            text="x",
            normalized_subject="a",
            normalized_predicate="b",
            confidence=1.2,
        )


def test_claim_ids_are_unique_per_instance() -> None:
    org = uuid4()
    first = ClaimRecord(
        organization_id=org, text="x", normalized_subject="a", normalized_predicate="b"
    )
    second = ClaimRecord(
        organization_id=org, text="x", normalized_subject="a", normalized_predicate="b"
    )
    assert first.id != second.id


# ---------------------------------------------------------------------------
# Postgres (migración 103)
# ---------------------------------------------------------------------------

@pytest.fixture
async def org():
    from src.infrastructure.postgres.relational_db import PostgresOrganizationRepository

    repo = PostgresOrganizationRepository()
    return await repo.create_organization(uuid4(), f"Ledger Org {uuid4().hex[:6]}")


def _evidence(org, **overrides) -> EvidenceRecord:
    payload = {
        "organization_id": org.id,
        "excerpt": "La penalidad es 7%.",
        "content_hash": f"h-{uuid4().hex}",
        "document_id": uuid4(),
        "page": 3,
        "section_path": ("5", "5.2"),
        "authority": "approved",
        "retrieval_score": 0.7,
        "reranker_score": 0.9,
    }
    payload.update(overrides)
    return EvidenceRecord(**payload)


@pytest.mark.asyncio
async def test_evidence_ledger_append_get_and_isolation(org) -> None:
    from src.infrastructure.postgres.evidence_ledger import (
        PostgresEvidenceLedgerRepository,
    )

    repo = PostgresEvidenceLedgerRepository()
    record = _evidence(org)
    saved = await repo.append(record)
    assert saved.id == record.id

    fetched = await repo.get(org.id, record.id)
    assert fetched is not None
    assert fetched.excerpt == record.excerpt
    assert fetched.page == 3
    assert fetched.section_path == ("5", "5.2")
    assert await repo.get(uuid4(), record.id) is None

    listed = await repo.list_for_document(org.id, record.document_id)
    assert [item.id for item in listed] == [record.id]
    assert await repo.list_for_document(uuid4(), record.document_id) == []


@pytest.mark.asyncio
async def test_claim_ledger_upsert_and_isolation(org) -> None:
    from src.infrastructure.postgres.evidence_ledger import (
        PostgresClaimLedgerRepository,
    )

    repo = PostgresClaimLedgerRepository()
    claim = ClaimRecord(
        organization_id=org.id,
        text="La penalidad actual es 7%.",
        normalized_subject="penalidad",
        normalized_predicate="es",
        normalized_object="7%",
        confidence=0.4,
    )
    saved = await repo.upsert(claim)
    assert saved.id == claim.id

    fetched = await repo.get(org.id, claim.id)
    assert fetched is not None and fetched.normalized_object == "7%"
    assert await repo.get(uuid4(), claim.id) is None

    updated = ClaimRecord(
        organization_id=org.id,
        id=claim.id,
        text=claim.text,
        normalized_subject="penalidad",
        normalized_predicate="es",
        normalized_object="7%",
        status=ClaimVerificationStatus.SUPPORTED,
        confidence=0.95,
        provenance=CatalogProvenance.OBSERVED,
    )
    again = await repo.upsert(updated)
    assert again.id == claim.id
    assert again.status is ClaimVerificationStatus.SUPPORTED

    by_subject = await repo.list_by_subject(org.id, "penalidad")
    assert [item.id for item in by_subject] == [claim.id]
    assert await repo.list_by_subject(uuid4(), "penalidad") == []


@pytest.mark.asyncio
async def test_claim_ledger_detects_structural_conflict(org) -> None:
    from src.infrastructure.postgres.evidence_ledger import (
        PostgresClaimLedgerRepository,
    )

    repo = PostgresClaimLedgerRepository()
    base = dict(
        organization_id=org.id,
        normalized_subject="penalidad",
        normalized_predicate="es",
    )
    five = await repo.upsert(ClaimRecord(text="Penalidad 5%.", normalized_object="5%", **base))
    seven = await repo.upsert(ClaimRecord(text="Penalidad 7%.", normalized_object="7%", **base))
    other = await repo.upsert(
        ClaimRecord(
            text="Plazo 30 días.",
            normalized_subject="plazo",
            normalized_predicate="es",
            normalized_object="30 dias",
            organization_id=org.id,
        )
    )

    conflicts = await repo.find_conflicting(org.id, "penalidad", "es", "7%")
    assert [item.id for item in conflicts] == [five.id]
    assert other.id not in {item.id for item in conflicts}

    # null participa del conflicto como valor distinto
    null_claim = await repo.upsert(
        ClaimRecord(
            text="Penalidad sin valor.",
            normalized_object=None,
            **base,
        )
    )
    with_null = await repo.find_conflicting(org.id, "penalidad", "es", "7%")
    assert {item.id for item in with_null} == {five.id, null_claim.id}


@pytest.mark.asyncio
async def test_claim_attach_evidence_is_idempotent_and_tenant_scoped(org) -> None:
    from src.infrastructure.postgres.evidence_ledger import (
        PostgresClaimLedgerRepository,
        PostgresEvidenceLedgerRepository,
    )

    evidence_repo = PostgresEvidenceLedgerRepository()
    claim_repo = PostgresClaimLedgerRepository()
    record = await evidence_repo.append(_evidence(org))
    claim = await claim_repo.upsert(
        ClaimRecord(
            organization_id=org.id,
            text="La penalidad actual es 7%.",
            normalized_subject="penalidad",
            normalized_predicate="es",
            normalized_object="7%",
        )
    )

    attached = await claim_repo.attach_evidence(org.id, claim.id, record.id)
    assert attached.evidence_ids == (record.id,)
    again = await claim_repo.attach_evidence(org.id, claim.id, record.id)
    assert again.evidence_ids == (record.id,)

    # upsert posterior no pierde evidencia adjunta
    stale = ClaimRecord(
        organization_id=org.id,
        id=claim.id,
        text=claim.text,
        normalized_subject="penalidad",
        normalized_predicate="es",
        normalized_object="7%",
        status=ClaimVerificationStatus.SUPPORTED,
        confidence=0.9,
    )
    preserved = await claim_repo.upsert(stale)
    assert preserved.evidence_ids == (record.id,)

    with pytest.raises(ValueError):
        await claim_repo.attach_evidence(uuid4(), claim.id, record.id)
    with pytest.raises(ValueError):
        await claim_repo.attach_evidence(org.id, claim.id, uuid4())
