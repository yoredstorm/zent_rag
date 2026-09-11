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
    KnowledgeCorpus,
    KnowledgeObjectStatus,
    StructuredBlock,
    StructuredBlockKind,
    StructuredDocument,
    inferred_is_not_approved,
)

_SESSION_KEY = "aa" * 32


def _settings(**env: str) -> Settings:
    get_settings.cache_clear()
    return Settings()


def test_knowledge_v2_flag_defaults_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_PORTAL_SESSION_KEY", _SESSION_KEY)
    monkeypatch.delenv("RAG_KNOWLEDGE_V2_ENABLED", raising=False)
    settings = _settings()
    assert settings.KNOWLEDGE_V2_ENABLED is False
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
