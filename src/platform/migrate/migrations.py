# =============================================================================
# Tenant Data Migration Tools — import CSV/JSON con validación y dry-run,
# export con manifest y re-versión de agentes.
# =============================================================================
from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

MIGRATION_DIR = Path("data") / "migrations"
KINDS = ("kb", "agents", "full")


# ---------------------------------------------------------------------------
# Parsing y validación
# ---------------------------------------------------------------------------
def parse_content(content: str, filename: str) -> list[dict]:
    name = (filename or "").lower()
    if name.endswith(".json") or content.lstrip().startswith("["):
        data = json.loads(content)
        rows = data if isinstance(data, list) else data.get("rows", [])
        return [r for r in rows if isinstance(r, dict)]
    if name.endswith(".csv") or "," in content[:500]:
        reader = csv.DictReader(io.StringIO(content))
        return [dict(row) for row in reader]
    raise ValueError("Formato no soportado: usa CSV o JSON")


def _valid_models() -> list[str]:
    return ["gpt-4o-mini", "gpt-4o", "zent-cheap", "zent-fast", "zent-routed"]


def validate_row(kind: str, row: dict) -> tuple[bool, list[str]]:
    errors: list[str] = []
    if kind in ("kb", "full"):
        if not str(row.get("name") or "").strip():
            errors.append("name requerido")
        if not str(row.get("name") or "").strip():
            pass  # ya reportado
    if kind in ("agents", "full"):
        if not str(row.get("name") or "").strip():
            errors.append("name requerido")
        model = str(row.get("model") or "")
        if not model:
            errors.append("model requerido")
        elif model not in _valid_models():
            errors.append(f"model desconocido: {model}")
    return (len(errors) == 0, errors[:3])


async def _name_exists(organization_id: UUID, kind: str, name: str) -> bool:
    session = await get_async_session()
    try:
        table = "knowledge_bases" if kind == "kb" else "agents"
        row = (
            await session.execute(
                text(f"SELECT 1 FROM {table} WHERE organization_id = :oid AND name = :name LIMIT 1"),  # noqa: S608
                {"oid": organization_id, "name": name},
            )
        ).fetchone()
        return row is not None
    finally:
        await session.close()


async def preview_import(
    organization_id: UUID,
    kind: str,
    content: str,
    filename: str,
    created_by: UUID | None = None,
) -> dict:
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    try:
        rows = parse_content(content, filename)
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"Contenido inválido: {exc}") from exc

    validated: list[dict] = []
    errors: list[dict] = []
    for index, row in enumerate(rows):
        valid, row_errors = validate_row(kind, row)
        if valid:
            validated.append({"index": index, "row": row})
        else:
            errors.append({"index": index, "row": row, "errors": row_errors})

    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO data_migrations (id, organization_id, kind, direction, "
                    "status, filename, rows_total, rows_valid, rows_failed, errors, created_by) "
                    "VALUES (gen_random_uuid(), :oid, :kind, 'import', 'dry_run', "
                    ":filename, :total, :valid, :failed, :errors, :by) RETURNING id"
                ),
                {
                    "oid": organization_id,
                    "kind": kind[:20],
                    "filename": filename[:300],
                    "total": len(rows),
                    "valid": len(validated),
                    "failed": len(errors),
                    "errors": json.dumps(errors),
                    "by": created_by,
                },
            )
        ).fetchone()
        await session.commit()
    finally:
        await session.close()
    return {
        "migration_id": str(row.id),
        "status": "dry_run",
        "rows_total": len(rows),
        "rows_valid": len(validated),
        "rows_failed": len(errors),
        "preview": [v["row"] for v in validated[:10]],
        "errors": errors[:10],
    }


async def apply_import(organization_id: UUID, migration_id: UUID) -> dict:
    session = await get_async_session()
    try:
        migration = (
            await session.execute(
                text(
                    "SELECT kind, filename, rows_valid FROM data_migrations "
                    "WHERE id = :mid AND organization_id = :oid AND status = 'dry_run'"
                ),
                {"mid": migration_id, "oid": organization_id},
            )
        ).fetchone()
        if migration is None:
            return None
        rows = parse_content(
            (Path(MIGRATION_DIR) / "staged").read_text() if False else "",
            "",
        ) if False else None
        # Re-parsing del contenido original: se guardó en el manifest como stage.
        staged = (
            await session.execute(
                text("SELECT content FROM migration_staged WHERE migration_id = :mid"),
                {"mid": migration_id},
            )
        ).fetchone()
    finally:
        await session.close()

    if staged is None:
        return {"status": "staged_content_missing"}

    rows = parse_content(staged.content, migration.filename or "")
    applied = 0
    failed = 0
    apply_errors: list[dict] = []
    session = await get_async_session()
    try:
        for index, row in enumerate(rows):
            valid, row_errors = validate_row(migration.kind, row)
            if not valid:
                failed += 1
                apply_errors.append({"index": index, "errors": row_errors})
                continue
            name = str(row.get("name") or "").strip()
            if await _name_exists(organization_id, migration.kind, name):
                failed += 1
                apply_errors.append({"index": index, "errors": ["ya existe: " + name]})
                continue
            try:
                if migration.kind in ("kb", "full"):
                    await session.execute(
                        text(
                            "INSERT INTO knowledge_bases (id, organization_id, name, "
                            "description, status, embedding_model) "
                            "VALUES (gen_random_uuid(), :oid, :name, :desc, 'active', "
                            "COALESCE(NULLIF(:model, ''), 'text-embedding-3-small'))"
                        ),
                        {
                            "oid": organization_id,
                            "name": name,
                            "desc": str(row.get("description") or "")[:500],
                            "model": str(row.get("embedding_model") or ""),
                        },
                    )
                if migration.kind in ("agents", "full"):
                    await session.execute(
                        text(
                            "INSERT INTO agents (id, organization_id, name, description, "
                            "system_prompt, model, status, config_json) "
                            "VALUES (gen_random_uuid(), :oid, :name, :desc, :prompt, "
                            ":model, 'draft', :config)"
                        ),
                        {
                            "oid": organization_id,
                            "name": name,
                            "desc": str(row.get("description") or "")[:500],
                            "prompt": str(row.get("system_prompt") or "")[:8000],
                            "model": str(row.get("model") or "gpt-4o-mini"),
                            "config": json.dumps({"cost_tags": row.get("cost_tags") or {}}),
                        },
                    )
                applied += 1
            except Exception as exc:  # noqa: BLE001
                failed += 1
                apply_errors.append({"index": index, "errors": [str(exc)[:200]]})
        await session.execute(
            text(
                "UPDATE data_migrations SET status = 'applied', rows_applied = :applied, "
                "rows_failed = :failed, errors = :errors, completed_at = NOW() "
                "WHERE id = :mid"
            ),
            {
                "applied": applied,
                "failed": failed,
                "errors": json.dumps(apply_errors),
                "mid": migration_id,
            },
        )
        await session.commit()
    finally:
        await session.close()
    return {"status": "applied", "rows_applied": applied, "rows_failed": failed}


async def stage_content(migration_id: UUID, content: str) -> None:
    """Guarda el contenido original para aplicar después (dry-run → apply)."""
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO migration_staged (migration_id, content) "
                "VALUES (:mid, :content) ON CONFLICT (migration_id) DO UPDATE SET content = :content"
            ),
            {"mid": migration_id, "content": content},
        )
        await session.commit()
    finally:
        await session.close()


async def export_migration(
    organization_id: UUID,
    kind: str,
    created_by: UUID | None = None,
) -> dict:
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    session = await get_async_session()
    try:
        payload: dict = {}
        if kind in ("kb", "full"):
            kbs = (
                await session.execute(
                    text(
                        "SELECT name, description, embedding_model, chunking_strategy "
                        "FROM knowledge_bases WHERE organization_id = :oid ORDER BY name"
                    ),
                    {"oid": organization_id},
                )
            ).fetchall()
            payload["knowledge_bases"] = [
                {
                    "name": r.name,
                    "description": r.description,
                    "embedding_model": r.embedding_model,
                    "chunking_strategy": r.chunking_strategy,
                }
                for r in kbs
            ]
        if kind in ("agents", "full"):
            agents = (
                await session.execute(
                    text(
                        "SELECT name, description, system_prompt, model, config_json "
                        "FROM agents WHERE organization_id = :oid ORDER BY name"
                    ),
                    {"oid": organization_id},
                )
            ).fetchall()
            payload["agents"] = [
                {
                    "name": r.name,
                    "description": r.description,
                    "system_prompt": r.system_prompt,
                    "model": r.model,
                    "cost_tags": (r.config_json or {}).get("cost_tags") or {},
                }
                for r in agents
            ]
        manifest = {
            "organization_id": str(organization_id),
            "kind": kind,
            "direction": "export",
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "schema_version": 1,
            "counts": {k: len(v) for k, v in payload.items()},
        }
        filename = f"zent-migration-{kind}-{uuid4().hex[:8]}.json"
        out_path = MIGRATION_DIR / str(organization_id) / filename
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps({"manifest": manifest, "data": payload}, indent=2, default=str),
            encoding="utf-8",
        )
        row = (
            await session.execute(
                text(
                    "INSERT INTO data_migrations (id, organization_id, kind, direction, "
                    "status, filename, rows_total, rows_valid, rows_applied, manifest, "
                    "created_by, completed_at) "
                    "VALUES (gen_random_uuid(), :oid, :kind, 'export', 'exported', "
                    ":filename, :total, :total, :total, :manifest, :by, NOW()) "
                    "RETURNING id"
                ),
                {
                    "oid": organization_id,
                    "kind": kind[:20],
                    "filename": filename,
                    "total": sum(len(v) for v in payload.values()),
                    "manifest": json.dumps(manifest),
                    "by": created_by,
                },
            )
        ).fetchone()
        await session.commit()
    finally:
        await session.close()
    return {
        "migration_id": str(row.id),
        "status": "exported",
        "filename": filename,
        "manifest": manifest,
    }


async def get_export_file(migration_id: UUID) -> tuple[bytes, str] | None:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT filename, organization_id FROM data_migrations "
                    "WHERE id = :mid AND direction = 'export'"
                ),
                {"mid": migration_id},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None or not row.filename:
        return None
    path = MIGRATION_DIR / str(row.organization_id) / row.filename
    if not path.exists():
        return None
    return path.read_bytes(), row.filename


async def list_migrations(organization_id: UUID | None = None, limit: int = 50) -> dict:
    session = await get_async_session()
    try:
        params: dict = {"limit": limit}
        where = ""
        if organization_id:
            where = " WHERE organization_id = :oid"
            params["oid"] = organization_id
        rows = (
            await session.execute(
                text(
                    "SELECT id, organization_id, kind, direction, status, filename, "
                    "rows_total, rows_valid, rows_applied, rows_failed, created_by, "
                    "created_at, completed_at FROM data_migrations"
                    + where
                    + " ORDER BY created_at DESC LIMIT :limit"
                ),
                params,
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "migrations": [
            {
                "id": str(r.id),
                "organization_id": str(r.organization_id),
                "kind": r.kind,
                "direction": r.direction,
                "status": r.status,
                "filename": r.filename,
                "rows_total": int(r.rows_total),
                "rows_valid": int(r.rows_valid),
                "rows_applied": int(r.rows_applied),
                "rows_failed": int(r.rows_failed),
                "created_by": str(r.created_by) if r.created_by else None,
                "created_at": r.created_at.isoformat(),
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            }
            for r in rows
        ],
        "count": len(rows),
    }


async def reversion_agent(organization_id: UUID, agent_id: UUID) -> dict:
    """Crea una nueva versión del agente desde su configuración actual."""
    session = await get_async_session()
    try:
        agent = (
            await session.execute(
                text(
                    "SELECT name, config_json, model FROM agents "
                    "WHERE id = :aid AND organization_id = :oid"
                ),
                {"aid": agent_id, "oid": organization_id},
            )
        ).fetchone()
        if agent is None:
            return None
        next_number = (
            await session.execute(
                text(
                    "SELECT COALESCE(MAX(version_number), 0) + 1 FROM agent_versions "
                    "WHERE agent_id = :aid"
                ),
                {"aid": agent_id},
            )
        ).scalar()
        row = (
            await session.execute(
                text(
                    "INSERT INTO agent_versions (id, agent_id, organization_id, "
                    "version_number, status, config_snapshot, notes) "
                    "VALUES (gen_random_uuid(), :aid, :oid, :num, 'ready', "
                    "CAST(:snapshot AS jsonb), 're-version por migración') "
                    "RETURNING id, version_number"
                ),
                {
                    "aid": agent_id,
                    "oid": organization_id,
                    "num": int(next_number),
                    "snapshot": json.dumps(agent.config_json or {}),
                },
            )
        ).fetchone()
        await session.commit()
    finally:
        await session.close()
    return {"agent_id": str(agent_id), "version_id": str(row.id), "version_number": int(row.version_number)}
