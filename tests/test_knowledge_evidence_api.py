from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from src.core.domain.evidence import EvidenceRecord


def _record(*, org_id=None, workspace_id=None) -> EvidenceRecord:
    return EvidenceRecord(
        organization_id=org_id or uuid4(),
        workspace_id=workspace_id,
        source_id=uuid4(),
        document_id=uuid4(),
        page=7,
        section_path=("cláusula", "riesgo"),
        excerpt="La cláusula exige aviso previo de treinta días.",
        content_hash="abc123",
        authority="document",
    )


async def _call(monkeypatch, record, *, workspace_id=None):
    import src.api.deps as deps
    import src.api.routes.knowledge_model as route

    org_id = record.organization_id if record else uuid4()
    ctx = SimpleNamespace(organization_id=org_id)

    class Repo:
        async def get(self, organization_id, evidence_id):  # noqa: ANN001
            assert organization_id == org_id
            return record

    async def fake_workspace(_request):
        return SimpleNamespace(id=workspace_id or uuid4())

    monkeypatch.setattr(route, "require_permission", lambda *a, **k: ctx)
    monkeypatch.setattr(deps, "get_evidence_ledger_repo", lambda: Repo())
    monkeypatch.setattr(
        "src.platform.workspaces.context.resolve_workspace", fake_workspace
    )
    return await route.get_evidence(uuid4(), SimpleNamespace())


@pytest.mark.asyncio
async def test_evidence_resolves_locator_for_same_workspace(monkeypatch) -> None:
    ws_id = uuid4()
    record = _record(workspace_id=ws_id)
    payload = await _call(monkeypatch, record, workspace_id=ws_id)
    assert payload["schema"] == "zent.evidence/v1"
    assert payload["page"] == 7
    assert payload["section_path"] == ["cláusula", "riesgo"]
    assert payload["source_id"] == str(record.source_id)
    assert payload["document_id"] == str(record.document_id)
    assert "treinta días" in payload["excerpt"]


@pytest.mark.asyncio
async def test_evidence_is_org_scoped(monkeypatch) -> None:
    with pytest.raises(HTTPException) as exc:
        await _call(monkeypatch, None)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_evidence_is_workspace_scoped(monkeypatch) -> None:
    record = _record(workspace_id=uuid4())
    with pytest.raises(HTTPException) as exc:
        await _call(monkeypatch, record, workspace_id=uuid4())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_evidence_without_workspace_is_org_scoped(monkeypatch) -> None:
    payload = await _call(monkeypatch, _record(workspace_id=None))
    assert payload["workspace_id"] is None
    assert payload["page"] == 7
