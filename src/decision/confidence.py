# =============================================================================
# JudgmentConfidencePolicy — un solo lugar para los umbrales del juicio.
# =============================================================================
# Ningún consumidor inventa números: la política resuelve, por pregunta (o por
# fase, o por riesgo), el umbral de Choice, el de Score y las bandas de Noul.
#
# Precedencia: pregunta (`threshold_key` o id) → fase → riesgo → default.
#
# Noul conserva su identidad de tres vías: YES / NO / UNCERTAIN. Los umbrales
# se calibran por pregunta y por riesgo; no hay constantes universales.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.core.domain.decision import RiskLevel
from src.decision.distributions import (
    DIRECTION_NO,
    DIRECTION_UNCERTAIN,
    DIRECTION_YES,
    NoulReading,
    noul_reading,
)

VERDICT_YES = DIRECTION_YES
VERDICT_NO = DIRECTION_NO
VERDICT_UNCERTAIN = DIRECTION_UNCERTAIN

#: Umbrales por defecto. Calibrables por settings/tenant; no son dogma (§24).
DEFAULT_CHOICE_THRESHOLD = 0.70
DEFAULT_SCORE_THRESHOLD = 0.70
DEFAULT_NOUL_YES = 0.65
DEFAULT_NOUL_NO = 0.35
DEFAULT_AMBIGUITY_MARGIN = 0.12


@dataclass(frozen=True, kw_only=True)
class JudgmentThresholds:
    """Umbrales de una pregunta concreta."""

    choice: float = DEFAULT_CHOICE_THRESHOLD
    score: float = DEFAULT_SCORE_THRESHOLD
    noul_yes: float = DEFAULT_NOUL_YES
    noul_no: float = DEFAULT_NOUL_NO
    ambiguity_margin: float = DEFAULT_AMBIGUITY_MARGIN
    require_certainty: float = 0.0

    def verdict(self, reading: NoulReading | None) -> str:
        """YES / NO / UNCERTAIN. Nunca convierte un 0.51 en YES (§26)."""
        if reading is None:
            return VERDICT_UNCERTAIN
        if reading.certainty < float(self.require_certainty or 0.0):
            return VERDICT_UNCERTAIN
        if reading.is_yes(self.noul_yes):
            return VERDICT_YES
        if reading.is_no(self.noul_no):
            return VERDICT_NO
        return VERDICT_UNCERTAIN

    def is_yes(self, reading: NoulReading | None) -> bool:
        return self.verdict(reading) == VERDICT_YES

    def is_no(self, reading: NoulReading | None) -> bool:
        return self.verdict(reading) == VERDICT_NO

    def is_uncertain(self, reading: NoulReading | None) -> bool:
        return self.verdict(reading) == VERDICT_UNCERTAIN

    def read(self, answer: Any) -> NoulReading | None:
        """Lee un Noul con las bandas de esta pregunta (0.0 sigue siendo NO)."""
        if answer is None:
            return None
        if isinstance(answer, NoulReading):
            return answer
        if isinstance(answer, dict) and "noul" in answer:
            from src.decision.questions import safe_noul

            return noul_reading(
                safe_noul(answer.get("noul"), 0.5),
                yes_threshold=self.noul_yes,
                no_threshold=self.noul_no,
            )
        if isinstance(answer, (int, float)) and not isinstance(answer, bool):
            return noul_reading(
                float(answer), yes_threshold=self.noul_yes, no_threshold=self.noul_no
            )
        return None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "choice": round(self.choice, 4),
            "score": round(self.score, 4),
            "noul_yes": round(self.noul_yes, 4),
            "noul_no": round(self.noul_no, 4),
            "ambiguity_margin": round(self.ambiguity_margin, 4),
        }


#: Umbrales por pregunta: lo que cambia una decisión, no lo que suena prudente.
_QUESTION_THRESHOLDS: dict[str, JudgmentThresholds] = {
    "reasoning_shape": JudgmentThresholds(choice=0.70),
    "preferred_capability": JudgmentThresholds(choice=0.60),
    "analysis_complexity": JudgmentThresholds(score=0.65),
    "scenario_completeness": JudgmentThresholds(score=0.70),
    "state_reconstruction_quality": JudgmentThresholds(score=0.70),
    "rule_coverage": JudgmentThresholds(score=0.65),
    "hypothesis_user_supported": JudgmentThresholds(noul_yes=0.70, noul_no=0.30),
    "hypothesis_user_contradicted": JudgmentThresholds(noul_yes=0.70, noul_no=0.30),
    "inference_possible": JudgmentThresholds(noul_yes=0.70),
    "inference_supported": JudgmentThresholds(noul_yes=0.75, noul_no=0.25),
    "analysis_complete": JudgmentThresholds(noul_yes=0.75, noul_no=0.25),
    "answerable": JudgmentThresholds(noul_yes=0.80, noul_no=0.20),
    "critical_fact_missing": JudgmentThresholds(noul_yes=0.70, noul_no=0.30),
    "critical_conflict_unresolved": JudgmentThresholds(noul_yes=0.70, noul_no=0.30),
    "critical_unknown_remaining": JudgmentThresholds(noul_yes=0.70, noul_no=0.30),
    "critical_transition_missing": JudgmentThresholds(noul_yes=0.70, noul_no=0.30),
    "timeline_coherent": JudgmentThresholds(noul_yes=0.70),
    "answer_readiness": JudgmentThresholds(score=0.80),
    "evidence_strength": JudgmentThresholds(score=0.75),
    "risk_of_wrong_answer": JudgmentThresholds(score=0.75),
    "next_action": JudgmentThresholds(choice=0.80),
    "generation_tier": JudgmentThresholds(choice=0.70),
    "expensive_llm_needed": JudgmentThresholds(noul_yes=0.70, noul_no=0.30),
    "simple_deterministic_answer_possible": JudgmentThresholds(
        noul_yes=0.75, noul_no=0.25
    ),
    "needs_complex_reasoning_model": JudgmentThresholds(noul_yes=0.75, noul_no=0.25),
}

#: Umbrales por riesgo: una señal de alto riesgo exige más certeza.
_RISK_THRESHOLDS: dict[str, JudgmentThresholds] = {
    RiskLevel.LOW.value: JudgmentThresholds(choice=0.60, score=0.60, noul_yes=0.60, noul_no=0.40),
    RiskLevel.MEDIUM.value: JudgmentThresholds(choice=0.70, score=0.70, noul_yes=0.65, noul_no=0.35),
    RiskLevel.HIGH.value: JudgmentThresholds(choice=0.80, score=0.75, noul_yes=0.75, noul_no=0.25),
    RiskLevel.CRITICAL.value: JudgmentThresholds(choice=0.90, score=0.85, noul_yes=0.85, noul_no=0.15),
}


@dataclass(frozen=True)
class JudgmentConfidencePolicy:
    """Resuelve umbrales. Configurable; el default no es universal (§24, §25)."""

    default: JudgmentThresholds = field(default_factory=JudgmentThresholds)
    by_question: dict[str, JudgmentThresholds] = field(default_factory=dict)
    by_phase: dict[str, JudgmentThresholds] = field(default_factory=dict)
    by_risk: dict[str, JudgmentThresholds] = field(default_factory=dict)

    def for_question(
        self,
        question_id: str,
        *,
        phase: str | None = None,
        risk: str = RiskLevel.LOW.value,
        threshold_key: str = "",
    ) -> JudgmentThresholds:
        key = threshold_key or question_id
        if key in self.by_question:
            return self.by_question[key]
        if phase and phase in self.by_phase:
            return self.by_phase[phase]
        if risk in self.by_risk:
            return self.by_risk[risk]
        return self.default

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "default": self.default.to_public_dict(),
            "questions": {
                key: value.to_public_dict() for key, value in sorted(self.by_question.items())
            },
            "phases": {
                key: value.to_public_dict() for key, value in sorted(self.by_phase.items())
            },
            "risk": {
                key: value.to_public_dict() for key, value in sorted(self.by_risk.items())
            },
        }

    @classmethod
    def default_policy(cls) -> "JudgmentConfidencePolicy":
        return cls(
            default=JudgmentThresholds(),
            by_question=dict(_QUESTION_THRESHOLDS),
            by_phase={},
            by_risk=dict(_RISK_THRESHOLDS),
        )

    @classmethod
    def from_settings(cls, settings: Any) -> "JudgmentConfidencePolicy":
        """Defaults del código + overrides de settings (nada hardcodeado)."""
        default = JudgmentThresholds(
            noul_yes=float(getattr(settings, "DECISION_NOUL_YES", DEFAULT_NOUL_YES)),
            noul_no=float(getattr(settings, "DECISION_NOUL_NO", DEFAULT_NOUL_NO)),
        )
        overrides: dict[str, JudgmentThresholds] = {}
        next_action_choice = _first_attr(
            settings, "RAG_JEV_PREFLIGHT_NEXT_ACTION_CHOICE", "JEV_PREFLIGHT_NEXT_ACTION_CHOICE"
        )
        if next_action_choice is not None:
            overrides["next_action"] = JudgmentThresholds(
                choice=float(next_action_choice),
                noul_yes=default.noul_yes,
                noul_no=default.noul_no,
            )
        strict = _first_attr(
            settings, "RAG_JEV_PREFLIGHT_STRICT_THRESHOLDS", "JEV_PREFLIGHT_STRICT_THRESHOLDS"
        )
        risk_map = dict(_RISK_THRESHOLDS)
        if strict is not None:
            risk_map[RiskLevel.HIGH.value] = JudgmentThresholds(
                choice=float(strict), score=float(strict), noul_yes=float(strict)
            )
        return cls(
            default=default,
            by_question={**_QUESTION_THRESHOLDS, **overrides},
            by_phase={},
            by_risk=risk_map,
        )


def _first_attr(settings: Any, *names: str) -> Any:
    for name in names:
        value = getattr(settings, name, None)
        if value is not None:
            return value
    return None


_POLICY: JudgmentConfidencePolicy | None = None


def default_policy() -> JudgmentConfidencePolicy:
    """Política del proceso: settings si están disponibles, defaults del código."""
    global _POLICY
    if _POLICY is None:
        try:
            from src.core.config import get_settings

            _POLICY = JudgmentConfidencePolicy.from_settings(get_settings())
        except Exception:  # noqa: BLE001 — sin settings, defaults del código
            _POLICY = JudgmentConfidencePolicy.default_policy()
    return _POLICY


def reset_policy() -> None:
    """Sólo para tests: la política se re-resuelve desde settings."""
    global _POLICY
    _POLICY = None


__all__ = [
    "DEFAULT_AMBIGUITY_MARGIN",
    "DEFAULT_CHOICE_THRESHOLD",
    "DEFAULT_NOUL_NO",
    "DEFAULT_NOUL_YES",
    "DEFAULT_SCORE_THRESHOLD",
    "JudgmentConfidencePolicy",
    "JudgmentThresholds",
    "VERDICT_NO",
    "VERDICT_UNCERTAIN",
    "VERDICT_YES",
    "default_policy",
    "reset_policy",
]
