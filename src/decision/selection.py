# =============================================================================
# Target selection — JEV elige dentro de un CandidateSet autorizado.
# =============================================================================
# Flujo: candidates autorizados → JEV Choice (target) → policy (risk-aware)
# → AuthorizedDecision → dispatcher. JEV nunca autoriza ni ejecuta: si el
# target no está en el set ofrecido, el judgment se rechaza y se aplica el
# fallback de la política.
#
# HIGH/CRITICAL exigen DOS señales independientes: target_choice y
# action_warranted. No se combinan con max().
# =============================================================================
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from src.decision.batch import PhaseQuestions, QuestionSpec, answer_for, noul_for
from src.decision.budget import budget_summary
from src.decision.candidates import CandidateSet
from src.decision.judgment import PHASE_TARGET_SELECTION, JudgmentContext, call_phase_judge
from src.decision.questions import noul_certainty
from src.decision.risk_policy import (
    FALLBACK_CLARIFY,
    FALLBACK_DEFAULT,
    FALLBACK_HUMAN,
    FALLBACK_RESPOND,
    DecisionRiskPolicy,
    RiskThresholds,
)

POLICY_EXECUTE = "execute"


@dataclass(frozen=True, kw_only=True)
class TargetSelection:
    """Resultado de selección. `policy_action` lo decide el código, no JEV."""

    capability: str
    kind: str
    target_id: str | None = None
    choice: str | None = None
    confidence: float = 0.0
    alternatives: tuple[str, ...] = ()
    warranted: bool | None = None
    warranted_noul: float | None = None
    warranted_certainty: float = 0.0
    policy_action: str = FALLBACK_RESPOND
    reason: str = ""
    candidates: int = 0
    candidate_ids: tuple[str, ...] = ()
    risk: str = "low"
    jev_used: bool = False
    provider: str = "rules"
    model: str = ""
    latency_ms: float = 0.0
    questions: tuple[str, ...] = ()
    thresholds: dict[str, Any] = field(default_factory=dict)

    @property
    def authorized(self) -> bool:
        return self.policy_action == POLICY_EXECUTE and bool(self.target_id)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "kind": self.kind,
            "target_id": self.target_id,
            "choice": self.choice,
            "confidence": round(self.confidence, 4),
            "alternatives": list(self.alternatives[:3]),
            "warranted": self.warranted,
            "warranted_certainty": round(self.warranted_certainty, 4),
            "policy_action": self.policy_action,
            "reason": self.reason,
            "candidates": self.candidates,
            "risk": self.risk,
            "jev_used": self.jev_used,
            "provider": self.provider,
            "model": self.model,
            "latency_ms": round(self.latency_ms, 2),
            "questions": list(self.questions),
            "thresholds": self.thresholds,
        }


def build_target_questions(
    candidates: CandidateSet,
    *,
    capability: str,
    thresholds: RiskThresholds,
) -> PhaseQuestions:
    """`target` (Choice) + `action_warranted` (Noul) cuando la política lo exige."""
    criteria = {candidate.id: candidate.to_jevy_criteria() for candidate in candidates.candidates}
    phase = PhaseQuestions(phase=PHASE_TARGET_SELECTION)
    phase.add(
        QuestionSpec(
            id="target",
            type="choice",
            instructions=(
                "Which candidate in `available_targets` is best suited for "
                "`user_request` given `capability`? Only offered ids are valid."
            ),
            criteria=criteria,
            sources=("target_selection",),
        )
    )
    if thresholds.warrant_required:
        phase.add(
            QuestionSpec(
                id="action_warranted",
                type="noul",
                instructions=(
                    "Is executing this target clearly warranted by `user_request` "
                    "and the candidate's risk/cost? If unsure, answer no."
                ),
                sources=("target_selection",),
            )
        )
    return phase


def _selection_state(
    *,
    user_request: str,
    capability: str,
    candidates: CandidateSet,
    tenant_policy: dict[str, Any] | None,
    budget: dict[str, Any] | None,
    thresholds: RiskThresholds,
) -> dict[str, Any]:
    lines = [f"[{c.id}] {c.to_jevy_criteria()}" for c in candidates.candidates[:12]]
    policy_view = {
        key: tenant_policy.get(key)
        for key in ("target_allowlist", "risk_policy", "sources")
        if isinstance(tenant_policy, dict) and tenant_policy.get(key) is not None
    }
    return {
        "user_request": (user_request or "")[:2000],
        "capability": capability,
        "available_targets": "\n".join(lines)[:4000],
        "tenant_policy": policy_view,
        "budget": budget_summary(budget),
        "risk_level": thresholds.risk,
    }


def _compose(
    *,
    capability: str,
    kind: str,
    candidates: CandidateSet,
    thresholds: RiskThresholds,
    choice: str,
    confidence: float,
    probabilities: dict[str, Any] | None,
    warranted_noul: float | None,
    jev_used: bool,
    provider: str,
    model: str,
    latency_ms: float,
    questions: tuple[str, ...],
    reason: str = "",
) -> TargetSelection:
    valid_ids = set(candidates.ids())
    alternatives = tuple(
        str(key)
        for key, _ in sorted(
            (
                (str(key), float(value))
                for key, value in (probabilities or {}).items()
                if str(key) != choice and str(key) in valid_ids
            ),
            key=lambda item: item[1],
            reverse=True,
        )[:3]
    )
    warranted_certainty = noul_certainty(warranted_noul) if warranted_noul is not None else 0.0
    warranted_ok = True
    if thresholds.warrant_required:
        warranted_ok = warranted_noul is not None and warranted_noul >= thresholds.warrant_threshold
    if choice not in valid_ids:
        action = thresholds.on_low_confidence
        why = reason or "invalid_target"
    elif confidence < thresholds.choice_threshold:
        action = thresholds.on_low_confidence
        why = reason or "low_confidence"
    elif not warranted_ok:
        action = thresholds.on_low_confidence
        why = reason or "action_not_warranted"
    else:
        action = POLICY_EXECUTE
        why = reason or "ok"
    return TargetSelection(
        capability=capability,
        kind=kind,
        target_id=choice if action == POLICY_EXECUTE else None,
        choice=choice or None,
        confidence=confidence,
        alternatives=alternatives,
        warranted=None if warranted_noul is None else warranted_ok,
        warranted_noul=warranted_noul,
        warranted_certainty=warranted_certainty,
        policy_action=action,
        reason=why,
        candidates=len(candidates.candidates),
        candidate_ids=candidates.ids(),
        risk=thresholds.risk,
        jev_used=jev_used,
        provider=provider,
        model=model,
        latency_ms=latency_ms,
        questions=questions,
        thresholds=thresholds.to_public_dict(),
    )


async def select_target(
    judge: Any,
    *,
    capability: str,
    candidates: CandidateSet,
    user_request: str,
    risk_policy: DecisionRiskPolicy,
    risk: str | None = None,
    explicit_target: str | None = None,
    tenant_policy: dict[str, Any] | None = None,
    budget: dict[str, Any] | None = None,
    organization_id: UUID | None = None,
    request_id: UUID | None = None,
    agent_id: UUID | None = None,
    cache: Any = None,
) -> TargetSelection:
    """Selecciona target dentro del set autorizado. Nunca ejecuta nada."""
    kind = candidates.kind
    resolved_risk = str(risk or _default_risk(candidates))
    thresholds = risk_policy.thresholds(resolved_risk)

    if explicit_target:
        # El target explícito siempre gana: no se gasta juicio.
        return TargetSelection(
            capability=capability,
            kind=kind,
            target_id=explicit_target,
            choice=explicit_target,
            confidence=1.0,
            policy_action=POLICY_EXECUTE,
            reason="explicit_target",
            candidates=len(candidates.candidates),
            candidate_ids=candidates.ids(),
            risk=resolved_risk,
            thresholds=thresholds.to_public_dict(),
        )
    if candidates.empty:
        return TargetSelection(
            capability=capability,
            kind=kind,
            policy_action=thresholds.on_low_confidence,
            reason="no_candidates",
            candidates=0,
            risk=resolved_risk,
            thresholds=thresholds.to_public_dict(),
        )
    if len(candidates.candidates) == 1:
        only = candidates.candidates[0]
        return TargetSelection(
            capability=capability,
            kind=kind,
            target_id=only.id,
            choice=only.id,
            confidence=1.0,
            policy_action=POLICY_EXECUTE,
            reason="single_candidate",
            candidates=1,
            candidate_ids=candidates.ids(),
            risk=resolved_risk,
            thresholds=thresholds.to_public_dict(),
        )
    if judge is None:
        return TargetSelection(
            capability=capability,
            kind=kind,
            policy_action=thresholds.on_low_confidence,
            reason="jev_unavailable",
            candidates=len(candidates.candidates),
            candidate_ids=candidates.ids(),
            risk=resolved_risk,
            thresholds=thresholds.to_public_dict(),
        )

    phase = build_target_questions(candidates, capability=capability, thresholds=thresholds)
    state = _selection_state(
        user_request=user_request,
        capability=capability,
        candidates=candidates,
        tenant_policy=tenant_policy,
        budget=budget,
        thresholds=thresholds,
    )
    try:
        payload = await call_phase_judge(
            judge,
            phase=PHASE_TARGET_SELECTION,
            state=state,
            questions=phase.to_jevy(),
            context=JudgmentContext(
                phase=PHASE_TARGET_SELECTION,
                organization_id=organization_id,
                request_id=request_id,
                agent_id=agent_id,
                capability=capability,
            ),
            cache=cache,
        )
    except Exception:  # noqa: BLE001 — un juicio caído nunca ejecuta nada
        payload = None
    if not isinstance(payload, dict):
        return TargetSelection(
            capability=capability,
            kind=kind,
            policy_action=thresholds.on_low_confidence,
            reason="no_payload",
            candidates=len(candidates.candidates),
            candidate_ids=candidates.ids(),
            risk=resolved_risk,
            thresholds=thresholds.to_public_dict(),
        )
    choice_ans = answer_for(payload, "target") or {}
    choice = str(choice_ans.get("choice") or "")
    confidence = float(choice_ans.get("confidence") or 0.0)
    probabilities = choice_ans.get("probabilities") if isinstance(choice_ans.get("probabilities"), dict) else {}
    warranted_noul = noul_for(payload, "action_warranted", default=None)
    return _compose(
        capability=capability,
        kind=kind,
        candidates=candidates,
        thresholds=thresholds,
        choice=choice,
        confidence=confidence,
        probabilities=probabilities,
        warranted_noul=warranted_noul,
        jev_used=True,
        provider=str(payload.get("provider") or "jev"),
        model=str(payload.get("model") or ""),
        latency_ms=float(payload.get("latency_ms") or 0.0),
        questions=phase.ids(),
    )


def _default_risk(candidates: CandidateSet) -> str:
    """Riesgo del set: el máximo de los candidatos (conservador)."""
    if not candidates.candidates:
        return "low"
    from src.decision.candidates import risk_rank

    top = max(candidates.candidates, key=lambda item: risk_rank(item.risk))
    return top.risk


# -----------------------------------------------------------------------------
# Observabilidad de selección (sin chain-of-thought)
# -----------------------------------------------------------------------------

_SELECTION_OBSERVATIONS: deque[dict[str, Any]] = deque(maxlen=200)


def record_candidate_set(candidate_set: CandidateSet) -> None:
    """Candidatos ofrecidos y rechazos por razón (sin datos sensibles)."""
    try:
        import src.infrastructure.observability.metrics as m

        kind = str(candidate_set.kind)
        m.zent_decision_candidates_total.labels(kind=kind).observe(
            len(candidate_set.candidates)
        )
        for rejection in candidate_set.rejected:
            m.zent_decision_candidates_rejected_total.labels(
                kind=kind, reason=rejection.reason
            ).inc()
    except Exception:  # noqa: BLE001
        pass


def record_target_selection(selection: TargetSelection, *, mode: str = "on") -> None:
    """Observación acotada del resultado de selección (sin CoT)."""
    try:
        import src.infrastructure.observability.metrics as m

        m.zent_decision_target_selection_total.labels(
            mode=str(mode), kind=str(selection.kind), action=str(selection.policy_action)
        ).inc()
    except Exception:  # noqa: BLE001
        pass
    _SELECTION_OBSERVATIONS.append({"mode": str(mode), **selection.to_public_dict()})


def selection_observations() -> list[dict[str, Any]]:
    return list(_SELECTION_OBSERVATIONS)


def clear_selection_observations() -> None:
    _SELECTION_OBSERVATIONS.clear()


def default_target(candidates: CandidateSet, *, tenant_policy: dict[str, Any] | None = None) -> str | None:
    """Target por defecto del tenant, si está declarado y es candidato válido."""
    policy = tenant_policy or {}
    defaults = policy.get("default_targets")
    if not isinstance(defaults, dict):
        return None
    kind = candidates.kind
    preferred = defaults.get(kind)
    if preferred and candidates.get(str(preferred)):
        return str(preferred)
    return None


def selection_outcome(
    selection: TargetSelection,
    *,
    candidates: CandidateSet,
    tenant_policy: dict[str, Any] | None = None,
) -> TargetSelection:
    """Aplica el fallback de la política cuando no se ejecuta."""
    import dataclasses

    if selection.policy_action != FALLBACK_DEFAULT:
        return selection
    preferred = default_target(candidates, tenant_policy=tenant_policy)
    if preferred:
        return dataclasses.replace(
            selection,
            target_id=preferred,
            choice=preferred,
            policy_action=POLICY_EXECUTE,
            reason="default_target",
        )
    return dataclasses.replace(
        selection, policy_action=FALLBACK_RESPOND, reason="no_default_target"
    )


__all__ = [
    "FALLBACK_CLARIFY",
    "FALLBACK_DEFAULT",
    "FALLBACK_HUMAN",
    "FALLBACK_RESPOND",
    "POLICY_EXECUTE",
    "TargetSelection",
    "build_target_questions",
    "default_target",
    "select_target",
    "selection_outcome",
]
