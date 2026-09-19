# =============================================================================
# Rules-first provider — deterministic. No JEV, no LLM.
# =============================================================================
# Reuses SqlIntentRouter.heuristic_score for slam-dunk SQL vs docs.
# Explicit routes (capability / tool / workflow / agent) always win.
# =============================================================================
from __future__ import annotations

import time

from src.core.domain.decision import (
    ComplexityLevel,
    DecisionContext,
    DecisionProviderName,
    RiskLevel,
    RoutingDecision,
)
from src.core.ports.decision import DecisionProvider

_EXPLICIT_HIGH = 1.0
_SQL_SLAM = 0.8


class RulesDecisionProvider(DecisionProvider):
    name = DecisionProviderName.RULES.value

    def __init__(self, *, sql_threshold: float = 0.8) -> None:
        self._sql_threshold = sql_threshold

    async def decide(self, context: DecisionContext) -> RoutingDecision:
        started = time.perf_counter()
        explicit = self._explicit(context)
        if explicit is not None:
            explicit.latency_ms = (time.perf_counter() - started) * 1000
            return explicit

        heuristic = _sql_heuristic(context.user_request)
        if context.sql_enabled and heuristic >= max(self._sql_threshold, _SQL_SLAM):
            return _resolved(
                capability="database.query",
                intent="database.query",
                needs_knowledge=False,
                confidence=_EXPLICIT_HIGH,
                latency_ms=(time.perf_counter() - started) * 1000,
                metadata={"rule": "sql_heuristic", "heuristic_score": heuristic},
            )
        # Documentary default is NOT a slam-dunk: leave it unresolved so JEV/legacy
        # can decide. Rules only fire when code is certain.
        return RoutingDecision(
            provider=self.name,
            resolved=False,
            confidence=0.0,
            capability="knowledge.answer",
            latency_ms=(time.perf_counter() - started) * 1000,
            metadata={"rule": "unresolved", "heuristic_score": heuristic},
        )

    def _explicit(self, context: DecisionContext) -> RoutingDecision | None:
        """Caller-named targets are deterministic intent, not a heuristic.

        They act in every routing mode (including legacy) and are marked so the
        composite never downgrades them to a shadow candidate.
        """
        decision: RoutingDecision | None = None
        if context.explicit_capability:
            decision = _resolved(
                capability=context.explicit_capability,
                intent=context.explicit_capability,
                confidence=_EXPLICIT_HIGH,
                metadata={"rule": "explicit_capability"},
                **_flags_for(context.explicit_capability),
            )
        elif context.explicit_workflow_id:
            decision = _resolved(
                capability="workflow.execute",
                intent="workflow.execute",
                confidence=_EXPLICIT_HIGH,
                needs_workflow=True,
                needs_knowledge=False,
                risk=RiskLevel.MEDIUM,
                metadata={
                    "rule": "explicit_workflow",
                    "workflow_id": context.explicit_workflow_id,
                },
            )
        elif context.explicit_agent_id:
            decision = _resolved(
                capability="agent.execute",
                intent="agent.execute",
                confidence=_EXPLICIT_HIGH,
                needs_agent=True,
                needs_knowledge=False,
                complexity=ComplexityLevel.MULTI_STEP,
                risk=RiskLevel.MEDIUM,
                metadata={"rule": "explicit_agent", "agent_id": context.explicit_agent_id},
            )
        elif context.explicit_tool:
            cap = _tool_capability(context.explicit_tool)
            decision = _resolved(
                capability=cap,
                intent=cap,
                confidence=_EXPLICIT_HIGH,
                needs_tool=True,
                needs_knowledge=False,
                risk=RiskLevel.HIGH,
                metadata={"rule": "explicit_tool", "tool": context.explicit_tool},
            )
        if decision is not None:
            decision.metadata = {**decision.metadata, "explicit": True}
        return decision


def _sql_heuristic(question: str) -> float:
    try:
        from src.agents.tools.sql_router import SqlIntentRouter

        return float(SqlIntentRouter.heuristic_score(question))
    except Exception:  # noqa: BLE001
        return 0.0


def _tool_capability(tool_name: str) -> str:
    mapping = {
        "search_knowledge": "knowledge.search",
        "query_database": "database.query",
        "call_api": "tool.call_api",
        "query_tabular_data": "database.query",
    }
    return mapping.get(tool_name, "tool.execute")


def _flags_for(capability: str) -> dict:
    return {
        "needs_knowledge": capability.startswith("knowledge."),
        "needs_agent": capability.startswith("agent."),
        "needs_workflow": capability.startswith("workflow."),
        "needs_tool": capability.startswith("tool."),
        "needs_reasoning": capability in {"llm.reason", "agent.reason"},
        "risk": RiskLevel.HIGH if capability.startswith("tool.") else RiskLevel.LOW,
    }


def _resolved(
    *,
    capability: str,
    intent: str,
    confidence: float,
    latency_ms: float = 0.0,
    needs_knowledge: bool = True,
    needs_agent: bool = False,
    needs_workflow: bool = False,
    needs_tool: bool = False,
    needs_reasoning: bool = False,
    complexity: ComplexityLevel = ComplexityLevel.BOUNDED,
    risk: RiskLevel = RiskLevel.LOW,
    metadata: dict | None = None,
) -> RoutingDecision:
    return RoutingDecision(
        intent=intent,
        capability=capability,
        complexity=complexity,
        needs_knowledge=needs_knowledge,
        needs_agent=needs_agent,
        needs_workflow=needs_workflow,
        needs_tool=needs_tool,
        needs_reasoning=needs_reasoning,
        risk=risk,
        confidence=confidence,
        provider=DecisionProviderName.RULES.value,
        latency_ms=latency_ms,
        resolved=True,
        metadata=metadata or {},
    )
