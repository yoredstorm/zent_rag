# =============================================================================
# Capability dispatcher — executes an authorized RoutingDecision.
# =============================================================================
# The Decision Engine only recommends. This module maps a capability id onto a
# registered handler (agent runtime, workflow engine, tool registry, RAG
# orchestrator, SQL expert, LLM) and runs it with an explicit, tenant-scoped
# request. Handlers are registered by the composition root (src/api/deps.py):
# the runtime layer never imports api/agents/platform.
#
# Judgment Fabric: cuando la capability exige target y el request no lo trae,
# `resolve_target` arma el CandidateSet autorizado (tenant + RBAC + fuentes +
# riesgo) y JEV elige dentro de él. La política re-autoriza después; el
# dispatcher nunca ejecuta un target que la política no autorizó.
# =============================================================================
from __future__ import annotations

import dataclasses
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from src.core.domain.decision import DecisionContext, RoutingDecision
from src.core.domain.runtime import RuntimeStep
from src.decision.candidates import (
    CandidateKind,
    CandidateRegistry,
    CandidateSet,
    candidate_kind_for_capability,
    candidate_policy_from_context,
    resolve_candidates,
)
from src.decision.capabilities import InMemoryCapabilityRegistry
from src.decision.policy import AuthorizedDecision, evaluate_policy
from src.decision.risk_policy import DecisionRiskPolicy
from src.decision.selection import (
    TargetSelection,
    record_candidate_set,
    record_target_selection,
    select_target,
    selection_outcome,
)
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
    request_id: UUID | None = None
    tenant_policy: dict[str, Any] = field(default_factory=dict)
    budget: dict[str, Any] = field(default_factory=dict)

    def target_value(self, capability: str) -> Any:
        field_name = TARGET_REQUIREMENTS.get(capability)
        if field_name is None:
            return None
        return getattr(self, field_name, None)


def with_target(request: DispatchRequest, kind: str, target_id: str) -> DispatchRequest:
    """Copia del request con el target elegido en el campo que corresponde."""
    field_name = {
        CandidateKind.AGENT.value: "agent_id",
        CandidateKind.WORKFLOW.value: "workflow_id",
        CandidateKind.TOOL.value: "tool",
    }.get(str(kind))
    if field_name is None:
        return request
    value: Any = target_id
    if field_name in {"agent_id", "workflow_id"}:
        try:
            value = UUID(str(target_id))
        except (ValueError, TypeError):
            return request
    return dataclasses.replace(request, **{field_name: value})


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
    prompt_tokens: int = 0
    completion_tokens: int = 0
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
        self._candidates: CandidateRegistry | None = None
        self._judge: Any = None
        self._risk_policy: DecisionRiskPolicy | None = None
        self._selection_mode = "off"
        self._judge_cache: Any = None

    def configure_target_selection(
        self,
        *,
        candidates: CandidateRegistry | None = None,
        judge: Any = None,
        risk_policy: DecisionRiskPolicy | None = None,
        mode: str = "off",
        cache: Any = None,
    ) -> None:
        """Inyectado por el composition root. `mode` off|shadow|on."""
        if candidates is not None:
            self._candidates = candidates
        if judge is not None:
            self._judge = judge
        if risk_policy is not None:
            self._risk_policy = risk_policy
        if cache is not None:
            self._judge_cache = cache
        self._selection_mode = str(mode or "off").lower()

    @property
    def selection_mode(self) -> str:
        return self._selection_mode

    def selection_enabled(self) -> bool:
        return self._selection_mode in {"shadow", "on"} and self._candidates is not None

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

    async def resolve_target(
        self,
        decision: RoutingDecision,
        request: DispatchRequest,
        *,
        explicit_target: str | None = None,
    ) -> "TargetResolution | None":
        """CandidateSet autorizado → JEV → policy. Nunca ejecuta ni autoriza."""
        if self._selection_mode == "off":
            return None
        kind = candidate_kind_for_capability(decision.capability)
        if kind is None or self._candidates is None:
            return None
        context = DecisionContext(
            user_request=request.query,
            organization_id=request.organization_id,
            user_id=request.user_id,
            role=request.role,
            permissions=request.permissions,
            tenant_policy=dict(request.tenant_policy or {}),
            budget=dict(request.budget or {}),
            available_capabilities=(decision.capability,),
        )
        risk_policy = self._risk_policy or DecisionRiskPolicy.from_settings(
            _settings_or_defaults(), tenant_policy=context.tenant_policy
        )
        policy = candidate_policy_from_context(context, capability=decision.capability)
        candidate_set = await resolve_candidates(
            self._candidates,
            kind,
            organization_id=request.organization_id,
            policy=policy,
            context=context,
        )
        record_candidate_set(candidate_set)
        selection = await select_target(
            self._judge,
            capability=decision.capability,
            candidates=candidate_set,
            user_request=request.query,
            risk_policy=risk_policy,
            explicit_target=explicit_target,
            tenant_policy=context.tenant_policy,
            budget=context.budget,
            organization_id=request.organization_id,
            request_id=request.request_id,
            agent_id=request.agent_id,
            cache=self._judge_cache,
        )
        selection = selection_outcome(
            selection, candidates=candidate_set, tenant_policy=context.tenant_policy
        )
        if selection.authorized:
            authorized = evaluate_policy(
                decision,
                context,
                registry=self._registry,
                risk_policy=risk_policy,
                target=selection.target_id,
                candidate_ids=candidate_set.ids(),
                action_warranted=selection.warranted_noul,
                confidence=selection.confidence,
                risk=selection.risk,
            )
        else:
            authorized = AuthorizedDecision(
                decision=decision,
                authorized=False,
                reason=selection.reason or "selection_not_authorized",
                risk=selection.risk,
                target_id=selection.target_id,
                requires_human=selection.policy_action == "human_review",
                policy_trace={"selection": selection.to_public_dict()},
            )
        record_target_selection(selection, mode=self._selection_mode)
        return TargetResolution(
            selection=selection,
            policy=authorized,
            candidates=candidate_set,
        )

    async def dispatch(
        self,
        decision: RoutingDecision,
        request: DispatchRequest,
        *,
        authorized: AuthorizedDecision | None = None,
    ) -> DispatchResult:
        started = time.perf_counter()
        capability = decision.capability

        if authorized is not None and not authorized.authorized:
            return self._finish(
                DispatchResult(
                    capability=capability,
                    status=_STATUS_DENIED,
                    error=authorized.reason or "policy_denied",
                    data={"policy": authorized.to_public_dict()},
                ),
                started,
            )
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


@dataclass(kw_only=True)
class TargetResolution:
    """Selección + política. El runtime sólo ejecuta si `executable`."""

    selection: TargetSelection
    policy: AuthorizedDecision | None = None
    candidates: CandidateSet | None = None

    @property
    def executable(self) -> bool:
        return bool(
            self.selection.authorized
            and self.policy is not None
            and self.policy.executable
        )

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "selection": self.selection.to_public_dict(),
            "policy": self.policy.to_public_dict() if self.policy is not None else None,
            "candidates": self.candidates.to_public_dict() if self.candidates is not None else None,
            "executable": self.executable,
        }


class _NullSettings:
    def __getattr__(self, name: str) -> Any:
        raise AttributeError(name)


def _settings_or_defaults() -> Any:
    try:
        from src.core.config import get_settings

        return get_settings()
    except Exception:  # noqa: BLE001 — defaults de código
        return _NullSettings()


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
