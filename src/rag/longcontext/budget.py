# =============================================================================
# AdaptiveContextBudget — cuánto contexto NECESITA esta consulta
# =============================================================================
# usable_context = min(modelo, tenant, request, costo) - reservas.
# La escalera de tiers es configurable (no lógica de negocio); el perfil
# economy/balanced/quality/maximum_quality ajusta cuánto se puede escalar.
# Nunca se supera usable_context y nunca se asume una ventana: se consulta el
# registry de capacidades del modelo real.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field, replace

from src.rag.longcontext.registry import ModelCapability, resolve_model_capability
from src.rag.longcontext.settings import LongContextSettings, ProfilePolicy

MIN_USABLE_CONTEXT = 1000


@dataclass(frozen=True, kw_only=True)
class AdaptiveContextBudget:
    capability: ModelCapability
    usable_context: int
    hard_limit: int
    profile: str
    policy: ProfilePolicy
    tiers: tuple[int, ...]
    start_tier: int
    max_tier: int
    request_limit: int | None = None
    tenant_limit: int | None = None
    cost_limit_tokens: int | None = None
    reserved: dict[str, int] = field(default_factory=dict)

    def target_tokens(self, tier_index: int) -> int:
        """Tokens objetivo para el tier pedido (clampeado a la escalera)."""
        index = max(0, min(int(tier_index), len(self.tiers) - 1))
        return min(self.tiers[index], self.usable_context)

    def clamp(self, tokens: int | None) -> int:
        if tokens is None:
            return self.target_tokens(self.start_tier)
        return max(1, min(int(tokens), self.usable_context))

    def escalated(self, current_index: int, *, steps: int = 1) -> int | None:
        """Índice del siguiente tier al que una expansión puede subir."""
        next_index = int(current_index) + max(1, int(steps))
        if next_index > self.max_tier:
            return None
        return next_index

    def tier_index_for_tokens(self, tokens: int) -> int:
        for index, value in enumerate(self.tiers):
            if value >= int(tokens):
                return index
        return len(self.tiers) - 1

    def to_public_dict(self) -> dict[str, object]:
        return {
            "model": self.capability.model_name,
            "model_context_limit": self.capability.context_window,
            "model_capability_source": self.capability.source,
            "hard_limit": self.hard_limit,
            "usable_context": self.usable_context,
            "profile": self.profile,
            "tiers": list(self.tiers),
            "start_tier": self.start_tier,
            "max_tier": self.max_tier,
            "max_expansions": self.policy.max_expansions,
            "gain_min": round(self.policy.gain_min, 4),
            "requirement_min": round(self.policy.requirement_min, 4),
            "reserved": dict(self.reserved),
            "request_limit": self.request_limit,
            "tenant_limit": self.tenant_limit,
            "cost_limit_tokens": self.cost_limit_tokens,
        }


def _tier_ceiling(settings: LongContextSettings, policy: ProfilePolicy, tiers: int) -> int:
    profile = settings.effective_profile
    if profile == "economy":
        return min(settings.max_tier, settings.start_tier + 2, tiers - 1)
    if profile == "quality":
        return min(settings.max_tier + 1, tiers - 1)
    if profile == "maximum_quality":
        return tiers - 1
    return min(settings.max_tier, tiers - 1)


def compute_context_budget(
    *,
    model: str,
    settings: LongContextSettings,
    system_tokens: int = 0,
    conversation_tokens: int = 0,
    tool_tokens: int = 0,
    output_reserve: int | None = None,
    request_limit: int | None = None,
    tenant_limit: int | None = None,
    cost_limit_tokens: int | None = None,
    capability: ModelCapability | None = None,
) -> AdaptiveContextBudget:
    """Presupuesto por request. Consulta el registry; no asume ventanas."""
    cap = capability or resolve_model_capability(
        model,
        overrides=settings.model_windows,
        default_window=settings.default_context_window,
    )
    limits: list[int] = [int(cap.context_window)]
    for value in (
        request_limit,
        tenant_limit,
        cost_limit_tokens,
        settings.request_token_limit or None,
        settings.tenant_token_limit or None,
    ):
        if value and int(value) > 0:
            limits.append(int(value))
    hard_limit = max(min(limits), MIN_USABLE_CONTEXT)

    reserved = {
        "output": int(
            output_reserve
            if output_reserve is not None and int(output_reserve) > 0
            else settings.output_reserve
        ),
        "system": int(system_tokens) if system_tokens > 0 else int(settings.system_reserve),
        "conversation": max(int(conversation_tokens), 0),
        "tools": int(tool_tokens) if tool_tokens > 0 else int(settings.tool_reserve),
        "safety": int(settings.safety_margin),
    }
    usable = max(hard_limit - sum(reserved.values()), MIN_USABLE_CONTEXT)

    tiers = tuple(int(tier) for tier in settings.tiers if 0 < int(tier) <= usable)
    if not tiers:
        tiers = (usable,)
    if tiers[-1] < usable:
        tiers = tiers + (usable,)

    policy = settings.policy()
    start = max(0, min(int(settings.start_tier), len(tiers) - 1))
    max_tier = max(start, _tier_ceiling(settings, policy, len(tiers)))

    return AdaptiveContextBudget(
        capability=cap,
        usable_context=usable,
        hard_limit=hard_limit,
        profile=settings.effective_profile,
        policy=policy,
        tiers=tiers,
        start_tier=start,
        max_tier=max_tier,
        request_limit=request_limit,
        tenant_limit=tenant_limit,
        cost_limit_tokens=cost_limit_tokens,
        reserved=reserved,
    )


def with_profile(
    budget: AdaptiveContextBudget,
    settings: LongContextSettings,
    profile: str,
) -> AdaptiveContextBudget:
    """Recalcula un presupuesto existente para otro perfil (request override)."""
    tuned = replace(settings, profile=profile)
    policy = tuned.policy()
    tiers = budget.tiers
    return replace(
        budget,
        profile=tuned.effective_profile,
        policy=policy,
        max_tier=max(
            budget.start_tier,
            _tier_ceiling(tuned, policy, len(tiers)),
        ),
    )


__all__ = [
    "AdaptiveContextBudget",
    "compute_context_budget",
    "with_profile",
]
