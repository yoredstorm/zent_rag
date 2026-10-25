from __future__ import annotations

import pytest
from httpx import AsyncClient

from src.platform.workflows.verification import (
    VerificationError,
    VerificationProbe,
    clear_adapters,
    register_adapter,
)
from tests.test_workflow_graph import _edge, _graph, _node
from tests.test_workflows import _create_org, _headers, _owner_session


class _FakeAdapter:
    kind = "rest_api"

    def __init__(
        self,
        *,
        real: bool = False,
        ready: bool = True,
        sandbox: bool = True,
        provider: bool = False,
        fail_verify: bool = False,
    ) -> None:
        self.real = real
        self.ready = ready
        self.sandbox = sandbox
        self.provider = provider
        self.fail_verify = fail_verify

    async def probe(self, binding):
        return VerificationProbe(
            ready=self.ready,
            sandbox=self.sandbox,
            provider=self.provider,
            real=self.real,
            environment="test-harness" if self.real else "unavailable",
            provider_ref="fake-provider" if self.real else "",
            reason="" if self.ready else "adapter_unavailable",
        )

    async def verify(self, level, binding, scenarios):
        if self.fail_verify:
            raise VerificationError("provider_http_500", "proveedor devolvió 500")
        return VerificationProbe(
            ready=self.ready,
            sandbox=self.sandbox,
            provider=self.provider,
            real=self.real,
            environment="test-harness" if self.real else "unavailable",
            provider_ref="fake-provider" if self.real else "",
            reason="" if self.ready else "adapter_unavailable",
            evidence={"scenarios": len(scenarios)},
        )


async def _org(client: AsyncClient, name: str) -> dict:
    org = await _create_org(client, name)
    org["session"] = await _owner_session(client, org["organization_id"])
    return org


async def _workflow_with_binding(client: AsyncClient, org: dict, *, metadata: dict | None = None) -> str:
    binding = await client.put(
        "/api/v1/workflows/capability-bindings/erp.order.create",
        headers=_headers(org),
        json={
            "provider_kind": "rest_api",
            "config": {"url": "https://erp.example.com/orders", "method": "POST"},
        },
    )
    assert binding.status_code == 200, binding.text
    graph = _graph(
        nodes=[
            _node("t", "trigger_webhook"),
            _node(
                "erp",
                "capability_call",
                {"capability": "erp.order.create", "inputs": {"id": "1"}},
            ),
            _node("end", "end"),
        ],
        edges=[_edge("e1", "t", "erp"), _edge("e2", "erp", "end")],
        entrypoints=["t"],
    )
    if metadata is not None:
        graph["metadata"] = metadata
    created = await client.post(
        "/api/v1/workflows",
        headers=_headers(org),
        json={
            "name": "P05 verification",
            "trigger_type": "webhook",
            "graph": graph,
            "workflow_version": 2,
        },
    )
    assert created.status_code == 200, created.text
    return created.json()["workflow_id"]


@pytest.fixture(autouse=True)
def _reset_adapters():
    clear_adapters()
    yield
    clear_adapters()


@pytest.mark.asyncio
async def test_sandbox_request_without_adapter_is_capped(
    async_client: AsyncClient,
) -> None:
    org = await _org(async_client, "P05 No Adapter")
    workflow_id = await _workflow_with_binding(async_client, org)

    test = await async_client.post(
        f"/api/v1/workflows/{workflow_id}/test",
        headers=_headers(org),
        json={"requested_level": "sandbox", "scenario": {"message": "hola"}},
    )
    assert test.status_code == 200, test.text
    body = test.json()
    assert body["effective_level"] == "simulation"
    assert body["capped_reason"] == "sandbox_adapter_unavailable"
    assert body["provider_verified"] is False
    assert body["readiness"]["sandbox_ready"] is False

    certified = await async_client.post(
        f"/api/v1/workflows/{workflow_id}/certifications",
        headers=_headers(org),
        json={"level": "sandbox"},
    )
    assert certified.status_code == 409, certified.text
    assert "sandbox_not_verified" in certified.text


@pytest.mark.asyncio
async def test_metadata_sandbox_ready_does_not_certify(
    async_client: AsyncClient,
) -> None:
    org = await _org(async_client, "P05 Metadata Fake")
    workflow_id = await _workflow_with_binding(
        async_client, org, metadata={"sandbox_ready": True, "provider_ready": True}
    )
    certified = await async_client.post(
        f"/api/v1/workflows/{workflow_id}/certifications",
        headers=_headers(org),
        json={"level": "sandbox"},
    )
    assert certified.status_code == 409, certified.text
    assert "sandbox_not_verified" in certified.text


@pytest.mark.asyncio
async def test_fake_adapter_cannot_authorize_sandbox_or_provider(
    async_client: AsyncClient,
) -> None:
    org = await _org(async_client, "P05 Fake Adapter")
    workflow_id = await _workflow_with_binding(async_client, org)
    register_adapter(
        _FakeAdapter(real=False, ready=True, sandbox=True, provider=True)
    )

    for level in ("sandbox", "provider"):
        certified = await async_client.post(
            f"/api/v1/workflows/{workflow_id}/certifications",
            headers=_headers(org),
            json={"level": level},
        )
        assert certified.status_code == 409, certified.text
        assert "not_verified" in certified.text


@pytest.mark.asyncio
async def test_provider_request_without_adapter_is_unverified(
    async_client: AsyncClient,
) -> None:
    org = await _org(async_client, "P05 Provider Missing")
    workflow_id = await _workflow_with_binding(async_client, org)
    test = await async_client.post(
        f"/api/v1/workflows/{workflow_id}/test",
        headers=_headers(org),
        json={"requested_level": "provider", "scenario": {"message": "hola"}},
    )
    assert test.status_code == 200, test.text
    body = test.json()
    assert body["effective_level"] == "simulation"
    assert body["result"] == "UNVERIFIED"
    assert body["provider_verified"] is False


@pytest.mark.asyncio
async def test_adapter_failure_does_not_issue_certificate(
    async_client: AsyncClient,
) -> None:
    org = await _org(async_client, "P05 Adapter Failure")
    workflow_id = await _workflow_with_binding(async_client, org)
    register_adapter(
        _FakeAdapter(real=True, ready=True, sandbox=True, fail_verify=True)
    )
    certified = await async_client.post(
        f"/api/v1/workflows/{workflow_id}/certifications",
        headers=_headers(org),
        json={"level": "sandbox"},
    )
    assert certified.status_code == 409, certified.text
    assert "provider_http_500" in certified.text


@pytest.mark.asyncio
async def test_certificate_is_not_visible_from_other_workspace(
    async_client: AsyncClient,
) -> None:
    org = await _org(async_client, "P05 Workspace Cert")
    workflow_id = await _workflow_with_binding(async_client, org)
    workspace = await async_client.post(
        "/api/v1/workspaces", headers=_headers(org), json={"name": "P05 B"}
    )
    assert workspace.status_code == 201, workspace.text
    headers_b = {**_headers(org), "X-Workspace-Id": workspace.json()["id"]}
    response = await async_client.get(
        f"/api/v1/workflows/{workflow_id}/certifications", headers=headers_b
    )
    assert response.status_code == 404, response.text
