# =============================================================================
# Knowledge Learning — API models (Pydantic v2)
# =============================================================================
from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from src.core.domain.knowledge_learning import (
    DEFAULT_GATE_THRESHOLDS,
    DEFAULT_SCORE_WEIGHTS,
)

_WEIGHT_KEYS = set(DEFAULT_SCORE_WEIGHTS)
_THRESHOLD_KEYS = set(DEFAULT_GATE_THRESHOLDS)


class StartLearningRequest(BaseModel):
    """POST /api/v1/knowledge/learning/start."""

    catalog_source_id: UUID
    trigger: Literal["manual", "scheduled", "onboarding"] = "manual"


class LearningSettingsRequest(BaseModel):
    """PUT /api/v1/knowledge/learning/settings (config por tenant)."""

    weights: dict[str, float] | None = None
    thresholds: dict[str, float] | None = None

    @field_validator("weights")
    @classmethod
    def _validate_weights(cls, value: dict[str, float] | None):
        if value is None:
            return value
        unknown = set(value) - _WEIGHT_KEYS
        if unknown:
            raise ValueError(
                f"weights desconocidos: {sorted(unknown)}; válidos: {sorted(_WEIGHT_KEYS)}"
            )
        for key, weight in value.items():
            if not 0 <= float(weight) <= 1:
                raise ValueError(f"weight '{key}' debe estar entre 0 y 1")
        return value

    @field_validator("thresholds")
    @classmethod
    def _validate_thresholds(cls, value: dict[str, float] | None):
        if value is None:
            return value
        unknown = set(value) - _THRESHOLD_KEYS
        if unknown:
            raise ValueError(
                f"thresholds desconocidos: {sorted(unknown)}; "
                f"válidos: {sorted(_THRESHOLD_KEYS)}"
            )
        for key, threshold in value.items():
            if float(threshold) < 0:
                raise ValueError(f"threshold '{key}' no puede ser negativo")
        return value


class SkipQuestionRequest(BaseModel):
    """POST /questions/{id}/skip (FASE 33D)."""

    reason: str | None = Field(default=None, max_length=500)


class AnswerQuestionRequest(BaseModel):
    """POST /questions/{id}/answer (FASE 33D)."""

    answer: str = Field(default="", max_length=8000)
    structured_answer: dict | None = None
    choice: str | None = Field(default=None, max_length=500)


class EvaluationRunRequest(BaseModel):
    """POST /evaluation/run (FASE 33G)."""

    source_id: UUID
