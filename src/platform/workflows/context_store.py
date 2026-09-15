# =============================================================================
# Workflow Context Store — contribuciones inmutables y proyección por run
# (Workflow Semantic Core, Fase 7; migración 115).
#
# - workflow_context_contributions: append-only, una fila por write aplicado.
# - workflow_run_contexts: proyección JSONB del contexto (sin `security`).
# Las refs de evidencia/claims se validan por organización antes de persistir:
# una ref que no pertenece al tenant se descarta (fail-closed).
# =============================================================================
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

_REF_SECTIONS = frozenset({"evidence_refs", "claim_refs"})

_CONTRIBUTIONS_DDL = """
CREATE TABLE IF NOT EXISTS workflow_context_contributions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL,
    organization_id UUID NOT NULL,
    node_id VARCHAR(80) NOT NULL,
    node_type VARCHAR(40) NOT NULL,
    section VARCHAR(40) NOT NULL,
    value_type VARCHAR(40) NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}',
    provenance JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""

_CONTRIBUTIONS_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_wf_contrib_run "
    "ON workflow_context_contributions(run_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_wf_contrib_org "
    "ON workflow_context_contributions(organization_id, created_at)",
)

_CONTEXTS_DDL = """
CREATE TABLE IF NOT EXISTS workflow_run_contexts (
    run_id UUID PRIMARY KEY,
    organization_id UUID NOT NULL,
    workspace_id UUID,
    schema_version INTEGER NOT NULL DEFAULT 1,
    context JSONB NOT NULL DEFAULT '{}',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""

_CONTEXTS_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_wf_run_contexts_org "
    "ON workflow_run_contexts(organization_id, updated_at)"
)

_ENSURED = False


async def ensure_context_tables() -> None:
    """Paridad dev/test si la migración 115 aún no se aplicó (la migración manda)."""
    global _ENSURED
    if _ENSURED:
        return
    session = await get_async_session()
    try:
        await session.execute(text(_CONTRIBUTIONS_DDL))
        await session.execute(text(_CONTEXTS_DDL))
        for statement in (*_CONTRIBUTIONS_INDEXES, _CONTEXTS_INDEX):
            await session.execute(text(statement))
        await session.commit()
        _ENSURED = True
    except Exception:  # noqa: BLE001 — no romper el run por DDL
        await session.rollback()
    finally:
        await session.close()


async def filter_persistable_applied(
    organization_id: UUID, applied: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Descarta writes de refs que no existen para la organización.

    Fail-closed: si el ledger no puede verificar la ref, no se persiste.
    """
    allowed: list[dict[str, Any]] = []
    for item in applied:
        section = str(item.get("section") or "")
        if section not in _REF_SECTIONS:
            allowed.append(item)
            continue
        ref_id = _entry_ref_id(item)
        if ref_id and await _ref_exists(section, organization_id, ref_id):
            allowed.append(item)
        else:
            logger.warning(
                "workflow context ref rejected",
                section=section,
                ref=str(ref_id),
            )
    return allowed


async def save_contribution(
    *,
    organization_id: UUID,
    run_id: UUID,
    node_id: str,
    node_type: str,
    report: dict[str, Any],
) -> int:
    """Persiste los writes aplicados de un nodo. Devuelve filas insertadas."""
    applied = list(report.get("applied") or [])
    if not applied:
        return 0
    persistable = await filter_persistable_applied(organization_id, applied)
    if not persistable:
        return 0
    session = await get_async_session()
    saved = 0
    try:
        for item in persistable:
            payload = item.get("payload") or {}
            provenance = payload.get("provenance") if isinstance(payload, dict) else {}
            await session.execute(
                text(
                    """
                    INSERT INTO workflow_context_contributions
                        (id, run_id, organization_id, node_id, node_type, section,
                         value_type, payload, provenance, created_at)
                    VALUES
                        (gen_random_uuid(), :rid, :oid, :nid, :ntype, :section,
                         :vtype, CAST(:payload AS jsonb), CAST(:provenance AS jsonb), NOW())
                    """
                ),
                {
                    "rid": str(run_id),
                    "oid": str(organization_id),
                    "nid": str(node_id)[:80],
                    "ntype": str(node_type)[:40],
                    "section": str(item.get("section") or "")[:40],
                    "vtype": str(item.get("value_type") or "json")[:40],
                    "payload": json.dumps(payload, ensure_ascii=False, default=str),
                    "provenance": json.dumps(provenance or {}, ensure_ascii=False, default=str),
                },
            )
            saved += 1
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
    return saved


async def save_run_context(
    *,
    organization_id: UUID,
    run_id: UUID,
    workspace_id: UUID | None,
    snapshot: dict[str, Any],
) -> None:
    """Proyecta el contexto del run (sin `security`) de forma idempotente."""
    safe_snapshot = {key: value for key, value in (snapshot or {}).items() if key != "security"}
    session = await get_async_session()
    try:
        await session.execute(
            text(
                """
                INSERT INTO workflow_run_contexts
                    (run_id, organization_id, workspace_id, schema_version, context, updated_at)
                VALUES
                    (:rid, :oid, :ws, :ver, CAST(:ctx AS jsonb), NOW())
                ON CONFLICT (run_id) DO UPDATE SET
                    context = EXCLUDED.context,
                    workspace_id = EXCLUDED.workspace_id,
                    schema_version = EXCLUDED.schema_version,
                    updated_at = NOW()
                """
            ),
            {
                "rid": str(run_id),
                "oid": str(organization_id),
                "ws": str(workspace_id) if workspace_id else None,
                "ver": int(safe_snapshot.get("schema_version") or 1),
                "ctx": json.dumps(safe_snapshot, ensure_ascii=False, default=str),
            },
        )
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def load_run_context(organization_id: UUID, run_id: UUID) -> dict[str, Any] | None:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT context FROM workflow_run_contexts "
                    "WHERE run_id = :rid AND organization_id = :oid"
                ),
                {"rid": str(run_id), "oid": str(organization_id)},
            )
        ).fetchone()
        return dict(row.context or {}) if row is not None else None
    finally:
        await session.close()


# ---------------------------------------------------------------------------
# Internos
# ---------------------------------------------------------------------------
def _entry_ref_id(item: dict[str, Any]) -> str | None:
    payload = item.get("payload")
    value = payload.get("value") if isinstance(payload, dict) else None
    if not isinstance(value, dict):
        return None
    if str(item.get("section")) == "evidence_refs":
        ref = value.get("evidence_id")
    else:
        ref = value.get("claim_id")
    return str(ref) if ref else None


async def _ref_exists(section: str, organization_id: UUID, ref_id: str) -> bool:
    try:
        uid = UUID(str(ref_id))
    except (TypeError, ValueError):
        return False
    try:
        if section == "evidence_refs":
            from src.api.deps import get_evidence_ledger_repo

            record = await get_evidence_ledger_repo().get(organization_id, uid)
        else:
            from src.api.deps import get_claim_ledger_repo

            record = await get_claim_ledger_repo().get(organization_id, uid)
    except Exception as exc:  # noqa: BLE001 — fail-closed
        logger.warning("workflow context ref lookup failed", error=str(exc)[:200])
        return False
    return record is not None


__all__ = [
    "ensure_context_tables",
    "filter_persistable_applied",
    "load_run_context",
    "save_contribution",
    "save_run_context",
]
