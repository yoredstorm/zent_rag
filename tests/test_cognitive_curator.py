# =============================================================================
# Knowledge Curator — Phase 7 (sugerencias gobernadas)
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest

from src.core.domain.catalog import CatalogProvenance
from src.core.domain.curator import (
    KnowledgeSuggestion,
    SuggestionKind,
    SuggestionStatus,
)


def test_suggestion_law_requires_human_for_approval() -> None:
    proposed = KnowledgeSuggestion(
        organization_id=uuid4(),
        kind=SuggestionKind.CONCEPT_REVIEW,
        title="Revisar conflicto",
    )
    assert proposed.status is SuggestionStatus.PROPOSED
    assert proposed.provenance is CatalogProvenance.INFERRED

    with pytest.raises(ValueError):
        KnowledgeSuggestion(
            organization_id=uuid4(),
            kind=SuggestionKind.FACT_CANDIDATE,
            title="x",
            status=SuggestionStatus.APPROVED,
        )
    with pytest.raises(ValueError):
        KnowledgeSuggestion(
            organization_id=uuid4(),
            kind=SuggestionKind.FACT_CANDIDATE,
            title="x",
            confidence=1.5,
        )


class _FakeCognitiveRepo:
    def __init__(self, plan: dict) -> None:
        self.plan = plan
        self.run_id = uuid4()

    async def get_run(self, organization_id, run_id):
        if str(run_id) != str(self.run_id):
            return None
        return {
            "id": str(self.run_id),
            "organization_id": str(organization_id),
            "workspace_id": None,
            "status": "completed",
            "plan": self.plan,
        }


class _FakeCuratorRepo:
    def __init__(self) -> None:
        self.proposed: list[KnowledgeSuggestion] = []

    async def propose(self, suggestion):
        self.proposed.append(suggestion)
        return suggestion


@pytest.mark.asyncio
async def test_curator_proposes_from_run_observations() -> None:
    from src.platform.cognitive.curator import KnowledgeCurator

    claim_id = uuid4()
    plan = {
        "conflicts": [
            {
                "claims": [str(claim_id)],
                "conflict_type": "temporal_update",
                "reason": "[temporal_update] penalidad distinta",
                "resolution": {"requires_review": True},
            }
        ],
        "debate": [
            {
                "claim_id": str(claim_id),
                "kind": "upheld",
                "challenge": {"detail": "claim sin evidencia"},
                "resolution_note": "challenge sostenido",
                "evidence_check_ratio": 0.0,
            },
            {
                "claim_id": str(uuid4()),
                "kind": "defended",
                "challenge": {"detail": "cita débil"},
                "resolution_note": "claim defendido",
                "evidence_check_ratio": 0.9,
            },
        ],
        "critique": {"missing_evidence": 4, "summary": "Critique: 4 sin evidencia"},
    }
    cognitive_repo = _FakeCognitiveRepo(plan)
    repo = _FakeCuratorRepo()
    curator = KnowledgeCurator(repo, cognitive_repo)

    suggestions = await curator.propose_from_run(uuid4(), cognitive_repo.run_id)

    kinds = {suggestion.kind for suggestion in suggestions}
    assert SuggestionKind.CONCEPT_REVIEW in kinds
    assert SuggestionKind.FACT_CANDIDATE in kinds
    assert all(s.status is SuggestionStatus.PROPOSED for s in suggestions)
    assert all(s.provenance is CatalogProvenance.INFERRED for s in suggestions)
    assert all(s.run_id == cognitive_repo.run_id for s in suggestions)
    assert any(claim_id in s.claim_ids for s in suggestions)


@pytest.mark.asyncio
async def test_curator_repo_roundtrip_decision_and_isolation() -> None:
    from src.infrastructure.postgres.curator import PostgresCuratorRepository
    from src.infrastructure.postgres.relational_db import (
        PostgresOrganizationRepository,
    )

    org = await PostgresOrganizationRepository().create_organization(
        uuid4(), f"Curator Org {uuid4().hex[:6]}"
    )
    repo = PostgresCuratorRepository()
    suggestion = KnowledgeSuggestion(
        organization_id=org.id,
        kind=SuggestionKind.BUSINESS_RULE,
        title="Regla candidata: venta cancelada no cuenta",
        reasoning="observación de run",
        confidence=0.5,
    )
    saved = await repo.propose(suggestion)
    assert saved.id == suggestion.id

    fetched = await repo.get(org.id, suggestion.id)
    assert fetched is not None and fetched.status is SuggestionStatus.PROPOSED
    assert await repo.get(uuid4(), suggestion.id) is None

    listed = await repo.list(org.id, status=SuggestionStatus.PROPOSED)
    assert [s.id for s in listed] == [suggestion.id]
    assert await repo.list(uuid4()) == []

    with pytest.raises(ValueError):
        await repo.decide(
            org.id,
            suggestion.id,
            status=SuggestionStatus.PROPOSED,
            decided_by=uuid4(),
        )

    decider = uuid4()
    decided = await repo.decide(
        org.id,
        suggestion.id,
        status=SuggestionStatus.APPROVED,
        decided_by=decider,
        reason="revisado",
    )
    assert decided is not None
    assert decided.status is SuggestionStatus.APPROVED
    assert decided.decided_by == decider
    assert decided.decided_at is not None
    assert await repo.decide(
        uuid4(), suggestion.id, status=SuggestionStatus.REJECTED, decided_by=decider
    ) is None


async def test_curator_api_flow(async_client, monkeypatch) -> None:
    from src.core.config import get_settings

    monkeypatch.setenv("RAG_COGNITIVE_OS_ENABLED", "limited")
    get_settings.cache_clear()
    try:
        resp = await async_client.post(
            "/api/v1/billing/subscription/create-trial",
            json={
                "company_name": "Curator API Co",
                "email": f"cur-{uuid4().hex[:8]}@example.com",
            },
        )
        assert resp.status_code == 200, resp.text
        auth = resp.json()
        headers = {
            "Authorization": f"Bearer {auth['api_token']}",
            "X-Organization-Id": auth["organization_id"],
        }
        created = await async_client.post(
            "/api/v1/cognitive/runs",
            headers=headers,
            json={"query": "¿Dónde está la política de vacaciones?"},
        )
        assert created.status_code == 201, created.text
        run_id = created.json()["run"]["id"]

        curated = await async_client.post(
            f"/api/v1/cognitive/runs/{run_id}/curate", headers=headers
        )
        assert curated.status_code == 200, curated.text
        assert curated.json()["suggestions"] == []

        listed = await async_client.get(
            "/api/v1/cognitive/suggestions", headers=headers
        )
        assert listed.status_code == 200
        assert listed.json()["suggestions"] == []

        missing = await async_client.post(
            f"/api/v1/cognitive/suggestions/{uuid4()}/decide",
            headers=headers,
            json={"decision": "approve", "reason": "x"},
        )
        assert missing.status_code == 404
    finally:
        get_settings.cache_clear()
