# =============================================================================
# TenantPurgeService — hard delete total de un tenant (Control Center)
# =============================================================================
# Elimina TODO rastro de una organización, incluidos usuarios y facturación:
#   1. filas de las tablas org-scoped (organization_id = org),
#   2. referencias a los usuarios de la org fuera de lo org-scoped,
#   3. referencias a la propia organización (columnas != organization_id),
#   4. núcleo: usuarios, membresías, suscripción y la fila de organizations,
#   5. almacenes externos: Qdrant, sesiones Redis, uploads/DSR en disco y las
#      bases gestionadas zent_cust_* con sus roles.
# Cierra con una verificación explícita de cero referencias huérfanas.
#
# Hay tablas protegidas: nunca se borra una fila de `organizations` que
# referencie a la org borrada (jerarquía entre tenants); si existe, se reporta
# como fallo en vez de eliminar a un tercero.
#
# Irreversible por diseño: preview, confirmación tipada y step-up viven en la
# ruta; este servicio solo ejecuta y reporta.
# =============================================================================
from __future__ import annotations

import re
import shutil
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

from sqlalchemy import text

from src.core.config import get_settings
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

_PREVIEW_TABLE_LIMIT = 30
_MAX_DELETE_PASSES = 6
_MAX_MANAGED_LIST = 50

#: Nombres que llegan de pg_catalog/information_schema; nunca se interpolan sin
#: validar.
_IDENTIFIER_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

#: Borrado forzado del núcleo al final (si el barrido org-scoped no lo logró).
_CORE_DELETES: tuple[tuple[str, str], ...] = (
    ("password_reset_tokens", "user_id"),
    ("users", "organization_id"),
    ("memberships", "organization_id"),
    ("subscriptions", "organization_id"),
    ("organizations", "id"),
)


class TenantPurgeInProgressError(ValueError):
    """Otra purga del mismo tenant está en curso."""


def _quote_ident(name: str) -> str:
    """Identificador de catálogo validado y entre comillas."""
    bare = name.split(".")[-1]
    if not _IDENTIFIER_RE.match(bare):
        raise ValueError(f"unsafe identifier: {name!r}")
    return f'"{bare}"'


def _is_fk_violation(exc: Exception) -> bool:
    """SQLSTATE 23503 (foreign_key_violation) a través de SQLAlchemy/asyncpg."""
    orig = getattr(exc, "orig", exc)
    for attr in ("sqlstate", "pgcode"):
        if getattr(orig, attr, None) == "23503":
            return True
    return "foreign key" in str(orig).lower()


class TenantPurgeService:
    """Hard delete de una organización. Nunca toca filas de otras organizaciones."""

    # -------------------------------------------------------------------------
    # Descubrimiento e impacto
    # -------------------------------------------------------------------------

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
        return [row.table_name for row in rows if _IDENTIFIER_RE.match(row.table_name)]

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
                logger.warning("tenant purge count failed", table=table, error=str(exc)[:160])
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

    async def organization_summary(self, organization_id: UUID) -> dict | None:
        session = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        """
                        SELECT o.id, o.name, o.company_name, o.email, o.status,
                               o.created_at,
                               EXISTS (
                                   SELECT 1 FROM users u
                                   WHERE u.organization_id = o.id
                                     AND (u.is_platform_admin = true
                                          OR EXISTS (
                                              SELECT 1 FROM user_platform_roles upr
                                              WHERE upr.user_id = u.id
                                          ))
                               ) OR EXISTS (
                                   SELECT 1
                                   FROM memberships m
                                   JOIN users u2 ON u2.id = m.user_id
                                   WHERE m.organization_id = o.id
                                     AND (u2.is_platform_admin = true
                                          OR EXISTS (
                                              SELECT 1 FROM user_platform_roles upr2
                                              WHERE upr2.user_id = u2.id
                                          ))
                               ) AS has_platform_admin
                        FROM organizations o
                        WHERE o.id = :oid
                        """
                    ),
                    {"oid": organization_id},
                )
            ).fetchone()
        finally:
            await session.close()
        if row is None:
            return None
        return {
            "id": str(row.id),
            "name": row.name,
            "company_name": row.company_name,
            "email": row.email,
            "status": row.status,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "has_platform_admin": bool(row.has_platform_admin),
            "protected": bool(row.has_platform_admin),
            "protected_reason": ("platform_admin_member" if row.has_platform_admin else None),
        }

    async def _managed_db_inventory(self, organization_id: UUID) -> dict:
        """Bases y roles gestionados derivados del UUID corto de la org."""
        org8 = str(organization_id).replace("-", "")[:8]
        session = await get_async_session()
        try:
            dbs = (
                await session.execute(
                    text("SELECT datname FROM pg_database WHERE datname ~ :pat ORDER BY 1 LIMIT :lim"),
                    {"pat": f"^zent_cust_{org8}_", "lim": _MAX_MANAGED_LIST},
                )
            ).fetchall()
            roles = (
                await session.execute(
                    text("SELECT rolname FROM pg_roles WHERE rolname ~ :pat ORDER BY 1 LIMIT :lim"),
                    {
                        "pat": f"^(zent_schema_admin|zent_query_reader)_{org8}_",
                        "lim": _MAX_MANAGED_LIST,
                    },
                )
            ).fetchall()
        finally:
            await session.close()
        return {
            "databases": [str(r.datname) for r in dbs],
            "roles": [str(r.rolname) for r in roles],
        }

    async def _qdrant_count(self, organization_id: UUID) -> int | None:
        try:
            from src.infrastructure.qdrant.vector_store import QdrantVectorStore

            with self._system_tenant_scope(organization_id):
                return await QdrantVectorStore().count_organization_points(organization_id)
        except Exception as exc:  # noqa: BLE001 - inventario best-effort
            logger.warning("tenant purge qdrant count failed", error=str(exc)[:160])
            return None

    @contextmanager
    def _system_tenant_scope(self, organization_id: UUID):
        """Identidad system de la org objetivo para almacenes con guard tenant.

        La purga corre bajo una sesión de plataforma (tenant_id='platform');
        Qdrant exige que el organization_id operado coincida con el contexto.
        Se publica temporalmente el contexto system de la org y se restaura.
        """
        from src.platform.tenants.context import (
            clear_tenant_context,
            get_tenant_context,
            set_tenant_context,
            system_context,
        )

        previous = get_tenant_context()
        set_tenant_context(system_context(organization_id))
        try:
            yield
        finally:
            if previous is None:
                clear_tenant_context()
            else:
                set_tenant_context(previous)

    async def _external_inventory(self, organization_id: UUID) -> dict:
        managed = await self._managed_db_inventory(organization_id)
        return {
            "qdrant_points": await self._qdrant_count(organization_id),
            "managed_databases": managed["databases"],
            "managed_roles": managed["roles"],
        }

    async def _snapshot(self, organization_id: UUID) -> dict:
        impact = await self._impact(organization_id)
        external = await self._external_inventory(organization_id)
        return {**impact, **external}

    async def preview(self, organization_id: UUID) -> dict:
        snapshot = await self._snapshot(organization_id)
        ordered = dict(sorted(snapshot["tables"].items(), key=lambda item: item[1], reverse=True))
        top = dict(list(ordered.items())[:_PREVIEW_TABLE_LIMIT])
        users = snapshot["tables"].get("users", 0)
        memberships = snapshot["tables"].get("memberships", 0)
        subscriptions = snapshot["tables"].get("subscriptions", 0)
        return {
            "organization": await self.organization_summary(organization_id),
            "tables": top,
            "tables_total": snapshot["tables_total"],
            "truncated": snapshot["tables_total"] > len(top),
            "total_rows": snapshot["total_rows"],
            "users": users,
            "memberships": memberships,
            "subscriptions": subscriptions,
            "qdrant_points": snapshot["qdrant_points"],
            "managed_databases": snapshot["managed_databases"],
            "managed_roles": snapshot["managed_roles"],
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

    async def execute(self, organization_id: UUID) -> dict:
        lock_key = f"tenant-purge:{organization_id}"
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
                raise TenantPurgeInProgressError("purge_in_progress")
            return await self._execute_locked(organization_id)
        finally:
            if locked:
                try:
                    await lock_session.execute(
                        text("SELECT pg_advisory_unlock(hashtext(:key))"),
                        {"key": lock_key},
                    )
                except Exception as exc:  # noqa: BLE001 - el lock muere con la conexión
                    logger.warning("tenant purge unlock failed", error=str(exc)[:160])
            await lock_session.close()

    async def _execute_locked(self, organization_id: UUID) -> dict:
        before = await self._snapshot(organization_id)
        failures: list[dict] = []
        deleted: dict[str, int] = {}

        session = await get_async_session()
        user_ids: list[UUID] = []
        try:
            user_rows = (
                await session.execute(
                    text("SELECT id FROM users WHERE organization_id = :oid"),
                    {"oid": organization_id},
                )
            ).fetchall()
            user_ids = [row.id for row in user_rows]

            targets = await self._target_tables(session)
            pending = await self._delete_order(session, targets)
            await self._delete_org_scoped(session, organization_id, before["tables"], pending, deleted, failures)
            await self._cleanup_refs(session, "users", user_ids, deleted, failures)
            await self._cleanup_refs(
                session,
                "organizations",
                [organization_id],
                deleted,
                failures,
                exclude_col="organization_id",
            )
            await self._delete_core(session, organization_id, user_ids, deleted, failures)
        finally:
            await session.close()

        failures.extend(await self._purge_external(organization_id, user_ids))

        after = await self._impact(organization_id)
        verification = await self._verify(organization_id, user_ids, after)

        status = "ok" if not failures and verification["clean"] else "partial"
        return {
            "status": status,
            "organization_id": str(organization_id),
            "before": before,
            "after": after,
            "deleted": deleted,
            "verification": verification,
            "failures": failures,
        }

    async def _delete_org_scoped(
        self,
        session,
        organization_id: UUID,
        before_counts: dict[str, int],
        pending: list[str],
        deleted: dict[str, int],
        failures: list[dict],
    ) -> None:
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
                    count = before_counts.get(table, 0)
                    if count:
                        deleted[table] = count
                except Exception as exc:  # noqa: BLE001
                    await session.rollback()
                    if _is_fk_violation(exc):
                        remaining.append(table)
                        continue
                    failures.append({"table": table, "error": str(exc)[:180]})
                    logger.warning(
                        "tenant purge delete failed",
                        table=table,
                        error=str(exc)[:200],
                    )
            if remaining and len(remaining) == len(pending):
                failures.extend({"table": table, "error": "fk_pending_after_retries"} for table in remaining)
                break
            pending = remaining

    async def _fk_refs(self, session, parent: str) -> list[tuple[str, str, str, bool]]:
        """(child, col, action, nullable) para cada FK que apunta a `parent`."""
        rows = (
            await session.execute(
                text(
                    """
                    SELECT c.conrelid::regclass::text AS child,
                           a.attname AS col,
                           c.confdeltype AS action,
                           (NOT a.attnotnull) AS nullable
                    FROM pg_constraint c
                    JOIN pg_attribute a
                      ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey)
                    WHERE c.contype = 'f' AND c.confrelid = CAST(:parent AS regclass)
                      AND a.attnum = ANY(c.conkey)
                    ORDER BY 1, 2
                    """
                ),
                {"parent": parent},
            )
        ).fetchall()
        seen: dict[tuple[str, str], tuple[str, str, str, bool]] = {}
        for row in rows:
            key = (row.child, row.col)
            seen[key] = (row.child, row.col, row.action, bool(row.nullable))
        return list(seen.values())

    async def _cleanup_refs(
        self,
        session,
        parent: str,
        ids: list[UUID],
        deleted: dict[str, int],
        failures: list[dict],
        *,
        exclude_col: str | None = None,
    ) -> None:
        if not ids:
            return
        placeholders = ", ".join(f":u{i}" for i in range(len(ids)))
        params = {f"u{i}": uid for i, uid in enumerate(ids)}
        for child, col, action, nullable in await self._fk_refs(session, parent):
            if exclude_col is not None and col == exclude_col:
                continue
            bare_child = child.split(".")[-1]
            try:
                quoted_child = _quote_ident(child)
                quoted_col = _quote_ident(col)
                if nullable and action == "n":
                    await session.execute(
                        text(
                            f"UPDATE {quoted_child} SET {quoted_col} = NULL "  # noqa: S608 — identificadores validados
                            f"WHERE {quoted_col} IN ({placeholders})"
                        ),
                        params,
                    )
                elif bare_child == "organizations":
                    # Nunca eliminar otra organización: si alguien la referencia,
                    # se reporta en vez de borrar un tercero.
                    count = (
                        await session.execute(
                            text(
                                f"SELECT COUNT(*) FROM {quoted_child} "  # noqa: S608 — identificadores validados
                                f"WHERE {quoted_col} IN ({placeholders})"
                            ),
                            params,
                        )
                    ).scalar()
                    if int(count or 0) > 0 and f"{child}.{col}" not in deleted:
                        failures.append({"table": f"{child}.{col}", "error": "protected_org_ref"})
                    continue
                else:
                    await session.execute(
                        text(
                            f"DELETE FROM {quoted_child} "  # noqa: S608 — identificadores validados
                            f"WHERE {quoted_col} IN ({placeholders})"
                        ),
                        params,
                    )
                await session.commit()
                label = f"{child}.{col}"
                if label not in deleted:
                    # El rowcount exacto no es crítico: se registra la referencia
                    # atendida para el reporte.
                    deleted[label] = 0
            except Exception as exc:  # noqa: BLE001
                await session.rollback()
                failures.append({"table": f"{child}.{col}", "error": str(exc)[:180]})
                logger.warning(
                    "tenant purge ref cleanup failed",
                    ref=f"{child}.{col}",
                    error=str(exc)[:200],
                )

    async def _delete_core(
        self,
        session,
        organization_id: UUID,
        user_ids: list[UUID],
        deleted: dict[str, int],
        failures: list[dict],
    ) -> None:
        for table, column in _CORE_DELETES:
            try:
                if table == "password_reset_tokens":
                    if not user_ids:
                        continue
                    placeholders = ", ".join(f":u{i}" for i in range(len(user_ids)))
                    params = {f"u{i}": uid for i, uid in enumerate(user_ids)}
                    result = await session.execute(
                        text(
                            f'DELETE FROM "password_reset_tokens" WHERE "user_id" IN ({placeholders})'  # noqa: S608 — tabla fija
                        ),
                        params,
                    )
                elif column == "id":
                    result = await session.execute(
                        text(f'DELETE FROM "{table}" WHERE "id" = :oid'),  # noqa: S608 — tabla fija
                        {"oid": organization_id},
                    )
                else:
                    result = await session.execute(
                        text(
                            f'DELETE FROM "{table}" WHERE "organization_id" = :oid'  # noqa: S608 — tabla fija
                        ),
                        {"oid": organization_id},
                    )
                await session.commit()
                if result.rowcount:
                    deleted[table] = max(deleted.get(table, 0), int(result.rowcount))
            except Exception as exc:  # noqa: BLE001
                await session.rollback()
                failures.append({"table": table, "error": str(exc)[:180]})
                logger.warning(
                    "tenant purge core delete failed",
                    table=table,
                    error=str(exc)[:200],
                )

    # -------------------------------------------------------------------------
    # Almacenes externos
    # -------------------------------------------------------------------------

    async def _purge_external(self, organization_id: UUID, user_ids: list[UUID]) -> list[dict]:
        failures: list[dict] = []

        try:
            from src.infrastructure.qdrant.vector_store import QdrantVectorStore

            with self._system_tenant_scope(organization_id):
                await QdrantVectorStore().delete_by_organization(organization_id)
        except Exception as exc:  # noqa: BLE001
            failures.append({"target": "qdrant", "error": str(exc)[:180]})
            logger.warning("tenant purge qdrant failed", error=str(exc)[:200])

        try:
            from src.platform.auth.session import revoke_user_sessions

            for uid in user_ids:
                try:
                    await revoke_user_sessions(uid)
                except Exception as exc:  # noqa: BLE001
                    failures.append({"target": f"sessions:{uid}", "error": str(exc)[:180]})
        except Exception as exc:  # noqa: BLE001
            failures.append({"target": "sessions", "error": str(exc)[:180]})

        for label, path in (
            ("uploads", self._uploads_dir(organization_id)),
            ("dsr", self._dsr_dir(organization_id)),
        ):
            try:
                if path.exists():
                    shutil.rmtree(path)
            except Exception as exc:  # noqa: BLE001
                failures.append({"target": label, "error": str(exc)[:180]})
                logger.warning("tenant purge directory failed", target=label, error=str(exc)[:200])

        try:
            inventory = await self._managed_db_inventory(organization_id)
        except Exception as exc:  # noqa: BLE001
            failures.append({"target": "managed_db", "error": str(exc)[:180]})
            return failures

        provider = None
        for db_name in inventory["databases"]:
            try:
                if provider is None:
                    from src.platform.managed_db.local_postgres import (
                        LocalPostgresProvider,
                    )

                    provider = LocalPostgresProvider()
                await provider.delete_database(db_name)
            except Exception as exc:  # noqa: BLE001
                failures.append({"target": f"database:{db_name}", "error": str(exc)[:180]})
        for role_name in inventory["roles"]:
            try:
                await self._drop_role(role_name)
            except Exception as exc:  # noqa: BLE001
                failures.append({"target": f"role:{role_name}", "error": str(exc)[:180]})
        return failures

    async def _drop_role(self, role_name: str) -> None:
        if not _IDENTIFIER_RE.match(role_name):
            raise ValueError(f"unsafe role name: {role_name!r}")
        session = await get_async_session()
        try:
            await session.execute(text("COMMIT"))
            await session.execute(text(f'DROP ROLE IF EXISTS "{role_name}"'))
        finally:
            await session.close()

    # -------------------------------------------------------------------------
    # Verificación final
    # -------------------------------------------------------------------------

    async def _count_refs(
        self,
        session,
        parent: str,
        ids: list[UUID],
        *,
        exclude_col: str | None = None,
    ) -> int:
        if not ids:
            return 0
        placeholders = ", ".join(f":u{i}" for i in range(len(ids)))
        params = {f"u{i}": uid for i, uid in enumerate(ids)}
        total = 0
        for child, col, _action, _nullable in await self._fk_refs(session, parent):
            if exclude_col is not None and col == exclude_col:
                continue
            try:
                value = (
                    await session.execute(
                        text(
                            f"SELECT COUNT(*) FROM {_quote_ident(child)} "  # noqa: S608 — identificadores validados
                            f"WHERE {_quote_ident(col)} IN ({placeholders})"
                        ),
                        params,
                    )
                ).scalar()
                total += int(value or 0)
            except Exception:  # noqa: BLE001 - conteo best-effort
                await session.rollback()
        return total

    async def _verify(self, organization_id: UUID, user_ids: list[UUID], after: dict) -> dict:
        session = await get_async_session()
        try:
            user_refs = await self._count_refs(session, "users", user_ids)
            org_refs = await self._count_refs(
                session,
                "organizations",
                [organization_id],
                exclude_col="organization_id",
            )
        finally:
            await session.close()

        qdrant_points = await self._qdrant_count(organization_id)
        try:
            managed = await self._managed_db_inventory(organization_id)
        except Exception:  # noqa: BLE001
            managed = {"databases": [], "roles": []}

        clean = (
            after["total_rows"] == 0
            and user_refs == 0
            and org_refs == 0
            and qdrant_points == 0
            and not managed["databases"]
            and not managed["roles"]
        )
        return {
            "org_rows": after["total_rows"],
            "user_refs": user_refs,
            "org_refs": org_refs,
            "qdrant_points": qdrant_points,
            "managed_databases": managed["databases"],
            "managed_roles": managed["roles"],
            "clean": clean,
        }

    # -------------------------------------------------------------------------
    # Rutas locales
    # -------------------------------------------------------------------------

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
