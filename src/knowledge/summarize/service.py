# =============================================================================
# Knowledge V2 — Document summarization (Phase C slice 3)
# =============================================================================
# Resúmenes multi-nivel: SectionSummary por sección + DocumentSummary del
# documento (brief §7). SIEMPRE INFERRED — los resúmenes nunca sustituyen el
# contenido original y nada se auto-aprueba. Modalidad shadow (no persiste);
# el rollout ASSISTED/ACTIVE llega con la persistencia (Phase E).
#
# El LLM es un asistente: si falla (timeout/parse), cae a fallback extractivo
# determinista (primeras frases + topics = headings) con mode="extractive".
# =============================================================================
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from src.core.domain.catalog import CatalogProvenance
from src.core.domain.knowledge_v2 import (
    DocumentSection,
    DocumentSummary,
    KnowledgeObjectStatus,
    SectionSummary,
    StructuredDocument,
)
from src.core.ports import LLMProvider
from src.knowledge.structure.base import content_hash

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


class SummaryError(Exception):
    """El resumen no pudo generarse (el llamador decide si es fatal)."""


@dataclass(frozen=True, kw_only=True)
class SummarizerConfig:
    document_max_chars: int = 24_000
    section_max_chars: int = 6_000
    model: str | None = None
    temperature: float = 0.2
    max_tokens: int = 512
    #: Tope de secciones resumidas por documento (0 = todas). Un manual de 700
    #: páginas con cientos de secciones multiplicaba el costo sin control.
    max_sections: int = 0


@dataclass
class SummaryUsage:
    """Uso real de la corrida de resumen (tokens que reporta el provider)."""

    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    sections_total: int = 0
    sections_skipped: int = 0
    llm_disabled: bool = False

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def add(self, response: Any) -> None:
        self.calls += 1
        self.prompt_tokens += int(getattr(response, "prompt_tokens", 0) or 0)
        self.completion_tokens += int(getattr(response, "completion_tokens", 0) or 0)


@dataclass(frozen=True, kw_only=True)
class SummarizationOutput:
    document_summary: DocumentSummary
    section_summaries: tuple[SectionSummary, ...]
    mode: str  # "llm" | "extractive"


class DocumentSummarizer:
    """Genera el resumen de nivel documento y por sección (INFERRED)."""

    def __init__(
        self,
        llm: LLMProvider,
        *,
        config: SummarizerConfig | None = None,
    ) -> None:
        self._llm = llm
        self._config = config or SummarizerConfig()

    async def summarize(
        self,
        document: StructuredDocument,
        *,
        usage: SummaryUsage | None = None,
        allow_llm: bool = True,
    ) -> SummarizationOutput:
        """Resume el documento. `usage` acumula los tokens reales por llamada.

        `allow_llm=False` (presupuesto agotado) usa el camino extractivo
        determinista sin gastar una sola llamada.
        """
        uso = usage if usage is not None else SummaryUsage()
        uso.llm_disabled = not allow_llm
        secciones = list(document.sections)
        uso.sections_total = len(secciones)
        if self._config.max_sections and len(secciones) > self._config.max_sections:
            uso.sections_skipped = len(secciones) - self._config.max_sections
            secciones = secciones[: self._config.max_sections]

        section_summaries: list[SectionSummary] = []
        for section in secciones:
            section_summaries.append(
                await self._summarize_section(document, section, usage=uso, allow_llm=allow_llm)
            )

        doc_summary = await self._summarize_document(document, usage=uso, allow_llm=allow_llm)
        mode_value = (
            doc_summary.metadata.get("mode", "extractive")
            if isinstance(doc_summary.metadata, dict)
            else "extractive"
        )
        return SummarizationOutput(
            document_summary=doc_summary,
            section_summaries=tuple(section_summaries),
            mode=mode_value,
        )

    # ------------------------------------------------------------------
    # Nivel documento
    # ------------------------------------------------------------------
    async def _summarize_document(
        self,
        document: StructuredDocument,
        *,
        usage: SummaryUsage,
        allow_llm: bool = True,
    ) -> DocumentSummary:
        text = _document_source_text(document)
        model = self._config.model
        try:
            if not allow_llm:
                raise SummaryError("llm disabled")
            summary_text, key_points = await self._llm_summarize(
                text,
                kind="documento",
                max_chars=self._config.document_max_chars,
                model=model,
                usage=usage,
            )
            mode = "llm"
        except (SummaryError, Exception):
            summary_text, key_points = _extractive_summary(text, document=document)
            mode = "extractive"
        return DocumentSummary(
            id=uuid4(),
            document_id=document.id,
            organization_id=document.organization_id,
            workspace_id=document.workspace_id,
            source_id=document.source_id,
            summary=summary_text,
            key_topics=key_points,
            key_points=key_points,
            language=document.language,
            token_count=len(summary_text.split()),
            model=model,
            content_hash=content_hash(summary_text),
            provenance=CatalogProvenance.INFERRED,
            status=KnowledgeObjectStatus.INFERRED,
            metadata={"mode": mode},
        )

    # ------------------------------------------------------------------
    # Nivel sección
    # ------------------------------------------------------------------
    async def _summarize_section(
        self,
        document: StructuredDocument,
        section: DocumentSection,
        *,
        usage: SummaryUsage,
        allow_llm: bool = True,
    ) -> SectionSummary:
        text = _section_source_text(document, section)
        model = self._config.model
        try:
            if not allow_llm:
                raise SummaryError("llm disabled")
            summary_text, key_points = await self._llm_summarize(
                text,
                kind="sección",
                max_chars=self._config.section_max_chars,
                model=model,
                usage=usage,
            )
            mode = "llm"
        except (SummaryError, Exception):
            summary_text, key_points = _extractive_summary(text)
            mode = "extractive"
        return SectionSummary(
            id=uuid4(),
            document_id=document.id,
            section_id=section.id,
            organization_id=document.organization_id,
            workspace_id=document.workspace_id,
            source_id=document.source_id,
            summary=summary_text,
            key_points=key_points,
            language=document.language,
            token_count=len(summary_text.split()),
            model=model,
            content_hash=content_hash(summary_text),
            provenance=CatalogProvenance.INFERRED,
            status=KnowledgeObjectStatus.INFERRED,
            metadata={"mode": mode, "section_path": list(section.section_path)},
        )

    async def _llm_summarize(
        self,
        source: str,
        *,
        kind: str,
        max_chars: int,
        model: str | None,
        usage: SummaryUsage | None = None,
    ) -> tuple[str, tuple[str, ...]]:
        text = source[:max_chars]
        if not text.strip():
            raise SummaryError("empty source")
        prompt = (
            f"Resume la {kind} siguiente en 2-4 frases y extrae hasta 5 puntos "
            "clave. Responde SOLO JSON: {\"summary\": str, \"key_points\": [str]}.\n\n"
            f"Texto:\n{text}"
        )
        response = await self._llm.generate(
            prompt,
            model=model,
            max_tokens=self._config.max_tokens,
            temperature=self._config.temperature,
            system_prompt=(
                "Eres un resumidor de conocimiento empresarial. Nunca inventes "
                "información que no esté en el texto."
            ),
        )
        if usage is not None:
            usage.add(response)
        raw = (response.content or "").strip()
        match = _JSON_BLOCK_RE.search(raw)
        if not match:
            raise SummaryError("LLM did not return a JSON object")
        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise SummaryError("invalid summary JSON") from exc
        summary = str(payload.get("summary") or "").strip()
        points = tuple(str(p) for p in payload.get("key_points") or [])
        if not summary:
            raise SummaryError("empty summary from LLM")
        return summary, points


# ---------------------------------------------------------------------------
# Fallback extractivo determinista (no LLM)
# ---------------------------------------------------------------------------

def _document_source_text(document: StructuredDocument) -> str:
    parts = [b.text for b in document.blocks if b.text]
    for table in document.tables:
        parts.append(_render_table_text(table))
    return "\n\n".join(parts)


def _section_source_text(
    document: StructuredDocument, section: DocumentSection
) -> str:
    content = [section.heading] if section.heading else []
    by_id = {b.id: b for b in document.blocks}
    for block_id in section.block_ids:
        block = by_id.get(block_id)
        if block is not None and block.text:
            content.append(block.text)
    return "\n\n".join(content)


def _render_table_text(table) -> str:
    parts = [" | ".join(table.headers)]
    parts.extend(" | ".join(row) for row in table.rows)
    return "\n".join(parts)


def _extractive_summary(
    text: str,
    *,
    document: StructuredDocument | None = None,
) -> tuple[str, tuple[str, ...]]:
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    summary = " ".join(sentences[:3]).strip() or (text.strip()[:400] if text.strip() else "Sin contenido.")
    if document is not None:
        topics = tuple(
            s.heading for s in document.sections if s.heading
        )[:5]
    else:
        topics = ()
    return summary, topics
