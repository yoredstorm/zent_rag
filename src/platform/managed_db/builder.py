# =============================================================================
# Database Builder — friendly types → PostgreSQL DDL
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import text

from src.catalog.store import PostgresCatalogStore
from src.core.domain.catalog import (
    CatalogEntity,
    CatalogField,
    CatalogProvenance,
    FieldRole,
    MappingType,
)
from src.core.domain.entities import TenantContext
from src.infrastructure.postgres.session import get_async_session
from src.platform.managed_db.service import (
    ensure_managed_schema,
    get_managed_database,
    run_schema_admin_sql,
)

FRIENDLY_TYPES = {
    "Text": "TEXT",
    "Long Text": "TEXT",
    "Number": "NUMERIC",
    "Money": "NUMERIC(19,4)",
    "Integer": "INTEGER",
    "Boolean": "BOOLEAN",
    "Date": "DATE",
    "Date & Time": "TIMESTAMPTZ",
    "Identifier": "UUID DEFAULT gen_random_uuid()",
    "Relation": "UUID",
    "JSON": "JSONB",
    "Email": "TEXT",
    "Phone": "TEXT",
}

STATES = frozenset(
    {"DRAFT", "AI_PROPOSED", "REVIEWED", "APPROVED", "APPLIED", "FAILED"}
)


def to_ddl(proposal: dict) -> str:
    statements: list[str] = []
    for table in proposal.get("tables") or []:
        name = _ident(table.get("name") or "table")
        cols = []
        for field in table.get("fields") or []:
            fname = _ident(field.get("name") or "col")
            pg = FRIENDLY_TYPES.get(field.get("type") or "Text", "TEXT")
            extra = " NOT NULL" if field.get("required") else ""
            extra += " UNIQUE" if field.get("unique") else ""
            default = field.get("default")
            if default:
                extra += f" DEFAULT {default}"
            cols.append(f'    "{fname}" {pg}{extra}')
        if not any("PRIMARY KEY" in c.upper() or "gen_random_uuid" in c for c in cols):
            cols.insert(0, '    "id" UUID PRIMARY KEY DEFAULT gen_random_uuid()')
        statements.append(
            f'CREATE TABLE IF NOT EXISTS "{name}" (\n' + ",\n".join(cols) + "\n);"
        )
    for rel in proposal.get("relationships") or []:
        src = _ident(rel.get("from_table") or "")
        dst = _ident(rel.get("to_table") or "")
        src_col = _ident(rel.get("from_column") or "id")
        dst_col = _ident(rel.get("to_column") or "id")
        if src and dst:
            statements.append(
                f'ALTER TABLE "{src}" ADD CONSTRAINT "{src}_{src_col}_fkey" '
                f'FOREIGN KEY ("{src_col}") REFERENCES "{dst}" ("{dst_col}")'
            )
    return "\n".join(statements)


def _ident(raw: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in (raw or "").strip())
    return cleaned[:63] or "col"


def relationship_label(rel: dict) -> str:
    frm = rel.get("from_table") or "Record"
    to = rel.get("to_table") or "Record"
    return f"Each {frm} belongs to one {to}"


async def save_proposal(
    ctx: TenantContext,
    workspace_id: UUID,
    managed_database_id: UUID,
    proposal: dict,
    *,
    status: str = "DRAFT",
    prompt: str | None = None,
) -> dict:
    await ensure_managed_schema()
    if status not in STATES:
        raise ValueError("invalid proposal status")
    ddl = to_ddl(proposal)
    pid = uuid4()
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO managed_schema_proposals "
                "(id, organization_id, workspace_id, managed_database_id, status, "
                "prompt, proposal_json, ddl_preview, created_by) "
                "VALUES (:id, :oid, :wid, :mid, :st, :prompt, CAST(:pj AS jsonb), :ddl, :by)"
            ),
            {
                "id": pid,
                "oid": ctx.organization_id,
                "wid": workspace_id,
                "mid": managed_database_id,
                "st": status,
                "prompt": prompt,
                "pj": __import__("json").dumps(proposal),
                "ddl": ddl,
                "by": ctx.user_id,
            },
        )
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
    return {"id": str(pid), "status": status, "ddl_preview": ddl, "proposal": proposal}


async def set_proposal_status(
    organization_id: UUID, proposal_id: UUID, status: str
) -> None:
    if status not in STATES:
        raise ValueError("invalid proposal status")
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "UPDATE managed_schema_proposals SET status = :st, updated_at = now() "
                "WHERE id = :id AND organization_id = :oid"
            ),
            {"st": status, "id": proposal_id, "oid": organization_id},
        )
        await session.commit()
    finally:
        await session.close()


async def apply_proposal(
    ctx: TenantContext, workspace_id: UUID, proposal_id: UUID
) -> dict:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT id, managed_database_id, proposal_json, ddl_preview, status "
                    "FROM managed_schema_proposals "
                    "WHERE id = :id AND organization_id = :oid AND workspace_id = :wid"
                ),
                {"id": proposal_id, "oid": ctx.organization_id, "wid": workspace_id},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None:
        raise ValueError("Proposal not found")
    proposal = row.proposal_json if isinstance(row.proposal_json, dict) else {}
    ddl = row.ddl_preview or to_ddl(proposal)
    try:
        await run_schema_admin_sql(ctx.organization_id, workspace_id, ddl)
        await set_proposal_status(ctx.organization_id, proposal_id, "APPLIED")
        await _materialize_semantics(ctx.organization_id, workspace_id, proposal)
        return {"status": "APPLIED", "ddl_preview": ddl}
    except Exception:
        await set_proposal_status(ctx.organization_id, proposal_id, "FAILED")
        raise


async def _materialize_semantics(
    organization_id: UUID, workspace_id: UUID, proposal: dict
) -> None:
    store = PostgresCatalogStore()
    await store.ensure_tables()
    managed = await get_managed_database(organization_id, workspace_id)
    source_id = None
    if managed and managed.get("connector_id"):
        source = await store.upsert_source(
            organization_id=organization_id,
            connector_id=UUID(managed["connector_id"]),
            engine="postgres",
            workspace_id=workspace_id,
        )
        source_id = source["id"]
    for table in proposal.get("tables") or []:
        entity = CatalogEntity(
            organization_id=organization_id,
            name=_ident(table.get("name") or "Entity"),
            display_name=table.get("name") or "Entity",
            provenance=CatalogProvenance.APPROVED,
            status="approved",
        )
        entity_id = await store.upsert_entity(entity)
        table_id = None
        if source_id is not None:
            table_id, _ = await store.upsert_table(
                organization_id=organization_id,
                source_id=source_id,
                schema_name="public",
                table_name=_ident(table.get("name") or "table"),
            )
        for idx, field in enumerate(table.get("fields") or []):
            mapped_column_id = None
            if table_id is not None:
                mapped_column_id = await store.upsert_column(
                    organization_id=organization_id,
                    table_id=table_id,
                    column_name=_ident(field.get("name") or "col"),
                    ordinal_position=idx + 1,
                    data_type=FRIENDLY_TYPES.get(field.get("type") or "Text", "TEXT"),
                    nullable=not field.get("required"),
                )
            friendly = field.get("type") or "Text"
            role = FieldRole.UNKNOWN.value
            if friendly in {"Money", "Number", "Integer"}:
                role = FieldRole.MEASURE.value
            elif friendly in {"Date", "Date & Time"}:
                role = FieldRole.DATE.value
            elif friendly == "Identifier":
                role = FieldRole.IDENTIFIER.value
            await store.upsert_field(
                CatalogField(
                    organization_id=organization_id,
                    entity_id=entity_id,
                    name=_ident(field.get("name") or "field"),
                    description=field.get("name"),
                    provenance=CatalogProvenance.APPROVED,
                    status="approved",
                    mapped_column_id=mapped_column_id,
                    mapping_type=MappingType.APPROVED_BY_SCHEMA_DESIGN.value,
                    role=role,
                )
            )
