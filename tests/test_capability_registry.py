# =============================================================================
# Intelligent Capability Registry (Prompt 02).
#
# Cubre los 10 casos obligatorios: instalada/habilitada, no instalada, sin
# credenciales, sin permiso, dos proveedores, cambio de versión, composición
# incompatible, aislamiento multi-tenant, capacidad nueva sin tocar el prompt
# y catálogo grande con top-k.
# =============================================================================
from __future__ import annotations

import json
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from src.infrastructure.postgres.session import get_async_session
from src.platform.marketplace.runtime import install_integration
from src.platform.workflows.capability_registry import (
    CapabilityAvailability,
    CapabilityDescriptor,
    build_capability_snapshot,
    reset_registry_cache,
    search_descriptors,
)
from src.platform.workflows.capability_services import (
    compose_capabilities,
    schema_links,
)
from tests.test_workflows import _create_org, _headers, _owner_session

_PERMS = frozenset(
    {
        "workflows:read",
        "workflows:create",
        "external_actions:execute",
        "agents:execute",
        "knowledge:read",
    }
)


def _descriptor(
    ref: str,
    display: str,
    *,
    source: str = "commerce",
    executable: bool = True,
    aliases: list[str] | None = None,
    input_schema: dict | None = None,
    output_schema: dict | None = None,
) -> CapabilityDescriptor:
    return CapabilityDescriptor(
        capability_ref=ref,
        display_name=display,
        description=f"{display} para el negocio.",
        owner_module="tests",
        category="test",
        aliases=aliases or [],
        input_schema=input_schema or {"type": "object", "properties": {}},
        output_schema=output_schema or {"type": "object", "properties": {}},
        required_inputs=[],
        side_effects=["read"],
        risk_level="info",
        required_permissions=[],
        availability=CapabilityAvailability(
            status="AVAILABLE" if executable else "NEEDS_CONFIGURATION",
            published=True,
            installed=True,
            configured=executable,
            permitted=True,
            executable=executable,
        ),
        source=source,  # type: ignore[arg-type]
    )


async def _workspace(org: dict):
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT id FROM workspaces WHERE organization_id = :oid "
                    "ORDER BY created_at LIMIT 1"
                ),
                {"oid": org["organization_id"]},
            )
        ).fetchone()
        return row.id if row else None
    finally:
        await session.close()


async def _snapshot(org: dict, *, permissions: frozenset[str] = _PERMS):
    reset_registry_cache()
    workspace_id = await _workspace(org)
    return await build_capability_snapshot(
        UUID(str(org["organization_id"])),
        workspace_id,
        permissions=permissions,
        force_refresh=True,
    )


async def _install(org: dict, slug: str) -> str:
    workspace_id = await _workspace(org)
    result = await install_integration(
        UUID(str(org["organization_id"])), slug, workspace_id=workspace_id
    )
    return str(result["install_id"])


async def _bump_action(action_id: str, *, delta: int = 1) -> None:
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "UPDATE integration_actions SET version = version + :d "
                "WHERE action_id = :aid"
            ),
            {"d": delta, "aid": action_id},
        )
        await session.commit()
    finally:
        await session.close()


async def _insert_action(action_id: str, display_name: str) -> None:
    session = await get_async_session()
    try:
        manifest = (
            await session.execute(
                text("SELECT id FROM integration_manifests WHERE slug = 'demo-echo' LIMIT 1")
            )
        ).fetchone()
        assert manifest is not None
        await session.execute(
            text(
                "INSERT INTO integration_actions "
                "(integration_id, capability_slug, action_id, display_name, description, "
                "input_schema, output_schema, risk_level, read_only, requires_approval, "
                "contains_personal_data, timeout_ms, idempotency_support, cost_model, "
                "provider_config, version, status) "
                "VALUES (:iid, 'echo', :aid, :name, :desc, "
                "CAST(:inp AS jsonb), CAST(:out AS jsonb), 'info', true, false, false, "
                "2000, false, '{\"model\": \"FREE\"}'::jsonb, "
                "'{\"kind\": \"demo_echo\"}'::jsonb, 1, 'ACTIVE')"
            ),
            {
                "iid": manifest.id,
                "aid": action_id,
                "name": display_name,
                "desc": f"{display_name} (acción de prueba).",
                "inp": json.dumps({"type": "object", "required": ["text"], "properties": {"text": {"type": "string"}}}),
                "out": json.dumps({"type": "object", "properties": {"echo": {"type": "string"}}}),
            },
        )
        await session.commit()
    finally:
        await session.close()


async def _delete_action(action_id: str) -> None:
    session = await get_async_session()
    try:
        await session.execute(
            text("DELETE FROM integration_actions WHERE action_id = :aid"),
            {"aid": action_id},
        )
        await session.commit()
    finally:
        await session.close()


# ---------------------------------------------------------------------------
# Casos 1-4: estados de disponibilidad
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_installed_and_enabled_capability_is_available(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Cap Installed")
    await _install(org, "demo-echo")
    snapshot = await _snapshot(org)
    descriptor = snapshot.index()["demo.echo"]
    assert descriptor.availability.installed is True
    assert descriptor.availability.enabled is True
    assert descriptor.availability.status == "AVAILABLE"
    assert descriptor.availability.executable is True
    assert descriptor.required_permissions == ["external_actions:execute"]
    assert "text" in descriptor.required_inputs


@pytest.mark.asyncio
async def test_existing_but_not_installed_is_an_option(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Cap Not Installed")
    snapshot = await _snapshot(org)
    descriptor = snapshot.index()["demo.echo"]
    assert descriptor.availability.installed is False
    assert descriptor.availability.status == "NEEDS_INSTALLATION"
    assert descriptor.availability.executable is False
    assert any("instala" in reason for reason in descriptor.availability.reasons)


@pytest.mark.asyncio
async def test_installed_without_credentials_needs_credentials(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Cap Credentials")
    await _install(org, "sunat")
    snapshot = await _snapshot(org)
    descriptor = snapshot.index()["peru.taxpayer.lookup"]
    assert descriptor.availability.installed is True
    assert descriptor.availability.status == "NEEDS_CREDENTIALS"
    assert descriptor.availability.executable is False


@pytest.mark.asyncio
async def test_user_without_permission_cannot_execute(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Cap Permission")
    await _install(org, "demo-echo")
    snapshot = await _snapshot(org, permissions=frozenset({"workflows:read"}))
    descriptor = snapshot.index()["demo.echo"]
    assert descriptor.availability.installed is True
    assert descriptor.availability.status == "PERMISSION_DENIED"
    assert descriptor.availability.executable is False
    assert any("permiso" in reason.lower() for reason in descriptor.availability.reasons)


# ---------------------------------------------------------------------------
# Casos 5-6: proveedores equivalentes y versión de contrato
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_two_providers_expose_alternatives(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Cap Alternatives")
    await _install(org, "demo-echo")
    alt_action = f"demo.echo.alt.{uuid4().hex[:8]}"
    await _insert_action(alt_action, "Echo alternativo")
    try:
        snapshot = await _snapshot(org)
        first = snapshot.index()["demo.echo"]
        second = snapshot.index()[alt_action]
        assert alt_action in first.metadata["provider_alternatives"]
        assert "demo.echo" in second.metadata["provider_alternatives"]
    finally:
        await _delete_action(alt_action)


@pytest.mark.asyncio
async def test_contract_version_change_changes_hashes(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Cap Version")
    await _install(org, "demo-echo")
    before = await _snapshot(org)
    before_item = before.index()["demo.echo"]
    await _bump_action("demo.echo")
    try:
        after = await _snapshot(org)
        after_item = after.index()["demo.echo"]
        assert after_item.version == before_item.version + 1
        assert after_item.contract_hash != before_item.contract_hash
        assert after.snapshot_hash != before.snapshot_hash
    finally:
        await _bump_action("demo.echo", delta=-1)


# ---------------------------------------------------------------------------
# Caso 7: composición por contratos
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_composition_is_derived_from_schemas(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Cap Compose")
    snapshot = await _snapshot(org)
    good = compose_capabilities(snapshot, "catalog.products.search", "sales.order.create")
    assert good is not None
    assert good["links"], good
    assert any(link["type"] == "array" for link in good["links"])
    bad = compose_capabilities(snapshot, "payments.checkout.create", "sales.order.create")
    assert bad is not None
    assert not any(link["input_field"] == "items" for link in bad["links"])
    mismatch = schema_links(
        {"type": "object", "properties": {"id": {"type": "string"}}},
        {"type": "object", "required": ["items"], "properties": {"items": {"type": "array"}}},
    )
    assert mismatch["links"] == []
    assert mismatch["unmatched_required"] == ["items"]


# ---------------------------------------------------------------------------
# Caso 8: aislamiento multi-tenant
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tenant_isolation_does_not_leak_installs_or_agents(
    async_client: AsyncClient,
) -> None:
    org_a = await _create_org(async_client, "Cap Tenant A")
    org_a["session"] = await _owner_session(async_client, org_a["organization_id"])
    org_b = await _create_org(async_client, "Cap Tenant B")
    org_b["session"] = await _owner_session(async_client, org_b["organization_id"])
    await _install(org_a, "demo-echo")
    agent = await async_client.post(
        "/api/v1/agents",
        headers=_headers(org_a),
        json={
            "name": f"Agente Privado {uuid4().hex[:6]}",
            "system_prompt": "secreto-interno-no-exponer",
            "tools": [],
        },
    )
    assert agent.status_code == 201, agent.text
    agent_id = agent.json()["id"]

    snapshot_a = await _snapshot(org_a)
    snapshot_b = await _snapshot(org_b)
    assert snapshot_a.index()["demo.echo"].availability.installed is True
    assert snapshot_b.index()["demo.echo"].availability.installed is False
    assert f"agent.{agent_id}" in snapshot_a.index()
    assert f"agent.{agent_id}" not in snapshot_b.index()

    # La API de B no puede inspeccionar el agente de A.
    response = await async_client.get(
        f"/api/v1/capabilities/agent.{agent_id}", headers=_headers(org_b)
    )
    assert response.status_code == 404
    # El contrato del agente no filtra el system_prompt.
    descriptor = snapshot_a.index()[f"agent.{agent_id}"]
    assert "secreto-interno-no-exponer" not in json.dumps(descriptor.model_dump(mode="json"))


# ---------------------------------------------------------------------------
# Caso 9: capacidad nueva sin editar prompt/código
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_new_capability_is_discovered_without_code_changes(
    async_client: AsyncClient,
) -> None:
    org = await _create_org(async_client, "Cap Dynamic")
    await _install(org, "demo-echo")
    action_id = f"demo.echo.patente.{uuid4().hex[:8]}"
    await _insert_action(action_id, "Verificación de patente municipal")
    try:
        snapshot = await _snapshot(org)
        scored, _ = search_descriptors(
            snapshot.capabilities, "verificar patente municipal", limit=5
        )
        refs = [item.capability_ref for item, _ in scored]
        assert action_id in refs
        assert refs[0] == action_id
    finally:
        await _delete_action(action_id)


# ---------------------------------------------------------------------------
# Caso 10: catálogo grande, top-k sin truncar arbitrariamente
# ---------------------------------------------------------------------------
def test_large_catalog_returns_top_k_and_total() -> None:
    descriptors = [
        _descriptor(
            f"synthetic.cap.{index:03d}",
            f"Capacidad sintética {index}",
            source="node",
            aliases=["catálogo", "productos"] if index == 87 else [],
        )
        for index in range(150)
    ]
    descriptors[87] = _descriptor(
        "catalog.products.search",
        "Buscar productos del catálogo",
        aliases=["productos", "catalogo", "product"],
        input_schema={"type": "object", "required": ["query"], "properties": {"query": {"type": "string"}}},
        output_schema={"type": "object", "properties": {"products": {"type": "array"}}},
    )
    scored, total = search_descriptors(descriptors, "", limit=5)
    assert total == 150
    assert len(scored) == 5
    scored, total = search_descriptors(descriptors, "buscar productos en el catálogo", limit=5)
    assert total >= 1
    assert scored[0][0].capability_ref == "catalog.products.search"
    assert len(scored) <= 5


# ---------------------------------------------------------------------------
# Digest del planner: contratos, no solo nombres
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_capability_digest_includes_contracts_and_kb_names(
    async_client: AsyncClient,
) -> None:
    from src.platform.workflows.architect_discovery import (
        capability_digest,
        discover_capabilities,
    )

    org = await _create_org(async_client, "Cap Digest")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    kb = await async_client.post(
        "/api/v1/knowledge-bases",
        json={"name": f"Políticas Comerciales {uuid4().hex[:5]}"},
        headers=_headers(org),
    )
    assert kb.status_code == 201, kb.text
    await _install(org, "demo-echo")
    reset_registry_cache()
    session = await get_async_session()
    try:
        kb_row = (
            await session.execute(
                text(
                    "SELECT workspace_id FROM knowledge_bases "
                    "WHERE organization_id = :oid AND name LIKE 'Políticas Comerciales%' "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"oid": org["organization_id"]},
            )
        ).fetchone()
    finally:
        await session.close()
    kb_workspace = kb_row.workspace_id if kb_row else None
    caps = await discover_capabilities(
        UUID(str(org["organization_id"])),
        workspace_id=kb_workspace,
        permissions=_PERMS,
    )
    digest = capability_digest(caps, query="buscar productos y avisar", max_items=10)
    assert "catalog.products.search" in digest
    assert "inputs:" in digest and "outputs:" in digest
    assert "estado=" in digest and "ejecutable=" in digest
    assert "Políticas Comerciales" in digest
    assert "for_each" not in digest.split("Primitivas de workflow")[1].split("\n")[0]


# ---------------------------------------------------------------------------
# API de inspección
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_capability_api_search_inspect_and_metrics(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Cap API")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    await _install(org, "demo-echo")
    reset_registry_cache()

    search = await async_client.get(
        "/api/v1/capabilities?q=buscar%20productos&limit=5", headers=_headers(org)
    )
    assert search.status_code == 200, search.text
    body = search.json()
    assert body["snapshot_hash"]
    assert body["returned"] <= 5
    refs = [item["capability_ref"] for item in body["results"]]
    assert "catalog.products.search" in refs
    assert body["coverage"]["business_capabilities"] > 0

    inspect = await async_client.get(
        "/api/v1/capabilities/catalog.products.search", headers=_headers(org)
    )
    assert inspect.status_code == 200, inspect.text
    capability = inspect.json()["capability"]
    assert capability["input_schema"]["required"] == ["query"]
    assert "products" in capability["output_schema"]["properties"]
    assert capability["contract_hash"]

    deps = await async_client.get(
        "/api/v1/capabilities/catalog.products.search/dependencies", headers=_headers(org)
    )
    assert deps.status_code == 200, deps.text
    assert deps.json()["dependencies"]

    availability = await async_client.get(
        "/api/v1/capabilities/demo.echo/availability", headers=_headers(org)
    )
    assert availability.json()["availability"]["status"] == "AVAILABLE"

    binding = await async_client.get(
        "/api/v1/capabilities/catalog.products.search/binding", headers=_headers(org)
    )
    assert binding.status_code == 200
    assert binding.json()["found"] is False

    compose = await async_client.get(
        "/api/v1/capabilities/catalog.products.search/compose?to=sales.order.create",
        headers=_headers(org),
    )
    assert compose.status_code == 200
    assert compose.json()["links"]

    metrics = await async_client.get("/api/v1/capabilities/metrics", headers=_headers(org))
    assert metrics.status_code == 200
    coverage = metrics.json()["coverage"]
    assert coverage["total_capabilities"] >= 60
    assert 0 <= coverage["business_completeness"] <= 1
    assert isinstance(coverage["contract_gaps"], list)

    events = await async_client.get("/api/v1/capabilities/events?q=pago", headers=_headers(org))
    assert events.status_code == 200
    assert events.json()["returned"] >= 1
    event = await async_client.get(
        "/api/v1/capabilities/events/sales.closed", headers=_headers(org)
    )
    assert event.status_code == 200
    assert event.json()["event"]["fields"]

    resources = await async_client.get("/api/v1/capabilities/resources", headers=_headers(org))
    assert resources.status_code == 200

    templates = await async_client.get(
        "/api/v1/capabilities/templates?q=ventas", headers=_headers(org)
    )
    assert templates.status_code == 200

    unknown = await async_client.get(
        "/api/v1/capabilities/no.existe", headers=_headers(org)
    )
    assert unknown.status_code == 404
