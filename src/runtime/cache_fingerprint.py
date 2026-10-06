# =============================================================================
# Cache fingerprint — huella del conocimiento para claves de respuesta
# =============================================================================
# La capa agents/runtime no puede importar adaptadores (tests de arquitectura),
# por eso el fingerprint vive acá: la fábrica de sesión de Postgres es el único
# acceso permitido y la implementación es una sola para API, edge y runtime.
#
# Incluye reglas canónicas (cantidad + updated_at) y documentos estructurados
# (updated_at): si una regla cambia, la clave cambia y la respuesta vieja NO se
# reutiliza. Fail-closed: ante error devuelve "" y el caller desactiva la caché.
# =============================================================================
from __future__ import annotations

from hashlib import sha256
from uuid import UUID

from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)


async def knowledge_cache_fingerprint(organization_id: UUID | str) -> str:
    """Fingerprint tenant-scoped del conocimiento. "" = no cachear."""
    try:
        from sqlalchemy import text as sql_text

        from src.infrastructure.postgres.session import get_async_session
        from src.infrastructure.redis.cache import (
            _RESPONSE_DECISION_VERSION,
            _RESPONSE_SEMANTICS_POLICY_VERSION,
        )

        session = await get_async_session()
        try:
            row = (
                await session.execute(
                    sql_text(
                        "SELECT "
                        "(SELECT count(*)::text FROM knowledge_canonical_objects "
                        " WHERE organization_id = :org AND kind = 'BUSINESS_RULE') AS rules, "
                        "(SELECT COALESCE(max(updated_at)::text, '') "
                        " FROM knowledge_canonical_objects WHERE organization_id = :org) "
                        " AS rules_updated, "
                        "(SELECT COALESCE(max(updated_at)::text, '') "
                        " FROM structured_documents WHERE organization_id = :org) "
                        " AS docs_updated"
                    ),
                    {"org": organization_id},
                )
            ).first()
        finally:
            await session.close()
        if row is None:
            return ""
        material = (
            f"{row.rules}|{row.rules_updated}|{row.docs_updated}|"
            f"{_RESPONSE_SEMANTICS_POLICY_VERSION}|{_RESPONSE_DECISION_VERSION}"
        )
        return sha256(material.encode("utf-8")).hexdigest()[:32]
    except Exception as exc:  # noqa: BLE001 — sin fingerprint no se cachea
        logger.warning("Knowledge cache fingerprint failed", error=str(exc)[:160])
        return ""


__all__ = ["knowledge_cache_fingerprint"]
