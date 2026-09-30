# =============================================================================
# ExactRetriever — tercera pata: candidatos literales
# =============================================================================
# La vectorial y la léxica tokenizan y pierden símbolos; esta pata compara la
# frase contra el contenido crudo (substring, case-insensitive) y marca cada
# acierto como MUST_KEEP. Es aditiva: no reemplaza ninguna pata. El barrido es
# acotado (puntos/ms) y respeta el filtro ACL/tenant del store (role, user,
# groups, workspace, knowledge_base, source_ids).
# =============================================================================
from __future__ import annotations

from src.core.domain.entities import RetrievalChunk, RetrievalContext
from src.infrastructure.observability.logging_config import get_logger
from src.rag.longcontext.exact_tokens import ExactToken, exact_needles
from src.rag.longcontext.must_keep import mark_must_keep
from src.rag.retrieval.models import RetrievalQuery

logger = get_logger(__name__)

#: Tope de tokens exactos usados por consulta (settings pueden bajarlo/subirlo).
_DEFAULT_MAX_NEEDLES = 8
_DEFAULT_CHUNKS = 4
_DEFAULT_MAX_POINTS = 4000
_DEFAULT_MAX_MS = 1500.0


class ExactRetriever:
    """Pata exacta sobre el store (scan literal con fallback tokenizado)."""

    def __init__(self, store: object) -> None:
        self._store = store

    def _settings(self) -> tuple[bool, int, int, int, float]:
        """(activo, chunks, puntos, needles, ms). Tolerante a settings."""
        try:
            from src.core.config import get_settings

            settings = get_settings()

            def _leer(nombre: str, default):
                return getattr(settings, nombre, default)

            activo = str(_leer("RAG_EXACT_SEARCH", "on")).lower() not in {
                "off",
                "0",
                "false",
            }
            return (
                activo,
                max(int(_leer("RAG_EXACT_SEARCH_CHUNKS", _DEFAULT_CHUNKS) or 0), 1),
                max(int(_leer("RAG_EXACT_SEARCH_MAX_POINTS", _DEFAULT_MAX_POINTS) or 0), 0),
                max(int(_leer("RAG_EXACT_SEARCH_MAX_NEEDLES", _DEFAULT_MAX_NEEDLES) or 0), 1),
                max(float(_leer("RAG_EXACT_SEARCH_MAX_MS", _DEFAULT_MAX_MS) or 0.0), 0.0),
            )
        except Exception:  # noqa: BLE001 — la pata exacta nunca rompe el retrieval
            return True, _DEFAULT_CHUNKS, _DEFAULT_MAX_POINTS, _DEFAULT_MAX_NEEDLES, _DEFAULT_MAX_MS

    async def retrieve(
        self,
        query: RetrievalQuery,
        tokens: list[ExactToken] | tuple[ExactToken, ...],
    ) -> RetrievalContext:
        activo, chunks_limit, max_points, max_needles, max_ms = self._settings()
        if not activo or not getattr(query, "exact_search", True):
            return RetrievalContext(chunks=[], retrieval_latency_ms=0.0)
        needles = exact_needles(tokens, max_items=max_needles)
        if not needles:
            return RetrievalContext(chunks=[], retrieval_latency_ms=0.0)

        scan = getattr(self._store, "scan_text_literal", None)
        if not callable(scan):
            # Fallback: barrido tokenizado histórico (pierde símbolos, pero
            # cubre códigos alfanuméricos mientras el adaptador no exponga el
            # scan literal).
            scan = getattr(self._store, "scan_text", None)
        if not callable(scan):
            return RetrievalContext(chunks=[], retrieval_latency_ms=0.0)

        try:
            context = await scan(
                organization_id=query.organization_id,
                needles=list(needles),
                source_ids=query.source_ids or None,
                knowledge_base_id=query.knowledge_base_id,
                workspace_id=query.workspace_id,
                role=query.role,
                user_id=query.user_id,
                groups=query.groups,
                limit=chunks_limit,
                max_points=max_points,
                max_ms=max_ms,
            )
        except Exception as exc:  # noqa: BLE001 — best-effort, jamás tumba el retrieval
            logger.warning("Exact scan failed", error=str(exc)[:200])
            return RetrievalContext(chunks=[], retrieval_latency_ms=0.0)

        kinds = _kind_index(tokens, needles)
        marked = [self._mark(chunk, needles, kinds) for chunk in context.chunks]
        if marked:
            logger.info(
                "Exact leg matched",
                needles=len(needles),
                chunks=len(marked),
                organization_id=str(query.organization_id),
            )
        return RetrievalContext(
            chunks=marked,
            query_embedding=query.query_embedding,
            retrieval_latency_ms=context.retrieval_latency_ms,
        )

    @staticmethod
    def _mark(
        chunk: RetrievalChunk,
        needles: list[str],
        kinds: dict[str, str],
    ) -> RetrievalChunk:
        content = (chunk.content or "").lower()
        matched = next((needle for needle in needles if needle.lower() in content), needles[0])
        return mark_must_keep(
            chunk,
            needle=matched,
            kind=kinds.get(matched.lower(), ""),
            retrieval="exact",
        )


def _kind_index(
    tokens: list[ExactToken] | tuple[ExactToken, ...],
    needles: list[str],
) -> dict[str, str]:
    """needle (lower) -> kind del token que lo aportó."""
    index: dict[str, str] = {}
    allowed = {needle.lower() for needle in needles}
    for token in tokens:
        for needle in token.needles:
            key = (needle or "").strip().lower()
            if key and key in allowed:
                index.setdefault(key, token.kind)
    return index


__all__ = ["ExactRetriever"]
