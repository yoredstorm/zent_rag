"""Auto-provisioning del demo vertical (farmacia) para organizaciones nuevas.

Cuando RAG_SEED_DEMO_DATA=true y el schema demo `farmacia` existe en el
Postgres de la plataforma, cada trial recién creado recibe los vectores del
demo: se encolan syncs por tabla (farmacia.*) en la cola del ingestion worker.

Fail-soft: si algo falla, el trial se crea igual sin datos demo.
"""

from __future__ import annotations

import sys
from uuid import UUID

from sqlalchemy import text

from src.core.config import get_settings
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.relational_db import get_async_session

logger = get_logger(__name__)

_DEMO_SCHEMA = "farmacia"


async def _demo_schema_tables() -> list[str]:
    session = await get_async_session()
    try:
        rows = await session.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = :s AND table_type IN ('BASE TABLE', 'VIEW') "
                "ORDER BY table_name"
            ),
            {"s": _DEMO_SCHEMA},
        )
        return [str(r.table_name) for r in rows.fetchall()]
    finally:
        await session.close()


async def provision_demo_kb(organization_id: UUID) -> bool:
    """Encuela la ingestión del demo farmacia para la organización.

    Returns True si se encoló la ingestión demo, False si no aplica
    (flag apagado, schema demo ausente o error — siempre fail-soft).
    """
    settings = get_settings()
    if not settings.SEED_DEMO_DATA:
        return False
    if "pytest" in sys.modules:
        # Bajo pytest no se encolan jobs reales contra Redis/demo.
        return False

    try:
        tables = await _demo_schema_tables()
        if not tables:
            logger.info(
                "provision_demo_kb: schema %s ausente; demo no disponible",
                _DEMO_SCHEMA,
            )
            return False

        from src.connectors.sql.queue import enqueue_sync

        # full_refresh solo en la primera tabla: la API borra los vectores de
        # TODO el org al activarlo; el resto hace upsert incremental.
        # ignore_org_filter=True: la data demo del schema farmacia es compartida
        # (pertenece al org demo), se ingiere completa y se etiqueta con el
        # organization del trial.
        for index, table in enumerate(tables):
            await enqueue_sync(
                organization_id,
                schema_name=_DEMO_SCHEMA,
                table_name=table,
                full_refresh=(index == 0),
                ignore_org_filter=True,
            )
        logger.info(
            "provision_demo_kb: demo farmacia encolado",
            organization_id=str(organization_id),
            tables=len(tables),
        )
        return True
    except Exception:  # noqa: BLE001
        logger.exception(
            "provision_demo_kb failed; el trial continúa sin datos demo"
        )
        return False
