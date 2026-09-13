# =============================================================================
# Data Watchers — observación incremental de datos sin agentes corriendo
# (Fases C+E del plan Living Workflows).
#
# Un watcher es SQL + condición + transición. Cuando detecta un cambio relevante
# genera un BusinessEvent y lo entrega al dispatcher existente, que dispara el
# workflow con el engine actual. No hay motor nuevo, ni DB triggers físicos.
#
# Estrategias MVP:
#   watermark_polling  primary key incremental (WHERE pk > checkpoint)
#   timestamp_polling  updated_at > checkpoint
#   query_watch        alias estable: watermark si hay pk, timestamp si no
#
# Seguridad:
#   - identificadores whitelisteados (sin SQL libre del usuario)
#   - sesión reader-only existente + LIMIT acotado + ORDER BY cursor
#   - payload de fila = UNTRUSTED INPUT (solo datos, nunca instrucciones)
#   - aislamiento por organization_id/workspace_id en cada consulta
# =============================================================================
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session
from src.platform.workflows.business_events import BusinessEvent, build_business_event
from src.platform.workflows.engine import _eval_condition
from src.platform.workflows.intent import CANONICAL_TO_ENGINE, normalize_operator

logger = get_logger(__name__)

MODEL_CONFIG = ConfigDict(extra="forbid")

POLLING_STRATEGIES = ("watermark_polling", "timestamp_polling", "query_watch")
WATCHER_STRATEGIES = (*POLLING_STRATEGIES, "application_event", "webhook")
TRANSITION_MODES = ("on_change", "on_enter", "on_exit", "while_true")
WATCHER_STATUSES = ("listening", "checking", "error", "paused")

MAX_ROWS_PER_CHECK = 100
MAX_CHECK_LIMIT = 500
IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]{0,62}$")

QueryRunner = Callable[[str, dict[str, Any]], Awaitable[list[dict[str, Any]]]]


class WatcherError(ValueError):
    """Configuración de watcher inválida (mensaje seguro, sin secretos)."""


def _safe_ident(value: str, what: str) -> str:
    name = str(value or "").strip()
    if not IDENT_RE.match(name):
        raise WatcherError(f"{what} inválido: usa solo letras, números y guión bajo")
    return name


def _quoted_table(schema_name: str | None, table_name: str) -> str:
    table = _safe_ident(table_name, "tabla")
    schema = str(schema_name or "").strip()
    if schema:
        return f'"{_safe_ident(schema, "esquema")}"."{table}"'
    return f'"{table}"'


def engine_operator(raw: str) -> str:
    """Acepta operador canónico del Condition Builder o del engine."""
    text_value = str(raw or "==").strip()
    if text_value in {"==", "!=", ">", ">=", "<", "<=", "contains", "not_contains",
                      "starts_with", "ends_with", "is_empty", "not_empty", "changed"}:
        return text_value
    canonical = normalize_operator(text_value)
    return CANONICAL_TO_ENGINE[canonical.value]


class WatcherCondition(BaseModel):
    model_config = MODEL_CONFIG

    field: str = Field(min_length=1, max_length=80)
    operator: str = Field(default="<", max_length=40)
    value: Any = None

    @model_validator(mode="after")
    def _normalize(self) -> "WatcherCondition":
        self.field = _safe_ident(self.field, "campo")
        self.operator = engine_operator(self.operator)
        return self


class WatcherDefinition(BaseModel):
    """Definición persistible de un data watcher (misión §12)."""

    model_config = MODEL_CONFIG

    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=600)
    source_id: UUID | None = None
    strategy: Literal[
        "watermark_polling", "timestamp_polling", "query_watch", "application_event", "webhook"
    ] = "watermark_polling"
    entity: str = Field(default="registro", max_length=80)
    schema_name: str | None = Field(default=None, max_length=63)
    table_name: str = Field(min_length=1, max_length=63)
    primary_key: str | None = Field(default=None, max_length=63)
    timestamp_field: str | None = Field(default=None, max_length=63)
    selected_fields: list[str] = Field(default_factory=list, max_length=50)
    condition: WatcherCondition
    transition_mode: Literal["on_change", "on_enter", "on_exit", "while_true"] = "on_enter"
    interval_seconds: int = Field(default=300, ge=60, le=86_400)
    cooldown_seconds: int = Field(default=0, ge=0, le=604_800)
    debounce_seconds: int = Field(default=0, ge=0, le=86_400)
    event_type: str = Field(default="", max_length=160)
    entity_field: str | None = Field(default=None, max_length=63)
    workflow_id: UUID | None = None
    status: Literal["listening", "checking", "error", "paused"] = "listening"

    @model_validator(mode="after")
    def _validate(self) -> "WatcherDefinition":
        _safe_ident(self.table_name, "tabla")
        if self.primary_key:
            self.primary_key = _safe_ident(self.primary_key, "primary_key")
        if self.timestamp_field:
            self.timestamp_field = _safe_ident(self.timestamp_field, "timestamp_field")
        if self.entity_field:
            self.entity_field = _safe_ident(self.entity_field, "entity_field")
        self.selected_fields = [_safe_ident(f, "campo") for f in self.selected_fields]
        if self.strategy in POLLING_STRATEGIES:
            if not self.primary_key and not self.timestamp_field:
                raise WatcherError("un watcher de polling necesita primary_key o timestamp_field")
            if self.strategy == "timestamp_polling" and not self.timestamp_field:
                raise WatcherError("timestamp_polling necesita timestamp_field")
        if not self.event_type:
            slug = re.sub(r"[^a-z0-9]+", ".", f"watcher.{self.entity}".lower()).strip(".")
            self.event_type = f"{slug}.changed"
        return self


class WatcherState(BaseModel):
    """Estado incremental del watcher (misión §14)."""

    model_config = MODEL_CONFIG

    last_value: dict[str, Any] = Field(default_factory=dict)
    last_payload: dict[str, Any] = Field(default_factory=dict)
    last_condition_result: bool | None = None
    last_event_at: datetime | None = None
    last_triggered_at: datetime | None = None
    checkpoint: dict[str, Any] = Field(default_factory=dict)
    cooldown_until: datetime | None = None
    pending_since: datetime | None = None
    failure_count: int = 0
    last_error: str | None = None
    last_dedupe_key: str | None = None
    last_check_at: datetime | None = None
    check_count: int = 0
    trigger_count: int = 0


# ---------------------------------------------------------------------------
# Decisión pura (testeable sin I/O)
# ---------------------------------------------------------------------------
def should_fire(
    mode: str,
    previous_result: bool | None,
    current_result: bool,
    *,
    changed: bool,
    condition_present: bool,
) -> tuple[bool, str]:
    """Decide si el cambio merece disparar el workflow.

    - on_enter: false→true
    - on_exit: true→false
    - on_change: cambió un valor vigilado (la condición no filtra)
    - while_true: la condición es verdadera en cada check (cooldown controla)
    """
    if mode == "on_change":
        if changed:
            return True, "cambió un valor vigilado"
        return False, "los valores vigilados no cambiaron"
    if not condition_present:
        return False, "el watcher no tiene condición"
    if mode == "while_true":
        if current_result:
            return True, "la condición sigue cumpliéndose"
        return False, "la condición ya no se cumple"
    previous = bool(previous_result)
    if mode == "on_exit":
        if previous and not current_result:
            return True, "la condición dejó de cumplirse (recuperación)"
        return False, "la condición no pasó de cumplirse a no cumplirse"
    # on_enter (default)
    if not previous and current_result:
        return True, "la condición empezó a cumplirse"
    if previous and current_result:
        return False, "la condición ya se cumplía antes"
    return False, "la condición no se cumple"


def should_suppress_by_cooldown(state: WatcherState, now: datetime) -> bool:
    return state.cooldown_until is not None and state.cooldown_until > now


def debounce_ready(state: WatcherState, debounce_seconds: int, now: datetime) -> tuple[bool, WatcherState]:
    """Aplica debounce: la condición debe sostenerse N segundos antes de disparar."""
    if debounce_seconds <= 0:
        return True, state
    if state.pending_since is None:
        state.pending_since = now
        return False, state
    return (now - state.pending_since) >= timedelta(seconds=debounce_seconds), state


# ---------------------------------------------------------------------------
# Persistencia
# ---------------------------------------------------------------------------
_DDL_DEFINITIONS = """
CREATE TABLE IF NOT EXISTS workflow_watchers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    workspace_id UUID,
    name VARCHAR(160) NOT NULL,
    description TEXT,
    source_id UUID,
    strategy VARCHAR(30) NOT NULL DEFAULT 'watermark_polling',
    entity VARCHAR(80) NOT NULL DEFAULT 'registro',
    schema_name VARCHAR(63),
    table_name VARCHAR(63) NOT NULL,
    primary_key VARCHAR(63),
    timestamp_field VARCHAR(63),
    selected_fields JSONB NOT NULL DEFAULT '[]',
    condition JSONB NOT NULL DEFAULT '{}',
    transition_mode VARCHAR(20) NOT NULL DEFAULT 'on_enter',
    interval_seconds INT NOT NULL DEFAULT 300,
    cooldown_seconds INT NOT NULL DEFAULT 0,
    debounce_seconds INT NOT NULL DEFAULT 0,
    event_type VARCHAR(160) NOT NULL DEFAULT '',
    entity_field VARCHAR(63),
    workflow_id UUID,
    status VARCHAR(20) NOT NULL DEFAULT 'listening',
    created_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_check_at TIMESTAMPTZ
)
"""

_DDL_STATES = """
CREATE TABLE IF NOT EXISTS workflow_watcher_states (
    watcher_id UUID PRIMARY KEY REFERENCES workflow_watchers(id) ON DELETE CASCADE,
    organization_id UUID NOT NULL,
    last_value JSONB NOT NULL DEFAULT '{}',
    last_payload JSONB NOT NULL DEFAULT '{}',
    last_condition_result BOOLEAN,
    last_event_at TIMESTAMPTZ,
    last_triggered_at TIMESTAMPTZ,
    checkpoint JSONB NOT NULL DEFAULT '{}',
    cooldown_until TIMESTAMPTZ,
    pending_since TIMESTAMPTZ,
    failure_count INT NOT NULL DEFAULT 0,
    last_error TEXT,
    last_dedupe_key VARCHAR(300),
    last_check_at TIMESTAMPTZ,
    check_count INT NOT NULL DEFAULT 0,
    trigger_count INT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""

_DDL_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_workflow_watchers_org ON workflow_watchers(organization_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_workflow_watchers_due ON workflow_watchers(status, last_check_at)",
)

_READ_FIELDS = (
    "id, organization_id, workspace_id, name, description, source_id, strategy, entity, "
    "schema_name, table_name, primary_key, timestamp_field, selected_fields, condition, "
    "transition_mode, interval_seconds, cooldown_seconds, debounce_seconds, event_type, "
    "entity_field, workflow_id, status, created_by, created_at, updated_at, last_check_at"
)

_TABLE_MISSING = ("workflow_watchers", "workflow_watcher_states")


async def ensure_watcher_tables() -> None:
    """Crea las tablas si la base es anterior a la migración 110 (fail-silent)."""
    session = await get_async_session()
    try:
        await session.execute(text(_DDL_DEFINITIONS))
        await session.execute(text(_DDL_STATES))
        for statement in _DDL_INDEXES:
            await session.execute(text(statement))
        await session.commit()
    except Exception:  # noqa: BLE001
        await session.rollback()
        logger.warning("Failed to ensure watcher tables")
    finally:
        await session.close()


def _row_to_definition(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "organization_id": str(row.organization_id),
        "workspace_id": str(row.workspace_id) if row.workspace_id else None,
        "name": row.name,
        "description": row.description,
        "source_id": str(row.source_id) if row.source_id else None,
        "strategy": row.strategy,
        "entity": row.entity,
        "schema_name": row.schema_name,
        "table_name": row.table_name,
        "primary_key": row.primary_key,
        "timestamp_field": row.timestamp_field,
        "selected_fields": row.selected_fields or [],
        "condition": row.condition or {},
        "transition_mode": row.transition_mode,
        "interval_seconds": int(row.interval_seconds),
        "cooldown_seconds": int(row.cooldown_seconds),
        "debounce_seconds": int(row.debounce_seconds),
        "event_type": row.event_type,
        "entity_field": row.entity_field,
        "workflow_id": str(row.workflow_id) if row.workflow_id else None,
        "status": row.status,
        "created_by": str(row.created_by) if row.created_by else None,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
        "last_check_at": row.last_check_at.isoformat() if row.last_check_at else None,
    }


def _row_to_state(row: Any) -> dict[str, Any]:
    if row is None:
        return WatcherState().model_dump(mode="json")
    return {
        "last_value": row.last_value or {},
        "last_payload": row.last_payload or {},
        "last_condition_result": row.last_condition_result,
        "last_event_at": row.last_event_at.isoformat() if row.last_event_at else None,
        "last_triggered_at": row.last_triggered_at.isoformat() if row.last_triggered_at else None,
        "checkpoint": row.checkpoint or {},
        "cooldown_until": row.cooldown_until.isoformat() if row.cooldown_until else None,
        "pending_since": row.pending_since.isoformat() if row.pending_since else None,
        "failure_count": int(row.failure_count),
        "last_error": row.last_error,
        "last_dedupe_key": row.last_dedupe_key,
        "last_check_at": row.last_check_at.isoformat() if row.last_check_at else None,
        "check_count": int(row.check_count),
        "trigger_count": int(row.trigger_count),
    }


async def create_watcher(
    organization_id: UUID,
    definition: WatcherDefinition,
    *,
    workspace_id: UUID | None = None,
    created_by: UUID | None = None,
) -> dict[str, Any]:
    await ensure_watcher_tables()
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO workflow_watchers (id, organization_id, workspace_id, name, "  # noqa: S608 (constantes)
                    "description, source_id, strategy, entity, schema_name, table_name, "
                    "primary_key, timestamp_field, selected_fields, condition, transition_mode, "
                    "interval_seconds, cooldown_seconds, debounce_seconds, event_type, "
                    "entity_field, workflow_id, status, created_by) "
                    "VALUES (gen_random_uuid(), :oid, :ws, :name, :desc, :source, :strategy, "
                    ":entity, :schema, :table, :pk, :ts, CAST(:fields AS jsonb), "
                    "CAST(:condition AS jsonb), :mode, :interval, :cooldown, :debounce, "
                    ":etype, :efield, :wid, :status, :by) "
                    f"RETURNING {_READ_FIELDS}"  # noqa: S608 (constante)
                ),
                {
                    "oid": organization_id,
                    "ws": workspace_id,
                    "name": definition.name,
                    "desc": definition.description,
                    "source": definition.source_id,
                    "strategy": definition.strategy,
                    "entity": definition.entity,
                    "schema": definition.schema_name,
                    "table": definition.table_name,
                    "pk": definition.primary_key,
                    "ts": definition.timestamp_field,
                    "fields": json.dumps(definition.selected_fields),
                    "condition": json.dumps(definition.condition.model_dump(mode="json")),
                    "mode": definition.transition_mode,
                    "interval": definition.interval_seconds,
                    "cooldown": definition.cooldown_seconds,
                    "debounce": definition.debounce_seconds,
                    "etype": definition.event_type,
                    "efield": definition.entity_field,
                    "wid": definition.workflow_id,
                    "status": definition.status,
                    "by": created_by,
                },
            )
        ).fetchone()
        await session.commit()
    finally:
        await session.close()
    return _row_to_definition(row)


async def list_watchers(
    organization_id: UUID, workspace_id: UUID | None = None
) -> list[dict[str, Any]]:
    await ensure_watcher_tables()
    session = await get_async_session()
    try:
        sql = f"SELECT {_READ_FIELDS} FROM workflow_watchers WHERE organization_id = :oid"  # noqa: S608 (constante)
        params: dict[str, Any] = {"oid": organization_id}
        if workspace_id is not None:
            sql += " AND (workspace_id = :ws OR workspace_id IS NULL)"
            params["ws"] = workspace_id
        rows = (await session.execute(text(sql + " ORDER BY created_at DESC"), params)).fetchall()
    finally:
        await session.close()
    return [_row_to_definition(r) for r in rows]


async def get_watcher(organization_id: UUID, watcher_id: UUID) -> dict[str, Any] | None:
    await ensure_watcher_tables()
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    f"SELECT {_READ_FIELDS} FROM workflow_watchers "  # noqa: S608 (constante)
                    "WHERE id = :wid AND organization_id = :oid"
                ),
                {"wid": watcher_id, "oid": organization_id},
            )
        ).fetchone()
    finally:
        await session.close()
    return _row_to_definition(row) if row is not None else None


async def get_watcher_state(organization_id: UUID, watcher_id: UUID) -> dict[str, Any] | None:
    await ensure_watcher_tables()
    session = await get_async_session()
    try:
        watcher = (
            await session.execute(
                text("SELECT id FROM workflow_watchers WHERE id = :wid AND organization_id = :oid"),
                {"wid": watcher_id, "oid": organization_id},
            )
        ).fetchone()
        if watcher is None:
            return None
        row = (
            await session.execute(
                text("SELECT * FROM workflow_watcher_states WHERE watcher_id = :wid"),
                {"wid": watcher_id},
            )
        ).fetchone()
    finally:
        await session.close()
    return _row_to_state(row)


async def update_watcher_status(
    organization_id: UUID, watcher_id: UUID, status: str
) -> dict[str, Any] | None:
    if status not in WATCHER_STATUSES:
        raise WatcherError(f"status inválido: {status}")
    return await update_watcher(organization_id, watcher_id, {"status": status})


async def update_watcher(
    organization_id: UUID, watcher_id: UUID, fields: dict[str, Any]
) -> dict[str, Any] | None:
    """Actualiza campos permitidos (whitelist) del watcher."""
    allowed = {
        "name",
        "description",
        "strategy",
        "entity",
        "schema_name",
        "table_name",
        "primary_key",
        "timestamp_field",
        "selected_fields",
        "condition",
        "transition_mode",
        "interval_seconds",
        "cooldown_seconds",
        "debounce_seconds",
        "event_type",
        "entity_field",
        "workflow_id",
        "status",
    }
    updates = {k: v for k, v in (fields or {}).items() if k in allowed and v is not None}
    if not updates:
        return await get_watcher(organization_id, watcher_id)
    if "status" in updates and updates["status"] not in WATCHER_STATUSES:
        raise WatcherError(f"status inválido: {updates['status']}")
    await ensure_watcher_tables()
    session = await get_async_session()
    try:
        sets: list[str] = []
        params: dict[str, Any] = {"wid": watcher_id, "oid": organization_id}
        for key, value in updates.items():
            if key in ("selected_fields", "condition"):
                sets.append(f"{key} = CAST(:{key} AS jsonb)")
                params[key] = json.dumps(value)
            else:
                sets.append(f"{key} = :{key}")
                params[key] = value
        sets.append("updated_at = NOW()")
        row = (
            await session.execute(
                text(
                    f"UPDATE workflow_watchers SET {', '.join(sets)} "  # noqa: S608 (whitelist)
                    f"WHERE id = :wid AND organization_id = :oid RETURNING {_READ_FIELDS}"
                ),
                params,
            )
        ).fetchone()
        await session.commit()
    finally:
        await session.close()
    return _row_to_definition(row) if row is not None else None


async def delete_watcher(organization_id: UUID, watcher_id: UUID) -> bool:
    await ensure_watcher_tables()
    session = await get_async_session()
    try:
        result = await session.execute(
            text("DELETE FROM workflow_watchers WHERE id = :wid AND organization_id = :oid"),
            {"wid": watcher_id, "oid": organization_id},
        )
        await session.commit()
        return result.rowcount > 0
    finally:
        await session.close()


async def _save_state(
    organization_id: UUID, watcher_id: UUID, state: WatcherState
) -> None:
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO workflow_watcher_states (watcher_id, organization_id, last_value, "
                "last_payload, last_condition_result, last_event_at, last_triggered_at, checkpoint, "
                "cooldown_until, pending_since, failure_count, last_error, last_dedupe_key, "
                "last_check_at, check_count, trigger_count, updated_at) "
                "VALUES (:wid, :oid, CAST(:last_value AS jsonb), CAST(:last_payload AS jsonb), "
                ":result, :event_at, :triggered_at, CAST(:checkpoint AS jsonb), :cooldown, "
                ":pending, :failures, :error, :dedupe, :checked_at, :checks, :triggers, NOW()) "
                "ON CONFLICT (watcher_id) DO UPDATE SET last_value = EXCLUDED.last_value, "
                "last_payload = EXCLUDED.last_payload, "
                "last_condition_result = EXCLUDED.last_condition_result, "
                "last_event_at = EXCLUDED.last_event_at, "
                "last_triggered_at = EXCLUDED.last_triggered_at, "
                "checkpoint = EXCLUDED.checkpoint, cooldown_until = EXCLUDED.cooldown_until, "
                "pending_since = EXCLUDED.pending_since, failure_count = EXCLUDED.failure_count, "
                "last_error = EXCLUDED.last_error, last_dedupe_key = EXCLUDED.last_dedupe_key, "
                "last_check_at = EXCLUDED.last_check_at, check_count = EXCLUDED.check_count, "
                "trigger_count = EXCLUDED.trigger_count, updated_at = NOW()"
            ),
            {
                "wid": watcher_id,
                "oid": organization_id,
                "last_value": json.dumps(state.last_value, default=str),
                "last_payload": json.dumps(state.last_payload, default=str),
                "result": state.last_condition_result,
                "event_at": state.last_event_at,
                "triggered_at": state.last_triggered_at,
                "checkpoint": json.dumps(state.checkpoint, default=str),
                "cooldown": state.cooldown_until,
                "pending": state.pending_since,
                "failures": state.failure_count,
                "error": state.last_error,
                "dedupe": state.last_dedupe_key,
                "checked_at": state.last_check_at,
                "checks": state.check_count,
                "triggers": state.trigger_count,
            },
        )
        await session.commit()
    finally:
        await session.close()


async def _mark_checked(organization_id: UUID, watcher_id: UUID) -> None:
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "UPDATE workflow_watchers SET last_check_at = NOW(), updated_at = NOW() "
                "WHERE id = :wid AND organization_id = :oid"
            ),
            {"wid": watcher_id, "oid": organization_id},
        )
        await session.commit()
    finally:
        await session.close()


# ---------------------------------------------------------------------------
# Query incremental
# ---------------------------------------------------------------------------
async def _default_query_runner(sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    """Reader-only session existente: managed DB o fallback readonly interno."""
    from src.infrastructure.postgres.readonly_session import (
        apply_readonly_transaction,
        get_readonly_session,
    )
    from src.platform.managed_db.service import open_managed_query_session

    session = None
    org_raw = params.get("organization_id")
    if org_raw:
        try:
            session = await open_managed_query_session(UUID(str(org_raw)))
        except Exception as exc:  # noqa: BLE001
            logger.warning("watcher managed session skipped", error=str(exc)[:150])
            session = None
    if session is None:
        session = await get_readonly_session()
    try:
        await apply_readonly_transaction(session, 10)
        result = await session.execute(text(sql), params)
        return [dict(row._mapping) for row in result.fetchall()]
    finally:
        await session.close()


def build_incremental_sql(watcher: dict[str, Any], checkpoint: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """SQL acotado con cursor; nunca full scan ni SQL libre del usuario."""
    table = _quoted_table(watcher.get("schema_name"), watcher["table_name"])
    selected = [_safe_ident(f, "campo") for f in (watcher.get("selected_fields") or [])]
    condition_field = _safe_ident(str((watcher.get("condition") or {}).get("field") or ""), "campo")
    pk = watcher.get("primary_key")
    ts = watcher.get("timestamp_field")
    columns: list[str] = []
    for candidate in [pk, ts, condition_field, *(watcher.get("entity_field"),), *selected]:
        if candidate and candidate not in columns:
            columns.append(candidate)
    if not columns:
        raise WatcherError("el watcher no tiene columnas para consultar")
    col_sql = ", ".join(f'"{c}"' for c in columns)

    strategy = watcher.get("strategy") or "watermark_polling"
    params: dict[str, Any] = {"limit": min(int(watcher.get("limit") or MAX_ROWS_PER_CHECK), MAX_CHECK_LIMIT)}
    if ts and (strategy == "timestamp_polling" or not pk):
        cursor = checkpoint.get("timestamp")
        where = f'WHERE "{ts}" > :cursor' if cursor else ""
        params["cursor"] = cursor or datetime(1970, 1, 1, tzinfo=timezone.utc)
        sql = f"SELECT {col_sql} FROM {table} {where} ORDER BY \"{ts}\" ASC LIMIT :limit"  # noqa: S608 (identificadores validados)
        return sql, params
    if not pk:
        raise WatcherError("watermark_polling necesita primary_key")
    cursor = checkpoint.get("pk")
    where = f'WHERE "{pk}" > :cursor' if cursor is not None else ""
    params.pop("cursor", None)
    if cursor is not None:
        params["cursor"] = cursor
    sql = f"SELECT {col_sql} FROM {table} {where} ORDER BY \"{pk}\" ASC LIMIT :limit"  # noqa: S608 (identificadores validados)
    return sql, params


def _new_checkpoint(
    watcher: dict[str, Any], row: dict[str, Any], previous: dict[str, Any]
) -> dict[str, Any]:
    checkpoint = dict(previous or {})
    pk = watcher.get("primary_key")
    ts = watcher.get("timestamp_field")
    if pk and row.get(pk) is not None:
        checkpoint["pk"] = row.get(pk)
    if ts and row.get(ts) is not None:
        value = row.get(ts)
        checkpoint["timestamp"] = value.isoformat() if isinstance(value, datetime) else str(value)
    return checkpoint


# ---------------------------------------------------------------------------
# Check
# ---------------------------------------------------------------------------
@dataclass
class CheckOutcome:
    status: str
    reason: str
    watcher_id: str
    transition: str | None = None
    before: dict[str, Any] = field(default_factory=dict)
    after: dict[str, Any] = field(default_factory=dict)
    changed_fields: list[str] = field(default_factory=list)
    condition_result: bool | None = None
    event: dict[str, Any] | None = None
    triggered: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "watcher_id": self.watcher_id,
            "transition": self.transition,
            "before": self.before,
            "after": self.after,
            "changed_fields": self.changed_fields,
            "condition_result": self.condition_result,
            "event": self.event,
            "triggered": self.triggered,
        }


def evaluate_row_condition(condition: dict[str, Any], row: dict[str, Any]) -> bool:
    field = str(condition.get("field") or "")
    operator = engine_operator(str(condition.get("operator") or "=="))
    return bool(_eval_condition(row.get(field), operator, condition.get("value")))


async def check_watcher(
    organization_id: UUID,
    watcher_id: UUID,
    *,
    query_runner: QueryRunner | None = None,
    now: datetime | None = None,
    force: bool = False,
) -> CheckOutcome | None:
    """Ejecuta un check incremental. None si el watcher no existe en la org."""
    now = now or datetime.now(timezone.utc)
    watcher = await get_watcher(organization_id, watcher_id)
    if watcher is None:
        return None
    outcome = CheckOutcome(status="no_change", reason="", watcher_id=str(watcher_id))

    if watcher["status"] == "paused" and not force:
        outcome.status = "skipped"
        outcome.reason = "El watcher está en pausa."
        return outcome
    if watcher["strategy"] not in POLLING_STRATEGIES:
        outcome.status = "skipped"
        outcome.reason = "La estrategia no requiere polling (evento/webhook)."
        return outcome

    state_payload = await get_watcher_state(organization_id, watcher_id)
    state = WatcherState.model_validate(state_payload)
    outcome.before = dict(state.last_value or {})

    if should_suppress_by_cooldown(state, now) and not force:
        outcome.status = "cooldown"
        outcome.reason = "En enfriamiento: no se vuelve a avisar todavía."
        outcome.condition_result = state.last_condition_result
        await _save_state(organization_id, watcher_id, state)
        return outcome

    runner = query_runner or _default_query_runner
    try:
        sql, params = build_incremental_sql(watcher, state.checkpoint)
        params["organization_id"] = str(organization_id)
        rows = await runner(sql, params)
    except Exception as exc:  # noqa: BLE001
        state.failure_count += 1
        state.last_error = str(exc)[:300]
        state.last_check_at = now
        await _save_state(organization_id, watcher_id, state)
        await _mark_checked(organization_id, watcher_id)
        if state.failure_count >= 5:
            await update_watcher_status(organization_id, watcher_id, "error")
        outcome.status = "error"
        outcome.reason = f"No pude revisar los datos: {state.last_error}"
        return outcome

    state.check_count += 1
    state.last_check_at = now
    state.failure_count = 0
    state.last_error = None
    if watcher.get("status") == "error":
        # Se recupera solo: vuelve a escuchar cuando el check funciona.
        await update_watcher_status(organization_id, watcher_id, "listening")

    if not rows:
        outcome.status = "no_change"
        outcome.reason = "Sin filas nuevas desde la última revisión."
        outcome.condition_result = state.last_condition_result
        await _save_state(organization_id, watcher_id, state)
        await _mark_checked(organization_id, watcher_id)
        return outcome

    row = dict(rows[-1])
    projected = {
        key: (value.isoformat() if isinstance(value, datetime) else value)
        for key, value in row.items()
        if key in (watcher.get("selected_fields") or []) or key == watcher.get("entity_field")
    }
    condition_result = evaluate_row_condition(watcher.get("condition") or {}, row)
    previous_projected = {
        key: value for key, value in (state.last_value or {}).items() if key in projected
    }
    changed = bool(previous_projected) and any(
        previous_projected.get(key) != value for key, value in projected.items()
    )
    previous_result = state.last_condition_result

    fire, why = should_fire(
        watcher.get("transition_mode") or "on_enter",
        previous_result,
        condition_result,
        changed=changed,
        condition_present=bool(watcher.get("condition")),
    )
    outcome.condition_result = condition_result

    if not fire:
        state.last_condition_result = condition_result
        state.last_value = {**state.last_value, **projected}
        state.pending_since = None
        state.checkpoint = _new_checkpoint(watcher, row, state.checkpoint)
        outcome.status = "condition_false" if not condition_result else "no_change"
        outcome.reason = f"No se ejecutó porque {why}."
        outcome.after = projected
        await _save_state(organization_id, watcher_id, state)
        await _mark_checked(organization_id, watcher_id)
        return outcome

    debounce_seconds = int(watcher.get("debounce_seconds") or 0)
    ready, state = debounce_ready(state, debounce_seconds, now)
    if not ready and not force:
        state.last_condition_result = condition_result
        state.last_value = {**state.last_value, **projected}
        outcome.status = "debounce"
        outcome.reason = (
            f"La condición se cumple, pero debe sostenerse {debounce_seconds} segundos antes de avisar."
        )
        await _save_state(organization_id, watcher_id, state)
        await _mark_checked(organization_id, watcher_id)
        return outcome

    before_data = dict(state.last_value or {})
    after_data = {**before_data, **projected}
    transition_before = previous_result
    event: BusinessEvent = build_business_event(
        organization_id=organization_id,
        event_type=watcher.get("event_type") or "watcher.changed",
        source="watcher",
        workspace_id=UUID(watcher["workspace_id"]) if watcher.get("workspace_id") else None,
        source_id=str(watcher_id),
        entity_type=watcher.get("entity"),
        entity_id=str(
            projected.get(watcher.get("entity_field") or "")
            or row.get(watcher.get("primary_key") or "")
            or ""
        )
        or None,
        operation="transition",
        before=before_data,
        after=after_data,
        metadata={
            "watcher_id": str(watcher_id),
            "way": why,
            "condition": watcher.get("condition"),
            "transition_mode": watcher.get("transition_mode"),
            "transition": _transition_name(transition_before, condition_result),
        },
    )
    outcome.transition = _transition_name(transition_before, condition_result)
    outcome.after = after_data
    outcome.changed_fields = event.changed_fields

    if event.dedupe_key and state.last_dedupe_key == event.dedupe_key:
        state.last_condition_result = condition_result
        state.last_value = after_data
        state.pending_since = None
        state.checkpoint = _new_checkpoint(watcher, row, state.checkpoint)
        outcome.status = "deduplicated"
        outcome.reason = "El evento ya se había entregado; no se repite."
        await _save_state(organization_id, watcher_id, state)
        await _mark_checked(organization_id, watcher_id)
        return outcome

    from src.platform.workflows.events import dispatch_event_to_workflows

    fired = 0
    try:
        fired = await dispatch_event_to_workflows(
            f"{event.event_type}@v{event.event_version}", event.to_dispatch_payload()
        )
    except Exception as exc:  # noqa: BLE001
        state.failure_count += 1
        state.last_error = str(exc)[:300]
        logger.warning("watcher dispatch failed", watcher_id=str(watcher_id), error=str(exc)[:200])

    state.last_value = after_data
    state.last_payload = event.to_dispatch_payload()
    state.last_condition_result = condition_result
    state.last_event_at = now
    state.pending_since = None
    state.checkpoint = _new_checkpoint(watcher, row, state.checkpoint)
    state.last_dedupe_key = event.dedupe_key
    if fired:
        state.last_triggered_at = now
        state.trigger_count += 1
        cooldown = int(watcher.get("cooldown_seconds") or 0)
        if cooldown > 0:
            state.cooldown_until = now + timedelta(seconds=cooldown)
    if state.failure_count:
        state.failure_count = 0
    await _save_state(organization_id, watcher_id, state)
    await _mark_checked(organization_id, watcher_id)

    outcome.status = "triggered" if fired else "no_trigger"
    outcome.reason = (
        f"Workflow activado: {why}."
        if fired
        else "No hay automatizaciones suscritas a este evento."
    )
    outcome.event = event.to_dict()
    outcome.triggered = fired > 0
    return outcome


def _transition_name(before: bool | None, after: bool) -> str:
    from src.platform.workflows.business_events import transition_of

    return transition_of(before, after)


# ---------------------------------------------------------------------------
# Loop
# ---------------------------------------------------------------------------
async def run_due_watchers(now: datetime | None = None, limit: int = 50) -> dict[str, Any]:
    """Revisa watchers cuyo intervalo venció (fail-soft por watcher)."""
    now = now or datetime.now(timezone.utc)
    await ensure_watcher_tables()
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT id, organization_id, interval_seconds, last_check_at FROM workflow_watchers "
                    "WHERE status IN ('listening', 'error') ORDER BY last_check_at NULLS FIRST LIMIT :limit"
                ),
                {"limit": min(int(limit), MAX_CHECK_LIMIT)},
            )
        ).fetchall()
    except Exception as exc:  # noqa: BLE001
        logger.warning("watchers query failed", error=str(exc)[:150])
        return {"checked": 0, "triggered": 0, "skipped": 0}
    finally:
        await session.close()

    checked = triggered = skipped = 0
    for row in rows:
        last = row.last_check_at
        if last is not None and last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        interval = max(int(row.interval_seconds or 300), 60)
        if last is not None and (now - last) < timedelta(seconds=interval):
            skipped += 1
            continue
        try:
            outcome = await check_watcher(row.organization_id, row.id, now=now)
        except Exception as exc:  # noqa: BLE001
            logger.warning("watcher check failed", watcher_id=str(row.id), error=str(exc)[:200])
            continue
        if outcome is None:
            continue
        checked += 1
        if outcome.triggered:
            triggered += 1
    result = {"checked": checked, "triggered": triggered, "skipped": skipped}
    _emit_watcher_metrics(result)
    return result


def _emit_watcher_metrics(result: dict[str, Any]) -> None:
    """Métricas fail-soft (los nombres viven en observability.py)."""
    try:
        from src.platform.workflows.observability import (
            workflow_watcher_checks_total,
            workflow_watcher_transitions_total,
        )

        if workflow_watcher_checks_total is not None:
            workflow_watcher_checks_total.labels(outcome="checked").inc(result.get("checked", 0))
            workflow_watcher_checks_total.labels(outcome="skipped").inc(result.get("skipped", 0))
        if workflow_watcher_transitions_total is not None:
            workflow_watcher_transitions_total.inc(result.get("triggered", 0))
    except Exception:  # noqa: BLE001
        pass


async def watcher_scheduler_loop() -> None:
    """Tick cada 60s; el intervalo real lo define cada watcher."""
    import asyncio

    while True:
        try:
            await run_due_watchers()
        except Exception as exc:  # noqa: BLE001
            logger.warning("watcher scheduler iteration failed", error=str(exc)[:200])
        await asyncio.sleep(60)


__all__ = [
    "CheckOutcome",
    "MAX_ROWS_PER_CHECK",
    "POLLING_STRATEGIES",
    "TRANSITION_MODES",
    "WATCHER_STATUSES",
    "WATCHER_STRATEGIES",
    "WatcherCondition",
    "WatcherDefinition",
    "WatcherError",
    "WatcherState",
    "build_incremental_sql",
    "check_watcher",
    "create_watcher",
    "delete_watcher",
    "ensure_watcher_tables",
    "evaluate_row_condition",
    "get_watcher",
    "get_watcher_state",
    "list_watchers",
    "run_due_watchers",
    "should_fire",
    "should_suppress_by_cooldown",
    "update_watcher_status",
    "watcher_scheduler_loop",
]
