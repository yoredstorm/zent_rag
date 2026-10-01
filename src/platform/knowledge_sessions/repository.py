# =============================================================================
# Knowledge Sessions — repositorio Postgres (org-scoped, fail-soft)
# =============================================================================
# Tablas creadas por la migración 136. ``ensure_tables`` las crea de forma
# idempotente para entornos de desarrollo/tests que no corren Alembic.
# =============================================================================
from __future__ import annotations

import json
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.domain.knowledge_session import (
    LearningSession,
    LearningSessionSource,
    LearningSessionStatus,
    SourceLearningStatus,
)
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

_SESSION_COLS = (
    "id, organization_id, workspace_id, title, origin, status, stage, "
    "source_count, available_sources, completed_sources, failed_sources, "
    "metrics, knowledge_delta, totals_before, totals_after, warnings, errors, "
    "started_at, available_at, completed_at, sealed_at, created_at, updated_at"
)

_SOURCE_COLS = (
    "id, organization_id, session_id, source_id, job_id, name, source_type, "
    "status, stage, stats, error, available_at, completed_at, created_at, updated_at"
)

_EVENT_COLS = (
    "seq, id, organization_id, session_id, source_id, event_type, stage, "
    "severity, message, payload, aggregate, created_at"
)

_CREATE_TABLES = [
    """
    CREATE TABLE IF NOT EXISTS knowledge_learning_sessions (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        organization_id UUID NOT NULL,
        workspace_id UUID,
        title VARCHAR(255) NOT NULL DEFAULT '',
        origin VARCHAR(32) NOT NULL DEFAULT 'upload',
        status VARCHAR(24) NOT NULL DEFAULT 'preparing',
        stage VARCHAR(24) NOT NULL DEFAULT 'reading',
        source_count INTEGER NOT NULL DEFAULT 0,
        available_sources INTEGER NOT NULL DEFAULT 0,
        completed_sources INTEGER NOT NULL DEFAULT 0,
        failed_sources INTEGER NOT NULL DEFAULT 0,
        metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
        knowledge_delta JSONB NOT NULL DEFAULT '{}'::jsonb,
        totals_before JSONB NOT NULL DEFAULT '{}'::jsonb,
        totals_after JSONB NOT NULL DEFAULT '{}'::jsonb,
        warnings INTEGER NOT NULL DEFAULT 0,
        errors INTEGER NOT NULL DEFAULT 0,
        started_at TIMESTAMPTZ,
        available_at TIMESTAMPTZ,
        completed_at TIMESTAMPTZ,
        sealed_at TIMESTAMPTZ,
        created_by UUID,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS knowledge_learning_session_sources (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        organization_id UUID NOT NULL,
        session_id UUID NOT NULL,
        source_id UUID,
        job_id UUID,
        name VARCHAR(512) NOT NULL DEFAULT '',
        source_type VARCHAR(32) NOT NULL DEFAULT 'file',
        status VARCHAR(24) NOT NULL DEFAULT 'pending',
        stage VARCHAR(24) NOT NULL DEFAULT 'reading',
        stats JSONB NOT NULL DEFAULT '{}'::jsonb,
        error TEXT,
        available_at TIMESTAMPTZ,
        completed_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS knowledge_learning_session_events (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        seq BIGSERIAL NOT NULL,
        organization_id UUID NOT NULL,
        session_id UUID NOT NULL,
        source_id UUID,
        event_type VARCHAR(60) NOT NULL,
        stage VARCHAR(24),
        severity VARCHAR(10) NOT NULL DEFAULT 'info',
        message TEXT NOT NULL DEFAULT '',
        payload JSONB NOT NULL DEFAULT '{}'::jsonb,
        aggregate BOOLEAN NOT NULL DEFAULT false,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    # Dev/test: bases creadas por una versión previa del DDL.
    "ALTER TABLE knowledge_learning_sessions "
    "ADD COLUMN IF NOT EXISTS sealed_at TIMESTAMPTZ",
]

_CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_knowledge_learning_sessions_org_created "
    "ON knowledge_learning_sessions(organization_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_knowledge_learning_session_sources_session "
    "ON knowledge_learning_session_sources(session_id, created_at ASC)",
    "CREATE INDEX IF NOT EXISTS idx_knowledge_learning_session_sources_job "
    "ON knowledge_learning_session_sources(job_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_knowledge_learning_session_events_seq "
    "ON knowledge_learning_session_events(seq)",
    "CREATE INDEX IF NOT EXISTS idx_knowledge_learning_session_events_session_seq "
    "ON knowledge_learning_session_events(session_id, seq ASC)",
    "CREATE INDEX IF NOT EXISTS idx_knowledge_learning_session_events_org_created "
    "ON knowledge_learning_session_events(organization_id, created_at DESC)",
]


def _json(value: object) -> str:
    return json.dumps(value or {}, default=str)


def _as_dict(value: object) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, json.JSONDecodeError):
            return {}
    return {}


class PostgresKnowledgeSessionRepository:
    """Persistencia de sesiones, fuentes y eventos de aprendizaje."""

    # -------------------------------------------------------------- lifecycle
    async def ensure_tables(self) -> None:
        session: AsyncSession = await get_async_session()
        try:
            for stmt in _CREATE_TABLES:
                await session.execute(text(stmt))
            for stmt in _CREATE_INDEXES:
                try:
                    await session.execute(text(stmt))
                except Exception as exc:  # noqa: BLE001
                    await session.rollback()
                    logger.warning("Knowledge session index skipped", error=str(exc)[:200])
            await session.commit()
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.warning("Knowledge session ensure_tables failed", error=str(exc)[:200])
        finally:
            await session.close()

    # -------------------------------------------------------------- sesiones
    async def create_session(
        self,
        organization_id: UUID,
        *,
        title: str = "",
        origin: str = "upload",
        workspace_id: UUID | None = None,
        created_by: UUID | None = None,
        totals_before: dict | None = None,
    ) -> LearningSession:
        session: AsyncSession = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        f"INSERT INTO knowledge_learning_sessions "  # noqa: S608 — SQL construido solo con columnas constantes
                        f"(organization_id, workspace_id, title, origin, status, stage, "
                        f"totals_before, started_at) "
                        f"VALUES (:oid, :wid, :title, :origin, 'preparing', 'reading', "
                        f"CAST(:before AS jsonb), now()) "
                        f"RETURNING {_SESSION_COLS}"  # noqa: S608 — cols constantes
                    ),
                    {
                        "oid": organization_id,
                        "wid": workspace_id,
                        "title": (title or "")[:255],
                        "origin": (origin or "upload")[:32],
                        "before": _json(totals_before or {}),
                    },
                )
            ).fetchone()
            await session.commit()
            return self._session_row(row)
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def get_session(
        self, organization_id: UUID, session_id: UUID
    ) -> LearningSession | None:
        session: AsyncSession = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        f"SELECT {_SESSION_COLS} FROM knowledge_learning_sessions "  # noqa: S608 — SQL construido solo con columnas constantes
                        "WHERE organization_id = :oid AND id = :sid"
                    ),
                    {"oid": organization_id, "sid": session_id},
                )
            ).fetchone()
            return self._session_row(row) if row else None
        finally:
            await session.close()

    async def seal_session(self, organization_id: UUID, session_id: UUID) -> bool:
        """Marca la sesión como cerrada: no se adjuntarán más fuentes.

        Idempotente. A partir de aquí el finalize puede declarar el aprendizaje
        terminado (``completed``/``partial``) en lugar de dejarlo ``available``.
        """
        session: AsyncSession = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "UPDATE knowledge_learning_sessions SET "
                    "sealed_at = COALESCE(sealed_at, now()), updated_at = now() "
                    "WHERE organization_id = :oid AND id = :sid "
                    "RETURNING sealed_at"
                ),
                {"oid": organization_id, "sid": session_id},
            )
            row = result.fetchone()
            await session.commit()
            return row is not None
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def list_sessions(
        self, organization_id: UUID, *, limit: int = 20
    ) -> list[LearningSession]:
        session: AsyncSession = await get_async_session()
        try:
            rows = (
                await session.execute(
                    text(
                        f"SELECT {_SESSION_COLS} FROM knowledge_learning_sessions "  # noqa: S608 — SQL construido solo con columnas constantes
                        "WHERE organization_id = :oid "
                        "ORDER BY created_at DESC LIMIT :limit"
                    ),
                    {"oid": organization_id, "limit": max(1, min(int(limit), 100))},
                )
            ).fetchall()
            return [self._session_row(row) for row in rows]
        finally:
            await session.close()

    async def find_session_for_job(
        self, organization_id: UUID, job_id: UUID
    ) -> LearningSession | None:
        session: AsyncSession = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        "SELECT s.id, s.organization_id, s.workspace_id, s.title, "
                        "s.origin, s.status, s.stage, s.source_count, "
                        "s.available_sources, s.completed_sources, s.failed_sources, "
                        "s.metrics, s.knowledge_delta, s.totals_before, s.totals_after, "
                        "s.warnings, s.errors, s.started_at, s.available_at, "
                        "s.completed_at, s.created_at, s.updated_at "
                        "FROM knowledge_learning_sessions s "
                        "JOIN knowledge_learning_session_sources ss "
                        "  ON ss.session_id = s.id AND ss.organization_id = s.organization_id "
                        "WHERE ss.organization_id = :oid AND ss.job_id = :jid "
                        "ORDER BY s.created_at DESC LIMIT 1"
                    ),
                    {"oid": organization_id, "jid": job_id},
                )
            ).fetchone()
            return self._session_row(row) if row else None
        finally:
            await session.close()

    async def update_session(self, session_id: UUID, **fields) -> None:
        allowed = {
            "status", "stage", "title", "metrics", "knowledge_delta",
            "totals_before", "totals_after", "warnings", "errors",
            "source_count", "available_sources", "completed_sources",
            "failed_sources", "started_at", "available_at", "completed_at",
        }
        updates = {key: value for key, value in fields.items() if key in allowed}
        if not updates:
            return
        json_keys = {"metrics", "knowledge_delta", "totals_before", "totals_after"}
        params: dict = {"sid": session_id}
        assignments: list[str] = []
        for key, value in updates.items():
            params[key] = _json(value) if key in json_keys else value
            if key in json_keys:
                assignments.append(f"{key} = CAST(:{key} AS jsonb)")
            else:
                assignments.append(f"{key} = :{key}")
        session: AsyncSession = await get_async_session()
        try:
            await session.execute(
                text(
                    "UPDATE knowledge_learning_sessions SET "  # noqa: S608 — SQL construido solo con columnas constantes
                    + ", ".join(assignments)
                    + ", updated_at = now() WHERE id = :sid"  # noqa: S608
                ),
                params,
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    # --------------------------------------------------------------- fuentes
    async def add_source(
        self,
        organization_id: UUID,
        *,
        session_id: UUID,
        source_id: UUID | None,
        job_id: UUID | None,
        name: str,
        source_type: str,
    ) -> LearningSessionSource:
        session: AsyncSession = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        f"INSERT INTO knowledge_learning_session_sources "  # noqa: S608 — SQL construido solo con columnas constantes
                        f"(organization_id, session_id, source_id, job_id, name, "
                        f"source_type, status, stage) "
                        f"VALUES (:oid, :sid, :src, :jid, :name, :stype, 'pending', 'reading') "
                        f"RETURNING {_SOURCE_COLS}"  # noqa: S608
                    ),
                    {
                        "oid": organization_id,
                        "sid": session_id,
                        "src": source_id,
                        "jid": job_id,
                        "name": (name or "")[:512],
                        "stype": (source_type or "file")[:32],
                    },
                )
            ).fetchone()
            await session.execute(
                text(
                    "UPDATE knowledge_learning_sessions SET "
                    "source_count = source_count + 1, updated_at = now() "
                    "WHERE id = :sid"
                ),
                {"sid": session_id},
            )
            await session.commit()
            return self._source_row(row)
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def list_sources(
        self, organization_id: UUID, session_id: UUID
    ) -> list[LearningSessionSource]:
        session: AsyncSession = await get_async_session()
        try:
            rows = (
                await session.execute(
                    text(
                        f"SELECT {_SOURCE_COLS} FROM knowledge_learning_session_sources "  # noqa: S608 — SQL construido solo con columnas constantes
                        "WHERE organization_id = :oid AND session_id = :sid "
                        "ORDER BY created_at ASC"
                    ),
                    {"oid": organization_id, "sid": session_id},
                )
            ).fetchall()
            return [self._source_row(row) for row in rows]
        finally:
            await session.close()

    async def get_source_by_job(
        self, organization_id: UUID, job_id: UUID
    ) -> LearningSessionSource | None:
        session: AsyncSession = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        f"SELECT {_SOURCE_COLS} FROM knowledge_learning_session_sources "  # noqa: S608 — SQL construido solo con columnas constantes
                        "WHERE organization_id = :oid AND job_id = :jid "
                        "ORDER BY created_at DESC LIMIT 1"
                    ),
                    {"oid": organization_id, "jid": job_id},
                )
            ).fetchone()
            return self._source_row(row) if row else None
        finally:
            await session.close()

    async def update_source(self, source_row_id: UUID, **fields) -> None:
        allowed = {
            "status", "stage", "stats", "error", "available_at", "completed_at",
        }
        updates = {key: value for key, value in fields.items() if key in allowed}
        if not updates:
            return
        params: dict = {"rid": source_row_id}
        assignments: list[str] = []
        for key, value in updates.items():
            params[key] = _json(value) if key == "stats" else value
            if key == "stats":
                assignments.append("stats = CAST(:stats AS jsonb)")
            else:
                assignments.append(f"{key} = :{key}")
        session: AsyncSession = await get_async_session()
        try:
            await session.execute(
                text(
                    "UPDATE knowledge_learning_session_sources SET "  # noqa: S608 — SQL construido solo con columnas constantes
                    + ", ".join(assignments)
                    + ", updated_at = now() WHERE id = :rid"  # noqa: S608
                ),
                params,
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def refresh_session_rollup(self, organization_id: UUID, session_id: UUID) -> None:
        """Recalcula métricas y contadores desde las fuentes (fuente de verdad).

        También decide el estado de la sesión:
          - alguna fuente consultable -> ``available``
          - todas consultables y ninguna en curso -> ``optimizing``
          - todas terminadas -> ``completed`` / ``partial``
        """
        session: AsyncSession = await get_async_session()
        try:
            rollup = (
                await session.execute(
                    text(
                        """
                        SELECT
                            COUNT(*) AS total,
                            COUNT(*) FILTER (WHERE status = 'available') AS available,
                            COUNT(*) FILTER (WHERE status = 'completed') AS completed,
                            COUNT(*) FILTER (WHERE status = 'failed') AS failed,
                            COUNT(*) FILTER (WHERE status IN ('learning','pending')) AS active
                        FROM knowledge_learning_session_sources
                        WHERE organization_id = :oid AND session_id = :sid
                        """
                    ),
                    {"oid": organization_id, "sid": session_id},
                )
            ).fetchone()
            metrics_row = (
                await session.execute(
                    text(
                        """
                        SELECT COALESCE(jsonb_object_agg(key, total), '{}'::jsonb) AS metrics
                        FROM (
                            SELECT key, SUM(value::numeric)::bigint AS total
                            FROM knowledge_learning_session_sources ss,
                                 jsonb_each_text(ss.stats)
                            WHERE ss.organization_id = :oid AND ss.session_id = :sid
                            GROUP BY key
                        ) t
                        """
                    ),
                    {"oid": organization_id, "sid": session_id},
                )
            ).fetchone()
            metrics = _as_dict(metrics_row.metrics) if metrics_row else {}

            current = (
                await session.execute(
                    text(
                        "SELECT status, sealed_at FROM knowledge_learning_sessions "
                        "WHERE organization_id = :oid AND id = :sid"
                    ),
                    {"oid": organization_id, "sid": session_id},
                )
            ).fetchone()
            status = str(current.status) if current else "preparing"
            sealed = bool(getattr(current, "sealed_at", None))
            total = int(rollup.total or 0)
            available = int(rollup.available or 0)
            completed = int(rollup.completed or 0)
            failed = int(rollup.failed or 0)
            active = int(rollup.active or 0)

            if total == 0:
                new_status = status
            elif status in ("completed", "partial", "failed", "canceled"):
                new_status = status
            elif active == 0:
                # Todas las fuentes terminaron. Si la sesión aún no se selló
                # (el cliente puede adjuntar más fuentes), queda "available":
                # consultable, sin declarar el aprendizaje terminado.
                if sealed:
                    new_status = "partial" if failed else "completed"
                else:
                    new_status = "available" if available + completed > 0 else "learning"
            elif available + completed > 0:
                new_status = "available"
            else:
                new_status = "learning"

            await session.execute(
                text(
                    """
                    UPDATE knowledge_learning_sessions SET
                        metrics = CAST(:metrics AS jsonb),
                        source_count = :total,
                        available_sources = :available,
                        completed_sources = :completed,
                        failed_sources = :failed,
                        status = :status,
                        available_at = CASE
                            WHEN :available > 0 AND available_at IS NULL THEN now()
                            ELSE available_at END,
                        completed_at = CASE
                            WHEN :terminal_status IN ('completed','partial') AND completed_at IS NULL
                                THEN now()
                            ELSE completed_at END,
                        updated_at = now()
                    WHERE organization_id = :oid AND id = :sid
                    """
                ),
                {
                    "metrics": _json(metrics),
                    "total": total,
                    "available": available,
                    "completed": completed,
                    "failed": failed,
                    "status": new_status,
                    "terminal_status": new_status,
                    "oid": organization_id,
                    "sid": session_id,
                },
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    # --------------------------------------------------------------- eventos
    async def append_event(
        self,
        organization_id: UUID,
        *,
        session_id: UUID,
        event_type: str,
        source_id: UUID | None = None,
        stage: str | None = None,
        severity: str = "info",
        message: str = "",
        payload: dict | None = None,
        aggregate: bool = False,
    ) -> dict:
        event = await self.append_events(
            organization_id,
            events=[
                {
                    "session_id": session_id,
                    "source_id": source_id,
                    "event_type": event_type,
                    "stage": stage,
                    "severity": severity,
                    "message": message,
                    "payload": payload or {},
                    "aggregate": aggregate,
                }
            ],
        )
        return event[0]

    async def append_events(
        self, organization_id: UUID, *, events: list[dict]
    ) -> list[dict]:
        """Inserta un lote de eventos en una sola sentencia con RETURNING.

        Los lotes son chicos (el observer agrega por ventanas), así que se
        construye un INSERT multi-fila con nombres de bind únicos: evita el
        executemany (que no devuelve filas en el dialecto asyncpg).
        """
        if not events:
            return []
        params: dict = {}
        tuples: list[str] = []
        for index, item in enumerate(events):
            params[f"oid{index}"] = organization_id
            params[f"sid{index}"] = item.get("session_id")
            params[f"src{index}"] = item.get("source_id")
            params[f"etype{index}"] = str(item.get("event_type") or "")[:60]
            params[f"stage{index}"] = (
                str(item["stage"])[:24] if item.get("stage") else None
            )
            params[f"sev{index}"] = str(item.get("severity") or "info")[:10]
            params[f"msg{index}"] = str(item.get("message") or "")[:2000]
            params[f"payload{index}"] = _json(item.get("payload"))
            params[f"agg{index}"] = bool(item.get("aggregate"))
            tuples.append(
                f"(:oid{index}, :sid{index}, :src{index}, :etype{index}, "
                f":stage{index}, :sev{index}, :msg{index}, "
                f"CAST(:payload{index} AS jsonb), :agg{index})"
            )
        session: AsyncSession = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "INSERT INTO knowledge_learning_session_events "  # noqa: S608 — SQL construido solo con columnas constantes
                    "(organization_id, session_id, source_id, event_type, stage, "
                    "severity, message, payload, aggregate) VALUES "
                    + ", ".join(tuples)
                    + " RETURNING " + _EVENT_COLS  # noqa: S608 — cols constantes
                ),
                params,
            )
            events_out = [self._event_row(row) for row in result.fetchall()]
            await session.commit()
            return events_out
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def list_events(
        self,
        organization_id: UUID,
        session_id: UUID,
        *,
        since_seq: int = 0,
        source_id: UUID | None = None,
        event_type: str | None = None,
        limit: int = 400,
    ) -> list[dict]:
        session: AsyncSession = await get_async_session()
        try:
            query = (
                f"SELECT {_EVENT_COLS} FROM knowledge_learning_session_events "  # noqa: S608 — SQL construido solo con columnas constantes
                "WHERE organization_id = :oid AND session_id = :sid AND seq > :since"
            )
            params: dict = {
                "oid": organization_id,
                "sid": session_id,
                "since": max(0, int(since_seq)),
                "limit": max(1, min(int(limit), 2000)),
            }
            if source_id is not None:
                query += " AND source_id = :src"
                params["src"] = source_id
            if event_type:
                query += " AND event_type = :etype"
                params["etype"] = event_type
            query += " ORDER BY seq ASC LIMIT :limit"  # noqa: S608
            rows = (await session.execute(text(query), params)).fetchall()
            return [self._event_row(row) for row in rows]
        finally:
            await session.close()

    # ----------------------------------------------------------------- filas
    @staticmethod
    def _session_row(row) -> LearningSession:
        return LearningSession(
            id=row.id,
            organization_id=row.organization_id,
            workspace_id=row.workspace_id,
            title=row.title or "",
            origin=row.origin or "upload",
            status=str(row.status),
            stage=str(row.stage),
            source_count=int(row.source_count or 0),
            available_sources=int(row.available_sources or 0),
            completed_sources=int(row.completed_sources or 0),
            failed_sources=int(row.failed_sources or 0),
            metrics=_as_dict(row.metrics),
            knowledge_delta=_as_dict(row.knowledge_delta),
            totals_before=_as_dict(row.totals_before),
            totals_after=_as_dict(row.totals_after),
            warnings=int(row.warnings or 0),
            errors=int(row.errors or 0),
            started_at=row.started_at,
            available_at=row.available_at,
            completed_at=row.completed_at,
            sealed_at=getattr(row, "sealed_at", None),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _source_row(row) -> LearningSessionSource:
        return LearningSessionSource(
            id=row.id,
            session_id=row.session_id,
            organization_id=row.organization_id,
            source_id=row.source_id,
            job_id=row.job_id,
            name=row.name or "",
            source_type=row.source_type or "file",
            status=str(row.status),
            stage=str(row.stage),
            stats=_as_dict(row.stats),
            error=row.error,
            available_at=row.available_at,
            completed_at=row.completed_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _event_row(row) -> dict:
        return {
            "seq": int(row.seq),
            "id": str(row.id),
            "organization_id": str(row.organization_id),
            "session_id": str(row.session_id),
            "source_id": str(row.source_id) if row.source_id else None,
            "event_type": str(row.event_type),
            "stage": row.stage,
            "severity": str(row.severity or "info"),
            "message": str(row.message or ""),
            "payload": _as_dict(row.payload),
            "aggregate": bool(row.aggregate),
            "created_at": row.created_at.isoformat()
            if isinstance(row.created_at, datetime)
            else str(row.created_at or ""),
        }


__all__ = ["PostgresKnowledgeSessionRepository", "LearningSessionStatus", "SourceLearningStatus"]
