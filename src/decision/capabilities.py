# =============================================================================
# Capability registry — wraps existing tools; does not duplicate handlers.
# =============================================================================
from __future__ import annotations

from dataclasses import replace

from src.core.domain.decision import (
    ADVISORY_CAPABILITIES,
    BUILTIN_CAPABILITIES,
    CapabilitySpec,
    CostClass,
    RiskLevel,
)
from src.core.ports.decision import CapabilityRegistry

_ADVISORY = ADVISORY_CAPABILITIES


def _advisory(cap_id: str) -> str:
    """Availability for a capability the current RAG path cannot execute yet."""
    return "advisory" if cap_id in _ADVISORY else "available"

_SPECS: dict[str, CapabilitySpec] = {
    "knowledge.search": CapabilitySpec(
        id="knowledge.search",
        name="Search knowledge",
        description="Semantic/lexical search over tenant knowledge.",
        required_permission="",
        tags=("knowledge", "read"),
        cost_class=CostClass.CHEAP,
        timeout_seconds=20.0,
        handler="rag_orchestrator",
    ),
    "knowledge.retrieve": CapabilitySpec(
        id="knowledge.retrieve",
        name="Retrieve knowledge",
        description="Fetch specific passages from the knowledge index.",
        tags=("knowledge", "read"),
        cost_class=CostClass.CHEAP,
        handler="rag_orchestrator",
    ),
    "knowledge.answer": CapabilitySpec(
        id="knowledge.answer",
        name="Answer from knowledge",
        description="RAG answer using retrieved context (existing RAGOrchestrator).",
        tags=("knowledge", "rag"),
        cost_class=CostClass.STANDARD,
        timeout_seconds=60.0,
        handler="rag_orchestrator",
    ),
    "database.query": CapabilitySpec(
        id="database.query",
        name="Query database",
        description="Text-to-SQL / tabular lookup (existing SqlExpert).",
        required_permission="tool:query_database",
        tags=("sql", "data"),
        risk_level=RiskLevel.MEDIUM,
        cost_class=CostClass.STANDARD,
        timeout_seconds=15.0,
        handler="sql_expert",
    ),
    "database.schema": CapabilitySpec(
        id="database.schema",
        name="Inspect schema",
        description="Read catalog/schema metadata.",
        required_permission="sources:sql",
        tags=("sql", "catalog"),
        cost_class=CostClass.CHEAP,
        handler="sql_expert",
    ),
    "agent.execute": CapabilitySpec(
        id="agent.execute",
        name="Execute agent",
        description="Existing AgentRuntime.run loop.",
        tags=("agent",),
        risk_level=RiskLevel.MEDIUM,
        cost_class=CostClass.EXPENSIVE,
        timeout_seconds=60.0,
        handler="agent_runtime",
    ),
    "agent.reason": CapabilitySpec(
        id="agent.reason",
        name="Agent reason",
        description="Agent reasoning without a forced tool.",
        tags=("agent",),
        cost_class=CostClass.EXPENSIVE,
        handler="agent_runtime",
    ),
    "agent.delegate": CapabilitySpec(
        id="agent.delegate",
        name="Delegate agent",
        description="Hand off to another agent via AgentRuntime.",
        tags=("agent",),
        risk_level=RiskLevel.MEDIUM,
        cost_class=CostClass.EXPENSIVE,
        handler="agent_runtime",
    ),
    "workflow.start": CapabilitySpec(
        id="workflow.start",
        name="Start workflow",
        description="Existing run_workflow from the start node.",
        tags=("workflow",),
        risk_level=RiskLevel.MEDIUM,
        cost_class=CostClass.STANDARD,
        handler="workflow_engine",
    ),
    "workflow.execute": CapabilitySpec(
        id="workflow.execute",
        name="Execute workflow",
        description="Existing run_workflow.",
        tags=("workflow",),
        risk_level=RiskLevel.MEDIUM,
        cost_class=CostClass.STANDARD,
        handler="workflow_engine",
    ),
    "workflow.resume": CapabilitySpec(
        id="workflow.resume",
        name="Resume workflow",
        description="Existing run_workflow(resume=True).",
        tags=("workflow",),
        risk_level=RiskLevel.MEDIUM,
        handler="workflow_engine",
    ),
    "tool.call_api": CapabilitySpec(
        id="tool.call_api",
        name="Call API",
        description="Builtin call_api tool.",
        required_permission="tool:call_api",
        tags=("tool",),
        risk_level=RiskLevel.HIGH,
        timeout_seconds=10.0,
        handler="tool_registry",
    ),
    "api.request": CapabilitySpec(
        id="api.request",
        name="API request",
        description="HTTP request via the existing call_api tool.",
        required_permission="tool:call_api",
        tags=("tool", "data"),
        risk_level=RiskLevel.HIGH,
        timeout_seconds=10.0,
        handler="tool_registry",
    ),
    "tool.send_email": CapabilitySpec(
        id="tool.send_email",
        name="Send email",
        description="Email tool if registered for the tenant.",
        required_permission="tool:send_email",
        tags=("tool",),
        risk_level=RiskLevel.HIGH,
        handler="tool_registry",
    ),
    "email.send": CapabilitySpec(
        id="email.send",
        name="Send email",
        description="Email tool if registered for the tenant.",
        required_permission="tool:send_email",
        tags=("tool",),
        risk_level=RiskLevel.HIGH,
        handler="tool_registry",
    ),
    "tool.execute": CapabilitySpec(
        id="tool.execute",
        name="Execute tool",
        description="Named tool from the existing tool registry.",
        tags=("tool",),
        risk_level=RiskLevel.HIGH,
        timeout_seconds=10.0,
        handler="tool_registry",
    ),
    "document.read": CapabilitySpec(
        id="document.read",
        name="Read document",
        description="Read an identified source document.",
        tags=("knowledge", "read"),
        cost_class=CostClass.CHEAP,
        handler="rag_orchestrator",
    ),
    "llm.reason": CapabilitySpec(
        id="llm.reason",
        name="Reason with LLM",
        description="Generative reasoning LLM without retrieval.",
        tags=("llm",),
        cost_class=CostClass.EXPENSIVE,
        handler="llm_provider",
    ),
    "llm.generate": CapabilitySpec(
        id="llm.generate",
        name="Generate text",
        description="Short generative completion.",
        tags=("llm",),
        cost_class=CostClass.STANDARD,
        handler="llm_provider",
    ),
    "respond_directly": CapabilitySpec(
        id="respond_directly",
        name="Respond directly",
        description="Answer without retrieval or tools.",
        tags=("llm",),
        cost_class=CostClass.CHEAP,
        handler="llm_provider",
    ),
}

_TOOL_CAPABILITY = {
    "search_knowledge": "knowledge.search",
    "query_database": "database.query",
    "call_api": "tool.call_api",
    "query_tabular_data": "database.query",
}

# Advisory capabilities stay in the registry (Control Center shows them) but
# are not offered to JEV as routable options for the RAG path.
_SPECS = {
    _key: (replace(_spec, availability="advisory") if _spec.id in _ADVISORY else _spec)
    for _key, _spec in _SPECS.items()
}


class InMemoryCapabilityRegistry(CapabilityRegistry):
    """Static catalog plus live tool names from agents.tools.registry."""

    def __init__(self, extra: dict[str, CapabilitySpec] | None = None) -> None:
        self._specs = dict(_SPECS)
        if extra:
            self._specs.update(extra)

    def sync_tools(self) -> None:
        try:
            from src.agents.tools.registry import list_tools
        except Exception:  # noqa: BLE001
            return
        for name, tool in list_tools().items():
            cap_id = _TOOL_CAPABILITY.get(name)
            if cap_id and cap_id in self._specs:
                continue
            permission = str(getattr(tool, "permission", "") or "")
            timeout = float(getattr(tool, "timeout_seconds", 10.0) or 10.0)
            mapped = cap_id or f"tool.{name}"
            if mapped in self._specs:
                continue
            self._specs[mapped] = CapabilitySpec(
                id=mapped,
                name=name,
                description=str(getattr(tool, "description", "") or name),
                required_permission=permission,
                tags=("tool",),
                risk_level=RiskLevel.HIGH if permission else RiskLevel.MEDIUM,
                timeout_seconds=timeout,
                availability="advisory",
            )

    def get(self, capability_id: str) -> CapabilitySpec | None:
        return self._specs.get(capability_id)

    def list_available(
        self,
        *,
        permissions: frozenset[str],
        tenant_allowlist: frozenset[str] | None = None,
    ) -> tuple[CapabilitySpec, ...]:
        out: list[CapabilitySpec] = []
        for spec in self._specs.values():
            if not self.is_allowed(
                spec.id,
                permissions=permissions,
                tenant_allowlist=tenant_allowlist,
            ):
                continue
            out.append(spec)
        return tuple(out)

    def is_allowed(
        self,
        capability_id: str,
        *,
        permissions: frozenset[str],
        tenant_allowlist: frozenset[str] | None = None,
    ) -> bool:
        spec = self._specs.get(capability_id)
        if spec is None:
            return False
        if tenant_allowlist is not None and capability_id not in tenant_allowlist:
            return False
        required = spec.required_permission
        if not required:
            return True
        if "*" in permissions or "admin:*" in permissions:
            return True
        return required in permissions


def default_capability_ids(
    *,
    sql_enabled: bool,
    knowledge_enabled: bool = True,
    include_advisory: bool = False,
) -> tuple[str, ...]:
    ids = [
        cap
        for cap in BUILTIN_CAPABILITIES
        if include_advisory or cap not in ADVISORY_CAPABILITIES
    ]
    if not sql_enabled:
        ids = [c for c in ids if not c.startswith("database.")]
    if not knowledge_enabled:
        ids = [c for c in ids if not c.startswith("knowledge.")]
    return tuple(ids)
