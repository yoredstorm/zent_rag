# =============================================================================
# Data Onboarding — persistencia de sesiones (org-scoped)
# =============================================================================
from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session
from src.platform.data_onboarding.constants import KINDS, STATUSES, STEPS

logger = get_logger(__name__)

_CREATE = """
CREATE TABLE IF NOT EXISTS data_onboarding_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    workspace_id UUID,
    created_by UUID,
    kind VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'NOT_STARTED',
    step VARCHAR(32) NOT NULL DEFAULT 'choose',
    connector_id UUID,
    catalog_source_id UUID,
    kb_source_id UUID,
    skipped_review BOOLEAN NOT NULL DEFAULT false,
    skipped_test BOOLEAN NOT NULL DEFAULT false,
    state_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""

_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_data_onboarding_sessions_org "
    "ON data_onboarding_sessions(organization_id, status)"
)


class DataOnboardingStore:
    _ready = False

    async def ensure_tables(self) -> None:
        if self._ready:
            return
        session = await get_async_session()
        try:
            await session.execute(text(_CREATE))
            await session.execute(text(_INDEX))
            await session.commit()
            self._ready = True
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.warning("data_onboarding_sessions ensure failed", error=str(exc)[:200])
        finally:
            await session.close()

    def _row(self, row) -> dict:
        state = row.state_json if isinstance(row.state_json, dict) else {}
        return {
            "id": str(row.id),
            "organization_id": str(row.organization_id),
            "workspace_id": str(row.workspace_id) if row.workspace_id else None,
            "created_by": str(row.created_by) if row.created_by else None,
            "kind": row.kind,
            "status": row.status,
            "step": row.step,
            "connector_id": str(row.connector_id) if row.connector_id else None,
            "catalog_source_id": str(row.catalog_source_id) if row.catalog_source_id else None,
            "kb_source_id": str(row.kb_source_id) if row.kb_source_id else None,
            "skipped_review": bool(row.skipped_review),
            "skipped_test": bool(row.skipped_test),
            "state": state,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    async def create(
        self,
        organization_id: UUID,
        kind: str,
        *,
        workspace_id: UUID | None = None,
        created_by: UUID | None = None,
    ) -> dict:
        if kind not in KINDS:
            raise ValueError(f"kind must be one of {sorted(KINDS)}")
        await self.ensure_tables()
        sid = uuid4()
        session = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        "INSERT INTO data_onboarding_sessions "
                        "(id, organization_id, workspace_id, created_by, kind) "
                        "VALUES (:id, :oid, :wid, :uid, :kind) "
                        "RETURNING id, organization_id, workspace_id, created_by, kind, "
                        "status, step, connector_id, catalog_source_id, kb_source_id, "
                        "skipped_review, skipped_test, state_json, created_at, updated_at"
                    ),
                    {
                        "id": sid,
                        "oid": organization_id,
                        "wid": workspace_id,
                        "uid": created_by,
                        "kind": kind,
                    },
                )
            ).fetchone()
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
        return self._row(row)

    async def get(self, organization_id: UUID, session_id: UUID) -> dict | None:
        await self.ensure_tables()
        session = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        "SELECT id, organization_id, workspace_id, created_by, kind, "
                        "status, step, connector_id, catalog_source_id, kb_source_id, "
                        "skipped_review, skipped_test, state_json, created_at, updated_at "
                        "FROM data_onboarding_sessions "
                        "WHERE organization_id = :oid AND id = :id"
                    ),
                    {"oid": organization_id, "id": session_id},
                )
            ).fetchone()
        finally:
            await session.close()
        return self._row(row) if row else None

    async def list(
        self,
        organization_id: UUID,
        *,
        status: str | None = None,
        workspace_id: UUID | None = None,
        limit: int = 50,
    ) -> list[dict]:
        await self.ensure_tables()
        session = await get_async_session()
        try:
            sql = (
                "SELECT id, organization_id, workspace_id, created_by, kind, "
                "status, step, connector_id, catalog_source_id, kb_source_id, "
                "skipped_review, skipped_test, state_json, created_at, updated_at "
                "FROM data_onboarding_sessions WHERE organization_id = :oid "
            )
            params: dict = {"oid": organization_id, "limit": min(limit, 100)}
            if status:
                sql += "AND status = :status "
                params["status"] = status
            if workspace_id is not None:
                sql += "AND workspace_id = :wid "
                params["wid"] = workspace_id
            sql += "ORDER BY updated_at DESC LIMIT :limit"
            rows = (await session.execute(text(sql), params)).fetchall()
        finally:
            await session.close()
        return [self._row(r) for r in rows]

    async def update(self, organization_id: UUID, session_id: UUID, **fields) -> dict | None:
        await self.ensure_tables()
        allowed = {
            "status",
            "step",
            "connector_id",
            "catalog_source_id",
            "kb_source_id",
            "skipped_review",
            "skipped_test",
            "state_json",
            "workspace_id",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if "status" in updates and updates["status"] not in STATUSES:
            raise ValueError("invalid status")
        if "step" in updates and updates["step"] not in STEPS:
            raise ValueError("invalid step")
        if not updates:
            return await self.get(organization_id, session_id)
        sets = ["updated_at = NOW()"]
        params: dict = {"oid": organization_id, "id": session_id}
        for key, value in updates.items():
            if key == "state_json":
                sets.append("state_json = CAST(:state_json AS jsonb)")
                params["state_json"] = json.dumps(value)
            else:
                sets.append(f"{key} = :{key}")
                params[key] = value
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    "UPDATE data_onboarding_sessions SET "  # noqa: S608 — column names from fixed `allowed` whitelist, values bound params
                    + ", ".join(sets)
                    + " WHERE organization_id = :oid AND id = :id"
                ),
                params,
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
        return await self.get(organization_id, session_id)


def merge_state(current: dict, patch: dict) -> dict:
    merged = dict(current or {})
    merged.update(patch)
    merged.pop("password", None)
    merged.pop("secrets", None)
    merged.pop("bearer_token", None)
    merged.pop("api_key", None)
    return merged


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
