# =============================================================================
# Cognitive Workflows — D5: entidades con identidad canónica existente.
#
# La ref intenta resolverse contra CanonicalKnowledgeRepository (kind=ENTITY);
# si no existe queda label-only, nunca se inventan IDs.
# =============================================================================
from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from src.platform.workflows.entities import resolve_entity_ref
from tests.test_workflows import _create_org, _headers, _owner_session


class _FakeCanonicalRepo:
    def __init__(self, canonical_id: UUID, *, match: str = "acme sac") -> None:
        self.canonical_id = canonical_id
        self.match = match
        self.calls: list[tuple] = []

    async def get_by_natural_key(self, organization_id, kind, natural_key):  # noqa: ANN001
        self.calls.append((organization_id, kind, natural_key))
        if self.match in str(natural_key):
            return SimpleNamespace(canonical_id=self.canonical_id)
        return None


@pytest.mark.asyncio
async def test_resolve_entity_ref_canonical_and_label_only(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.platform.workflows import entities as entities_mod

    canonical_id = uuid4()
    repo = _FakeCanonicalRepo(canonical_id)
    monkeypatch.setattr(entities_mod, "_canonical_repo", lambda: repo)

    found = await resolve_entity_ref(uuid4(), kind="customer", label="ACME SAC")
    assert found is not None
    assert found["resolution"] == "canonical"
    assert found["canonical_id"] == str(canonical_id)
    assert found["kind"] == "customer"
    assert repo.calls and "entity:customer:acme sac" in repo.calls[0][2]

    missing = await resolve_entity_ref(uuid4(), kind="customer", label="Otro Cliente")
    assert missing is not None
    assert missing["resolution"] == "label_only"
    assert "canonical_id" not in missing

    assert await resolve_entity_ref(uuid4(), kind="customer", label="   ") is None


@pytest.mark.asyncio
async def test_resolve_entity_ref_fail_soft(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.platform.workflows import entities as entities_mod

    class _Boom:
        async def get_by_natural_key(self, organization_id, kind, natural_key):  # noqa: ANN001
            raise RuntimeError("canonical down")

    monkeypatch.setattr(entities_mod, "_canonical_repo", lambda: _Boom())
    ref = await resolve_entity_ref(uuid4(), kind="supplier", label="Proveedor X")
    assert ref is not None
    assert ref["resolution"] == "label_only"


def _node(nid: str, ntype: str, config: dict | None = None, **extra) -> dict:
    node: dict = {
        "id": nid,
        "type": ntype,
        "label": ntype,
        "config": config or {},
        "input_ports": [{"name": "in", "type": "json"}],
        "output_ports": [{"name": "out", "type": "json"}],
        "retry_policy": {"max_attempts": 1},
        "timeout_ms": 60_000,
        "error_policy": "fail",
    }
    node.update(extra)
    return node


def _edge(eid: str, frm: str, to: str, **extra) -> dict:
    edge: dict = {"id": eid, "from_node": frm, "from_port": "out", "to_node": to, "to_port": "in"}
    edge.update(extra)
    return edge


def _graph(nodes: list[dict], edges: list[dict], entrypoints: list[str]) -> dict:
    return {
        "workflow_version": 2,
        "nodes": nodes,
        "edges": edges,
        "variables": {},
        "entrypoints": entrypoints,
        "metadata": {},
    }


@pytest.mark.asyncio
async def test_business_result_contributes_entity_refs(
    async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    org = await _create_org(async_client, "D5 Entities")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    headers = _headers(org)

    canonical_id = uuid4()
    repo = _FakeCanonicalRepo(canonical_id)

    from src.api.deps import get_canonical_repo
    from src.api.main import app

    app.dependency_overrides[get_canonical_repo] = lambda: repo

    graph = _graph(
        [
            _node("t", "trigger_webhook"),
            _node(
                "br",
                "business_result",
                {
                    "title": "Alta de cliente",
                    "entities": [
                        "ACME SAC",
                        {"kind": "policy", "label": "Política de descuentos"},
                    ],
                },
            ),
        ],
        [_edge("e1", "t", "br")],
        ["t"],
    )
    created = await async_client.post(
        "/api/v1/workflows",
        headers={**headers, "Idempotency-Key": f"d5-{uuid4().hex}"},
        json={"name": "D5 Entities", "trigger_type": "webhook", "graph": graph},
    )
    assert created.status_code == 200, created.text
    run = await async_client.post(
        f"/api/v1/workflows/{created.json()['workflow_id']}/run",
        headers={**headers, "Idempotency-Key": f"d5r-{uuid4().hex}"},
        json={"payload": {"message": "alta"}},
    )
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["status"] == "succeeded", body

    output = body["result"]["structured_output"]["nodes"]["br"]["output"]
    by_label = {ref["label"]: ref for ref in output["entities"]}
    assert by_label["ACME SAC"]["resolution"] == "canonical"
    assert by_label["ACME SAC"]["canonical_id"] == str(canonical_id)
    assert by_label["Política de descuentos"]["resolution"] == "label_only"

    context_refs = {
        entry["value"]["label"]: entry["value"]
        for entry in body["result"]["context"]["entity_refs"]
    }
    assert context_refs["ACME SAC"]["canonical_id"] == str(canonical_id)
    assert context_refs["Política de descuentos"]["resolution"] == "label_only"
    assert "security" not in body["result"]["context"]
