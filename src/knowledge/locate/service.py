# =============================================================================
# Citation Locator — Knowledge V2 (Phase G: PDF highlight [1] → página)
# =============================================================================
# Resuelve un anchor (query/excerpt) a la página más probable de una fuente
# usando bloques estructurados con bbox. Determinista por overlap de tokens;
# el LLM (opcional, flag-off) SOLO puede escoger entre candidatos reales —
# nunca inventa páginas. Devuelve page/confidence/method/bbox/excerpt.
# =============================================================================
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text

from src.core.ports import LLMProvider
from src.infrastructure.postgres.session import get_async_session

_BLOCKS_SQL = text(
    """
    SELECT b.id, b.page_number, b.text, b.bbox
    FROM structured_blocks b
    WHERE b.organization_id = :oid AND b.source_id = :sid
      AND b.node_type = 'block' AND b.page_number IS NOT NULL
      AND b.text <> ''
    ORDER BY b.page_number, b.order_index
    """
)

_TOKEN_SPLIT_RE = re.compile(r"[\W_]+", re.UNICODE)


@dataclass(frozen=True, kw_only=True)
class PageCandidate:
    page: int
    score: float
    excerpt: str
    bbox: dict | None = None

    def to_dict(self) -> dict:
        return {
            "page": self.page,
            "score": round(self.score, 4),
            "excerpt": self.excerpt[:200],
            "bbox": self.bbox,
        }


@dataclass(frozen=True, kw_only=True)
class LocateResult:
    page: int | None
    confidence: float = 0.0
    method: str = "heuristic"  # heuristic | llm
    excerpt: str = ""
    bbox: dict | None = None
    candidates: tuple[PageCandidate, ...] = ()

    def to_dict(self) -> dict:
        return {
            "page": self.page,
            "confidence": round(self.confidence, 4),
            "method": self.method,
            "excerpt": self.excerpt[:300],
            "bbox": self.bbox,
            "candidates": [c.to_dict() for c in self.candidates[:5]],
        }


def _tokens(text: str) -> set[str]:
    return {t for t in _TOKEN_SPLIT_RE.split(text.lower()) if t}


class CitationLocator:
    """Ancla un snippet/query a la página (con LLM opcional, validado)."""

    def __init__(self, llm: LLMProvider | None = None) -> None:
        self._llm = llm

    async def locate(
        self,
        organization_id: UUID,
        source_id: UUID,
        query: str,
        *,
        page_hint: int | None = None,
    ) -> LocateResult:
        blocks = await self._load_blocks(organization_id, source_id)
        query_tokens = _tokens(query)
        candidates = self._rank_pages(blocks, query_tokens, page_hint)
        if not candidates:
            return LocateResult(page=None)

        best = candidates[0]
        method = "heuristic"
        if self._llm is not None:
            llm_page = await self._ask_llm(query, candidates[:5])
            if llm_page is not None:
                selected = next(
                    (c for c in candidates if c.page == llm_page), None
                )
                if selected is not None:
                    best = selected
                    method = "llm"

        return LocateResult(
            page=best.page,
            confidence=best.score,
            method=method,
            excerpt=best.excerpt,
            bbox=best.bbox,
            candidates=tuple(candidates),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    async def _load_blocks(
        self, organization_id: UUID, source_id: UUID
    ) -> list[dict]:
        session = await get_async_session()
        try:
            rows = (
                await session.execute(
                    _BLOCKS_SQL,
                    {"oid": str(organization_id), "sid": str(source_id)},
                )
            ).fetchall()
            return [
                {
                    "page": row.page_number,
                    "text": row.text,
                    "bbox": row.bbox if isinstance(row.bbox, dict) else None,
                    "id": row.id,
                }
                for row in rows
            ]
        finally:
            await session.close()

    def _rank_pages(
        self,
        blocks: list[dict],
        query_tokens: set[str],
        page_hint: int | None,
    ) -> list[PageCandidate]:
        if not query_tokens:
            return []
        by_page: dict[int, list[dict]] = {}
        for block in blocks:
            by_page.setdefault(block["page"], []).append(block)

        ranked: list[PageCandidate] = []
        for page, page_blocks in by_page.items():
            ratios = []
            best_block: dict | None = None
            best_ratio = 0.0
            for block in page_blocks:
                block_tokens = _tokens(block["text"])
                if not block_tokens:
                    continue
                ratio = len(query_tokens & block_tokens) / len(query_tokens)
                ratios.append(ratio)
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_block = block
            if not ratios:
                continue
            score = max(ratios)
            if (
                page_hint is not None
                and page == page_hint
                and score < 0.5
            ):
                score = max(score, 0.5)  # page_hint como señal suave
            ranked.append(
                PageCandidate(
                    page=page,
                    score=score,
                    excerpt=(best_block["text"] if best_block else "")[:600],
                    bbox=best_block["bbox"] if best_block else None,
                )
            )
        ranked.sort(key=lambda c: c.score, reverse=True)
        return ranked

    async def _ask_llm(
        self, query: str, candidates: list[PageCandidate]
    ) -> int | None:
        """Pide al LLM la página; valida contra candidatos (no inventa)."""
        if self._llm is None or not candidates:
            return None
        allowed = {c.page for c in candidates}
        prompt = (
            "Estas son páginas candidatas de un documento con su comienzo de "
            "texto. Devuelve SOLO JSON {\"page\": <número o null>} con la "
            "página donde mejor encaja la consulta. Si ninguna page contiene "
            "información, devuelve null. NO inventes páginas fuera de la lista.\n\n"
            "Consulta: "
            + query
            + "\n\nCandidatas:\n"
            + "\n".join(
                f"- página {c.page} (score {round(c.score, 2)}): {c.excerpt[:140]}"
                for c in candidates
            )
        )
        try:
            response = await self._llm.generate(
                prompt,
                max_tokens=64,
                temperature=0.0,
                system_prompt=(
                    "Eres un localizador de evidencia. Delegación estricta: "
                    "solo respondes con la página entre las candidatas."
                ),
            )
            match = re.search(r"\{.*\}", response.content or "", re.DOTALL)
            if not match:
                return None
            payload = json.loads(match.group(0))
            raw = payload.get("page")
            if raw is None:
                return None
            page = int(raw)
            return page if page in allowed else None
        except Exception:  # noqa: BLE001 - fallback heurístico siempre
            return None
