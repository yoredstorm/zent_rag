# =============================================================================
# Capability dispatcher — executes an authorized RoutingDecision.
# =============================================================================
# The Decision Engine only recommends. This module maps a capability id onto a
# registered handler (agent runtime, workflow engine, tool registry, RAG
# orchestrator, SQL expert, LLM) and runs it with an explicit, tenant-scoped
# request. Handlers are registered by the composition root (src/api/deps.py):
# the runtime layer never imports api/agents/platform.
# =============================================================================
from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from src.core.domain.decision import RoutingDecision
from src.core.domain.runtime import RuntimeStep
from src.decision.capabilities import InMemoryCapabilityRegistry
from src.runtime.executor import CapabilityExecutor

DispatchHandler = Callable[["DispatchRequest", RoutingDecision], Awaitable["DispatchResult"]]

# Capability family -> request field that must carry a concrete target.
TARGET_REQUIREMENTS: dict[str, str] = {
    "agent.execute": "agent_id",
    "agent.reason": "agent_id",
    "agent.delegate": "agent_id",
    "workflow.start": "workflow_id",
    "workflow.execute": "workflow_id",
    "workflow.resume": "run_id",
    "tool.call_api": "tool",
    "api.request": "tool",
    "tool.send_email": "tool",
    "email.send": "tool",
    "tool.execute": "tool",
}

_STATUS_COMPLETED = "completed"
_STATUS_NEEDS_TARGET = "needs_target"
_STATUS_UNAVAILABLE = "unavailable"
_STATUS_DENIED = "denied"
_STATUS_FAILED = "failed"


@dataclass(kw_only=True)
class DispatchRequest:
    """Execution surface for one capability. Never contains model-controlled
    identity: tenant, user and role come from the authenticated request."""

    organization_id: UUID
    user_id: UUID | None = None
    role: str = "admin"
    permissions: frozenset[str] = frozenset()
    query: str = ""
    conversation_id: UUID | None = None
    workspace_id: UUID | None = None
    agent_id: UUID | None = None
    workflow_id: UUID | None = None
    run_id: UUID | None = None
    tool: str | None = None
    tool_arguments: dict[str, Any] = field(default_factory=dict)
    org_config: dict = field(default_factory=dict)
    api_key_id: UUID | None = None
    on_delta: Callable[[str], Awaitable[None]] | None = None
    trace_id: str | None = None

    def target_value(self, capability: str) -> Any:
        field_name = TARGET_REQUIREMENTS.get(capability)
        if field_name is None:
            return None
        return getattr(self, field_name, None)


@dataclass(kw_only=True)
class DispatchResult:
    capability: str
    handler: str = ""
    status: str = _STATUS_COMPLETED
    answer: str = ""
    error: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    latency_ms: float = 0.0
    tokens: int = 0
    cost: float = 0.0
    run_id: str | None = None

    @property
    def completed(self) -> bool:
        return self.status == _STATUS_COMPLETED


class CapabilityDispatcher:
    """Maps authorized capabilities onto registered handlers."""

    def __init__(self, registry: InMemoryCapabilityRegistry | None = None) -> None:
        self._registry = registry or InMemoryCapabilityRegistry()
        self._registry.sync_tools()
        self._executor = CapabilityExecutor(self._registry)
        self._handlers: dict[str, DispatchHandler] = {}

    def register(self, handler_name: str, handler: DispatchHandler) -> None:
        self._handlers[handler_name] = handler

    def registered_handlers(self) -> tuple[str, ...]:
        return tuple(sorted(self._handlers))

    def handler_name(self, capability: str) -> str:
        return self._executor.handler_name(capability)

    def can_dispatch(self, capability: str) -> bool:
        return self.handler_name(capability) in self._handlers

    def type_requires_target(self, capability: str) -> bool:
        return TARGET_REQUIREMENTS.get(capability) is not None

    async def dispatch(
        self,
        decision: RoutingDecision,
        request: DispatchRequest,
    ) -> DispatchResult:
        started = time.perf_counter()
        capability = decision.capability

        if not decision.resolved:
            return self._finish(
                DispatchResult(
                    capability=capability,
                    status=_STATUS_UNAVAILABLE,
                    error="decision_not_resolved",
                ),
                started,
            )
        if decision.metadata.get("acting") is False:
            return self._finish(
                DispatchResult(
                    capability=capability,
                    status=_STATUS_UNAVAILABLE,
                    error="decision_is_observational",
                ),
                started,
            )

        handler = self.handler_name(capability)
        field_name = TARGET_REQUIREMENTS.get(capability)
        if field_name is not None and request.target_value(capability) in (None, ""):
            return self._finish(
                DispatchResult(
                    capability=capability,
                    handler=handler,
                    status=_STATUS_NEEDS_TARGET,
                    error=f"missing_target:{field_name}",
                ),
                started,
            )

        fn = self._handlers.get(handler)
        if fn is None:
            return self._finish(
                DispatchResult(
                    capability=capability,
                    handler=handler,
                    status=_STATUS_UNAVAILABLE,
                    error=f"handler_not_registered:{handler}",
                ),
                started,
            )

        try:
            result = await fn(request, decision)
        except Exception as exc:  # noqa: BLE001 — never break the caller
            return self._finish(
                DispatchResult(
                    capability=capability,
                    handler=handler,
                    status=_STATUS_FAILED,
                    error=f"{type(exc).__name__}: {exc}"[:300],
                ),
                started,
            )
        if not result.capability:
            result.capability = capability
        if not result.handler:
            result.handler = handler
        return self._finish(result, started)

    @staticmethod
    def _finish(result: DispatchResult, started: float) -> DispatchResult:
        if result.latency_ms <= 0:
            result.latency_ms = (time.perf_counter() - started) * 1000
        return result


def denied(
    capability: str,
    *,
    handler: str = "",
    reason: str = "permission_denied",
) -> DispatchResult:
    return DispatchResult(
        capability=capability,
        handler=handler,
        status=_STATUS_DENIED,
        error=reason,
    )


def execution_step(result: DispatchResult, *, duration_ms: float | None = None) -> RuntimeStep:
    """RuntimeStep for ExecutionState tracing."""
    status = "ok" if result.completed else "error"
    return RuntimeStep(
        name="execute",
        status=status,
        duration_ms=round(duration_ms if duration_ms is not None else result.latency_ms, 2),
        tokens=result.tokens,
        cost=result.cost,
        capability=result.capability,
        detail=result.handler if result.completed else (result.error or result.handler),
    )
