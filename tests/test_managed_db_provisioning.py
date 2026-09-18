# =============================================================================
# Managed DB provisioning — roles con password + scripts con ';' en valores
# =============================================================================
# Regresiones reales (P4):
#   1. CREATE/ALTER ROLE no aceptan bind params en PASSWORD: el provider debe
#      usar un literal escapado (antes los roles quedaban sin crear y el
#      materializador fallaba con "password authentication failed").
#   2. Postgres 15+ no da CREATE en public: el admin de schema queda owner.
#   3. Los INSERT batch contienen ';' y comillas en descripciones: el script
#      debe ejecutarse completo (protocolo simple), no partido por ';'.
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text

from src.core.domain.entities import TenantContext
from src.infrastructure.postgres.relational_db import (
    PostgresOrganizationRepository,
    PostgresWorkspaceRepository,
)
from src.infrastructure.postgres.session import get_async_session
from src.platform.managed_db.local_postgres import _sql_literal
from src.platform.managed_db.service import (
    open_managed_query_session,
    provision_managed_database,
    run_schema_admin_sql,
)


def test_sql_literal_escapes_quotes() -> None:
    assert _sql_literal("abc123") == "'abc123'"
    assert _sql_literal("o'brien") == "'o''brien'"


async def _cleanup(db_name: str, roles: list[str]) -> None:
    session = await get_async_session()
    try:
        await session.execute(text("COMMIT"))
        await session.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))
        for role in roles:
            await session.execute(text(f'DROP ROLE IF EXISTS "{role}"'))
        await session.commit()
    except Exception:  # noqa: BLE001 - limpieza best-effort
        await session.rollback()
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_provision_creates_roles_and_runs_scripts_with_semicolons(
    monkeypatch,
) -> None:
    from src.platform.managed_db import service as managed_service

    async def _allow(*_args, **_kwargs):
        return None

    async def _entitlements(*_args, **_kwargs):
        return {"entitlements": {"managed_db": True, "managed_db_max_mb": 256}}

    monkeypatch.setattr(managed_service, "check_entitlement", _allow)
    monkeypatch.setattr(managed_service, "get_org_entitlements", _entitlements)

    organization = await PostgresOrganizationRepository().create_organization(
        uuid4(), f"Managed DB {uuid4().hex[:6]}"
    )
    workspace = await PostgresWorkspaceRepository().create_workspace(
        organization.id, "Default", "default"
    )
    ctx = TenantContext(
        tenant_id=organization.id,
        roles=frozenset({"owner"}),
        permissions=frozenset({"*"}),
        scopes=frozenset({"portal"}),
        auth_type="portal_session",
    )

    managed = await provision_managed_database(ctx, workspace.id)
    db_name = managed["db_name"]
    assert db_name.startswith("zent_cust_")
    roles = [
        f"zent_schema_admin_{str(organization.id).replace('-', '')[:8]}_{str(workspace.id).replace('-', '')[:8]}",
        f"zent_query_reader_{str(organization.id).replace('-', '')[:8]}_{str(workspace.id).replace('-', '')[:8]}",
    ]
    try:
        # 1+2: el admin puede crear en public (owner del schema).
        await run_schema_admin_sql(
            organization.id,
            workspace.id,
            'CREATE TABLE IF NOT EXISTS "probe" ('
            '"id" UUID PRIMARY KEY DEFAULT gen_random_uuid(), "texto" TEXT);',
        )
        # 3: el valor tiene ';' y comilla simple: no debe partir la sentencia.
        await run_schema_admin_sql(
            organization.id,
            workspace.id,
            "INSERT INTO \"probe\" (\"texto\") VALUES ('a; b ''c''');",
        )
        session = await open_managed_query_session(organization.id, workspace.id)
        assert session is not None
        try:
            rows = (
                await session.execute(text('SELECT "texto" FROM "probe"'))
            ).fetchall()
        finally:
            await session.close()
        assert rows and rows[0][0] == "a; b 'c'"

        # CSV completo: todas las columnas y filas, nombre SQL limpio.
        from uuid import uuid4 as _uuid4

        from src.knowledge.tabular.builder import build_tabular_workbook
        from src.knowledge.tabular.csv_reader import build_csv_workbook_grid
        from src.knowledge.tabular.managed_materializer import materialize_table
        from tests import tabular_fixtures as fx

        grid, _dialect = build_csv_workbook_grid(fx.simple_csv_bytes(), "simple.csv")
        workbook = build_tabular_workbook(
            grid,
            organization_id=organization.id,
            external_id="obj/simple.csv",
            source_id=_uuid4(),
            filename="simple.csv",
        )
        csv_table = workbook.tables()[0]
        result = await materialize_table(
            csv_table,
            organization_id=organization.id,
            workspace_id=workspace.id,
            workbook_name="simple.csv",
            sheet_name="simple",
            source_id=_uuid4(),
        )
        assert result.status == "applied", result.detail
        assert result.table_name == "zent_simple"
        assert result.rows_written == 2

        session = await open_managed_query_session(organization.id, workspace.id)
        assert session is not None
        try:
            csv_rows = (
                await session.execute(
                    text(
                        'SELECT "field_name", "start_position", "length" '
                        'FROM "zent_simple" ORDER BY "start_position"'
                    )
                )
            ).fetchall()
        finally:
            await session.close()
        assert [tuple(row) for row in csv_rows] == [
            ("Carrier Code", 28, 2),
            ("Tariff Number", 30, 3),
        ]
    finally:
        await _cleanup(db_name, roles)
