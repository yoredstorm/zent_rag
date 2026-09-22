# =============================================================================
# OutcomeEvaluator — éxito multidimensional. HTTP 200 no cuenta.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass

from src.core.domain.learning_cycle import RunSignal


def _clamp(value: float | None) -> float | None:
    if value is None:
        return None
    return min(1.0, max(0.0, float(value)))


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


@dataclass(frozen=True, kw_only=True)
class OutcomeVector:
    quality: float | None
    grounding: float | None
    task_success: float | None
    cost: float
    latency_ms: float
    signals: dict[str, float | None]

    def as_dict(self) -> dict:
        return {
            "quality": self.quality,
            "grounding": self.grounding,
            "task_success": self.task_success,
            "cost": self.cost,
            "latency_ms": self.latency_ms,
            "signals": dict(self.signals),
        }


class OutcomeEvaluator:
    """Agrega señales. No las aplasta a un único número."""

    def evaluate(self, signal: RunSignal) -> OutcomeVector:
        flags = self._flags(signal)
        grounding_parts: list[float] = []
        if signal.grounding is not None:
            grounding = _clamp(signal.grounding)
        else:
            if signal.answer_grounded is not None:
                grounding_parts.append(1.0 if signal.answer_grounded else 0.0)
            if signal.claims_supported is not None:
                grounding_parts.append(1.0 if signal.claims_supported else 0.0)
            grounding = _mean(grounding_parts)
        if signal.task_success is not None:
            task_success = _clamp(signal.task_success)
        else:
            task_success = _mean([value for value in flags.values() if value is not None])
        return OutcomeVector(
            quality=_clamp(signal.quality),
            grounding=grounding,
            task_success=task_success,
            cost=float(signal.cost or 0.0),
            latency_ms=float(signal.latency_ms or 0.0),
            signals=flags,
        )

    def _flags(self, signal: RunSignal) -> dict[str, float | None]:
        feedback = (signal.explicit_feedback or "").strip().lower()
        feedback_value: float | None
        if feedback in {"positive", "accepted", "up"}:
            feedback_value = 1.0
        elif feedback in {"negative", "rejected", "down"}:
            feedback_value = 0.0
        else:
            feedback_value = None
        human = None if signal.human_accepted is None else (1.0 if signal.human_accepted else 0.0)
        return {
            "retrieval_successful": _bit(signal.retrieval_successful),
            "evidence_sufficient": _bit(signal.evidence_sufficient),
            "answer_grounded": _bit(signal.answer_grounded),
            "claims_supported": _bit(signal.claims_supported),
            "tool_succeeded": _bit(signal.tool_succeeded),
            "agent_completed": _bit(signal.agent_completed),
            "workflow_completed": _bit(signal.workflow_completed),
            "no_immediate_retry": 0.0 if signal.retried else 1.0,
            "no_fallback": 0.0 if signal.fallback else 1.0,
            "human_accepted": human,
            "explicit_feedback": feedback_value,
        }


def _bit(value: bool | None) -> float | None:
    if value is None:
        return None
    return 1.0 if value else 0.0
