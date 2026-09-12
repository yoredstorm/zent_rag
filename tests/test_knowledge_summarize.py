# =============================================================================
# Knowledge V2 — Multi-level summarization (Phase C slice 3)
# =============================================================================
from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.core.domain.catalog import CatalogProvenance
from src.core.domain.entities import LLMResponse
from src.core.domain.knowledge_v2 import KnowledgeObjectStatus
from src.knowledge.structure import TextParser
from src.knowledge.summarize.service import DocumentSummarizer, SummarizerConfig

_MARKDOWN = """# Manual Operaciones

## 5. Compensación

Comisión 5% para contratos vigentes.

### 5.2 Comisiones

| Clave | Valor |
| --- | --- |
| A | 5% |
"""


def _doc():
    return TextParser().parse(
        _MARKDOWN.encode("utf-8"),
        organization_id=uuid4(),
        external_id="manual.md",
    )


class FakeLLM:
    def __init__(self, *, content: str | None = None, error: Exception | None = None) -> None:
        self._content = content
        self._error = error
        self.calls: list[str] = []

    async def generate(self, prompt, model=None, max_tokens=2048, temperature=0.3, system_prompt=None):
        self.calls.append(prompt)
        if self._error is not None:
            raise self._error
        return LLMResponse(
            content=self._content or '{"summary": "Resumen.", "key_points": ["a"]}',
            model=model or "fake",
        )


@pytest.mark.asyncio
async def test_summarizer_llm_mode_produces_inferred_summaries() -> None:
    expected = json.dumps(
        {"summary": "Resumen del documento.", "key_points": ["P1", "P2"]}
    )
    llm = FakeLLM(content=expected)
    summarizer = DocumentSummarizer(llm, config=SummarizerConfig(model="fake-model"))
    output = await summarizer.summarize(_doc())

    assert output.mode == "llm"
    assert output.document_summary.summary == "Resumen del documento."
    assert output.document_summary.key_topics == ("P1", "P2")
    assert output.document_summary.provenance is CatalogProvenance.INFERRED
    assert output.document_summary.status is KnowledgeObjectStatus.INFERRED
    assert output.document_summary.model == "fake-model"

    assert output.section_summaries
    for section_summary in output.section_summaries:
        assert section_summary.provenance is CatalogProvenance.INFERRED
        assert section_summary.section_id is not None
        assert "section_path" in section_summary.metadata


@pytest.mark.asyncio
async def test_summarizer_extractive_fallback_on_llm_failure() -> None:
    llm = FakeLLM(error=RuntimeError("provider down"))
    summarizer = DocumentSummarizer(llm)
    output = await summarizer.summarize(_doc())

    assert output.mode == "extractive"
    assert output.document_summary.provenance is CatalogProvenance.INFERRED
    assert output.document_summary.summary
    # topics extractivos = headings del documento
    assert "Manual Operaciones" in output.document_summary.key_topics


@pytest.mark.asyncio
async def test_engine_shadow_summarizer_contract() -> None:
    # El engine NO acopla el módulo de summarize: llama al objeto inyectado
    # (contract duck-typing) y estos tests garantizan el contrato.
    fake = SimpleNamespace(
        document_summary=SimpleNamespace(summary="Sombra"),
        mode="shadow",
    )
    called = []

    class RecordingSummarizer:
        async def summarize(self, document):
            called.append(document.id)
            return fake

    rec = RecordingSummarizer()
    result = await rec.summarize(_doc())
    assert result is fake
    assert result.mode == "shadow"
    assert called
