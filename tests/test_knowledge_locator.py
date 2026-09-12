# =============================================================================
# Citation Locator + Source file — Knowledge V2 (PDF highlight [1]→página)
# =============================================================================
from __future__ import annotations

import zlib
from uuid import uuid4

import pytest

from src.core.domain.knowledge_v2 import KnowledgeCorpus
from src.infrastructure.postgres.knowledge_corpora import (
    PostgresKnowledgeCorpusRepository,
)
from src.infrastructure.postgres.knowledge_repos import PostgresSourceRepository
from src.infrastructure.postgres.relational_db import (
    PostgresOrganizationRepository,
    PostgresWorkspaceRepository,
)
from src.infrastructure.postgres.structured_documents import (
    PostgresStructuredDocumentRepository,
)
from src.knowledge.locate import CitationLocator
from src.knowledge.structure.pdf_parser import PdfParser

PAGE1 = "Comisión cinco por ciento según el contrato."
PAGE2 = "Las multas se aplican desde el año siguiente."


def _two_page_pdf() -> bytes:
    """PDF de 2 páginas (una Tj por página)."""
    streams = []
    for y, text in ((720, PAGE1), (720, PAGE2)):
        payload = f"BT /F1 12 Tf 72 {y} Td ({text}) Tj ET".encode("latin-1")
        streams.append(zlib.compress(payload))
    objs = [
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj",
        b"2 0 obj << /Type /Pages /Kids [3 0 R 6 0 R] /Count 2 >> endobj",
        (
            b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >> endobj"
        ),
        b"4 0 obj << /Length %d /Filter /FlateDecode >> stream\n" % len(streams[0])
        + streams[0]
        + b"\nendstream endobj",
        b"5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj",
        (
            b"6 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Contents 7 0 R /Resources << /Font << /F1 5 0 R >> >> >> endobj"
        ),
        b"7 0 obj << /Length %d /Filter /FlateDecode >> stream\n" % len(streams[1])
        + streams[1]
        + b"\nendstream endobj",
    ]
    head = b"%PDF-1.4\n"
    body = b""
    offsets: list[int] = []
    pos = len(head)
    for obj in objs:
        offsets.append(pos)
        body += obj + b"\n"
        pos += len(obj) + 1
    xref_pos = pos
    xref = (
        b"xref\n0 8\n0000000000 65535 f \n"
        + b"".join(f"{off:010d} 00000 n \n".encode() for off in offsets)
    )
    trailer = b"trailer << /Size 8 /Root 1 0 R >>\nstartxref\n" + str(xref_pos).encode() + b"\n%%EOF\n"
    return head + body + xref + trailer


async def _seed_pdf_source():
    org_repo = PostgresOrganizationRepository()
    organization = await org_repo.create_organization(uuid4(), f"Locate Org {uuid4().hex[:6]}")
    workspace = await PostgresWorkspaceRepository().create_workspace(
        organization.id, "Ops", "ops"
    )
    corpus_repo = PostgresKnowledgeCorpusRepository()
    corpus = KnowledgeCorpus(
        id=uuid4(),
        organization_id=organization.id,
        workspace_id=workspace.id,
        name="Operaciones",
        slug="operaciones",
    )
    await corpus_repo.create_corpus(corpus)
    source = await PostgresSourceRepository().create_source(
        organization.id, "manual.pdf", "file", workspace_id=workspace.id
    )
    await corpus_repo.attach_source(organization.id, source.id, corpus.id)

    doc = PdfParser().parse(
        _two_page_pdf(),
        organization_id=organization.id,
        external_id="manual.pdf",
        source_id=source.id,
        workspace_id=workspace.id,
    )
    assert doc.page_count == 2
    doc.check_consistency()
    await PostgresStructuredDocumentRepository().upsert_document(doc)
    return organization, workspace, corpus, source


class FakeLocateLLM:
    def __init__(self, content: str | None = None, error: Exception | None = None) -> None:
        self._content = content
        self._error = error
        self.prompt_seen: str = ""

    async def generate(self, prompt, model=None, max_tokens=2048, temperature=0.3, system_prompt=None):
        self.prompt_seen = prompt
        if self._error is not None:
            raise self._error
        return type(
            "R",
            (),
            {
                "content": self._content or '{"page": 1}',
                "model": model or "fake",
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "total_tokens": 2,
            },
        )()  # type: ignore[return-value]


@pytest.mark.asyncio
async def test_locator_heuristic_finds_page_and_bbox() -> None:
    organization, _ws, _corpus, source = await _seed_pdf_source()
    locator = CitationLocator(llm=None)
    result = await locator.locate(
        organization.id,
        source.id,
        "La comisión es cinco por ciento",
        page_hint=2,
    )
    assert result.page == 1
    assert result.method == "heuristic"
    assert result.confidence >= 0.5
    assert result.bbox is not None  # bloque con bbox persistido del PDF
    assert "comisión" in result.excerpt.lower()


@pytest.mark.asyncio
async def test_locator_llm_validation_never_invents_page() -> None:
    organization, _ws, _corpus, source = await _seed_pdf_source()
    llm = FakeLocateLLM(content='{"page": 999}')  # página fuera de las candidatas
    locator = CitationLocator(llm=llm)
    result = await locator.locate(
        organization.id, source.id, "multas se aplican"
    )
    # LLM descartado (999 no es candidata) → heurística real
    assert result.page in (1, 2)
    assert "prompt_seen" in vars(llm)

    llm_ok = FakeLocateLLM(content='{"page": 2}')
    locator_ok = CitationLocator(llm=llm_ok)
    result_ok = await locator_ok.locate(
        organization.id, source.id, "multas se aplican desde el año"
    )
    assert result_ok.page == 2
    assert result_ok.method == "llm"
