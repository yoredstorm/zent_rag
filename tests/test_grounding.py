# =============================================================================
# Grounding — GroundedAnswer / Citations / Claim Verification (Phase G backend)
# =============================================================================
from __future__ import annotations

from uuid import uuid4

from src.core.domain.entities import RetrievalChunk
from src.rag.grounding import (
    ClaimStatus,
    ClaimVerifier,
    GroundingService,
    VerificationConfig,
)
from src.rag.grounding.citations import build_citations, citation_from_chunk, instrument_answer
from src.rag.retrieval.structured import AssembledContext, V2RetrievalOptions


def _chunk(
    content: str,
    *,
    document_id=None,
    external_id="manual.pdf",
    page=43,
    section_path=(),
    chunk_id=None,
    score=0.9,
) -> RetrievalChunk:
    document_id = document_id or uuid4()
    metadata = {
        "document_id": str(document_id),
        "external_id": external_id,
        "page_start": page,
        "section_path": list(section_path) if section_path else None,
        "source_id": str(uuid4()),
        "content_hash": f"hash-{content[:12]}",
        "v2_chunk": "true",
    }
    if chunk_id:
        metadata["chunk_id"] = str(chunk_id)
    return RetrievalChunk(
        document_id=document_id,
        content=content,
        score=score,
        metadata=metadata,
    )


def _assembled(children, parents=()) -> AssembledContext:
    return AssembledContext(
        children=tuple(children),
        parents=tuple(parents),
        context=tuple(children) + tuple(parents),
        options=V2RetrievalOptions(),
    )


def test_citation_locator_maps_page_and_section() -> None:
    chunk = _chunk(
        "Comisión 5%.",
        external_id="Manual Operaciones.pdf",
        page=43,
        section_path=("5", "5.2"),
    )
    citation = citation_from_chunk(chunk, relevance=0.93)
    assert "Manual Operaciones.pdf" in citation.locator
    assert "página 43" in citation.locator
    assert "5.2" in citation.locator
    assert citation.document_name == "Manual Operaciones.pdf"
    assert citation.page == 43
    assert citation.section_path == ("5", "5.2")
    assert citation.relevance == 0.93


def test_build_citations_dedupes_and_orders_by_relevance() -> None:
    first = _chunk("Texto A.", page=1, score=0.9)
    second = _chunk("Texto B.", page=2, score=0.7)
    dup = _chunk("Texto A.", page=1, score=0.8)  # mismo doc/page/excerpt
    citations = build_citations(_assembled([first, second, dup]), limit=5)
    assert len(citations) <= 3
    assert citations[0].relevance >= citations[-1].relevance


def test_instrument_answer_adds_numbered_references() -> None:
    chunk = _chunk("Comisión 5%.")
    citation = citation_from_chunk(chunk)
    cited, used = instrument_answer(
        "La comisión es 5% [1].",
        [citation],
    )
    assert "**Referencias** [1]" in cited
    assert len(used) == 1


def test_claim_verifier_supported_unsupported_and_partial() -> None:
    verifier = ClaimVerifier(
        config=VerificationConfig(
            supported_ratio=0.6,
            partial_ratio=0.25,
        )
    )
    context_chunk = _chunk(
        "La comisión es cinco por ciento según el contrato vigente."
    )
    assembled = _assembled([context_chunk])
    claims = verifier.verify(
        "La comisión es cinco por ciento. El vuelo dura tres horas.",
        assembled,
    )
    statuses = {claim.status for claim in claims}
    assert ClaimStatus.SUPPORTED in statuses
    assert ClaimStatus.UNSUPPORTED in statuses
    for claim in claims:
        if claim.status is ClaimStatus.UNSUPPORTED:
            assert claim.supporting_citations == ()


def test_grounding_service_assembles_grounded_answer() -> None:
    context_chunk = _chunk(
        "La comisión es cinco por ciento según el contrato vigente.",
        external_id="Contrato 2025.pdf",
        section_path=("8",),
    )
    service = GroundingService()
    grounded = service.ground(
        "La comisión es cinco por ciento. El vuelo dura tres horas.",
        _assembled([context_chunk]),
    )

    assert grounded.confidence > 0.0
    assert any(c.status is ClaimStatus.SUPPORTED for c in grounded.claims)
    assert any(c.status is ClaimStatus.UNSUPPORTED for c in grounded.claims)
    assert grounded.missing_information
    assert grounded.sources_used
    as_dict = grounded.to_dict()
    assert as_dict["answer"]
    assert isinstance(as_dict["citations"], list)
    assert as_dict["sources_used"][0] == str(context_chunk.document_id)
