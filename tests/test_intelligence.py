# =============================================================================
# Phase 32C — Business Results, copilot, packs e intelligence
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from tests.test_workflows import _create_org, _headers, _owner_session


# ---------------------------------------------------------------------------
# BusinessResult API
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_business_result_lifecycle(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Intel Results")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    created = await async_client.post(
        "/api/v1/intelligence/results",
        headers={**_headers(org), "Idempotency-Key": f"int-{uuid4().hex}"},
        json={
            "title": "Brief diario de ventas",
            "summary": "Las ventas aumentaron 12.8%",
            "section": "reports",
            "importance": "HIGH",
            "metrics": {"sales": 84210, "pct_change": 12.8, "tickets": 248},
            "insights": ["El ticket promedio subió 3%"],
            "entities": [{"entity_type": "company", "entity_id": "demo"}],
            "evidence": [{"provider": "ERP", "action_id": "analytics"}],
        },
    )
    # Los resultados se escriben desde el runtime de workflow (nodo
    # business_result); el POST directo no es parte de la superficie pública.
    assert created.status_code == 405

    from src.platform.intelligence.results import BusinessResult, save_result

    saved = await save_result(
        UUID(org["organization_id"]),
        BusinessResult(
            title="Brief diario de ventas",
            summary="Las ventas aumentaron 12.8%",
            section="reports",
            importance="HIGH",
            metrics={"sales": 84210, "pct_change": 12.8, "tickets": 248},
            insights=["Ticket promedio subió 3%"],
            entities=[{"entity_type": "company", "entity_id": "demo"}],
        ),
    )
    assert saved["notified"] is True  # HIGH → notificación in-app

    inbox = await async_client.get("/api/v1/intelligence/results", headers=h)
    assert inbox.status_code == 200, inbox.text
    body = inbox.json()
    assert len(body["results"]) >= 1
    assert body["results"][0]["title"] == "Brief diario de ventas"
    assert body["results"][0]["importance"] == "HIGH"
    assert body["sections"].get("reports")

    by_entity = await async_client.get(
        "/api/v1/intelligence/results",
        headers=h,
        params={"entity_type": "company", "entity_id": "demo"},
    )
    assert any(r["title"] == "Brief diario de ventas" for r in by_entity.json()["results"])

    detail = await async_client.get(
        f"/api/v1/intelligence/results/{saved['result_id']}", headers=h
    )
    assert detail.json()["metrics"]["sales"] == 84210


# ---------------------------------------------------------------------------
# Workflow Copilot
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_workflow_copilot_daily_sales(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Intel Copilot")
    org["session"] = await _owner_session(async_client, org["organization_id"])

    r = await async_client.post(
        "/api/v1/intelligence/workflow/draft",
        headers={**_headers(org), "Idempotency-Key": f"int-c-{uuid4().hex}"},
        json={"prompt": "Todos los días a las 6pm dime cómo fueron las ventas y una comparación con ayer por correo"},
    )
    assert r.status_code == 200, r.text
    draft = r.json()
    assert draft["draft"] is True
    assert draft["must_review"] is True
    assert draft["name"] == "Brief ejecutivo de ventas diario"
    assert draft["trigger_type"] == "schedule"
    assert draft["trigger_config"]["daily"]["time"] == "18:00"
    assert draft["trigger_config"]["daily"]["timezone"] == "America/Lima"
    assert any(s["type"] == "query_business_data" for s in draft["steps"])
    assert any(s["type"] == "business_result" for s in draft["steps"])
    assert draft["questions"]  # preguntas necesarias

    r2 = await async_client.post(
        "/api/v1/intelligence/workflow/draft",
        headers={**_headers(org), "Idempotency-Key": f"int-c2-{uuid4().hex}"},
        json={"prompt": "Verifica los contribuyentes nuevos con RUC en SUNAT"},
    )
    assert r2.status_code == 200, r2.text
    draft2 = r2.json()
    assert "sunat" in (draft2["integration_hint"] or "")
    assert draft2["trigger_type"] == "event"

    def flat(steps: list) -> list:
        out: list = []
        for s in steps:
            out.append(s)
            out.extend(flat(s.get("then") or []))
            out.extend(flat(s.get("else") or []))
        return out

    assert any(s["type"] == "marketplace_action" for s in flat(draft2["steps"]))
    assert any(s["type"] == "llm" for s in flat(draft2["steps"]))


# ---------------------------------------------------------------------------
# Nodo business_result en workflow
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_workflow_business_result_node(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Intel WF Result")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    created = await async_client.post(
        "/api/v1/workflows",
        headers={**_headers(org), "Idempotency-Key": f"int-w-{uuid4().hex}"},
        json={
            "name": "Result Flow",
            "steps": [
                {"type": "llm", "config": {"prompt": "ventas en alza"}},
                {
                    "type": "business_result",
                    "config": {
                        "title": "Reporte X",
                        "section": "reports",
                        "importance": "INFO",
                        "summary": "{{steps.0.output.text}}",
                        "metrics": {"sales": 100},
                    },
                },
            ],
        },
    )
    assert created.status_code == 200, created.text
    wid = created.json()["workflow_id"]
    run = await async_client.post(
        f"/api/v1/workflows/{wid}/run",
        headers={**_headers(org), "Idempotency-Key": f"int-wr-{uuid4().hex}"},
        json={"payload": {}},
    )
    assert run.status_code == 200, run.text
    assert run.json()["status"] == "succeeded", run.json()

    inbox = await async_client.get(
        "/api/v1/intelligence/results", headers=h, params={"limit": 5}
    )
    titles = [r["title"] for r in inbox.json()["results"]]
    assert "Reporte X" in titles


# ---------------------------------------------------------------------------
# Packs de inteligencia (workflow + integración)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_business_pack_install(async_client: AsyncClient) -> None:
    from src.platform.marketplace.runtime import ensure_business_packs

    await ensure_business_packs()

    org = await _create_org(async_client, "Intel Packs")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    catalog = await async_client.get("/api/v1/integrations/catalog", headers=h)
    slugs = [c["slug"] for c in catalog.json()["catalog"]]
    assert "pack-daily-sales-brief" in slugs
    assert "pack-customer-verification" in slugs

    pack = await async_client.post(
        "/api/v1/integrations/installs",
        headers={**_headers(org), "Idempotency-Key": f"int-p-{uuid4().hex}"},
        json={"integration_slug": "pack-customer-verification"},
    )
    assert pack.status_code in (200, 201), pack.text
    body = pack.json()
    assert body.get("pack") is True
    assert "workflow_id" in body
    assert body["install_ids"].get("demo-echo")

    wf = await async_client.get(f"/api/v1/workflows/{body['workflow_id']}", headers=h)
    assert wf.status_code == 200
    graph = wf.json().get("graph") or {}
    nodes = graph.get("nodes") or []
    market_node = next((n for n in nodes if n["type"] == "marketplace_action"), None)
    assert market_node is not None
    placeholder_free = "{{_pack." not in str(graph)
    assert placeholder_free  # los install_id reales reemplazaron los placeholders

    # El workflow del pack usa demo-echo instalado → puede correr con el trigger manual.
    run = await async_client.post(
        f"/api/v1/workflows/{body['workflow_id']}/run",
        headers={**_headers(org), "Idempotency-Key": f"int-pr-{uuid4().hex}"},
        json={"payload": {"ruc": "20100047218", "name": "Acme"}},
    )
    assert run.status_code == 200, run.text
    assert run.json()["status"] == "succeeded", run.json()


# ---------------------------------------------------------------------------
# Loop guard en el dispatcher de eventos
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_event_loop_guard_depth(async_client: AsyncClient) -> None:
    from src.platform.workflows.events import dispatch_event_to_workflows

    org = await _create_org(async_client, "Intel Loop")
    org["session"] = await _owner_session(async_client, org["organization_id"])

    payload = {"organization_id": org["organization_id"], "kind": "cl"}
    deep = dict(payload, _wf_chain=["a", "b", "c", "d"])
    fired = await dispatch_event_to_workflows("invoice.detected", deep)
    assert fired == 0  # profundidad máxima alcanzada → no dispara
    short = dict(payload, _wf_chain=["a"])
    fired2 = await dispatch_event_to_workflows("nope.event", short)
    assert fired2 == 0  # sin triggers, también 0


# ---------------------------------------------------------------------------
# Automations stats + assist options
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_intelligence_stats_and_assist(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Intel Stats")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    stats = await async_client.get("/api/v1/intelligence/automations/stats", headers=h)
    assert stats.status_code == 200, stats.text
    body = stats.json()
    assert "active_automations" in body
    assert "runs_today" in body
    assert "external_calls_24h" in body

    options = await async_client.get("/api/v1/intelligence/assist/options", headers=h)
    assert options.status_code == 200, options.text
    assert "knowledge_bases" in options.json()
    assert "agents" in options.json()
    assert "integrations" in options.json()
