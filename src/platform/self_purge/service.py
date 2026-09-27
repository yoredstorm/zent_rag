# =============================================================================
# SelfPurgeService — borrado total self-service de una organización
# =============================================================================
# Borra TODA la data de la organización conservando la identidad: usuario,
# membresía, organización, workspaces y suscripción. Deja un único registro
# de auditoría del propio reset.
#
# La allowlist de emails vive en RAG_SELF_PURGE_EMAILS (vacío = deshabilitado).
# Irreversible por diseño: preview before/after + confirmación tipada + step-up
# se exigen en la ruta, nunca aquí.
# =============================================================================
from __future__ import annotations

import re
import shutil
from pathlib import Path
from uuid import UUID

from sqlalchemy import text

from src.core.config import get_settings
from src.core.domain.entities import TenantContext
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.relational_db import PostgresAuditLogRepository
from src.infrastructure.postgres.session import get_async_session
from src.platform.audit.service import AuditLogService

logger = get_logger(__name__)

#: Entidades que sobreviven al borrado aunque tengan organization_id.
_PRESERVE_TABLES = frozenset(
    {
        "organizations",
        "users",
        "memberships",
        "roles",
        "permissions",
        "role_permissions",
        "workspaces",
        "alembic_version",
    }
)

#: Prefijos que sobreviven (suscripción y facturación).
_PRESERVE_PREFIXES = ("subscription", "billing", "plan")

_PREVIEW_TABLE_LIMIT = 30
_MAX_DELETE_PASSES = 6

#: Los nombres vienen de information_schema, pero nunca se interpolan sin validar.
_IDENTIFIER_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


class PurgeInProgressError(ValueError):
    """Otra corrida de self-purge está en curso para la organización."""


class SelfPurgeService:
    """Borrado total por organización. Nunca borra fuera de (organization_id)."""

    def __init__(self, audit: AuditLogService | None = None) -> None:
        self._audit = audit or AuditLogService(PostgresAuditLogRepository())

    # -------------------------------------------------------------------------
    # Allowlist
    # -------------------------------------------------------------------------

    def allowed_emails(self) -> frozenset[str]:
        raw = get_settings().RAG_SELF_PURGE_EMAILS or ""
        return frozenset(part.strip().lower() for part in raw.split(",") if part.strip())

    def allowed(self, email: str | None) -> bool:
        if not email:
            return False
        return email.strip().lower() in self.allowed_emails()

    async def resolve_email(self, user_id: UUID | None) -> str | None:
        if user_id is None:
            return None
        session = await get_async_session()
        try:
            row = (
                await session.execute(
                    text("SELECT email FROM users WHERE id = :uid"), {"uid": user_id}
                )
            ).fetchone()
        finally:
            await session.close()
        if row is None or not getattr(row, "email", None):
            return None
        return str(row.email).strip().lower()

    # -------------------------------------------------------------------------
    # Descubrimiento de tablas objetivo
    # -------------------------------------------------------------------------

    def _is_target(self, table: str) -> bool:
        if not _IDENTIFIER_RE.match(table):
            return False
        if table in _PRESERVE_TABLES:
            return False
        return not table.startswith(_PRESERVE_PREFIXES)

    async def _target_tables(self, session) -> list[str]:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT c.table_name
                    FROM information_schema.columns c
                    JOIN information_schema.tables t
                      ON t.table_schema = c.table_schema
                     AND t.table_name = c.table_name
                    WHERE c.table_schema = 'public'
                      AND c.column_name = 'organization_id'
                      AND t.table_type = 'BASE TABLE'
                    ORDER BY c.table_name
                    """
                )
            )
        ).fetchall()
        return [row.table_name for row in rows if self._is_target(row.table_name)]

    async def _counts(self, session, org: UUID, tables: list[str]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for table in tables:
            try:
                value = (
                    await session.execute(
                        text(
                            f'SELECT COUNT(*) FROM "{table}" WHERE organization_id = :oid'  # noqa: S608 — tabla validada
                        ),
                        {"oid": org},
                    )
                ).scalar()
                counts[table] = int(value or 0)
            except Exception as exc:  # noqa: BLE001 - una tabla ilegible no frena el resto
                await session.rollback()
                logger.warning("self purge count failed", table=table, error=str(exc)[:160])
        return counts

    async def _impact(self, org: UUID) -> dict:
        session = await get_async_session()
        try:
            tables = await self._target_tables(session)
            counts = await self._counts(session, org, tables)
        finally:
            await session.close()
        non_empty = {name: value for name, value in counts.items() if value > 0}
        return {
            "tables": non_empty,
            "tables_total": len(non_empty),
            "total_rows": sum(non_empty.values()),
        }

    async def preview(self, organization_id: UUID) -> dict:
        impact = await self._impact(organization_id)
        ordered = dict(
            sorted(impact["tables"].items(), key=lambda item: item[1], reverse=True)
        )
        top = dict(list(ordered.items())[:_PREVIEW_TABLE_LIMIT])
        return {
            "tables": top,
            "tables_total": impact["tables_total"],
            "truncated": impact["tables_total"] > len(top),
            "total_rows": impact["total_rows"],
            "uploads_bytes": self._dir_size(self._uploads_dir(organization_id)),
            "dsr_artifacts": self._dir_entries(self._dsr_dir(organization_id)),
        }

    # -------------------------------------------------------------------------
    # Orden de borrado (hijos antes que padres)
    # -------------------------------------------------------------------------

    async def _delete_order(self, session, targets: list[str]) -> list[str]:
        target_set = set(targets)
        rows = (
            await session.execute(
                text(
                    """
                    SELECT child.relname AS child, parent.relname AS parent
                    FROM pg_constraint c
                    JOIN pg_class child ON child.oid = c.conrelid
                    JOIN pg_class parent ON parent.oid = c.confrelid
                    JOIN pg_namespace ns ON ns.oid = child.relnamespace
                    WHERE c.contype = 'f' AND ns.nspname = 'public'
                    """
                )
            )
        ).fetchall()

        # Arista child -> parent ("child depende de parent"). Un nodo es
        # borrable cuando nadie depende de él (indegree 0 en esa orientación).
        indegree = {table: 0 for table in targets}
        parents_of: dict[str, list[str]] = {table: [] for table in targets}
        for row in rows:
            child, parent = row.child, row.parent
            if child == parent or child not in target_set or parent not in target_set:
                continue
            indegree[parent] += 1
            parents_of[child].append(parent)

        queue = [table for table in targets if indegree[table] == 0]
        order: list[str] = []
        while queue:
            node = queue.pop(0)
            order.append(node)
            for parent in parents_of[node]:
                indegree[parent] -= 1
                if indegree[parent] == 0:
                    queue.append(parent)

        # Ciclos: el loop de pasadas los resuelve por reintento.
        order.extend(table for table in targets if table not in set(order))
        return order

    # -------------------------------------------------------------------------
    # Ejecución
    # -------------------------------------------------------------------------

    async def execute(self, ctx: TenantContext) -> dict:
        organization_id = ctx.organization_id
        lock_key = f"self-purge:{organization_id}"
        lock_session = await get_async_session()
        locked = False
        try:
            locked = bool(
                (
                    await lock_session.execute(
                        text("SELECT pg_try_advisory_lock(hashtext(:key))"),
                        {"key": lock_key},
                    )
                ).scalar()
            )
            if not locked:
                raise PurgeInProgressError("purge_in_progress")
            return await self._execute_locked(ctx)
        finally:
            if locked:
                try:
                    await lock_session.execute(
                        text("SELECT pg_advisory_unlock(hashtext(:key))"),
                        {"key": lock_key},
                    )
                except Exception as exc:  # noqa: BLE001 - el lock muere con la conexión
                    logger.warning(
                        "self purge unlock failed", error=str(exc)[:160]
                    )
            await lock_session.close()

    async def _execute_locked(self, ctx: TenantContext) -> dict:
        organization_id = ctx.organization_id
        before = await self._impact(organization_id)
        failures: list[dict] = []
        deleted: dict[str, int] = {}

        session = await get_async_session()
        try:
            targets = await self._target_tables(session)
            pending = await self._delete_order(session, targets)
            for _pass in range(_MAX_DELETE_PASSES):
                if not pending:
                    break
                remaining: list[str] = []
                for table in pending:
                    try:
                        await session.execute(
                            text(
                                f'DELETE FROM "{table}" WHERE organization_id = :oid'  # noqa: S608 — tabla validada
                            ),
                            {"oid": organization_id},
                        )
                        await session.commit()
                        count = before["tables"].get(table, 0)
                        if count:
                            deleted[table] = count
                    except Exception as exc:  # noqa: BLE001
                        await session.rollback()
                        if _is_fk_violation(exc):
                            remaining.append(table)
                            continue
                        failures.append({"table": table, "error": str(exc)[:180]})
                        logger.warning(
                            "self purge delete failed",
                            table=table,
                            error=str(exc)[:200],
                        )
                if remaining and len(remaining) == len(pending):
                    failures.extend(
                        {"table": table, "error": "fk_pending_after_retries"}
                        for table in remaining
                    )
                    break
                pending = remaining
        finally:
            await session.close()

        failures.extend(await self._purge_external(organization_id))
        after = await self._impact(organization_id)

        result = {
            "status": "ok" if not failures else "partial",
            "before": before,
            "after": after,
            "deleted": deleted,
            "failures": failures,
        }
        try:
            await self._audit.write(
                ctx,
                "self_purge.executed",
                "organization",
                organization_id,
                metadata={
                    "rows_before": before["total_rows"],
                    "rows_after": after["total_rows"],
                    "tables_before": before["tables_total"],
                    "tables_after": after["tables_total"],
                    "failures": len(failures),
                },
            )
        except Exception as exc:  # noqa: BLE001 - el reset no falla por la auditoría
            logger.warning("self purge audit failed", error=str(exc)[:160])
        return result

    # -------------------------------------------------------------------------
    # Almacenes externos
    # -------------------------------------------------------------------------

    async def _purge_external(self, organization_id: UUID) -> list[dict]:
        failures: list[dict] = []
        try:
            from src.infrastructure.qdrant.vector_store import QdrantVectorStore

            await QdrantVectorStore().delete_by_organization(organization_id)
        except Exception as exc:  # noqa: BLE001
            failures.append({"table": "qdrant", "error": str(exc)[:180]})
            logger.warning("self purge qdrant failed", error=str(exc)[:200])
        for label, path in (
            ("uploads", self._uploads_dir(organization_id)),
            ("dsr", self._dsr_dir(organization_id)),
        ):
            try:
                if path.exists():
                    shutil.rmtree(path)
            except Exception as exc:  # noqa: BLE001
                failures.append({"table": label, "error": str(exc)[:180]})
                logger.warning(
                    "self purge directory failed", target=label, error=str(exc)[:200]
                )
        return failures

    def _uploads_dir(self, organization_id: UUID) -> Path:
        return Path(get_settings().UPLOAD_DIR) / str(organization_id)

    def _dsr_dir(self, organization_id: UUID) -> Path:
        from src.platform.governance.governance import DSR_DIR

        return DSR_DIR / str(organization_id)

    @staticmethod
    def _dir_size(path: Path) -> int:
        if not path.exists():
            return 0
        total = 0
        for item in path.rglob("*"):
            if item.is_file():
                try:
                    total += item.stat().st_size
                except OSError:
                    continue
        return total

    @staticmethod
    def _dir_entries(path: Path) -> int:
        if not path.exists():
            return 0
        try:
            return sum(1 for _ in path.iterdir())
        except OSError:
            return 0


def _is_fk_violation(exc: Exception) -> bool:
    """SQLSTATE 23503 (foreign_key_violation) a través de SQLAlchemy/asyncpg."""
    orig = getattr(exc, "orig", exc)
    for attr in ("sqlstate", "pgcode"):
        if getattr(orig, attr, None) == "23503":
            return True
    return "foreign key" in str(orig).lower()
