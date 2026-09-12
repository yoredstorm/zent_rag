# =============================================================================
# Corpus Studio — artefactos reales sobre structured_documents (Phase G)
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest

from src.infrastructure.postgres.knowledge_corpora import (
    PostgresKnowledgeCorpusRepository,
)
from src.infrastructure.postgres.relational_db import (
    PostgresOrganizationRepository,
    PostgresWorkspaceRepository,
)
from src.infrastructure.postgres.structured_documents import (
    PostgresStructuredDocumentRepository,
)
from src.knowledge.structure import TextParser
from src.platform.studio.service import CorpusStudioService

_PARSER = TextParser()


def _md() -> str:
    return (
        "# Manual Operaciones\n\n"
        "Comisión 5% con vigencia desde 2024-01-01.\n\n"
        "El incumplimiento genera penalización del 10%.\n\n"
        "| Clave | Valor |\n| --- | --- |\n| A | 5% |\n"
    )


async def _seed_org_corpus_document():
    org_repo = PostgresOrganizationRepository()
    organization = await org_repo.create_organization(uuid4(), f"Studio Org {uuid4().hex[:6]}")
    workspace = await PostgresWorkspaceRepository().create_workspace(
        organization.id, "Operaciones", "ops"
    )
    corpus_repo = PostgresKnowledgeCorpusRepository()
    from src.core.domain.knowledge_v2 import KnowledgeCorpus

    corpus = KnowledgeCorpus(
        id=uuid4(),
        organization_id=organization.id,
        workspace_id=workspace.id,
        name="Operaciones",
        slug="operaciones",
    )
    await corpus_repo.create_corpus(corpus)

    from src.infrastructure.postgres.knowledge_repos import PostgresSourceRepository

    source = await PostgresSourceRepository().create_source(
        organization.id,
        "manual-operaciones",
        "file",
        workspace_id=workspace.id,
    )
    await corpus_repo.attach_source(organization.id, source.id, corpus.id)

    doc = _PARSER.parse(
        _md().encode("utf-8"),
        organization_id=organization.id,
        external_id="manual.md",
        source_id=source.id,
        workspace_id=workspace.id,
    )
    doc.check_consistency()
    await PostgresStructuredDocumentRepository().upsert_document(doc)
    return organization, corpus, doc


@pytest.mark.asyncio
async def test_studio_artifacts_are_real_and_provenanced() -> None:
    organization, corpus, doc = await _seed_org_corpus_document()
    service = CorpusStudioService()

    result = await service.build(organization.id, corpus.id)
    payload = result.to_dict()
    names = {artifact["artifact"] for artifact in payload["artifacts"]}
    assert {
        "executive_summary",
        "key_facts",
        "faq",
        "timeline",
        "risks",
    } <= names

    by_name = {a["artifact"]: a for a in payload["artifacts"]}

    # summary estructural: título real
    summary = by_name["executive_summary"]
    assert summary["sources_used"] == 1
    assert summary["items"][0]["title"] == "Manual Operaciones"
    assert summary["items"][0]["source"] == "observed"

    # key facts: fila de tabla real
    facts = by_name["key_facts"]
    assert any(item["text"] and "5%" in item["text"] for item in facts["items"])
    assert all(item["source"] == "observed" for item in facts["items"])

    # timeline: fecha ISO observada
    timeline = by_name["timeline"]
    assert any(item["date"] == "2024-01-01" for item in timeline["items"])

    # faq: preguntas INFERRED basadas en títulos reales
    faq = by_name["faq"]
    assert any("Manual Operaciones" in (item["question"] or "") for item in faq["items"])
    assert all(item["source"] == "inferred" for item in faq["items"])

    # riesgos: cue real extraída
    risks = by_name["risks"]
    assert any("penalizaci" in (item.get("cue") or "") or "incumplimiento" in (item.get("cue") or "") for item in risks["items"])

    # el documento persiste con su árbol (blocks incluyen la tabla)
    assert doc.block_count > 0
