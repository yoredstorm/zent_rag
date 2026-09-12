# =============================================================================
# Knowledge V2 — readiness / cutover assessment (Phase H)
# =============================================================================
# Estado real del corte: flags efectivos + conteos de datos estructurados
# (documentos, bloques, corpora, fuentes con docs). READY es una señal
# operativa honesta: el switch productivo (promote) debe además validarse con
# las métricas shadow (overlap/latencia) registradas antes de promoverse.
# =============================================================================
from __future__ import annotations

from uuid import UUID

from sqlalchemy import text

from src.core.config import get_settings
from src.infrastructure.postgres.session import get_async_session

_COUNTS_SQL = text(
    """
    SELECT
        (SELECT COUNT(*)::int FROM structured_documents
         WHERE organization_id = :oid) AS documents,
        (SELECT COUNT(*)::int FROM structured_blocks
         WHERE organization_id = :oid) AS blocks,
        (SELECT COUNT(*)::int FROM knowledge_corpora
         WHERE organization_id = :oid) AS corpora,
        (SELECT COUNT(*)::int FROM structured_documents
         WHERE organization_id = :oid AND source_id IS NOT NULL) AS docs_with_source
    """
)


async def assess_v2_readiness(organization_id: UUID) -> dict:
    """Evalúa el estado V2 real de una organización (scoped por tenant)."""
    settings = get_settings()
    session = await get_async_session()
    try:
        row = (await session.execute(_COUNTS_SQL, {"oid": str(organization_id)})).fetchone()
    finally:
        await session.close()

    documents = int(row.documents or 0)
    blocks = int(row.blocks or 0)
    corpora = int(row.corpora or 0)
    docs_with_source = int(row.docs_with_source or 0)

    chunks_indexed = blocks > 0 and documents > 0
    has_corpus = corpora > 0
    promote_ready = bool(
        settings.KNOWLEDGE_V2_ENABLED
        and chunks_indexed
        and has_corpus
        and docs_with_source > 0
    )

    return {
        "organization_id": str(organization_id),
        "flags": {
            "enabled": settings.KNOWLEDGE_V2_ENABLED,
            "promote": settings.KNOWLEDGE_V2_PROMOTE,
            "shadow": settings.KNOWLEDGE_V2_SHADOW,
            "locate_llm": settings.KNOWLEDGE_LOCATE_LLM_ENABLED,
        },
        "counts": {
            "structured_documents": documents,
            "structured_blocks": blocks,
            "knowledge_corpora": corpora,
            "sources_with_docs": docs_with_source,
        },
        "ready": promote_ready,
        "gate": (
            "Datos estructurados + corpus OK. Antes de promover en producción, "
            "valida shadow metrics (knowledge_shadow_retrievals_total/overlap/latency)."
            if promote_ready
            else (
                "Falta: habilitar el flag V2, re-procesar fuentes (backfill) o "
                "crear un corpus con fuentes indexadas."
            )
        ),
    }
