# =============================================================================
# Conversation Guard — contador durable por participante/conversación.
#
# No es un motor nuevo: es estado de control para workflows durables. Evita que
# una decisión de intención incierta detenga la conversación y permite un
# fallback explícito. Nunca cuenta errores técnicos.
# =============================================================================
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

GUARD_TABLE_SQL = (
    """
    CREATE TABLE IF NOT EXISTS workflow_conversation_guards (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        organization_id UUID NOT NULL,
        workspace_id UUID,
        scope_type VARCHAR(20) NOT NULL,
        scope_key VARCHAR(64) NOT NULL,
        failures INTEGER NOT NULL DEFAULT 0,
        warning_sent BOOLEAN NOT NULL DEFAULT FALSE,
        cooldown_until TIMESTAMPTZ,
        last_failure_at TIMESTAMPTZ,
        last_success_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (organization_id, scope_type, scope_key)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_workflow_conversation_guards_scope
    ON workflow_conversation_guards(organization_id, scope_type, scope_key)
    """,
)

_metrics: dict[str, Any] = {}


def _metric(event: str, status: str) -> None:
    try:
        if not _metrics:
            from prometheus_client import Counter

            _metrics["guard"] = Counter(
                "zent_workflow_conversation_guard_total",
                "Resultado del guard de conversación",
                ["event", "status"],
            )
        _metrics["guard"].labels(event=event, status=status).inc()
    except Exception:  # noqa: BLE001 — observabilidad no rompe conversación
        pass


async def ensure_conversation_guard_table() -> None:
    session = await get_async_session()
    try:
        for statement in GUARD_TABLE_SQL:
            await session.execute(text(statement))
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


def scope_digest(scope_type: str, value: str) -> str:
    raw = f"{str(scope_type).strip().lower()}:{str(value).strip()}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _row_payload(row: Any) -> dict[str, Any]:
    if row is None:
        return {
            "failures": 0,
            "warning_sent": False,
            "cooldown_until": None,
            "last_failure_at": None,
            "last_success_at": None,
        }
    return {
        "failures": int(row.failures or 0),
        "warning_sent": bool(row.warning_sent),
        "cooldown_until": row.cooldown_until,
        "last_failure_at": row.last_failure_at,
        "last_success_at": row.last_success_at,
    }


def _decision(
    *,
    failures: int,
    warning_sent: bool,
    cooldown_until: datetime | None,
    max_failures: int,
    warning_at: int,
    blocked_override: bool = False,
) -> dict[str, Any]:
    now = _now()
    cooling = cooldown_until is not None and cooldown_until > now
    blocked = bool(blocked_override or cooling or failures >= max_failures)
    warning = bool(warning_sent or (failures >= warning_at and not blocked))
    return {
        "allowed": not blocked and not cooling,
        "blocked": blocked or cooling,
        "warning": warning,
        "bypass": False,
        "failures": failures,
        "remaining": max(0, max_failures - failures),
        "warning_at": warning_at,
        "max_failures": max_failures,
        "cooldown_until": cooldown_until.isoformat() if cooldown_until else None,
        "message": "",
    }


async def check_guard(
    organization_id: UUID,
    *,
    scope_type: str,
    scope_key: str,
    max_failures: int = 5,
    warning_at: int = 3,
    cooldown_minutes: int = 20,
    workspace_id: UUID | None = None,
) -> dict[str, Any]:
    await ensure_conversation_guard_table()
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT failures, warning_sent, cooldown_until, last_failure_at, "
                    "last_success_at FROM workflow_conversation_guards "
                    "WHERE organization_id = :oid AND scope_type = :scope "
                    "AND scope_key = :skey FOR UPDATE"
                ),
                {"oid": organization_id, "scope": scope_type, "skey": scope_key},
            )
        ).fetchone()
        data = _row_payload(row)
        cooldown = data["cooldown_until"]
        now = _now()
        if cooldown is not None and cooldown <= now and data["failures"] >= max_failures:
            await session.execute(
                text(
                    "UPDATE workflow_conversation_guards SET failures = 0, "
                    "warning_sent = FALSE, cooldown_until = NULL, updated_at = NOW() "
                    "WHERE organization_id = :oid AND scope_type = :scope "
                    "AND scope_key = :skey"
                ),
                {"oid": organization_id, "scope": scope_type, "skey": scope_key},
            )
            data["failures"] = 0
            data["warning_sent"] = False
            data["cooldown_until"] = None
            cooldown = None
        if data["failures"] >= max_failures and cooldown is None:
            cooldown = now + timedelta(minutes=max(1, int(cooldown_minutes)))
            await session.execute(
                text(
                    "UPDATE workflow_conversation_guards SET cooldown_until = :until, "
                    "updated_at = NOW() WHERE organization_id = :oid "
                    "AND scope_type = :scope AND scope_key = :skey"
                ),
                {
                    "until": cooldown,
                    "oid": organization_id,
                    "scope": scope_type,
                    "skey": scope_key,
                },
            )
            data["cooldown_until"] = cooldown
        await session.commit()
    finally:
        await session.close()
    result = _decision(
        failures=data["failures"],
        warning_sent=data["warning_sent"],
        cooldown_until=data["cooldown_until"],
        max_failures=max_failures,
        warning_at=warning_at,
    )
    _metric("check", "blocked" if result["blocked"] else "allow")
    return result


async def record_failure(
    organization_id: UUID,
    *,
    scope_type: str,
    scope_key: str,
    max_failures: int = 5,
    warning_at: int = 3,
    cooldown_minutes: int = 20,
    workspace_id: UUID | None = None,
) -> dict[str, Any]:
    await ensure_conversation_guard_table()
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT failures, warning_sent, cooldown_until, last_failure_at, "
                    "last_success_at FROM workflow_conversation_guards "
                    "WHERE organization_id = :oid AND scope_type = :scope "
                    "AND scope_key = :skey FOR UPDATE"
                ),
                {"oid": organization_id, "scope": scope_type, "skey": scope_key},
            )
        ).fetchone()
        data = _row_payload(row)
        now = _now()
        cooldown = data["cooldown_until"]
        if cooldown is not None and cooldown > now:
            await session.commit()
            result = _decision(
                failures=data["failures"],
                warning_sent=data["warning_sent"],
                cooldown_until=cooldown,
                max_failures=max_failures,
                warning_at=warning_at,
            )
            _metric("failure", "blocked")
            return result
        if cooldown is not None and cooldown <= now:
            # Cooldown terminó: el siguiente ciclo empieza limpio.
            data = {**data, "failures": 0, "warning_sent": False, "cooldown_until": None}
        failures = data["failures"] + 1
        warning_sent = bool(data["warning_sent"] or failures >= warning_at)
        cooldown_until = (
            now + timedelta(minutes=max(1, int(cooldown_minutes)))
            if failures >= max_failures
            else None
        )
        if row is None:
            await session.execute(
                text(
                    "INSERT INTO workflow_conversation_guards "
                    "(organization_id, workspace_id, scope_type, scope_key, failures, "
                    "warning_sent, cooldown_until, last_failure_at) "
                    "VALUES (:oid, :ws, :scope, :skey, :failures, :warning, :until, NOW())"
                ),
                {
                    "oid": organization_id,
                    "ws": workspace_id,
                    "scope": scope_type,
                    "skey": scope_key,
                    "failures": failures,
                    "warning": warning_sent,
                    "until": cooldown_until,
                },
            )
        else:
            await session.execute(
                text(
                    "UPDATE workflow_conversation_guards SET failures = :failures, "
                    "warning_sent = :warning, cooldown_until = :until, "
                    "last_failure_at = NOW(), updated_at = NOW() "
                    "WHERE organization_id = :oid AND scope_type = :scope "
                    "AND scope_key = :skey"
                ),
                {
                    "failures": failures,
                    "warning": warning_sent,
                    "until": cooldown_until,
                    "oid": organization_id,
                    "scope": scope_type,
                    "skey": scope_key,
                },
            )
        await session.commit()
    finally:
        await session.close()
    result = _decision(
        failures=failures,
        warning_sent=warning_sent,
        cooldown_until=cooldown_until,
        max_failures=max_failures,
        warning_at=warning_at,
        blocked_override=failures >= max_failures,
    )
    _metric("failure", "blocked" if result["blocked"] else "warning" if result["warning"] else "recorded")
    return result


async def record_success(
    organization_id: UUID,
    *,
    scope_type: str,
    scope_key: str,
) -> dict[str, Any]:
    await ensure_conversation_guard_table()
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "UPDATE workflow_conversation_guards SET failures = 0, "
                "warning_sent = FALSE, cooldown_until = NULL, last_success_at = NOW(), "
                "updated_at = NOW() WHERE organization_id = :oid "
                "AND scope_type = :scope AND scope_key = :skey"
            ),
            {"oid": organization_id, "scope": scope_type, "skey": scope_key},
        )
        await session.commit()
    finally:
        await session.close()
    _metric("success", "reset")
    return {
        "allowed": True,
        "blocked": False,
        "warning": False,
        "bypass": False,
        "failures": 0,
        "remaining": 0,
        "cooldown_until": None,
        "reset": True,
        "message": "",
    }


__all__ = [
    "check_guard",
    "ensure_conversation_guard_table",
    "record_failure",
    "record_success",
    "scope_digest",
]
