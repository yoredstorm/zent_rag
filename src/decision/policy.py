# =============================================================================
# Authorization after Decision — JEV cannot grant capabilities.
# =============================================================================
# `evaluate_policy` consolida la política: capability + target + RBAC + risk +
# budget + confidence + action warranted + rate limit + confirmación humana.
# Devuelve un AuthorizedDecision con traza operativa (sin chain-of-thought).
# `authorize_decision` se mantiene como wrapper compatible (muta la decisión).
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.core.domain.decision import DecisionContext, RiskLevel, RoutingDecision
from src.core.ports.decision import CapabilityRegistry
from src.decision.candidates import candidate_kind_for_capability
from src.decision.capabilities import InMemoryCapabilityRegistry
from src.decision.risk_policy import DecisionRiskPolicy

_SAFE_FALLBACK = "knowledge.answer"

REASON_ALLOWED = "allowed"
REASON_CAPABILITY_DENIED = "capability_denied"
REASON_TARGET_NOT_ALLOWED = "target_not_allowed"
REASON_MISSING_TARGET = "missing_target"
REASON_LOW_CONFIDENCE = "low_confidence"
REASON_NOT_WARRANTED = "action_not_warranted"
REASON_BUDGET = "budget_block"
REASON_RATE_LIMIT = "rate_limited"
REASON_HUMAN = "human_confirmation_required"


@dataclass(kw_only=True)
class AuthorizedDecision:
    """Resultado de la política. El runtime sólo ejecuta si `executable`."""

    decision: RoutingDecision
    authorized: bool
    reason: str = REASON_ALLOWED
    risk: str = RiskLevel.LOW.value
    target_id: str | None = None
    requires_human: bool = False
    policy_trace: dict[str, Any] = field(default_factory=dict)

    @property
    def executable(self) -> bool:
        return self.authorized and not self.requires_human

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "authorized": self.authorized,
            "executable": self.executable,
            "reason": self.reason,
            "risk": self.risk,
            "target_id": self.target_id,
            "requires_human": self.requires_human,
            "capability": self.decision.capability,
            "confidence": round(float(self.decision.confidence or 0.0), 4),
            "policy": dict(self.policy_trace),
        }


def evaluate_policy(
    decision: RoutingDecision,
    context: DecisionContext,
    *,
    registry: CapabilityRegistry | None = None,
    risk_policy: DecisionRiskPolicy | None = None,
    target: str | None = None,
    candidate_ids: tuple[str, ...] | None = None,
    tenant_allowlist: frozenset[str] | None = None,
    action_warranted: float | None = None,
    confidence: float | None = None,
    rate_ok: bool = True,
    require_human_confirmation: bool | None = None,
    risk: str | None = None,
) -> AuthorizedDecision:
    """Decide si la acción puede ejecutarse. Nunca eleva permisos."""
    registry = registry or InMemoryCapabilityRegistry()
    policy = risk_policy or DecisionRiskPolicy.from_settings(
        _settings_shim(), tenant_policy=context.tenant_policy
    )
    capability = decision.capability
    kind = candidate_kind_for_capability(capability)
    risk_raw = risk or decision.metadata.get("risk") or _risk_for_capability(registry, capability)
    resolved_risk = risk_raw.value if hasattr(risk_raw, "value") else str(risk_raw or RiskLevel.LOW.value)
    thresholds = policy.thresholds(risk)
    conf = float(decision.confidence if confidence is None else confidence)
    trace: dict[str, Any] = {
        "capability": capability,
        "kind": kind,
        "risk": risk,
        "thresholds": thresholds.to_public_dict(),
        "confidence": round(conf, 4),
        "action_warranted": action_warranted,
        "target": target,
        "rate_ok": bool(rate_ok),
    }

    allowlist = tenant_allowlist
    if allowlist is None:
        raw = context.tenant_policy.get("capability_allowlist")
        if isinstance(raw, (list, tuple, set, frozenset)):
            allowlist = frozenset(str(x) for x in raw)
    if not registry.is_allowed(
        capability, permissions=context.permissions, tenant_allowlist=allowlist
    ) or capability not in context.available_capabilities:
        trace["reason"] = REASON_CAPABILITY_DENIED
        return AuthorizedDecision(
            decision=decision,
            authorized=False,
            reason=REASON_CAPABILITY_DENIED,
            risk=risk,
            target_id=target,
            policy_trace=trace,
        )
    if kind is not None:
        if candidate_ids is not None and (not target or target not in set(candidate_ids)):
            trace["reason"] = REASON_TARGET_NOT_ALLOWED
            return AuthorizedDecision(
                decision=decision,
                authorized=False,
                reason=REASON_TARGET_NOT_ALLOWED,
                risk=risk,
                target_id=target,
                policy_trace=trace,
            )
        if not target:
            trace["reason"] = REASON_MISSING_TARGET
            return AuthorizedDecision(
                decision=decision,
                authorized=False,
                reason=REASON_MISSING_TARGET,
                risk=risk,
                target_id=None,
                policy_trace=trace,
            )
    if conf < thresholds.choice_threshold:
        trace["reason"] = REASON_LOW_CONFIDENCE
        return AuthorizedDecision(
            decision=decision,
            authorized=False,
            reason=REASON_LOW_CONFIDENCE,
            risk=risk,
            target_id=target,
            requires_human=thresholds.on_low_confidence == "human_review",
            policy_trace=trace,
        )
    if thresholds.warrant_required:
        if action_warranted is None or float(action_warranted) < thresholds.warrant_threshold:
            trace["reason"] = REASON_NOT_WARRANTED
            return AuthorizedDecision(
                decision=decision,
                authorized=False,
                reason=REASON_NOT_WARRANTED,
                risk=risk,
                target_id=target,
                policy_trace=trace,
            )
    if (
        context.budget.get("on_limit") == "block"
        and context.budget.get("remaining_ok") is False
    ):
        trace["reason"] = REASON_BUDGET
        return AuthorizedDecision(
            decision=decision,
            authorized=False,
            reason=REASON_BUDGET,
            risk=risk,
            target_id=target,
            policy_trace=trace,
        )
    if not rate_ok:
        trace["reason"] = REASON_RATE_LIMIT
        return AuthorizedDecision(
            decision=decision,
            authorized=False,
            reason=REASON_RATE_LIMIT,
            risk=risk,
            target_id=target,
            policy_trace=trace,
        )
    human = (
        thresholds.human_confirmation
        if require_human_confirmation is None
        else bool(require_human_confirmation)
    )
    trace["reason"] = REASON_HUMAN if human else REASON_ALLOWED
    return AuthorizedDecision(
        decision=decision,
        authorized=True,
        reason=REASON_HUMAN if human else REASON_ALLOWED,
        risk=risk,
        target_id=target,
        requires_human=human,
        policy_trace=trace,
    )


def _risk_for_capability(registry: CapabilityRegistry, capability: str) -> str | None:
    spec = registry.get(capability) if hasattr(registry, "get") else None
    risk = getattr(spec, "risk_level", None)
    if risk is None:
        return None
    return risk.value if hasattr(risk, "value") else str(risk)


def _settings_shim() -> Any:
    """Settings con defaults de código cuando no se inyecta ninguno."""
    try:
        from src.core.config import get_settings

        return get_settings()
    except Exception:  # noqa: BLE001 — política con defaults de código
        return _NullSettings()


class _NullSettings:
    """Defaults de código: la política no depende de env para ser segura."""

    def __getattr__(self, name: str) -> Any:
        raise AttributeError(name)


def authorize_decision(
    decision: RoutingDecision,
    context: DecisionContext,
    registry: CapabilityRegistry | None = None,
    *,
    tenant_allowlist: frozenset[str] | None = None,
) -> RoutingDecision:
    """Strip unauthorized capabilities. Never elevates permissions."""
    registry = registry or InMemoryCapabilityRegistry()
    allowlist = tenant_allowlist
    if allowlist is None:
        raw = context.tenant_policy.get("capability_allowlist")
        if isinstance(raw, (list, tuple, set, frozenset)):
            allowlist = frozenset(str(x) for x in raw)
    requested = decision.capability
    allowed = registry.is_allowed(
        requested,
        permissions=context.permissions,
        tenant_allowlist=allowlist,
    )
    if allowed and requested in context.available_capabilities:
        return decision
    fallback = _SAFE_FALLBACK
    if fallback not in context.available_capabilities:
        fallback = "respond_directly"
    decision.capability = fallback
    decision.fallback_used = True
    decision.metadata = {
        **decision.metadata,
        "authorization_denied": True,
        "denied_capability": requested,
        "reason": "authorization",
    }
    decision.needs_tool = False
    decision.needs_agent = False
    decision.needs_workflow = False
    decision.needs_knowledge = fallback.startswith("knowledge.")
    return decision
