# =============================================================================
# Corpus Studio — artefactos reales sobre datos estructurados V2 (Phase G)
# =============================================================================
# Produce artefactos del Knowledge Studio a partir de lo que YA existe en
# Postgres (structured_documents + structured_blocks + kb_sources.corpus_id).
# Nada inventado: todo item lleva provenance (document_id, page, kind) y el
# pipeline declara source=observed|inferred. Sin LLM obligatorio.
# =============================================================================
from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.postgres.session import get_async_session

_DOCS_SQL = """
SELECT sd.id, sd.title, sd.document_type, sd.language,
       sd.page_count, sd.section_count, sd.block_count, sd.updated_at
FROM structured_documents sd
JOIN kb_sources s ON s.id = sd.source_id AND s.organization_id = sd.organization_id
WHERE sd.organization_id = :oid AND s.corpus_id = :cid
ORDER BY sd.updated_at DESC
LIMIT :limit
"""

_BLOCKS_SQL = """
SELECT b.document_id, b.node_type, b.kind, b.content_type,
       b.text, b.page_number, b.metadata, sd.title
FROM structured_blocks b
JOIN structured_documents sd ON sd.id = b.document_id
JOIN kb_sources s ON s.id = sd.source_id
WHERE sd.organization_id = :oid AND s.corpus_id = :cid
  AND b.node_type IN ('table', 'block', 'figure')
  AND b.text <> ''
ORDER BY b.document_id, b.order_index
LIMIT :limit
"""

_ISO_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_SHORT_DATE_RE = re.compile(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b")
_RISK_CUES = re.compile(
    r"\b(riesgo|riesgos|penalizaci[oó]n|incumplimiento|terminaci[oó]n|"
    r"indemnizaci[oó]n|exclusi[oó]n de responsabilidad|obligaci[oó]n|"
    r"risk|penalty|breach|termination|liability)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, kw_only=True)
class StudioArtifact:
    name: str
    items: tuple[dict, ...] = ()
    sources_used: int = 0
    provenance: str = "observed|inferred"

    def to_dict(self) -> dict:
        return {
            "artifact": self.name,
            "items": list(self.items),
            "sources_used": self.sources_used,
            "provenance": self.provenance,
        }


@dataclass(frozen=True, kw_only=True)
class StudioResult:
    artifacts: tuple[StudioArtifact, ...] = ()

    def to_dict(self) -> dict:
        return {"artifacts": [a.to_dict() for a in self.artifacts]}


def _row_dict(row) -> dict:
    metadata = row.metadata if isinstance(row.metadata, dict) else {}
    return {
        "document_id": str(row.document_id),
        "node_type": row.node_type,
        "kind": row.kind,
        "content_type": row.content_type,
        "text": row.text,
        "page": row.page_number,
        "metadata": metadata,
        "title": row.title,
    }


class CorpusStudioService:
    """Construye artefactos honestos: resúmenes estructurales, hechos de
    tablas, timeline por fechas, preguntas sugeridas y candidatos a riesgo."""

    def __init__(self, *, max_docs: int = 100, max_blocks: int = 2000) -> None:
        self._max_docs = max_docs
        self._max_blocks = max_blocks

    async def build(
        self,
        organization_id: UUID,
        corpus_id: UUID,
        *,
        artifacts: tuple[str, ...] | None = None,
    ) -> StudioResult:
        session = await get_async_session()
        try:
            docs_rows = (
                await session.execute(
                    text(_DOCS_SQL),
                    {"oid": str(organization_id), "cid": str(corpus_id), "limit": self._max_docs},
                )
            ).fetchall()
            blocks_rows = (
                await session.execute(
                    text(_BLOCKS_SQL),
                    {"oid": str(organization_id), "cid": str(corpus_id), "limit": self._max_blocks},
                )
            ).fetchall()
        finally:
            await session.close()

        docs = [dict(r._mapping) for r in docs_rows]
        blocks = [_row_dict(r) for r in blocks_rows]
        wanted = set(artifacts or ("executive_summary", "key_facts", "timeline", "faq", "risks"))

        result: list[StudioArtifact] = []
        if "executive_summary" in wanted:
            result.append(self._executive_summary(docs))
        if "key_facts" in wanted:
            result.append(self._key_facts(blocks))
        if "timeline" in wanted:
            result.append(self._timeline(blocks))
        if "faq" in wanted:
            result.append(self._faq(docs, blocks))
        if "risks" in wanted:
            result.append(self._risks(blocks))
        return StudioResult(artifacts=tuple(result))

    # ------------------------------------------------------------------
    # executive summary — estructural (real, sin LLM)
    # ------------------------------------------------------------------
    def _executive_summary(self, docs: list[dict]) -> StudioArtifact:
        items: list[dict] = []
        for doc in docs:
            items.append(
                {
                    "title": doc.get("title") or "Sin título",
                    "document_type": doc.get("document_type"),
                    "language": doc.get("language"),
                    "page_count": doc.get("page_count") or 0,
                    "section_count": doc.get("section_count") or 0,
                    "block_count": doc.get("block_count") or 0,
                    "document_id": str(doc.get("id") or ""),
                    "kind": "structural",
                    "source": "observed",
                }
            )
        return StudioArtifact(
            name="executive_summary",
            items=tuple(items),
            sources_used=len(docs),
        )

    # ------------------------------------------------------------------
    # key facts — tablas y figuras preservadas
    # ------------------------------------------------------------------
    def _key_facts(self, blocks: list[dict]) -> StudioArtifact:
        items: list[dict] = []
        for block in blocks:
            if block["node_type"] == "table":
                headers = block["metadata"].get("headers") or []
                rows = block["metadata"].get("rows") or []
                for row in rows[:20]:
                    rendered = " | ".join(str(c) for c in row)
                    if rendered.strip():
                        items.append(
                            {
                                "text": f"{block['title']} — {rendered}",
                                "document_id": block["document_id"],
                                "page": block["page"],
                                "kind": "table_cell",
                                "source": "observed",
                            }
                        )
                if headers and not rows:
                    items.append(
                        {
                            "text": f"{block['title']} — columnas: {' | '.join(str(h) for h in headers)}",
                            "document_id": block["document_id"],
                            "page": block["page"],
                            "kind": "table_schema",
                            "source": "observed",
                        }
                    )
            elif block["node_type"] == "figure":
                items.append(
                    {
                        "text": f"{block['title']} — figura {block.get('metadata', {}).get('figure_type', 'image')}",
                        "document_id": block["document_id"],
                        "page": block["page"],
                        "kind": "figure",
                        "source": "observed",
                    }
                )
        return StudioArtifact(name="key_facts", items=tuple(items), sources_used=len(blocks))

    # ------------------------------------------------------------------
    # timeline — fechas extraídas de bloques
    # ------------------------------------------------------------------
    def _timeline(self, blocks: list[dict]) -> StudioArtifact:
        items: list[dict] = []
        for block in blocks:
            for match in _ISO_DATE_RE.finditer(block["text"]):
                items.append(
                    {
                        "date": match.group(1),
                        "text": block["text"][:200],
                        "document_id": block["document_id"],
                        "page": block["page"],
                        "kind": "date",
                        "source": "observed",
                    }
                )
        for block in blocks:
            for match in _SHORT_DATE_RE.finditer(block["text"]):
                # solo si no hay ya ISO capturada en ese bloque (evitar duplicados)
                if _ISO_DATE_RE.search(block["text"]):
                    continue
                items.append(
                    {
                        "date": match.group(1),
                        "text": block["text"][:200],
                        "document_id": block["document_id"],
                        "page": block["page"],
                        "kind": "date",
                        "source": "observed",
                    }
                )
        items.sort(key=lambda item: str(item["date"]))
        return StudioArtifact(name="timeline", items=tuple(items[:200]), sources_used=len(blocks))

    # ------------------------------------------------------------------
    # FAQ — preguntas sugeridas basadas en contenido real (INFERRED)
    # ------------------------------------------------------------------
    def _faq(self, docs: list[dict], blocks: list[dict]) -> StudioArtifact:
        items: list[dict] = []
        for doc in docs[:20]:
            title = doc.get("title") or "documento"
            items.append(
                {
                    "question": f"¿De qué trata {title}?",
                    "document_id": str(doc.get("id") or ""),
                    "intent": "summary",
                    "source": "inferred",
                }
            )
            items.append(
                {
                    "question": f"¿Qué obligaciones o cláusulas aparecen en {title}?",
                    "document_id": str(doc.get("id") or ""),
                    "intent": "list",
                    "source": "inferred",
                }
            )
        for block in blocks:
            if block["node_type"] == "table" and block["title"]:
                items.append(
                    {
                        "question": f"¿Qué contiene la tabla de {block['title']}?",
                        "document_id": block["document_id"],
                        "intent": "table_aware",
                        "source": "inferred",
                    }
                )
        return StudioArtifact(name="faq", items=tuple(items[:60]), sources_used=len(docs) + len(blocks))

    # ------------------------------------------------------------------
    # risks — candidatos extraídos por señales léxicas (INFERRED)
    # ------------------------------------------------------------------
    def _risks(self, blocks: list[dict]) -> StudioArtifact:
        items: list[dict] = []
        for block in blocks[:1500]:
            match = _RISK_CUES.search(block["text"])
            if not match:
                continue
            cue = match.group(1).lower()
            items.append(
                {
                    "text": block["text"][:300],
                    "document_id": block["document_id"],
                    "page": block["page"],
                    "cue": cue,
                    "kind": "risk_candidate",
                    "source": "inferred",
                }
            )
        return StudioArtifact(name="risks", items=tuple(items[:100]), sources_used=len(blocks))
