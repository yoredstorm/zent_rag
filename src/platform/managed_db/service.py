# =============================================================================
# Managed DB registry + entitlements + connector wiring
# =============================================================================
from __future__ import annotations

from urllib.parse import quote_plus
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.core.config import get_settings
from src.core.domain.entities import TenantContext
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session
from src.platform.billing.entitlements import EntitlementDenied, check_entitlement, get_org_entitlements
from src.platform.managed_db.local_postgres import LocalPostgresProvider

logger = get_logger(__name__)

_SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS managed_databases (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
        workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        provider VARCHAR(40) NOT NULL DEFAULT 'local',
        db_name VARCHAR(120) NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'ready',
        size_quota_mb INT NOT NULL DEFAULT 256,
        connector_id UUID,
        backup_retention_days INT NOT NULL DEFAULT 0,
        last_backup_at TIMESTAMPTZ,
        restore_ready BOOLEAN NOT NULL DEFAULT false,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE (organization_id, workspace_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS managed_schema_proposals (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        organization_id UUID NOT NULL,
        workspace_id UUID NOT NULL,
        managed_database_id UUID NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'DRAFT',
        prompt TEXT,
        proposal_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        ddl_preview TEXT,
        created_by UUID,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
]


def get_managed_provider():
    settings = get_settings()
    name = getattr(settings, "MANAGED_DB_PROVIDER", "local") or "local"
    if name != "local":
        raise NotImplementedError(
            f"Managed DB provider {name} is not implemented. Use local in development."
        )
    return LocalPostgresProvider()


async def ensure_managed_schema() -> None:
    session = await get_async_session()
    try:
        for stmt in _SCHEMA:
            await session.execute(text(stmt))
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


def _row(row) -> dict:
    return {
        "id": str(row.id),
        "db_name": row.db_name,
        "status": row.status,
        "connector_id": str(row.connector_id) if row.connector_id else None,
        "size_quota_mb": row.size_quota_mb,
        "backup": {
            "restore_ready": getattr(row, "restore_ready", False),
            "last_backup_at": (
                row.last_backup_at.isoformat()
                if getattr(row, "last_backup_at", None)
                else None
            ),
            "retention_days": getattr(row, "backup_retention_days", 0),
        },
    }


async def provision_managed_database(
    ctx: TenantContext, workspace_id: UUID
) -> dict:
    await ensure_managed_schema()
    try:
        await check_entitlement(ctx.organization_id, "managed_db")
    except EntitlementDenied as exc:
        raise PermissionError(str(exc)) from exc
    ents_wrap = await get_org_entitlements(ctx.organization_id)
    ents = ents_wrap.get("entitlements") or {}
    if "managed_db_max_mb" in ents:
        raw_size = ents.get("managed_db_max_mb")
        size_mb = 102400 if raw_size is None else int(raw_size)
    else:
        size_mb = 256
    backups = bool(ents.get("managed_db_backups"))
    session = await get_async_session()
    try:
        existing = (
            await session.execute(
                text(
                    "SELECT id, db_name, status, connector_id, size_quota_mb, "
                    "backup_retention_days, restore_ready, last_backup_at "
                    "FROM managed_databases "
                    "WHERE organization_id = :oid AND workspace_id = :wid"
                ),
                {"oid": ctx.organization_id, "wid": workspace_id},
            )
        ).fetchone()
        if existing is not None:
            return _row(existing)
    finally:
        await session.close()

    created = await get_managed_provider().create_database(
        ctx.organization_id, workspace_id, size_mb=size_mb
    )
    connector_id = None
    kb_source_id = None
    try:
        from src.catalog.store import PostgresCatalogStore
        from src.infrastructure.postgres.knowledge_repos import PostgresSourceRepository
        from src.infrastructure.postgres.relational_db import PostgresConnectorRepository
        from src.infrastructure.secrets.secret_store_resolver import get_secret_store

        connector = await PostgresConnectorRepository().create_connector(
            ctx.organization_id,
            "Managed Database",
            "postgres",
            workspace_id=workspace_id,
            config_json={
                "host": created["host"],
                "port": created["port"],
                "database": created["db_name"],
                "user": created["query_reader_user"],
                "managed": True,
                "ssl": False,
            },
        )
        connector_id = connector.id
        await get_secret_store().put(
            ctx.organization_id,
            connector.id,
            {
                "password": created["query_reader_password"],
                "query_reader_password": created["query_reader_password"],
                "schema_admin_password": created["schema_admin_password"],
                "schema_admin_user": created["schema_admin_user"],
                "query_reader_user": created["query_reader_user"],
            },
        )
        source = await PostgresSourceRepository().create_source(
            ctx.organization_id,
            "Managed Database",
            "sql",
            config_json={"managed": True, "connector_id": str(connector.id)},
            workspace_id=workspace_id,
        )
        kb_source_id = source.id
        store = PostgresCatalogStore()
        await store.ensure_tables()
        await store.upsert_source(
            organization_id=ctx.organization_id,
            connector_id=connector.id,
            engine="postgres",
            kb_source_id=source.id,
            workspace_id=workspace_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Managed connector wiring skipped", error=str(exc)[:200])
        connector_id = connector_id
        kb_source_id = kb_source_id

    row_id = uuid4()
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO managed_databases "
                "(id, organization_id, workspace_id, provider, db_name, status, "
                "size_quota_mb, connector_id, backup_retention_days, restore_ready) "
                "VALUES (:id, :oid, :wid, 'local', :db, 'ready', :sz, :cid, :ret, :ready)"
            ),
            {
                "id": row_id,
                "oid": ctx.organization_id,
                "wid": workspace_id,
                "db": created["db_name"],
                "sz": size_mb,
                "cid": connector_id,
                "ret": 7 if backups else 0,
                "ready": backups,
            },
        )
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
    created["id"] = str(row_id)
    created["connector_id"] = str(connector_id) if connector_id else None
    created["kb_source_id"] = str(kb_source_id) if kb_source_id else None
    created["size_quota_mb"] = size_mb
    created["backup"] = {
        "restore_ready": backups,
        "last_backup_at": None,
        "retention_days": 7 if backups else 0,
    }
    created.pop("schema_admin_password", None)
    created.pop("query_reader_password", None)
    return created


def query_runtime_secrets(secrets: dict) -> dict:
    """SQL Expert / Text-to-SQL may only receive SELECT credentials."""
    blocked = {"schema_admin_password", "schema_admin_user"}
    return {k: v for k, v in (secrets or {}).items() if k not in blocked}


async def get_managed_database(organization_id: UUID, workspace_id: UUID) -> dict | None:
    await ensure_managed_schema()
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT id, db_name, status, connector_id, size_quota_mb, "
                    "backup_retention_days, restore_ready, last_backup_at "
                    "FROM managed_databases "
                    "WHERE organization_id = :oid AND workspace_id = :wid"
                ),
                {"oid": organization_id, "wid": workspace_id},
            )
        ).fetchone()
        return _row(row) if row else None
    finally:
        await session.close()


async def _connector_secrets(organization_id: UUID, connector_id: UUID) -> tuple[dict, dict]:
    from src.infrastructure.postgres.relational_db import PostgresConnectorRepository
    from src.infrastructure.secrets.secret_store_resolver import get_secret_store

    connector = await PostgresConnectorRepository().get_connector(
        organization_id, connector_id
    )
    config = getattr(connector, "config_json", None) or {} if connector else {}
    secrets = await get_secret_store().get(organization_id, connector_id)
    return config if isinstance(config, dict) else {}, secrets or {}


def _dsn(*, user: str, password: str, host: str, port: int | str, database: str) -> str:
    return (
        f"postgresql+asyncpg://{quote_plus(user)}:{quote_plus(password)}"
        f"@{host}:{port}/{database}"
    )


async def open_managed_query_session(
    organization_id: UUID, workspace_id: UUID | None = None
) -> AsyncSession | None:
    """Reader-only session against the workspace managed DB, or None."""
    await ensure_managed_schema()
    session = await get_async_session()
    try:
        sql = (
            "SELECT id, db_name, connector_id FROM managed_databases "
            "WHERE organization_id = :oid"
        )
        params: dict = {"oid": organization_id}
        if workspace_id is not None:
            sql += " AND workspace_id = :wid"
            params["wid"] = workspace_id
        sql += " ORDER BY created_at DESC LIMIT 1"
        row = (await session.execute(text(sql), params)).fetchone()
    finally:
        await session.close()
    if row is None or row.connector_id is None:
        return None
    config, secrets = await _connector_secrets(organization_id, row.connector_id)
    if config.get("managed") is not True and str(config.get("managed")).lower() != "true":
        # Still allow if registered as managed_databases row.
        pass
    cleaned = query_runtime_secrets(secrets)
    user = config.get("user") or cleaned.get("query_reader_user")
    password = cleaned.get("password") or cleaned.get("query_reader_password")
    host = config.get("host")
    port = config.get("port") or get_settings().POSTGRES_PORT
    database = config.get("database") or row.db_name
    if not user or not password or not host:
        return None
    engine = create_async_engine(
        _dsn(user=user, password=password, host=host, port=port, database=database),
        pool_size=1,
        max_overflow=0,
        pool_pre_ping=True,
        connect_args={"server_settings": {"default_transaction_read_only": "on"}},
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    return factory()


async def run_schema_admin_sql(
    organization_id: UUID, workspace_id: UUID, sql: str, params: dict | None = None
) -> None:
    managed = await get_managed_database(organization_id, workspace_id)
    if managed is None or not managed.get("connector_id"):
        await get_managed_provider().execute_admin_ddl(managed["db_name"] if managed else "managed", sql)
        return
    config, secrets = await _connector_secrets(organization_id, UUID(managed["connector_id"]))
    user = secrets.get("schema_admin_user")
    password = secrets.get("schema_admin_password")
    host = config.get("host") or get_settings().POSTGRES_HOST
    port = config.get("port") or get_settings().POSTGRES_PORT
    await get_managed_provider().execute_admin_ddl(
        managed["db_name"],
        sql,
        user=user,
        password=password,
        host=host,
        port=int(port),
        params=params,
    )
