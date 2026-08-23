# =============================================================================
# MCP Server — Auditoría + usage de tool calls
# =============================================================================
# Cada tool call (ok, error o denegado) escribe:
#   1. audit_logs: mcp_client, tool, tenant, user, execution, cost, result.
#   2. usage_events (idempotente por call_id) + contadores Redis cuando la
#      tool consumió recursos (tokens/costo/retrieval).
# Nunca se persiste el texto del query/argumentos: solo metadata de
# ejecución. La auditoría falla en silencio (no rompe el flujo).
# =============================================================================
from __future__ import annotations

from src.infrastructure.observability.logging_config import get_logger
from src.mcp_server.context import McpCallIdentity
from src.platform.audit.service import AuditLogService
from src.platform.billing.pricing import extract_provider
from src.platform.usage.usage_engine import (
    UsageEvent,
    get_usage_counters,
    record_event,
)

logger = get_logger(__name__)


class McpAudit:
    """Registro de auditoría + usage para tool calls MCP."""

    async def record(
        self,
        identity: McpCallIdentity,
        *,
        status: str,  # ok | denied | error | quota
        latency_ms: float = 0.0,
        cost: float = 0.0,
        tokens: int = 0,
        retrieval_count: int = 0,
        model: str | None = None,
        error_code: str | None = None,
    ) -> None:
        await self._write_audit(
            identity,
            status=status,
            latency_ms=latency_ms,
            cost=cost,
            tokens=tokens,
            retrieval_count=retrieval_count,
            model=model,
            error_code=error_code,
        )
        if status == "ok":
            await self._write_usage(
                identity,
                cost=cost,
                tokens=tokens,
                retrieval_count=retrieval_count,
                model=model,
                latency_ms=latency_ms,
            )

    async def _write_audit(
        self,
        identity: McpCallIdentity,
        *,
        status: str,
        latency_ms: float,
        cost: float,
        tokens: int,
        retrieval_count: int,
        model: str | None,
        error_code: str | None,
    ) -> None:
        try:
            from src.infrastructure.postgres.relational_db import (
                PostgresAuditLogRepository,
            )

            service = AuditLogService(PostgresAuditLogRepository())
            await service.write(
                identity.tenant,
                action="mcp.tool_call",
                resource_type="mcp_tool",
                resource_id=identity.call_id,
                metadata={
                    "mcp_client": identity.mcp_client,
                    "tool": identity.tool,
                    "role": identity.role,
                    "execution_latency_ms": round(latency_ms, 2),
                    "cost": round(cost, 8),
                    "tokens": tokens,
                    "retrieval_count": retrieval_count,
                    "model": model or "",
                    "result": status,
                    "error_code": error_code or "",
                },
            )
        except Exception as exc:  # pragma: no cover - fail-silent
            logger.warning("MCP audit write failed", error=str(exc))

    async def _write_usage(
        self,
        identity: McpCallIdentity,
        *,
        cost: float,
        tokens: int,
        retrieval_count: int,
        model: str | None,
        latency_ms: float,
    ) -> None:
        if cost <= 0 and tokens <= 0 and retrieval_count <= 0:
            return
        try:
            event = UsageEvent(
                request_id=_call_id_uuid(identity.call_id),
                organization_id=identity.tenant.tenant_id,
                user_id=identity.tenant.user_id,
                event_type="mcp_tool",
                api_key_id=identity.tenant.token_id,
                model=model,
                provider=extract_provider(model or ""),
                total_tokens=tokens,
                retrieval_count=retrieval_count,
                latency_ms=latency_ms,
                status="completed",
                estimated_cost=cost,
                actual_cost=cost,
            )
            inserted = await record_event(event)
            if inserted:
                await get_usage_counters().record(
                    identity.tenant.tenant_id,
                    _call_id_uuid(identity.call_id),
                    tokens=tokens,
                    cost=cost,
                )
        except Exception as exc:  # pragma: no cover - fail-silent
            logger.warning("MCP usage write failed", error=str(exc))


def _call_id_uuid(call_id: str):
    from uuid import UUID

    try:
        return UUID(call_id)
    except ValueError:  # pragma: no cover - call_id es siempre uuid4
        from uuid import uuid4

        return uuid4()
