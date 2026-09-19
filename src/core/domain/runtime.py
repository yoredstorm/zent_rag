# =============================================================================
# Zent AI Runtime domain — shared execution state. Not a prompt dump.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class RuntimeStep:
    name: str
    status: str = "ok"  # ok | skipped | error | pending_approval
    duration_ms: float = 0.0
    tokens: int = 0
    cost: float = 0.0
    confidence: float | None = None
    capability: str | None = None
    detail: str = ""

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "duration_ms": round(self.duration_ms, 2),
            "tokens": self.tokens,
            "cost": round(self.cost, 6),
            "confidence": self.confidence,
            "capability": self.capability,
            "detail": self.detail[:240],
        }


@dataclass
class ExecutionState:
    """Runtime-owned state. Models receive sanitized_for_model(), never this blob."""

    request: str = ""
    organization_id: UUID | None = None
    user_id: UUID | None = None
    conversation_id: UUID | None = None
    request_id: UUID = field(default_factory=uuid4)
    goal: str = ""
    current_step: str = "start"
    available_capabilities: tuple[str, ...] = ()
    evidence: list[dict[str, Any]] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    workflow_state: dict[str, Any] = field(default_factory=dict)
    agent_state: dict[str, Any] = field(default_factory=dict)
    budget: dict[str, Any] = field(default_factory=dict)
    token_budget: int = 0
    cost_so_far: float = 0.0
    decisions: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    steps: list[RuntimeStep] = field(default_factory=list)
    selected_capability: str | None = None
    generator_model: str | None = None
    created_at: datetime = field(default_factory=_now)

    def append_step(self, step: RuntimeStep) -> None:
        self.steps.append(step)
        self.current_step = step.name
        self.cost_so_far = round(self.cost_so_far + max(0.0, step.cost), 6)
        if step.status == "error" and step.detail:
            self.errors.append(step.detail[:300])

    def sanitized_for_model(self, *, max_chars: int = 4000) -> dict[str, Any]:
        """Narrow JSON for JEV/LLM. No secrets, no full evidence bodies."""
        evidence_preview = []
        used = 0
        for item in self.evidence[:8]:
            snippet = str(item.get("snippet") or item.get("content") or "")[:180]
            row = {"source": str(item.get("source_type") or "")[:40], "score": item.get("score")}
            if snippet:
                row["snippet"] = snippet
            evidence_preview.append(row)
            used += len(snippet)
            if used >= max_chars // 2:
                break
        tools = [
            {"tool": str(t.get("tool") or "")[:80], "ok": bool(t.get("ok", True))}
            for t in self.tool_results[-6:]
        ]
        remaining = None
        if isinstance(self.budget, dict) and self.budget.get("remaining") is not None:
            try:
                remaining = float(self.budget["remaining"])
            except (TypeError, ValueError):
                remaining = None
        return {
            "user_request": (self.request or "")[:2000],
            "goal": (self.goal or "")[:500],
            "current_step": self.current_step,
            "available_capabilities": list(self.available_capabilities)[:24],
            "evidence_preview": evidence_preview,
            "tool_results": tools,
            "cost_so_far": round(self.cost_so_far, 6),
            "budget_remaining": remaining,
            "last_decision": (self.decisions[-1] if self.decisions else None),
        }

    def to_trace_dict(self) -> dict[str, Any]:
        return {
            "request_id": str(self.request_id),
            "organization_id": str(self.organization_id) if self.organization_id else None,
            "goal": self.goal,
            "selected_capability": self.selected_capability,
            "generator_model": self.generator_model,
            "cost_so_far": round(self.cost_so_far, 6),
            "budget": {
                k: self.budget[k]
                for k in ("remaining", "on_limit", "currency")
                if k in self.budget
            },
            "decisions": self.decisions[-8:],
            "steps": [s.to_public_dict() for s in self.steps],
            "errors": self.errors[-8:],
        }


def with_capability(state: ExecutionState, capability: str) -> ExecutionState:
    return replace(state, selected_capability=capability)
