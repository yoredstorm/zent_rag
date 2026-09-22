# =============================================================================
# Decision Engine domain — routing judgment consumed by the Orchestrator.
# =============================================================================
# JEV/LLM/rules produce this shape. Authorization and execution stay outside.
# Named RoutingDecision to avoid colliding with workflows.DecisionResult.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import UUID, uuid4


class ComplexityLevel(str, Enum):
    TRIVIAL = "trivial"
    BOUNDED = "bounded"
    MULTI_STEP = "multi_step"
    REASONING = "reasoning"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class DecisionProviderName(str, Enum):
    RULES = "rules"
    JEV = "jev"
    LLM = "llm"
    COMPOSITE = "composite"
    LEGACY = "legacy"


class RoutingMode(str, Enum):
    LEGACY = "legacy"
    SHADOW = "shadow"
    JEV = "jev"
    HYBRID = "hybrid"


# Canonical capability ids. Orchestrator maps these onto existing handlers.
BUILTIN_CAPABILITIES: tuple[str, ...] = (
    "knowledge.search",
    "knowledge.retrieve",
    "knowledge.answer",
    "database.query",
    "database.schema",
    "agent.execute",
    "agent.reason",
    "agent.delegate",
    "workflow.start",
    "workflow.execute",
    "workflow.resume",
    "tool.call_api",
    "tool.send_email",
    "tool.execute",
    "document.read",
    "llm.reason",
    "llm.generate",
    "respond_directly",
)

# Capabilities the RAG/chat path can actually execute today. The rest are
# "advisory": they exist in the registry and the Control Center, but the
# current orchestrator only biases SQL vs RAG, so they must not be offered to
# JEV as routable options. Agent/workflow/tool runs execute through their own
# endpoints (agents/{id}/run, workflows, tool registry).
ADVISORY_CAPABILITIES: frozenset[str] = frozenset(
    {
        "agent.execute",
        "agent.reason",
        "agent.delegate",
        "workflow.start",
        "workflow.execute",
        "workflow.resume",
        "tool.call_api",
        "tool.send_email",
        "tool.execute",
        "api.request",
        "email.send",
    }
)

EXECUTABLE_CAPABILITIES: tuple[str, ...] = tuple(
    cap for cap in BUILTIN_CAPABILITIES if cap not in ADVISORY_CAPABILITIES
)

SCORE_COMPLEXITY_LEVELS: tuple[str, ...] = (
    "Trivial lookup or greeting; no retrieval or tools.",
    "Bounded single-source question answerable with search or SQL.",
    "Multi-step request that needs several capabilities composed.",
    "Open-ended reasoning that needs a generative LLM.",
)


class CostClass(str, Enum):
    FREE = "free"
    CHEAP = "cheap"
    STANDARD = "standard"
    EXPENSIVE = "expensive"


@dataclass(frozen=True, kw_only=True)
class CapabilitySpec:
    """Declarative capability. Handler lives in the Orchestrator, not here."""

    id: str
    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    risk_level: RiskLevel = RiskLevel.LOW
    cost_class: CostClass = CostClass.STANDARD
    required_permission: str = ""
    tags: tuple[str, ...] = ()
    timeout_seconds: float = 30.0
    handler: str = ""
    availability: str = "available"


@dataclass(kw_only=True)
class DecisionContext:
    """State evaluated by providers. No secrets. Tenant-scoped."""

    user_request: str
    organization_id: UUID
    request_id: UUID = field(default_factory=uuid4)
    user_id: UUID | None = None
    conversation_state: dict[str, Any] = field(default_factory=dict)
    available_capabilities: tuple[str, ...] = BUILTIN_CAPABILITIES
    tenant_policy: dict[str, Any] = field(default_factory=dict)
    budget: dict[str, Any] = field(default_factory=dict)
    permissions: frozenset[str] = field(default_factory=frozenset)
    explicit_capability: str | None = None
    explicit_tool: str | None = None
    explicit_workflow_id: str | None = None
    explicit_agent_id: str | None = None
    sql_enabled: bool = False
    knowledge_enabled: bool = True
    role: str = "admin"

    def sanitized_state(self) -> dict[str, Any]:
        """JSON state for System One. Truncated. No secrets."""
        request = (self.user_request or "")[:4000]
        conv = _sanitize_conversation(self.conversation_state)
        policy = {
            "sql_enabled": bool(self.sql_enabled or self.tenant_policy.get("sql_enabled")),
            "knowledge_enabled": bool(
                self.knowledge_enabled
                if "knowledge_enabled" not in self.tenant_policy
                else self.tenant_policy.get("knowledge_enabled")
            ),
            "role": self.role,
        }
        remaining_ok = self.budget.get("remaining_ok")
        if remaining_ok is None:
            remaining_ok = True
        budget = {
            "remaining_ok": bool(remaining_ok),
            "prefer_cheap": bool(self.budget.get("prefer_cheap", False)),
            "on_limit": str(self.budget.get("on_limit") or "block")[:20],
        }
        return {
            "user_request": request,
            "conversation_state": conv,
            "available_capabilities": list(self.available_capabilities),
            "tenant_policy": policy,
            "budget": budget,
        }


def _sanitize_conversation(raw: dict[str, Any]) -> dict[str, Any]:
    if not raw:
        return {}
    turns = int(raw.get("turn_count") or 0)
    last_user = str(raw.get("last_user") or "")[:500]
    last_assistant = str(raw.get("last_assistant") or "")[:500]
    return {
        "turn_count": turns,
        "is_followup": bool(raw.get("is_followup") or turns > 1),
        "last_user": last_user,
        "last_assistant": last_assistant,
    }


@dataclass(kw_only=True)
class RoutingDecision:
    """Standard engine output. Orchestrator executes; this only recommends."""

    intent: str = ""
    capability: str = "knowledge.answer"
    complexity: ComplexityLevel = ComplexityLevel.BOUNDED
    needs_knowledge: bool = True
    needs_agent: bool = False
    needs_workflow: bool = False
    needs_tool: bool = False
    needs_reasoning: bool = False
    risk: RiskLevel = RiskLevel.LOW
    confidence: float = 0.0
    provider: str = DecisionProviderName.LEGACY.value
    latency_ms: float = 0.0
    alternatives: tuple[str, ...] = ()
    fallback_used: bool = False
    resolved: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    raw_answers: dict[str, Any] = field(default_factory=dict)
    estimated_cost: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "capability": self.capability,
            "complexity": self.complexity.value
            if isinstance(self.complexity, ComplexityLevel)
            else str(self.complexity),
            "needs_knowledge": self.needs_knowledge,
            "needs_agent": self.needs_agent,
            "needs_workflow": self.needs_workflow,
            "needs_tool": self.needs_tool,
            "needs_reasoning": self.needs_reasoning,
            "risk": self.risk.value if isinstance(self.risk, RiskLevel) else str(self.risk),
            "confidence": round(float(self.confidence), 4),
            "provider": self.provider,
            "latency_ms": round(float(self.latency_ms), 2),
            "alternatives": list(self.alternatives),
            "fallback_used": self.fallback_used,
            "resolved": self.resolved,
        }


# Backward-compatible alias requested by the architecture brief.
DecisionResult = RoutingDecision


@dataclass(kw_only=True)
class DecisionTrace:
    """Auditable record. Tenant-isolated. No raw secrets."""

    decision_id: UUID = field(default_factory=uuid4)
    organization_id: UUID | None = None
    request_id: UUID | None = None
    user_id: UUID | None = None
    provider: str = ""
    questions: list[dict[str, Any]] = field(default_factory=list)
    results: list[dict[str, Any]] = field(default_factory=list)
    selected_capability: str = ""
    confidence: float = 0.0
    fallback_used: bool = False
    latency_ms: float = 0.0
    estimated_cost: float = 0.0
    routing_mode: str = RoutingMode.LEGACY.value
    actual_capability: str | None = None
    jev_capability: str | None = None
    agreement: bool | None = None
    shadow: bool = False
    canary: bool = False
    model: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": str(self.decision_id),
            "organization_id": str(self.organization_id) if self.organization_id else None,
            "request_id": str(self.request_id) if self.request_id else None,
            "provider": self.provider,
            "model": self.model,
            "questions": self.questions,
            "results": self.results,
            "selected_capability": self.selected_capability,
            "confidence": round(float(self.confidence), 4),
            "fallback_used": self.fallback_used,
            "latency_ms": round(float(self.latency_ms), 2),
            "estimated_cost": self.estimated_cost,
            "routing_mode": self.routing_mode,
            "actual_capability": self.actual_capability,
            "jev_capability": self.jev_capability,
            "agreement": self.agreement,
            "shadow": self.shadow,
            "canary": self.canary,
        }
