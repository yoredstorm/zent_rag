# =============================================================================
# Knowledge Platform Repositories — Postgres (raw SQL)
# =============================================================================
# ingestion_jobs es la fuente de verdad del estado de sync; Redis solo despierta
# al worker. Todos los métodos están scoped por organization_id (o toman el
# job/source por ID con verificación de pertenencia).
# =============================================================================
from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import text

from src.core.domain.entities import (
    IngestionJob,
    IngestionJobStatus,
    KbSource,
    SyncState,
)
from src.core.ports import (
    DocumentRegistryRepository,
    IngestionJobRepository,
    SourceRepository,
    SyncStateRepository,
)
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)


# -----------------------------------------------------------------------------
# Fuentes (kb_sources)
# -----------------------------------------------------------------------------
class PostgresSourceRepository(SourceRepository):

    _COLS = (
        "id, organization_id, knowledge_base_id, name, type, config_json, "
        "status, created_at"
    )

    @staticmethod
    def _row_to_source(row) -> KbSource:
        return KbSource(
            id=row.id,
            organization_id=row.organization_id,
            knowledge_base_id=row.knowledge_base_id,
            name=row.name,
            type=row.type,
            config_json=row.config_json if isinstance(row.config_json, dict) else {},
            status=row.status,
            created_at=row.created_at,
        )

    async def list_sources(
        self, organization_id: UUID, knowledge_base_id: UUID | None = None
    ) -> list[KbSource]:
        session = await get_async_session()
        try:
            query = (
                f"SELECT {self._COLS} FROM kb_sources "
                "WHERE organization_id = :oid "
            )
            params: dict = {"oid": organization_id}
            if knowledge_base_id is not None:
                query += "AND knowledge_base_id = :kid "
                params["kid"] = knowledge_base_id
            query += "ORDER BY created_at DESC"
            result = await session.execute(text(query), params)
            return [self._row_to_source(row) for row in result.fetchall()]
        finally:
            await session.close()

    async def get_source(
        self, organization_id: UUID, source_id: UUID
    ) -> KbSource | None:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    f"SELECT {self._COLS} FROM kb_sources "
                    "WHERE id = :sid AND organization_id = :oid"
                ),
                {"sid": source_id, "oid": organization_id},
            )
            row = result.fetchone()
            if row is None:
                return None
            return self._row_to_source(row)
        finally:
            await session.close()

    async def create_source(
        self,
        organization_id: UUID,
        name: str,
        source_type: str,
        knowledge_base_id: UUID | None = None,
        config_json: dict | None = None,
    ) -> KbSource:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "INSERT INTO kb_sources (id, organization_id, knowledge_base_id, "
                    "name, type, config_json, status) "
                    "VALUES (uuid_generate_v4(), :oid, :kid, :name, :type, "
                    "CAST(:config AS jsonb), 'created') "
                    f"RETURNING {self._COLS}"
                ),
                {
                    "oid": organization_id,
                    "kid": knowledge_base_id,
                    "name": name,
                    "type": source_type,
                    "config": json.dumps(config_json or {}),
                },
            )
            row = result.fetchone()
            await session.commit()
            return self._row_to_source(row)
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def update_source(
        self, organization_id: UUID, source_id: UUID, **fields
    ) -> KbSource:
        allowed = {"name", "config_json", "status", "knowledge_base_id"}
        updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
        session = await get_async_session()
        try:
            if updates:
                if "config_json" in updates:
                    updates["config_json"] = json.dumps(updates["config_json"])
                set_clauses = ", ".join(f"{k} = :{k}" for k in updates)
                params = {"oid": organization_id, "sid": source_id, **updates}
                await session.execute(
                    text(
                        f"UPDATE kb_sources SET {set_clauses}, updated_at = NOW() "
                        "WHERE id = :sid AND organization_id = :oid"
                    ),
                    params,
                )
                await session.commit()
            source = await self.get_source(organization_id, source_id)
            if source is None:
                raise ValueError(f"Source {source_id} not found")
            return source
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def delete_source(self, organization_id: UUID, source_id: UUID) -> None:
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    "DELETE FROM kb_sources WHERE id = :sid AND organization_id = :oid"
                ),
                {"sid": source_id, "oid": organization_id},
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# -----------------------------------------------------------------------------
# Jobs (ingestion_jobs)
# -----------------------------------------------------------------------------
class PostgresIngestionJobRepository(IngestionJobRepository):

    _COLS = (
        "id, organization_id, knowledge_base_id, source_id, job_type, status, "
        "progress, attempts, max_attempts, records_processed, records_failed, "
        "error_summary, cursor_snapshot, started_at, completed_at, retry_at, "
        "created_at, updated_at"
    )

    @staticmethod
    def _row_to_job(row) -> IngestionJob:
        return IngestionJob(
            id=row.id,
            organization_id=row.organization_id,
            knowledge_base_id=row.knowledge_base_id,
            source_id=row.source_id,
            job_type=row.job_type,
            status=IngestionJobStatus(row.status),
            progress=row.progress or 0,
            attempts=row.attempts or 0,
            max_attempts=row.max_attempts or 3,
            records_processed=row.records_processed or 0,
            records_failed=row.records_failed or 0,
            error_summary=row.error_summary if isinstance(row.error_summary, dict) else {},
            cursor_snapshot=row.cursor_snapshot if isinstance(row.cursor_snapshot, dict) else None,
            started_at=row.started_at,
            completed_at=row.completed_at,
            retry_at=row.retry_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def create_job(
        self,
        organization_id: UUID,
        job_type: str,
        source_id: UUID | None = None,
        knowledge_base_id: UUID | None = None,
        max_attempts: int = 3,
        training_run_id: UUID | None = None,
    ) -> IngestionJob:
        session = await get_async_session()
        try:
            job_id = uuid4()
            result = await session.execute(
                text(
                    "INSERT INTO ingestion_jobs (id, organization_id, knowledge_base_id, "
                    "source_id, job_type, max_attempts, training_run_id) "
                    "VALUES (:id, :oid, :kid, :sid, :jtype, :max_attempts, :trun) "
                    f"RETURNING {self._COLS}"
                ),
                {
                    "id": job_id,
                    "oid": organization_id,
                    "kid": knowledge_base_id,
                    "sid": source_id,
                    "jtype": job_type,
                    "max_attempts": max_attempts,
                    "trun": training_run_id,
                },
            )
            row = result.fetchone()
            await session.commit()
            return self._row_to_job(row)
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def get_job(
        self, organization_id: UUID | None, job_id: UUID
    ) -> IngestionJob | None:
        session = await get_async_session()
        try:
            query = f"SELECT {self._COLS} FROM ingestion_jobs WHERE id = :jid "
            params: dict = {"jid": job_id}
            if organization_id is not None:
                query += "AND organization_id = :oid "
                params["oid"] = organization_id
            result = await session.execute(text(query), params)
            row = result.fetchone()
            if row is None:
                return None
            return self._row_to_job(row)
        finally:
            await session.close()

    async def update_job(self, job_id: UUID, **fields) -> IngestionJob | None:
        allowed = {
            "status", "progress", "attempts", "records_processed", "records_failed",
            "error_summary", "cursor_snapshot", "started_at", "completed_at", "retry_at",
        }
        updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
        session = await get_async_session()
        try:
            if updates:
                for key in ("error_summary", "cursor_snapshot"):
                    if key in updates:
                        updates[key] = json.dumps(updates[key] or {})
                set_clauses = ", ".join(f"{k} = :{k}" for k in updates)
                await session.execute(
                    text(
                        f"UPDATE ingestion_jobs SET {set_clauses}, updated_at = NOW() "
                        "WHERE id = :jid"
                    ),
                    {"jid": job_id, **updates},
                )
                await session.commit()
            result = await session.execute(
                text(f"SELECT {self._COLS} FROM ingestion_jobs WHERE id = :jid"),
                {"jid": job_id},
            )
            row = result.fetchone()
            if row is None:
                return None
            return self._row_to_job(row)
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def record_error(self, job_id: UUID, attempt: int, error: str) -> None:
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    "INSERT INTO ingestion_job_errors (job_id, attempt, error) "
                    "VALUES (:jid, :attempt, :error)"
                ),
                {"jid": job_id, "attempt": attempt, "error": error},
            )
            await session.commit()
        except Exception:
            await session.rollback()
        finally:
            await session.close()

    async def list_jobs(
        self,
        organization_id: UUID,
        *,
        status: str | None = None,
        source_id: UUID | None = None,
        knowledge_base_id: UUID | None = None,
        limit: int = 50,
    ) -> list[IngestionJob]:
        session = await get_async_session()
        try:
            query = (
                f"SELECT {self._COLS} FROM ingestion_jobs "
                "WHERE organization_id = :oid "
            )
            params: dict = {"oid": organization_id, "limit": limit}
            if status:
                query += "AND status = :status "
                params["status"] = status
            if source_id is not None:
                query += "AND source_id = :sid "
                params["sid"] = source_id
            if knowledge_base_id is not None:
                query += "AND knowledge_base_id = :kid "
                params["kid"] = knowledge_base_id
            query += "ORDER BY created_at DESC LIMIT :limit"
            result = await session.execute(text(query), params)
            return [self._row_to_job(row) for row in result.fetchall()]
        finally:
            await session.close()

    async def list_due_jobs(self, now, limit: int = 50) -> list[IngestionJob]:
        """Jobs listos para (re)intento: pending, o failed con retry_at vencido."""
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    f"SELECT {self._COLS} FROM ingestion_jobs "
                    "WHERE (status = 'pending' OR (status = 'failed' AND retry_at <= :now)) "
                    "ORDER BY created_at ASC LIMIT :limit "
                    "FOR UPDATE SKIP LOCKED"
                ),
                {"now": now, "limit": limit},
            )
            return [self._row_to_job(row) for row in result.fetchall()]
        finally:
            await session.close()


# -----------------------------------------------------------------------------
# Sync state
# -----------------------------------------------------------------------------
class PostgresSyncStateRepository(SyncStateRepository):

    async def get_state(self, source_id: UUID) -> SyncState | None:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "SELECT source_id, cursor_json, last_success_at, last_error, "
                    "last_processed_count FROM source_sync_state WHERE source_id = :sid"
                ),
                {"sid": source_id},
            )
            row = result.fetchone()
            if row is None:
                return None
            return SyncState(
                source_id=row.source_id,
                cursor=row.cursor_json if isinstance(row.cursor_json, dict) else None,
                last_success_at=row.last_success_at,
                last_error=row.last_error,
                last_processed_count=row.last_processed_count or 0,
            )
        finally:
            await session.close()

    async def save_state(
        self,
        source_id: UUID,
        *,
        cursor: dict | None = None,
        error: str | None = None,
        processed_count: int = 0,
        success: bool = True,
    ) -> None:
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    "INSERT INTO source_sync_state (source_id, cursor_json, last_success_at, "
                    "last_error, last_processed_count, updated_at) "
                    "VALUES (:sid, CAST(:cursor AS jsonb), :success_at, :error, :count, NOW()) "
                    "ON CONFLICT (source_id) DO UPDATE SET "
                    "cursor_json = CAST(:cursor2 AS jsonb), "
                    "last_success_at = :success_at2, "
                    "last_error = :error2, "
                    "last_processed_count = :count2, "
                    "updated_at = NOW()"
                ),
                {
                    "sid": source_id,
                    "cursor": json.dumps(cursor) if cursor else "{}",
                    "cursor2": json.dumps(cursor) if cursor else "{}",
                    "success_at": datetime.now(timezone.utc) if success else None,
                    "success_at2": datetime.now(timezone.utc) if success else None,
                    "error": error,
                    "error2": error,
                    "count": processed_count,
                    "count2": processed_count,
                },
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# -----------------------------------------------------------------------------
# Document registry (source_documents)
# -----------------------------------------------------------------------------
class PostgresDocumentRegistryRepository(DocumentRegistryRepository):

    async def upsert_document(
        self,
        organization_id: UUID,
        source_id: UUID,
        external_id: str,
        document_id: UUID,
        content_hash: str,
    ) -> None:
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    "INSERT INTO source_documents (organization_id, source_id, external_id, "
                    "document_id, content_hash, status, last_seen_at) "
                    "VALUES (:oid, :sid, :ext, :did, :hash, 'active', NOW()) "
                    "ON CONFLICT (source_id, external_id) DO UPDATE SET "
                    "document_id = :did2, content_hash = :hash2, status = 'active', "
                    "last_seen_at = NOW()"
                ),
                {
                    "oid": organization_id,
                    "sid": source_id,
                    "ext": external_id,
                    "did": document_id,
                    "did2": document_id,
                    "hash": content_hash,
                    "hash2": content_hash,
                },
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def mark_missing_deleted(
        self, source_id: UUID, seen_external_ids: set[str]
    ) -> list[UUID]:
        """Marca 'deleted' los registry rows cuyo external_id ya no existe.

        El external_id en registry incluye sufijo '#<chunk>'; se compara por
        prefijo. Retorna los document_ids (puntos Qdrant) a borrar.
        """
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "SELECT external_id, document_id FROM source_documents "
                    "WHERE source_id = :sid AND status = 'active' "
                    "FOR UPDATE"
                ),
                {"sid": source_id},
            )
            rows = result.fetchall()
            stale_ids: list[UUID] = []
            stale_externals: list[str] = []
            for row in rows:
                base_external = row.external_id.rsplit("#", 1)[0]
                if base_external not in seen_external_ids:
                    stale_ids.append(row.document_id)
                    stale_externals.append(row.external_id)
            if stale_externals:
                await session.execute(
                    text(
                        "UPDATE source_documents SET status = 'deleted' "
                        "WHERE source_id = :sid AND external_id = ANY(:exts)"
                    ),
                    {"sid": source_id, "exts": stale_externals},
                )
                await session.commit()
            return stale_ids
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def delete_source_documents(self, source_id: UUID) -> None:
        session = await get_async_session()
        try:
            await session.execute(
                text("DELETE FROM source_documents WHERE source_id = :sid"),
                {"sid": source_id},
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
