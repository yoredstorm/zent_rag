# =============================================================================
# Decision Engine ports — vendor-agnostic. Orchestrator never imports JEV.
# =============================================================================
from __future__ import annotations

from abc import ABC, abstractmethod

from src.core.domain.decision import CapabilitySpec, DecisionContext, RoutingDecision


class DecisionProvider(ABC):
    """One intelligence source: rules, JEV, or a small LLM."""

    name: str = "unknown"

    @abstractmethod
    async def decide(self, context: DecisionContext) -> RoutingDecision:
        """Return a recommendation. Never executes capabilities."""


class CapabilityRegistry(ABC):
    """Catalog of executable capabilities. Decision selects; Orchestrator runs."""

    @abstractmethod
    def get(self, capability_id: str) -> CapabilitySpec | None: ...

    @abstractmethod
    def list_available(
        self,
        *,
        permissions: frozenset[str],
        tenant_allowlist: frozenset[str] | None = None,
    ) -> tuple[CapabilitySpec, ...]: ...

    @abstractmethod
    def is_allowed(
        self,
        capability_id: str,
        *,
        permissions: frozenset[str],
        tenant_allowlist: frozenset[str] | None = None,
    ) -> bool: ...
