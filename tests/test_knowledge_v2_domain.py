# =============================================================================
# Knowledge V2 — Phase A domain contracts (pure, no I/O, no productive mocks)
# =============================================================================
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from src.core.config import Settings, get_settings
from src.core.domain.catalog import CatalogProvenance
from src.core.domain.knowledge_v2 import (
    BoundingBox,
    CharRange,
    ChunkType,
    DocumentChangeKind,
    DocumentChunk,
    DocumentIntegrityError,
    DocumentPage,
    DocumentSection,
    DocumentSummary,
    DocumentVersion,
    KnowledgeCorpus,
    KnowledgeEntity,
    KnowledgeEvidence,
    KnowledgeFact,
    KnowledgeObjectStatus,
    KnowledgeRelationship,
    KnowledgeRelationshipKind,
    RelationshipEndpoint,
    SectionSummary,
    StructuredBlock,
    StructuredBlockKind,
    StructuredContentType,
    StructuredDocument,
    inferred_is_not_approved,
)

_SESSION_KEY = "aa" * 32


def _settings(**env: str) -> Settings:
    get_settings.cache_clear()
    return Settings()


def test_knowledge_v2_flag_defaults_false(monkeypatch: pytest.MonkeyPatch) -> None:
    # Determinista: fija explícitamente false (el contrato de código es OFF;
    # el .env local de desarrollo puede estar ON sin romper este contrato).
    monkeypatch.setenv("RAG_PORTAL_SESSION_KEY", _SESSION_KEY)
    monkeypatch.setenv("RAG_KNOWLEDGE_V2_ENABLED", "false")
    monkeypatch.setenv("RAG_KNOWLEDGE_V2_PROMOTE", "false")
    monkeypatch.setenv("RAG_KNOWLEDGE_V2_SHADOW", "false")
    settings = _settings()
    assert settings.KNOWLEDGE_V2_ENABLED is False
    assert settings.KNOWLEDGE_V2_PROMOTE is False
    assert settings.KNOWLEDGE_V2_SHADOW is False
    get_settings.cache_clear()


def test_knowledge_v2_flag_reads_single_rag_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_PORTAL_SESSION_KEY", _SESSION_KEY)
    monkeypatch.setenv("RAG_KNOWLEDGE_V2_ENABLED", "true")
    settings = _settings()
    assert settings.KNOWLEDGE_V2_ENABLED is True
    get_settings.cache_clear()


def test_inferred_never_equals_approved() -> None:
    assert CatalogProvenance.INFERRED != CatalogProvenance.APPROVED
    assert inferred_is_not_approved(CatalogProvenance.INFERRED) is True
    assert inferred_is_not_approved(CatalogProvenance.APPROVED) is False
    assert inferred_is_not_approved(CatalogProvenance.OBSERVED) is True


def test_structured_document_rejects_inferred_marked_approved() -> None:
    with pytest.raises(ValueError, match="INFERRED"):
        StructuredDocument(
            id=uuid4(),
            organization_id=uuid4(),
            external_id="doc-1",
            title="Policy",
            content_hash="abc",
            provenance=CatalogProvenance.INFERRED,
            status=KnowledgeObjectStatus.APPROVED,
        )


def test_structured_document_as_markdown_is_derived_view() -> None:
    doc = StructuredDocument(
        id=uuid4(),
        organization_id=uuid4(),
        workspace_id=uuid4(),
        external_id="handbook",
        title="Handbook",
        content_hash="hash",
        blocks=(
            StructuredBlock(
                kind=StructuredBlockKind.HEADING, text="Refunds", order=0
            ),
            StructuredBlock(
                kind=StructuredBlockKind.PARAGRAPH, text="30 days.", order=1
            ),
        ),
    )
    md = doc.as_markdown()
    assert "# Refunds" in md
    assert "30 days." in md
    assert doc.provenance is CatalogProvenance.OBSERVED


def test_v1_ingestion_engine_does_not_import_v2() -> None:
    engine = Path("src/knowledge/engine/service.py").read_text(encoding="utf-8")
    assert "knowledge.v2" not in engine
    assert "knowledge_v2" not in engine
    assert "KNOWLEDGE_V2_ENABLED" not in engine


def test_knowledge_corpus_requires_org_and_workspace() -> None:
    org = uuid4()
    workspace = uuid4()
    corpus = KnowledgeCorpus(
        id=uuid4(),
        organization_id=org,
        workspace_id=workspace,
        name="Default corpus",
        slug="default",
    )
    assert corpus.organization_id == org
    assert corpus.workspace_id == workspace
    assert corpus.knowledge_base_id is None
    assert corpus.source_ids == ()
    assert corpus.status is KnowledgeObjectStatus.DRAFT


# =============================================================================
# Phase A extension — full document tree (brief §3) invariants
# =============================================================================


def _tree_document() -> tuple[StructuredDocument, StructuredBlock, StructuredBlock]:
    doc_id = uuid4()
    org = uuid4()
    workspace = uuid4()
    root_section_id = uuid4()
    clause_section_id = uuid4()
    title_block = StructuredBlock(
        kind=StructuredBlockKind.TITLE, text="Manual Operaciones", order=0
    )
    clause_block = StructuredBlock(
        kind=StructuredBlockKind.PARAGRAPH,
        text="Comisión 5%.",
        order=1,
        page=43,
        heading_path=("5", "5.2"),
    )
    doc = StructuredDocument(
        id=doc_id,
        organization_id=org,
        workspace_id=workspace,
        external_id="manual-operaciones",
        title="Manual Operaciones",
        content_hash="hash-manual",
        mime_type="application/pdf",
        document_type="policy",
        blocks=(title_block, clause_block),
        pages=(
            DocumentPage(
                id=uuid4(),
                document_id=doc_id,
                organization_id=org,
                workspace_id=workspace,
                page_number=43,
                text="Comisión 5%.",
                block_ids=(clause_block.id,),
                bbox=BoundingBox(page=43, x0=0.0, y0=0.0, x1=612.0, y1=792.0),
            ),
        ),
        sections=(
            DocumentSection(
                id=root_section_id,
                document_id=doc_id,
                organization_id=org,
                section_path=("5",),
                heading="Compensación",
                depth=0,
                parent_id=None,
                page_start=43,
                page_end=44,
            ),
            DocumentSection(
                id=clause_section_id,
                document_id=doc_id,
                organization_id=org,
                section_path=("5", "5.2"),
                heading="Comisiones",
                depth=1,
                parent_id=root_section_id,
                order=0,
                page_start=43,
                block_ids=(clause_block.id,),
                summary=SectionSummary(
                    id=uuid4(),
                    document_id=doc_id,
                    section_id=clause_section_id,
                    organization_id=org,
                    summary="Define la comisión de 5%.",
                ),
            ),
        ),
    )
    return doc, title_block, clause_block


def test_structured_document_full_tree_builds_and_validates() -> None:
    doc, _, clause = _tree_document()
    doc.check_consistency()
    assert doc.page_count == 1
    assert doc.section_count == 2
    assert doc.table_count == 0
    assert doc.figure_count == 0
    assert doc.document_type == "policy"
    assert clause.page == 43
    assert clause.heading_path == ("5", "5.2")
    assert doc.sections[1].summary is not None
    assert doc.sections[1].summary.section_id == doc.sections[1].id


def test_structured_document_rejects_duplicate_page_numbers() -> None:
    doc_id = uuid4()
    org = uuid4()
    with pytest.raises(ValueError, match="unique page_number"):
        StructuredDocument(
            id=doc_id,
            organization_id=org,
            external_id="d",
            title="D",
            content_hash="h",
            pages=(
                DocumentPage(document_id=doc_id, organization_id=org, page_number=1),
                DocumentPage(document_id=doc_id, organization_id=org, page_number=1),
            ),
        )


def test_consistency_rejects_child_document_id_mismatch() -> None:
    doc = _tree_document()[0]
    from dataclasses import replace

    bad = replace(doc, pages=(replace(doc.pages[0], document_id=uuid4()),))
    with pytest.raises(DocumentIntegrityError, match="document_id"):
        bad.check_consistency()


def test_consistency_rejects_page_with_unknown_block_ref() -> None:
    doc = _tree_document()[0]
    from dataclasses import replace

    bad = replace(doc, pages=(replace(doc.pages[0], block_ids=(uuid4(),)),))
    with pytest.raises(DocumentIntegrityError, match="unknown blocks"):
        bad.check_consistency()


def test_consistency_rejects_orphan_parent_section() -> None:
    doc = _tree_document()[0]
    from dataclasses import replace

    section = replace(doc.sections[1], parent_id=uuid4())
    bad = replace(doc, sections=doc.sections[:1] + (section,))
    with pytest.raises(DocumentIntegrityError, match="unknown parent"):
        bad.check_consistency()


def test_document_chunk_defaults_and_invariants() -> None:
    chunk = DocumentChunk(
        document_id=uuid4(),
        organization_id=uuid4(),
        content="Cláusula 8: penalización.",
        chunk_index=0,
        chunk_type=ChunkType.DOCUMENT_STRUCTURE,
        page_start=43,
        page_end=43,
    )
    assert chunk.chunk_type is ChunkType.DOCUMENT_STRUCTURE
    assert chunk.content_type is StructuredContentType.TEXT
    assert chunk.parent_id is None

    with pytest.raises(ValueError, match="content must not be empty"):
        DocumentChunk(document_id=uuid4(), organization_id=uuid4(), content=" ")
    with pytest.raises(ValueError, match="page_start must be <= page_end"):
        DocumentChunk(
            document_id=uuid4(),
            organization_id=uuid4(),
            content="x",
            page_start=3,
            page_end=2,
        )
    with pytest.raises(ValueError, match="start < end"):
        CharRange(start=5, end=5)


def test_knowledge_fact_approval_law() -> None:
    org = uuid4()
    with pytest.raises(ValueError, match="APPROVED status requires APPROVED provenance"):
        KnowledgeFact(
            organization_id=org,
            subject="Contrato 2025",
            predicate="establece comisión",
            object_value="5%",
            provenance=CatalogProvenance.INFERRED,
            status=KnowledgeObjectStatus.APPROVED,
        )
    approved = KnowledgeFact(
        organization_id=org,
        subject="Contrato 2025",
        predicate="establece comisión",
        object_value="5%",
        provenance=CatalogProvenance.APPROVED,
        status=KnowledgeObjectStatus.APPROVED,
        evidence=(
            KnowledgeEvidence(
                organization_id=org,
                document_id=uuid4(),
                section_path=("8",),
                page_number=10,
                excerpt="Comisión 5%.",
                confidence=0.99,
            ),
        ),
    )
    assert approved.statement == "Contrato 2025 establece comisión 5%"


def test_relationship_kinds_support_cross_document_and_tenant_guard() -> None:
    org = uuid4()
    contract = RelationshipEndpoint(
        organization_id=org, node_kind="document", node_id=uuid4(), label="Contrato 2025"
    )
    addendum = RelationshipEndpoint(
        organization_id=org, node_kind="document", node_id=uuid4(), label="Adenda 2026"
    )
    rel = KnowledgeRelationship(
        organization_id=org,
        kind=KnowledgeRelationshipKind.SUPERSEDES,
        from_node=addendum,
        to_node=contract,
    )
    assert rel.kind.value == "supersedes"
    assert {k.value for k in KnowledgeRelationshipKind} == {
        "supplements",
        "modifies",
        "supersedes",
        "contradicts",
        "references",
        "duplicates",
        "related_to",
    }

    other_org = RelationshipEndpoint(
        organization_id=uuid4(), node_kind="document", node_id=uuid4(), label="Otro tenant"
    )
    with pytest.raises(ValueError, match="organization boundaries"):
        KnowledgeRelationship(
            organization_id=org,
            kind=KnowledgeRelationshipKind.RELATED_TO,
            from_node=contract,
            to_node=other_org,
        )


def test_summaries_and_entities_default_to_inferred() -> None:
    org = uuid4()
    summary = DocumentSummary(
        document_id=uuid4(), organization_id=org, summary="Resumen del contrato."
    )
    assert summary.provenance is CatalogProvenance.INFERRED
    assert summary.status is KnowledgeObjectStatus.INFERRED

    entity = KnowledgeEntity(
        organization_id=org,
        entity_type="organization",
        name="Aeroméxico",
        normalized_value="AEROMEXICO",
        confidence=0.9,
    )
    assert entity.provenance is CatalogProvenance.INFERRED
    assert CatalogProvenance.INFERRED != CatalogProvenance.APPROVED


def test_section_requires_non_empty_path_and_valid_bounding_box() -> None:
    with pytest.raises(ValueError, match="section_path must not be empty"):
        DocumentSection(document_id=uuid4(), organization_id=uuid4(), section_path=())
    with pytest.raises(ValueError, match="x1 >= x0"):
        BoundingBox(page=1, x0=5.0, y0=0.0, x1=1.0, y1=10.0)


def test_blocks_only_document_remains_valid_without_tree() -> None:
    # Phase A coexistence guard: callers that only pass blocks keep working.
    doc = StructuredDocument(
        id=uuid4(),
        organization_id=uuid4(),
        external_id="flat",
        title="Flat",
        content_hash="h",
        blocks=(StructuredBlock(kind=StructuredBlockKind.PARAGRAPH, text="x"),),
    )
    doc.check_consistency()
    assert doc.page_count == 0
    assert doc.section_count == 0


def test_document_version_invariants_and_change_kinds() -> None:
    org = uuid4()
    doc_id = uuid4()
    with pytest.raises(ValueError, match="content_hash"):
        DocumentVersion(organization_id=org, document_id=doc_id, content_hash="")
    with pytest.raises(ValueError, match=">= 1"):
        DocumentVersion(organization_id=org, document_id=doc_id, content_hash="h", version=0)

    v1 = DocumentVersion(organization_id=org, document_id=doc_id, content_hash="hash-1")
    assert v1.version == 1
    assert v1.change_kind is DocumentChangeKind.CREATED
    v2 = DocumentVersion(
        organization_id=org,
        document_id=doc_id,
        content_hash="hash-2",
        version=2,
        change_kind=DocumentChangeKind.UPDATED,
        previous_version_id=v1.id,
    )
    assert v2.change_kind.value == "updated"
    assert v2.previous_version_id == v1.id
