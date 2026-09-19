# =============================================================================
# Thin hook so RAGOrchestrator does not import JEV.
# =============================================================================
from __future__ import annotations

from uuid import UUID

from src.core.domain.decision import DecisionContext, RoutingDecision
from src.decision.capabilities import default_capability_ids
from src.decision.engine import DecisionEngine
from src.decision.metrics import record_agreement, record_decision
from src.decision.routing import capability_from_legacy_method
from src.decision.shadow import compare_shadow
from src.decision.traces import DecisionTraceStore
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.observability.tracing import trace_span

logger = get_logger(__name__)

# The RAG orchestrator executes SQL only when the SQL Expert is configured.
# Capability authorization here is availability-level: role/customer policy,
# org SQL blocklists and tool RBAC stay in the handlers themselves.
_SQL_CAPABILITY_PERMISSIONS = frozenset({"tool:query_database", "sources:sql"})


class OrchestratorDecisionHook:
    def __init__(self, engine: DecisionEngine) -> None:
        self._engine = engine
        self._store = DecisionTraceStore()

    def enabled(self) -> bool:
        settings = self._engine.settings
        return (
            settings.effective_mode != "legacy"
            or settings.shadow_enabled()
            or float(settings.shadow_sample_rate or 0.0) > 0.0
        )

    async def evaluate(
        self,
        *,
        organization_id: UUID,
        request_id: UUID,
        user_id: UUID | None,
        query: str,
        role: str,
        sql_enabled: bool,
        knowledge_enabled: bool = True,
        permissions: frozenset[str] = frozenset(),
        conversation_state: dict | None = None,
        tenant_policy: dict | None = None,
        include_advisory: bool = False,
        explicit_capability: str | None = None,
        explicit_tool: str | None = None,
        explicit_workflow_id: str | None = None,
        explicit_agent_id: str | None = None,
    ) -> RoutingDecision:
        budget: dict = {}
        try:
            from src.runtime.wallet import snapshot_budget

            budget = await snapshot_budget(organization_id)
        except Exception:  # noqa: BLE001
            budget = {}
        effective_permissions = set(permissions)
        if sql_enabled:
            effective_permissions.update(_SQL_CAPABILITY_PERMISSIONS)
        context = DecisionContext(
            user_request=query,
            organization_id=organization_id,
            request_id=request_id,
            user_id=user_id,
            role=role,
            sql_enabled=sql_enabled,
            knowledge_enabled=knowledge_enabled,
            permissions=frozenset(effective_permissions),
            tenant_policy=dict(tenant_policy or {}),
            available_capabilities=default_capability_ids(
                sql_enabled=sql_enabled,
                knowledge_enabled=knowledge_enabled,
                include_advisory=include_advisory,
            ),
            conversation_state=conversation_state or {},
            explicit_capability=explicit_capability,
            explicit_tool=explicit_tool,
            explicit_workflow_id=explicit_workflow_id,
            explicit_agent_id=explicit_agent_id,
            budget=budget,
        )
        async with trace_span("orchestrator.decision"):
            decision = await self._engine.decide(context)
        record_decision(decision)
        return decision

    async def after_actual(
        self,
        *,
        organization_id: UUID,
        request_id: UUID,
        user_id: UUID | None,
        query: str,
        actual_method: str,
        engine_decision: RoutingDecision,
        sql_enabled: bool,
        role: str = "admin",
        actual_capability: str | None = None,
    ) -> None:
        """Record what actually executed. Never changes execution."""
        actual = actual_capability or capability_from_legacy_method(actual_method)
        trace_id = engine_decision.metadata.get("trace_id")
        jev_candidate = _jev_candidate(engine_decision)
        if trace_id:
            try:
                await self._store.update_actual(
                    str(trace_id),
                    actual_capability=actual,
                    jev_capability=jev_candidate,
                )
                if engine_decision.resolved:
                    record_agreement(engine_decision.capability == actual)
                elif jev_candidate:
                    record_agreement(jev_candidate == actual)
                return
            except Exception as exc:  # noqa: BLE001
                logger.warning("decision trace update failed", error=str(exc)[:200])
        if engine_decision.resolved:
            record_agreement(engine_decision.capability == actual)
        elif jev_candidate:
            record_agreement(jev_candidate == actual)
        if not self._engine.settings.observes(request_id):
            return
        context = DecisionContext(
            user_request=query,
            organization_id=organization_id,
            request_id=request_id,
            user_id=user_id,
            sql_enabled=sql_enabled,
            role=role,
        )
        trace = compare_shadow(
            actual_method=actual_method,
            engine_decision=engine_decision,
            context=context,
        )
        if trace.agreement is not None:
            record_agreement(bool(trace.agreement))
        try:
            await self._store.record(trace)
        except Exception as exc:  # noqa: BLE001
            logger.warning("shadow trace failed", error=str(exc)[:200])


def _jev_candidate(decision: RoutingDecision) -> str | None:
    raw = decision.raw_answers.get("jev")
    if isinstance(raw, dict) and raw.get("capability"):
        return str(raw["capability"])
    if decision.provider == "jev" and decision.capability:
        return str(decision.capability)
    return None


def retrieval_hint(decision: RoutingDecision | None) -> dict[str, bool]:
    """How RAGOrchestrator should bias existing SQL/RAG branches.

    Hints apply only when the engine acted. Shadow/sampled decisions are
    observational and must never change execution.
    """
    no_hint = {"prefer_sql": False, "skip_sql": False}
    if decision is None or not decision.resolved:
        return dict(no_hint)
    if decision.metadata.get("acting") is False:
        return dict(no_hint)
    cap = decision.capability
    return {
        "prefer_sql": cap.startswith("database."),
        "skip_sql": cap.startswith("knowledge.")
        or cap in {"respond_directly", "llm.reason", "llm.generate"},
    }
