# =============================================================================
# Optional live JEV tests. Skipped unless TYPESAFE_API_KEY / JEV_API_KEY exist.
# =============================================================================
from __future__ import annotations

import os
from uuid import uuid4

import pytest

from src.core.domain.decision import DecisionContext
from src.decision.providers.jev import JevDecisionProvider
from src.decision.settings import DecisionEngineSettings

_KEY = (
    os.environ.get("TYPESAFE_API_KEY")
    or os.environ.get("JEV_API_KEY")
    or os.environ.get("RAG_JEV_API_KEY")
    or ""
).strip()

pytestmark = pytest.mark.skipif(not _KEY, reason="JEV_API_KEY / TYPESAFE_API_KEY not set")


@pytest.mark.asyncio
async def test_live_jev_choice_on_sample_state() -> None:
    settings = DecisionEngineSettings(
        jev_api_key=_KEY,
        jev_timeout_seconds=20.0,
        routing_mode="jev",
    )
    provider = JevDecisionProvider(settings)
    result = await provider.decide(
        DecisionContext(
            user_request="What is the vacation policy?",
            organization_id=uuid4(),
            available_capabilities=("knowledge.answer", "database.query", "respond_directly"),
            knowledge_enabled=True,
        )
    )
    assert result.resolved is True
    assert result.capability in {"knowledge.answer", "database.query", "respond_directly"}
    assert 0.0 <= result.confidence <= 1.0
