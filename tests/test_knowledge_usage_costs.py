# =============================================================================
# Ingesta — metering: tokens y costo de embeddings y del resumen
# =============================================================================
# Antes: los embeddings se contaban con costo 0 y el resumen (una llamada por
# sección + una por documento) no registraba nada. Ahora se costean con el
# registro de precios y se acotan por secciones/presupuesto.
from __future__ import annotations

from typing import ClassVar
from uuid import uuid4

import pytest

from src.core.domain.entities import LLMResponse
from src.core.domain.knowledge_v2 import (
    DocumentSection,
    StructuredBlock,
    StructuredBlockKind,
    StructuredDocument,
)
from src.core.ports import LLMProvider
from src.knowledge.cost.tracker import KnowledgeUsageTracker
from src.knowledge.summarize.service import (
    DocumentSummarizer,
    SummarizerConfig,
    SummaryUsage,
)


class _LLMFalso(LLMProvider):
    def __init__(self, respuesta: str = '{"summary": "ok", "key_points": ["a"]}') -> None:
        self.llm_calls: list[dict] = []
        self._respuesta = respuesta

    async def generate(self, prompt: str, **kwargs) -> LLMResponse:
        self.llm_calls.append({"prompt": prompt, **kwargs})
        return LLMResponse(
            content=self._respuesta,
            model=str(kwargs.get("model") or "fake"),
            prompt_tokens=100,
            completion_tokens=20,
            total_tokens=120,
        )

    async def generate_stream(self, *args, **kwargs):  # pragma: no cover
        raise NotImplementedError

    async def embed(self, text, model=None):  # pragma: no cover
        raise NotImplementedError

    async def rerank(self, query, documents, model=None, top_n=None):  # pragma: no cover
        return []


def _documento(secciones: int = 2) -> StructuredDocument:
    org = uuid4()
    doc_id = uuid4()
    bloques: list[StructuredBlock] = []
    sections: list[DocumentSection] = []
    for index in range(secciones):
        heading = StructuredBlock(
            kind=StructuredBlockKind.HEADING,
            text=f"5.{index} Sección {index}",
            order=index * 2,
            token_count=4,
            content_hash=f"h{index}",
        )
        cuerpo = StructuredBlock(
            kind=StructuredBlockKind.PARAGRAPH,
            text=f"Detalle de la sección {index} con texto suficiente para resumir.",
            order=index * 2 + 1,
            token_count=10,
            content_hash=f"b{index}",
        )
        bloques.extend([heading, cuerpo])
        sections.append(
            DocumentSection(
                id=uuid4(),
                document_id=doc_id,
                organization_id=org,
                section_path=(f"5.{index}",),
                heading=heading.text,
                depth=1,
                order=index,
                block_ids=(heading.id, cuerpo.id),
                content_hash=f"s{index}",
            )
        )
    return StructuredDocument(
        id=doc_id,
        organization_id=org,
        external_id="manual.pdf",
        title="manual",
        content_hash="doc-hash",
        blocks=tuple(bloques),
        sections=tuple(sections),
    )


class TestUsoDelResumen:
    @pytest.mark.asyncio
    async def test_acumula_los_tokens_reales_del_provider(self) -> None:
        llm = _LLMFalso()
        usage = SummaryUsage()
        await DocumentSummarizer(llm=llm).summarize(_documento(secciones=2), usage=usage)

        assert usage.calls == 3, "una por sección + una del documento"
        assert usage.prompt_tokens == 300
        assert usage.completion_tokens == 60
        assert usage.total_tokens == 360

    @pytest.mark.asyncio
    async def test_max_sections_recorta_y_lo_declara(self) -> None:
        llm = _LLMFalso()
        usage = SummaryUsage()
        summarizer = DocumentSummarizer(llm=llm, config=SummarizerConfig(max_sections=1))
        await summarizer.summarize(_documento(secciones=4), usage=usage)

        assert usage.sections_total == 4
        assert usage.sections_skipped == 3
        # 1 sección + documento
        assert usage.calls == 2

    @pytest.mark.asyncio
    async def test_allow_llm_false_usa_extractivo_sin_gastar(self) -> None:
        llm = _LLMFalso()
        usage = SummaryUsage()
        output = await DocumentSummarizer(llm=llm).summarize(
            _documento(secciones=3), usage=usage, allow_llm=False
        )

        assert llm.llm_calls == []
        assert usage.calls == 0
        assert usage.llm_disabled is True
        assert output.mode == "extractive"
        assert output.document_summary.metadata.get("mode") == "extractive"

    @pytest.mark.asyncio
    async def test_el_resumen_sigue_devolviendo_texto(self) -> None:
        llm = _LLMFalso('{"summary": "resumen corto", "key_points": ["k1", "k2"]}')
        output = await DocumentSummarizer(llm=llm).summarize(_documento(secciones=1))

        assert output.document_summary.summary == "resumen corto"
        assert output.document_summary.key_points == ("k1", "k2")
        assert output.mode == "llm"


class TestCostoDeTracker:
    CALCULOS: ClassVar[list[dict]] = []

    @pytest.fixture(autouse=True)
    def _capturar_inserts(self, monkeypatch: pytest.MonkeyPatch):
        capturados: list[dict] = []

        async def _fake_record(self, organization_id, **kwargs):  # noqa: ANN001
            capturados.append({"organization_id": organization_id, **kwargs})

        monkeypatch.setattr(KnowledgeUsageTracker, "record", _fake_record)
        self.__class__.CALCULOS = capturados
        return capturados

    @pytest.mark.asyncio
    async def test_embedding_con_costo_y_modelo(self) -> None:
        tracker = KnowledgeUsageTracker()
        await tracker.record_embedding_tokens(
            uuid4(), 1000, model="openai/baai/bge-m3", cost_usd=0.00002
        )

        assert self.CALCULOS[-1]["category"] == "embedding"
        assert self.CALCULOS[-1]["cost_usd"] == 0.00002
        assert self.CALCULOS[-1]["metadata"]["model"] == "openai/baai/bge-m3"

    @pytest.mark.asyncio
    async def test_llm_registra_prompt_y_completion(self) -> None:
        tracker = KnowledgeUsageTracker()
        await tracker.record_llm_tokens(
            uuid4(),
            prompt_tokens=300,
            completion_tokens=60,
            cost_usd=0.001,
            model="openai/deepseek/deepseek-v3.2",
            purpose="knowledge_summary",
        )

        assert self.CALCULOS[-1]["category"] == "llm"
        assert self.CALCULOS[-1]["tokens"] == 360
        assert self.CALCULOS[-1]["metadata"]["purpose"] == "knowledge_summary"
        assert self.CALCULOS[-1]["metadata"]["completion_tokens"] == 60


class TestCostoDeEmbeddings:
    @pytest.mark.asyncio
    async def test_estima_costo_con_el_registro_de_precios(self) -> None:
        from src.knowledge.engine.service import KnowledgeIngestionEngine

        costo = await KnowledgeIngestionEngine._embedding_cost("openai/baai/bge-m3", 1000)

        assert costo > 0, "un embedding no puede costar 0 en el dashboard"

    @pytest.mark.asyncio
    async def test_sin_tokens_no_hay_costo(self) -> None:
        from src.knowledge.engine.service import KnowledgeIngestionEngine

        assert await KnowledgeIngestionEngine._embedding_cost("openai/baai/bge-m3", 0) == 0.0


class TestTopeDeEmbedding:
    def test_recorta_sin_tocar_el_contenido_del_chunk(self) -> None:
        from src.knowledge.engine.service import KnowledgeIngestionEngine

        largo = "x" * 20000
        recortados = KnowledgeIngestionEngine._embed_texts([largo, "corto"])

        assert len(recortados[0]) <= 6000, "el padre gigante no puede ir entero al provider"
        assert recortados[1] == "corto"

    def test_tope_cero_no_recorta(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from src.core.config import get_settings
        from src.knowledge.engine.service import KnowledgeIngestionEngine

        monkeypatch.setattr(get_settings(), "RAG_EMBED_MAX_CHARS", 0)
        largo = "y" * 9000

        assert KnowledgeIngestionEngine._embed_texts([largo]) == [largo]


def test_los_chunks_de_tabla_no_se_pierden_al_chunkear() -> None:
    """Regresión del caso Cat31 §4.6.2: la tabla debe llegar al índice."""
    from src.knowledge.structure import chunk_structured_document

    document = _documento(secciones=1)
    doc_id = document.id
    filtro = document.sections[0]
    tabla = StructuredBlock(
        kind=StructuredBlockKind.TABLE,
        text="Value | Definition\n1 | apply the highest change fee",
        order=99,
        token_count=12,
        content_hash="t1",
    )
    documento = StructuredDocument(
        id=doc_id,
        organization_id=document.organization_id,
        external_id="manual.pdf",
        title="manual",
        content_hash="doc-hash-2",
        blocks=document.blocks + (tabla,),
        sections=(
            DocumentSection(
                id=filtro.id,
                document_id=doc_id,
                organization_id=document.organization_id,
                section_path=("4.6.2", "Fee Application (byte 105)"),
                heading="Fee Application (byte 105)",
                depth=1,
                order=0,
                block_ids=(*filtro.block_ids, tabla.id),
                content_hash="s0",
            ),
        ),
    )
    chunks = chunk_structured_document(documento)

    con_tabla = [c for c in chunks if "highest change fee" in c.content]
    assert con_tabla, "la fila de la tabla debe estar en algún chunk"
    assert all("byte 105" in c.content for c in con_tabla), "y con su ruta de sección"
