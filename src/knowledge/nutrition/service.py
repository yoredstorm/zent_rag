# =============================================================================
# Knowledge Nutrition — servicio del loop feedback -> acción
# =============================================================================
# Punto de entrada ÚNICO para convertir señales reales de un run en una acción
# de nutrición. Reutiliza el feedback/tracing existente: no crea un segundo
# sistema de feedback.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from src.infrastructure.observability.logging_config import get_logger

from .actions import action_for_classification
from .classifier import classify_failure
from .contracts import FailureClassification, FailureSignals, NutritionAction
from .store import PostgresNutritionStore

logger = get_logger(__name__)


@dataclass(frozen=True)
class NutritionOutcome:
    classification: FailureClassification
    action: NutritionAction
    persisted: bool = False
    action_id: str | None = None
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "classification": self.classification.to_dict(),
            "action": self.action.to_dict(),
            "persisted": self.persisted,
            "action_id": self.action_id,
            "warnings": list(self.warnings),
        }


async def apply_feedback_nutrition(
    signals: FailureSignals,
    *,
    organization_id: UUID,
    store: PostgresNutritionStore | None = None,
    persist: bool = True,
    model_version: str | None = None,
) -> NutritionOutcome:
    """Señales del run -> clasificación -> acción. Nunca destructiva."""
    classification = classify_failure(signals)
    action = action_for_classification(
        classification,
        organization_id=str(organization_id),
        workspace_id=signals.workspace_id,
        source_id=signals.source_id,
        document_id=signals.document_id,
        query=signals.query,
        evidence={"signals": classification.signals},
        model_version=model_version,
    )
    warnings: list[str] = []
    action_id: str | None = None
    persisted = False
    if persist:
        try:
            store = store or PostgresNutritionStore()
            action_id = await store.save_action(action, organization_id=organization_id)
            persisted = action_id is not None
        except Exception as exc:  # noqa: BLE001 — el feedback nunca rompe el run
            warnings.append(f"nutrition_action_persist_failed: {str(exc)[:200]}")
            logger.warning(
                "Nutrition action persist failed",
                failure_type=classification.failure_type,
                error=str(exc)[:250],
            )
    _observe(organization_id, action)
    return NutritionOutcome(
        classification=classification,
        action=action,
        persisted=persisted,
        action_id=action_id,
        warnings=tuple(warnings),
    )


def _observe(organization_id: UUID, action: NutritionAction) -> None:
    try:
        from src.infrastructure.observability.metrics import (
            knowledge_nutrition_actions_total,
        )

        knowledge_nutrition_actions_total.labels(
            organization_id=str(organization_id), action_type=action.action_type
        ).inc()
    except Exception:  # noqa: BLE001
        return
