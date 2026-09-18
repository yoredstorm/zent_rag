# =============================================================================
# Local PostgreSQL provider — CREATE DATABASE on the same cluster (dev)
# =============================================================================
from __future__ import annotations

import secrets
import string
from uuid import UUID

from sqlalchemy import text

from src.core.config import get_settings
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)


def _ident(prefix: str, org: UUID, workspace: UUID) -> str:
    return f"{prefix}_{str(org).replace('-', '')[:8]}_{str(workspace).replace('-', '')[:8]}"


def _password() -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(24))


def _sql_literal(value: str) -> str:
    """Literal SQL seguro: CREATE/ALTER ROLE no aceptan bind params en PASSWORD."""
    return "'" + str(value).replace("'", "''") + "'"


class LocalPostgresProvider:
    """Dev provider. Production adapters (RDS, Neon, …) must implement the Protocol."""

    async def create_database(
        self, organization_id: UUID, workspace_id: UUID, *, size_mb: int
    ) -> dict:
        settings = get_settings()
        db_name = _ident("zent_cust", organization_id, workspace_id)
        admin_role = _ident("zent_schema_admin", organization_id, workspace_id)
        reader_role = _ident("zent_query_reader", organization_id, workspace_id)
        admin_pw = _password()
        reader_pw = _password()
        session = await get_async_session()
        try:
            await session.execute(text("COMMIT"))
            await session.execute(text(f'CREATE DATABASE "{db_name}"'))
            for role, pw in ((admin_role, admin_pw), (reader_role, reader_pw)):
                try:
                    await session.execute(
                        text(
                            f'CREATE ROLE "{role}" LOGIN PASSWORD {_sql_literal(pw)}'  # noqa: S608 (rol derivado de UUIDs, password literal escapado)
                        )
                    )
                except Exception as create_exc:  # noqa: BLE001
                    logger.warning(
                        "CREATE ROLE failed, trying ALTER",
                        role=role,
                        error=str(create_exc)[:160],
                    )
                    await session.rollback()
                    try:
                        await session.execute(text("COMMIT"))
                    except Exception:  # noqa: BLE001
                        pass
                    try:
                        await session.execute(
                            text(
                                f'ALTER ROLE "{role}" WITH LOGIN PASSWORD {_sql_literal(pw)}'  # noqa: S608 (rol derivado de UUIDs, password literal escapado)
                            )
                        )
                    except Exception as role_exc:  # noqa: BLE001
                        logger.warning("CREATE ROLE skipped", role=role, error=str(role_exc)[:160])
            try:
                await session.execute(
                    text(f'GRANT CONNECT ON DATABASE "{db_name}" TO "{admin_role}", "{reader_role}"')
                )
            except Exception as grant_exc:  # noqa: BLE001
                logger.warning("GRANT CONNECT skipped", error=str(grant_exc)[:160])
        except Exception as exc:  # noqa: BLE001
            logger.warning("CREATE DATABASE skipped/failed", error=str(exc)[:200])
        finally:
            await session.close()
        # Postgres 15+: el schema public ya no da CREATE a PUBLIC. El admin de
        # schema queda como owner y el reader con USAGE (dentro de la DB nueva).
        await self._grant_schema_privileges(db_name, admin_role, reader_role)
        return {
            "provider": "local",
            "db_name": db_name,
            "host": settings.POSTGRES_HOST,
            "port": settings.POSTGRES_PORT,
            "schema_admin_user": admin_role,
            "query_reader_user": reader_role,
            "schema_admin_password": admin_pw,
            "query_reader_password": reader_pw,
            "size_mb": size_mb,
        }

    async def _grant_schema_privileges(
        self, db_name: str, admin_role: str, reader_role: str
    ) -> None:
        """Owner del schema public para el admin y USAGE para el reader.

        Se conecta a la DB nueva con las credenciales de plataforma (superuser):
        sin esto, Postgres 15+ niega CREATE en public al rol de schema.
        """
        from urllib.parse import quote_plus

        from sqlalchemy.ext.asyncio import create_async_engine

        settings = get_settings()
        password = settings.POSTGRES_PASSWORD
        password_value = (
            password.get_secret_value() if hasattr(password, "get_secret_value") else str(password)
        )
        dsn = (
            f"postgresql+asyncpg://{quote_plus(str(settings.POSTGRES_USER))}:"
            f"{quote_plus(password_value)}"
            f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{db_name}"
        )
        engine = create_async_engine(dsn, pool_size=1, max_overflow=0)
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text(f'ALTER SCHEMA public OWNER TO "{admin_role}"')  # noqa: S608 (rol derivado de UUIDs)
                )
                await conn.execute(
                    text(f'GRANT USAGE ON SCHEMA public TO "{reader_role}"')  # noqa: S608 (rol derivado de UUIDs)
                )
                # El reader (SQL/joins del usuario y agentes) debe poder leer las
                # tablas materializadas: default privileges para las futuras y
                # SELECT sobre las existentes.
                await conn.execute(
                    text(
                        f'ALTER DEFAULT PRIVILEGES FOR ROLE "{admin_role}" IN SCHEMA public '
                        f'GRANT SELECT ON TABLES TO "{reader_role}"'  # noqa: S608 (roles derivados de UUIDs)
                    )
                )
                await conn.execute(
                    text(
                        f'GRANT SELECT ON ALL TABLES IN SCHEMA public TO "{reader_role}"'  # noqa: S608 (rol derivado de UUIDs)
                    )
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "managed schema grants failed",
                database=db_name,
                error=str(exc)[:200],
            )
        finally:
            await engine.dispose()

    async def delete_database(self, database_id: str) -> None:
        session = await get_async_session()
        try:
            await session.execute(text("COMMIT"))
            await session.execute(text(f'DROP DATABASE IF EXISTS "{database_id}"'))
        except Exception as exc:  # noqa: BLE001
            logger.warning("DROP DATABASE skipped", error=str(exc)[:200])
        finally:
            await session.close()

    async def rotate_credentials(self, database_id: str) -> dict:
        return await self.create_readonly_user(database_id)

    async def create_readonly_user(self, database_id: str) -> dict:
        return {"user": f"zent_query_reader_{database_id[-8:]}", "password": _password()}

    async def create_schema_admin_user(self, database_id: str) -> dict:
        return {"user": f"zent_schema_admin_{database_id[-8:]}", "password": _password()}

    async def get_connection_info(self, database_id: str) -> dict:
        settings = get_settings()
        return {
            "host": settings.POSTGRES_HOST,
            "port": settings.POSTGRES_PORT,
            "database": database_id,
        }

    async def health_check(self, database_id: str) -> dict:
        return {"status": "ok", "database": database_id}

    async def backup_status(self, database_id: str) -> dict:
        return {"restore_ready": False, "last_backup_at": None, "retention_days": 0}

    async def execute_admin_ddl(
        self,
        database_id: str,
        sql: str,
        *,
        user: str | None = None,
        password: str | None = None,
        host: str | None = None,
        port: int | None = None,
        params: dict | None = None,
    ) -> None:
        await self._run_admin(database_id, sql, user=user, password=password, host=host, port=port)

    async def execute_admin_dml(
        self,
        database_id: str,
        sql: str,
        params: dict | None = None,
        *,
        user: str | None = None,
        password: str | None = None,
        host: str | None = None,
        port: int | None = None,
    ) -> None:
        await self._run_admin(
            database_id, sql, user=user, password=password, host=host, port=port, params=params
        )

    async def _run_admin(
        self,
        database_id: str,
        sql: str,
        *,
        user: str | None,
        password: str | None,
        host: str | None,
        port: int | None,
        params: dict | None = None,
    ) -> None:
        from urllib.parse import quote_plus

        from sqlalchemy.ext.asyncio import create_async_engine

        if not user or not password:
            logger.info("admin SQL skipped (no schema_admin credentials)", database=database_id)
            return
        settings = get_settings()
        host = host or settings.POSTGRES_HOST
        port = port or settings.POSTGRES_PORT
        dsn = (
            f"postgresql+asyncpg://{quote_plus(user)}:{quote_plus(password)}"
            f"@{host}:{port}/{database_id}"
        )
        engine = create_async_engine(dsn, pool_size=1, max_overflow=0)
        try:
            if params:
                async with engine.begin() as conn:
                    for stmt in [s.strip() for s in sql.split(";") if s.strip()]:
                        await conn.execute(text(stmt), params or {})
            else:
                # Script completo por protocolo simple (asyncpg): los valores de
                # celdas pueden contener ';' y partirían la sentencia con split.
                import asyncpg

                connection = await asyncpg.connect(
                    user=user,
                    password=password,
                    host=host,
                    port=int(port),
                    database=database_id,
                )
                try:
                    await connection.execute(sql)
                finally:
                    await connection.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning("admin SQL failed", database=database_id, error=str(exc)[:200])
            raise
        finally:
            await engine.dispose()
