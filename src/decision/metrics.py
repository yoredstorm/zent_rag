# =============================================================================
# Decision Engine Prometheus metrics — low cardinality labels.
# =============================================================================
from __future__ import annotations

from src.core.domain.decision import RoutingDecision
from src.decision.judgment import JUDGE_PHASES, usage_phase_label

_PROVIDER_LABELS = ("rules", "jev", "llm", "composite", "legacy")
_CAPABILITY_PREFIXES = (
    "knowledge",
    "database",
    "agent",
    "workflow",
    "tool",
    "document",
    "llm",
    "respond_directly",
)


def _provider(value: str) -> str:
    return value if value in _PROVIDER_LABELS else "other"


def _capability_family(capability: str) -> str:
    if capability == "respond_directly":
        return "respond_directly"
    prefix = (capability or "").split(".", 1)[0]
    return prefix if prefix in _CAPABILITY_PREFIXES else "other"


def record_decision(decision: RoutingDecision, *, fallback_reason: str = "") -> None:
    try:
        from src.infrastructure.observability import metrics as m
    except Exception:  # noqa: BLE001
        return
    provider = _provider(decision.provider)
    family = _capability_family(decision.capability)
    m.zent_decision_requests_total.labels(provider=provider, resolved=str(decision.resolved).lower()).inc()
    m.zent_decision_provider_total.labels(provider=provider).inc()
    m.zent_decision_latency_seconds.labels(provider=provider).observe(max(decision.latency_ms, 0.0) / 1000.0)
    m.zent_decision_confidence.labels(provider=provider).observe(min(1.0, max(0.0, decision.confidence)))
    m.zent_decision_capability_total.labels(capability=family).inc()
    if decision.estimated_cost:
        m.zent_decision_cost_usd.labels(provider=provider).inc(decision.estimated_cost)
    if decision.fallback_used:
        allowed = {
            "jev_unavailable",
            "confidence_low",
            "confidence_mid_disagreement",
            "timeout",
            "invalid",
            "authorization",
        }
        reason = fallback_reason or str(decision.metadata.get("reason") or "unknown")
        if reason not in allowed:
            reason = "other"
        m.zent_decision_fallback_total.labels(reason=reason).inc()


def record_agreement(agreed: bool) -> None:
    try:
        from src.infrastructure.observability import metrics as m
    except Exception:  # noqa: BLE001
        return
    m.zent_decision_agreement_total.labels(agreed=str(bool(agreed)).lower()).inc()


def record_judge(
    payload: dict | None,
    *,
    error: bool = False,
    phase: str = "unknown",
    latency_ms: float = 0.0,
) -> None:
    """Judge calls are metered apart from routing, now with phase labels."""
    try:
        from src.infrastructure.observability import metrics as m
    except Exception:  # noqa: BLE001
        return
    phase_label = usage_phase_label(phase)
    if phase_label not in JUDGE_PHASES:
        phase_label = "other"
    outcome = "error" if error or not isinstance(payload, dict) else "ok"
    m.zent_decision_judge_total.labels(outcome=outcome, phase=phase_label).inc()
    m.zent_decision_judge_latency_seconds.labels(phase=phase_label).observe(
        max(float(latency_ms or 0.0), 0.0) / 1000.0
    )
    if not isinstance(payload, dict):
        return
    usage = payload.get("usage")
    if isinstance(usage, dict):
        m.zent_decision_judge_tokens_total.labels(kind="input", phase=phase_label).inc(
            max(0, int(usage.get("input_tokens") or 0))
        )
        m.zent_decision_judge_tokens_total.labels(kind="output", phase=phase_label).inc(
            max(0, int(usage.get("output_tokens") or 0))
        )
    cost = float(payload.get("estimated_cost") or 0.0)
    if cost > 0:
        m.zent_decision_judge_cost_usd.labels(phase=phase_label).inc(cost)


def record_trace_written(decision: RoutingDecision) -> None:
    try:
        from src.infrastructure.observability import metrics as m
    except Exception:  # noqa: BLE001
        return
    m.zent_decision_traces_total.labels(provider=_provider(decision.provider)).inc()


def record_preflight_pack(pack, *, mode: str = "") -> None:
    """Un pack ejecutado: fase, resultado y preguntas por primitiva (fail-soft)."""
    try:
        from src.infrastructure.observability import metrics as m
    except Exception:  # noqa: BLE001
        return
    phase = usage_phase_label(getattr(pack, "phase", "unknown"))
    if getattr(pack, "skipped_reason", ""):
        outcome = "skipped"
    elif getattr(pack, "error", False):
        outcome = "error"
    else:
        outcome = "ok"
    m.zent_decision_preflight_total.labels(
        mode=str(mode or getattr(pack, "mode", "unknown")), phase=phase, outcome=outcome
    ).inc()
    for question in getattr(pack, "questions", ()) or ():
        m.zent_decision_preflight_questions_total.labels(
            phase=phase, type=str(getattr(question, "type", "unknown"))
        ).inc()


def record_escalation(decision) -> None:
    """La decisión compuesta: qué acción y qué tier salieron del juicio."""
    try:
        from src.infrastructure.observability import metrics as m
    except Exception:  # noqa: BLE001
        return
    mode = str(getattr(decision, "mode", "") or "unknown")
    action = str(getattr(decision, "action", "") or "unknown")
    tier = str(getattr(decision, "tier", "") or "unknown")
    m.zent_decision_preflight_escalation_total.labels(
        mode=mode, action=action, tier=tier
    ).inc()
    if not getattr(decision, "applied", False):
        return
    if not getattr(decision, "allow_generation", True):
        m.zent_decision_preflight_avoided_total.labels(reason=f"action_{action}").inc()
    elif tier in ("small", "deterministic"):
        m.zent_decision_preflight_avoided_total.labels(reason="cheaper_tier").inc()
    uncertain = len(list(getattr(decision, "uncertain_critical", ()) or ()))
    if uncertain:
        m.zent_decision_preflight_uncertain_total.labels(phase="pre_generation").inc(uncertain)
