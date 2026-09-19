# =============================================================================
# Canary / confidence helpers.
# =============================================================================
from __future__ import annotations

import hashlib
from uuid import UUID

from src.core.domain.decision import RoutingMode
from src.decision.settings import DecisionEngineSettings


def in_canary(request_id: UUID, percentage: int) -> bool:
    pct = int(percentage)
    if pct <= 0:
        return False
    if pct >= 100:
        return True
    digest = hashlib.sha256(str(request_id).encode("utf-8")).digest()
    return digest[0] % 100 < pct


def should_execute_engine(settings: DecisionEngineSettings, request_id: UUID) -> bool:
    mode = settings.effective_mode
    if mode == RoutingMode.JEV.value:
        return True
    if mode == RoutingMode.HYBRID.value:
        return in_canary(request_id, settings.canary_percentage)
    return False


def capability_from_legacy_method(method: str) -> str:
    if method == "sql":
        return "database.query"
    return "knowledge.answer"
