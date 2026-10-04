# =============================================================================
# Knowledge Nutrition — feedback -> clasificación -> acción -> score
# =============================================================================
from __future__ import annotations

from .actions import MIN_ACTION_CONFIDENCE, action_for_classification
from .classifier import classify_failure
from .contracts import (
    NUTRITION_POLICY_VERSION,
    NUTRITION_SCORE_VERSION,
    NUTRITION_WEIGHTS,
    FailureClassification,
    FailureSignals,
    FailureType,
    NutritionAction,
    NutritionActionStatus,
    NutritionActionType,
    NutritionDimensions,
    NutritionScore,
)
from .demand import (
    DemandItem,
    QueryDemandModel,
    QueryDemandProfile,
    build_demand_model,
    demand_profile_from_acceptance,
)
from .score import compute_nutrition_score
from .service import NutritionOutcome, apply_feedback_nutrition
from .store import PostgresNutritionStore

__all__ = [
    "MIN_ACTION_CONFIDENCE",
    "NUTRITION_POLICY_VERSION",
    "NUTRITION_SCORE_VERSION",
    "NUTRITION_WEIGHTS",
    "DemandItem",
    "FailureClassification",
    "FailureSignals",
    "FailureType",
    "NutritionAction",
    "NutritionActionStatus",
    "NutritionActionType",
    "NutritionDimensions",
    "NutritionOutcome",
    "NutritionScore",
    "PostgresNutritionStore",
    "QueryDemandModel",
    "QueryDemandProfile",
    "action_for_classification",
    "apply_feedback_nutrition",
    "build_demand_model",
    "classify_failure",
    "compute_nutrition_score",
    "demand_profile_from_acceptance",
]
