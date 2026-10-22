# =============================================================================
# Solutions — reusable composition of roles, agents, workflows and requirements.
#
# A Solution is a design/installation artifact. It does not execute, does not
# copy agents/workflows and does not contain tenant IDs or credentials.
# =============================================================================
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session
from src.platform.studio.contracts import (
    SolutionV1,
    scan_contract_secrets,
    solution_from_legacy_payload,
)

logger = get_logger(__name__)

_TABLE_SQL = (
    """
    CREATE TABLE IF NOT EXISTS studio_solutions (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        organization_id UUID NOT NULL,
        workspace_id UUID,
        slug VARCHAR(80) NOT NULL,
        name VARCHAR(150) NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        blueprint JSONB NOT NULL,
        version VARCHAR(20) NOT NULL DEFAULT '1.0.0',
        revision INT NOT NULL DEFAULT 1,
        status VARCHAR(20) NOT NULL DEFAULT 'draft',
        created_by UUID,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (organization_id, slug)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_studio_solutions_org
    ON studio_solutions(organization_id, workspace_id, updated_at DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS studio_solution_versions (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        solution_id UUID NOT NULL REFERENCES studio_solutions(id) ON DELETE CASCADE,
        organization_id UUID NOT NULL,
        version VARCHAR(20) NOT NULL,
        revision INT NOT NULL,
        snapshot JSONB NOT NULL,
        notes TEXT,
        created_by UUID,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (solution_id, revision)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_studio_solution_versions_solution
    ON studio_solution_versions(solution_id, revision DESC)
    """,
)


_schema_ready = False


class SolutionError(ValueError):
    pass


class SolutionConflict(SolutionError):
    pass


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, default=str)


async def ensure_solution_tables() -> None:
    global _schema_ready
    if _schema_ready:
        return
    session = await get_async_session()
    try:
        for statement in _TABLE_SQL:
            await session.execute(text(statement))
        await session.commit()
        _schema_ready = True
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


def _solution_payload(row: Any) -> dict[str, Any]:
    blueprint = row.blueprint if isinstance(row.blueprint, dict) else {}
    payload = dict(blueprint)
    payload["schema"] = "zent.solution/v1"
    payload["record_id"] = str(row.id)
    payload["solution_id"] = str(row.slug)
    payload["version"] = str(row.version)
    payload["status"] = str(row.status)
    payload["name"] = str(row.name)
    payload["description"] = str(row.description or "")
    return payload


def _bump_version(version: str) -> str:
    parts = str(version or "1.0.0").split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        return "1.0.1"
    major, minor, patch = (int(part) for part in parts)
    return f"{major}.{minor}.{patch + 1}"


async def _insert_version(session, row: Any, *, notes: str, created_by: UUID | None) -> None:
    await session.execute(
        text(
            "INSERT INTO studio_solution_versions (solution_id, organization_id, version, "
            "revision, snapshot, notes, created_by) VALUES (:sid, :oid, :version, :rev, "
            "CAST(:snap AS jsonb), :notes, :uid) "
            "ON CONFLICT (solution_id, revision) DO NOTHING"
        ),
        {
            "sid": row.id,
            "oid": row.organization_id,
            "version": row.version,
            "rev": row.revision,
            "snap": _json(_solution_payload(row)),
            "notes": notes,
            "uid": created_by,
        },
    )


async def create_solution(
    organization_id: UUID,
    *,
    workspace_id: UUID | None = None,
    user_id: UUID | None = None,
    payload: dict[str, Any],
) -> dict[str, Any]:
    await ensure_solution_tables()
    solution = SolutionV1.model_validate(payload)
    issues = scan_contract_secrets(solution.model_dump(by_alias=True))
    if issues:
        raise SolutionError("; ".join(issues[:6]))
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO studio_solutions (organization_id, workspace_id, slug, name, "
                    "description, blueprint, version, revision, status, created_by) "
                    "VALUES (:oid, :ws, :slug, :name, :desc, CAST(:blueprint AS jsonb), "
                    ":version, 1, :status, :uid) RETURNING *"
                ),
                {
                    "oid": organization_id,
                    "ws": workspace_id,
                    "slug": solution.solution_id,
                    "name": solution.name,
                    "desc": solution.description,
                    "blueprint": _json(solution.model_dump(by_alias=True)),
                    "version": solution.version,
                    "status": solution.status,
                    "uid": user_id,
                },
            )
        ).fetchone()
        await _insert_version(session, row, notes="created", created_by=user_id)
        await session.commit()
    except Exception as exc:
        await session.rollback()
        if "duplicate" in str(exc).lower():
            raise SolutionConflict(
                f"solution_id ya existe en este tenant: {solution.solution_id}"
            ) from exc
        raise
    finally:
        await session.close()
    return _solution_payload(row)


async def get_solution(
    organization_id: UUID, solution_id: UUID, *, workspace_id: UUID | None = None
) -> dict[str, Any] | None:
    await ensure_solution_tables()
    session = await get_async_session()
    try:
        sql = "SELECT * FROM studio_solutions WHERE id = :sid AND organization_id = :oid"
        params: dict[str, Any] = {"sid": solution_id, "oid": organization_id}
        if workspace_id is not None:
            sql += " AND (workspace_id = :ws OR workspace_id IS NULL)"
            params["ws"] = workspace_id
        row = (await session.execute(text(sql), params)).fetchone()
    finally:
        await session.close()
    return _solution_payload(row) if row else None


async def list_solutions(
    organization_id: UUID, *, workspace_id: UUID | None = None
) -> list[dict[str, Any]]:
    await ensure_solution_tables()
    session = await get_async_session()
    try:
        sql = "SELECT * FROM studio_solutions WHERE organization_id = :oid"
        params: dict[str, Any] = {"oid": organization_id}
        if workspace_id is not None:
            sql += " AND (workspace_id = :ws OR workspace_id IS NULL)"
            params["ws"] = workspace_id
        rows = (
            await session.execute(text(sql + " ORDER BY updated_at DESC LIMIT 200"), params)
        ).fetchall()
    finally:
        await session.close()
    return [_solution_payload(row) for row in rows]


async def update_solution(
    organization_id: UUID,
    solution_id: UUID,
    payload: dict[str, Any],
    *,
    user_id: UUID | None = None,
    notes: str | None = None,
) -> dict[str, Any] | None:
    current = await get_solution(organization_id, solution_id)
    if current is None:
        return None
    merged = {**current, **payload}
    merged["solution_id"] = current["solution_id"]
    merged["version"] = _bump_version(str(current.get("version") or "1.0.0"))
    solution = SolutionV1.model_validate(merged)
    await ensure_solution_tables()
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "UPDATE studio_solutions SET name = :name, description = :desc, "
                    "blueprint = CAST(:blueprint AS jsonb), version = :version, "
                    "revision = revision + 1, status = :status, updated_at = NOW() "
                    "WHERE id = :sid AND organization_id = :oid RETURNING *"
                ),
                {
                    "name": solution.name,
                    "desc": solution.description,
                    "blueprint": _json(solution.model_dump(by_alias=True)),
                    "version": solution.version,
                    "status": solution.status,
                    "sid": solution_id,
                    "oid": organization_id,
                },
            )
        ).fetchone()
        if row is not None:
            await _insert_version(
                session, row, notes=notes or "updated", created_by=user_id
            )
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
    return _solution_payload(row) if row else None


async def clone_solution(
    organization_id: UUID,
    solution_id: UUID,
    *,
    user_id: UUID | None = None,
    new_solution_id: str | None = None,
) -> dict[str, Any] | None:
    current = await get_solution(organization_id, solution_id)
    if current is None:
        return None
    payload = dict(current)
    payload["solution_id"] = new_solution_id or f"{current['solution_id']}_copy"[:80]
    payload["name"] = f"Copia de {current['name']}"[:150]
    payload["version"] = "1.0.0"
    payload["status"] = "draft"
    return await create_solution(
        organization_id, user_id=user_id, payload=payload
    )


async def list_solution_versions(
    organization_id: UUID, solution_id: UUID
) -> list[dict[str, Any]]:
    await ensure_solution_tables()
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT version, revision, notes, created_at FROM studio_solution_versions "
                    "WHERE solution_id = :sid AND organization_id = :oid "
                    "ORDER BY revision DESC LIMIT 100"
                ),
                {"sid": solution_id, "oid": organization_id},
            )
        ).fetchall()
    finally:
        await session.close()
    return [
        {
            "version": str(row.version),
            "revision": int(row.revision),
            "notes": row.notes,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]


async def get_solution_version(
    organization_id: UUID, solution_id: UUID, revision: int
) -> dict[str, Any] | None:
    await ensure_solution_tables()
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT snapshot FROM studio_solution_versions "
                    "WHERE solution_id = :sid AND organization_id = :oid AND revision = :rev"
                ),
                {"sid": solution_id, "oid": organization_id, "rev": revision},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None:
        return None
    snapshot = row.snapshot if isinstance(row.snapshot, dict) else {}
    out = dict(snapshot)
    out.pop("record_id", None)
    return out


async def export_solution(organization_id: UUID, solution_id: UUID) -> dict[str, Any] | None:
    solution = await get_solution(organization_id, solution_id)
    if solution is None:
        return None
    out = dict(solution)
    out.pop("id", None)
    out.pop("record_id", None)
    return out


async def import_solution(
    organization_id: UUID,
    payload: dict[str, Any],
    *,
    workspace_id: UUID | None = None,
    user_id: UUID | None = None,
) -> dict[str, Any]:
    solution = solution_from_legacy_payload(payload)
    return await create_solution(
        organization_id,
        workspace_id=workspace_id,
        user_id=user_id,
        payload=solution.model_dump(by_alias=True),
    )


def validate_solution(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        solution = SolutionV1.model_validate(payload)
    except Exception as exc:  # noqa: BLE001
        return {"valid": False, "errors": [str(exc)[:400]]}
    errors = scan_contract_secrets(solution.model_dump(by_alias=True))
    return {
        "valid": not errors,
        "errors": errors,
        "role_count": len(solution.roles),
        "agent_count": len(solution.agents),
        "workflow_count": len(solution.workflows),
        "requirements": solution.requirements,
        "installation_steps": len(solution.installation),
    }


__all__ = [
    "SolutionConflict",
    "SolutionError",
    "clone_solution",
    "create_solution",
    "ensure_solution_tables",
    "export_solution",
    "get_solution",
    "get_solution_version",
    "import_solution",
    "list_solution_versions",
    "list_solutions",
    "update_solution",
    "validate_solution",
]
