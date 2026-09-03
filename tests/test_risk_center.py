# =============================================================================
# AI Risk & Compliance Center v2 (PROMPT 47)
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient


async def _create_org(client: AsyncClient, name: str) -> dict:
    resp = await client.post(
        "/api/v1/billing/subscription/create-trial",
        json={
            "company_name": name,
            "email": f"rc-{uuid4().hex[:8]}@example.com",
            "country": "CL",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _owner_session(client: AsyncClient, organization_id: str) -> str:
    from src.infrastructure.postgres.relational_db import PostgresUserRepository
    from src.platform.auth.session import encrypt_session

    user = await PostgresUserRepository().get_by_external_id(
        UUID(organization_id), "default-admin"
    )
    assert user is not None
    return encrypt_session(user.id, UUID(organization_id))


def _headers(org: dict) -> dict:
    return {
        "Authorization": f"Bearer {org['session']}",
        "X-Organization-Id": org["organization_id"],
        "Idempotency-Key": f"rc-{uuid4().hex}",
    }


async def _platform_admin(client: AsyncClient, email: str) -> dict:
    import hashlib as hl

    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session
    from src.platform.auth.passwords import hash_password

    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO users (id, organization_id, external_id, email_hash, "
                "role, email, password_hash, is_platform_admin) "
                "VALUES (gen_random_uuid(), NULL, :ext, :eh, 'platform', :email, :ph, true)"
            ),
            {
                "ext": f"plat-{uuid4().hex[:12]}",
                "eh": hl.sha256(email.encode()).hexdigest(),
                "email": email,
                "ph": hash_password("secret-123"),
            },
        )
        await session.execute(
            text(
                "INSERT INTO user_platform_roles (user_id, role_id) "
                "SELECT u.id, pr.id FROM users u CROSS JOIN platform_roles pr "
                "WHERE lower(u.email) = lower(:email) AND pr.name = 'super_admin' "
                "ON CONFLICT DO NOTHING"
            ),
            {"email": email},
        )
        await session.commit()
    finally:
        await session.close()
    login = await client.post(
        "/api/v1/auth/platform/login", json={"email": email, "password": "secret-123"}
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.mark.asyncio
async def test_auto_assessment_from_real_data(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "RC Assess Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        # Eval con alucinación alta → riesgo hallucination.
        await session.execute(
            text(
                "INSERT INTO eval_v2_runs (id, organization_id, dataset_id, dataset_version, "
                "agent_id, agent_version_id, model, status, score_overall, hallucination_rate, "
                "passed_gate, completed_at) VALUES (gen_random_uuid(), :oid, gen_random_uuid(), 1, "
                "gen_random_uuid(), gen_random_uuid(), 'gpt-4o-mini', 'completed', 55, 0.6, false, NOW())"
            ),
            {"oid": UUID(org["organization_id"])},
        )
        # Incidente PII bloqueado.
        await session.execute(
            text(
                "INSERT INTO safety_incidents (id, organization_id, direction, rule_id, "
                "rule_name, score, snippet, action, status) "
                "VALUES (gen_random_uuid(), :oid, 'output', :rid, 'pii-detector', 92, "
                "'rut 12.345.678-9 detectado', 'block', 'open')"
            ),
            {"oid": UUID(org["organization_id"]), "rid": str(uuid4())},
        )
        # Errores API altos → security.
        for _ in range(8):
            await session.execute(
                text(
                    "INSERT INTO api_logs (id, organization_id, request_id, endpoint, "
                    "method, status, latency_ms) VALUES (gen_random_uuid(), :oid, :rid, "
                    "'/query', 'POST', 500, 200)"
                ),
                {"oid": UUID(org["organization_id"]), "rid": str(uuid4())},
            )
        await session.execute(
            text(
                "INSERT INTO api_logs (id, organization_id, request_id, endpoint, "
                "method, status, latency_ms) VALUES (gen_random_uuid(), :oid, :rid, "
                "'/query', 'POST', 200, 200)"
            ),
            {"oid": UUID(org["organization_id"]), "rid": str(uuid4())},
        )
        await session.commit()
    finally:
        await session.close()

    assess = await async_client.post("/api/v1/risk-center/assess", headers={**_headers(org)})
    assert assess.status_code == 200, assess.text
    created = [a["risk_type"] for a in assess.json()["assessments"] if a["created"]]
    assert "hallucination" in created
    assert "pii_leak" in created
    assert "security" in created  # 8 errores / 9 total > 5%

    # Re-assess → no duplica (existing_open).
    assess2 = await async_client.post("/api/v1/risk-center/assess", headers={**_headers(org)})
    created2 = [a["risk_type"] for a in assess2.json()["assessments"] if a["created"]]
    assert created2 == []

    register = await async_client.get("/api/v1/risk-center/register", headers=h)
    risks = register.json()["risks"]
    assert len(risks) == 4  # hallucination + pii_leak + security + safety (block_rate 11%)
    halluc = next(r for r in risks if r["risk_type"] == "hallucination")
    assert halluc["score"] >= 50  # 60% alucinación x impacto 90 / 100
    assert halluc["severity"] in ("high", "critical")
    assert halluc["source"] == "auto"
    assert "avg_hallucination_rate" in halluc["evidence"]


@pytest.mark.asyncio
async def test_manual_risk_mitigate_accept(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "RC Manual Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    created = await async_client.post(
        "/api/v1/risk-center/risks",
        headers={**_headers(org), "Idempotency-Key": f"rc-r-{uuid4().hex}"},
        json={"risk_type": "bias", "severity": "high", "notes": "datos desbalanceados"},
    )
    assert created.status_code == 200, created.text
    rid = created.json()["risk_id"]
    assert created.json()["source"] == "manual"

    # Tipo inválido → 400.
    bad = await async_client.post(
        "/api/v1/risk-center/risks",
        headers={**_headers(org), "Idempotency-Key": f"rc-b-{uuid4().hex}"},
        json={"risk_type": "nope", "severity": "high"},
    )
    assert bad.status_code == 400

    mitigated = await async_client.post(
        f"/api/v1/risk-center/risks/{rid}/mitigate",
        headers={**_headers(org), "Idempotency-Key": f"rc-m-{uuid4().hex}"},
        json={"description": "Se reentrenó el modelo con datos balanceados"},
    )
    assert mitigated.status_code == 200, mitigated.text
    assert mitigated.json()["status"] == "mitigated"

    mitigations = await async_client.get("/api/v1/risk-center/mitigations", headers=h)
    assert len(mitigations.json()["mitigations"]) == 1
    assert mitigations.json()["mitigations"][0]["risk_type"] == "bias"
    assert mitigations.json()["mitigations"][0]["action_type"] == "mitigation"

    # Aceptar otro riesgo.
    created2 = await async_client.post(
        "/api/v1/risk-center/risks",
        headers={**_headers(org), "Idempotency-Key": f"rc-r2-{uuid4().hex}"},
        json={"risk_type": "safety", "severity": "low"},
    )
    rid2 = created2.json()["risk_id"]
    accepted = await async_client.post(
        f"/api/v1/risk-center/risks/{rid2}/accept",
        headers={**_headers(org), "Idempotency-Key": f"rc-a-{uuid4().hex}"},
        json={"reason": "riesgo residual aceptado"},
    )
    assert accepted.json()["status"] == "accepted"

    # El heatmap solo muestra riesgos abiertos → ambos cerrados → vacío.
    heatmap = await async_client.get("/api/v1/risk-center/heatmap", headers=h)
    assert heatmap.json()["heatmap"] == []


@pytest.mark.asyncio
async def test_heatmap_by_agent(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "RC Heatmap Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    agent = (
        await async_client.post(
            "/api/v1/agents",
            headers={**_headers(org), "Idempotency-Key": f"rc-a-{uuid4().hex}"},
            json={"name": "Agente Ventas", "system_prompt": "ventas", "model": "gpt-4o-mini"},
        )
    ).json()

    from src.platform.riskcenter.risk_center import add_manual_risk

    await add_manual_risk(UUID(org["organization_id"]), "hallucination", "high", "alucina precios", UUID(agent["id"]))
    await add_manual_risk(UUID(org["organization_id"]), "bias", "medium", "sesgo", UUID(agent["id"]))

    heatmap = await async_client.get("/api/v1/risk-center/heatmap", headers=h)
    assert heatmap.status_code == 200, heatmap.text
    entries = heatmap.json()["heatmap"]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["agent_name"] == "Agente Ventas"
    assert entry["risks"]["hallucination"]["severity"] == "high"
    assert entry["risks"]["bias"]["score"] == 50.0  # medium = 0.5 x 100


@pytest.mark.asyncio
async def test_compliance_posture_and_trend(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "RC Posture Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    posture = await async_client.get("/api/v1/risk-center/compliance/posture?framework=eu_ai_act", headers=h)
    assert posture.status_code == 200, posture.text
    body = posture.json()
    assert body["total_controls"] == 8
    assert body["score"] == 0.0  # nada implementado

    # Implementar 2 controles.
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session
    from src.platform.compliance.audit_reports import update_control_status

    session = await get_async_session()
    try:
        controls = (
            await session.execute(
                text(
                    "SELECT control_id FROM compliance_controls "
                    "WHERE framework = 'eu_ai_act' ORDER BY control_id LIMIT 2"
                )
            )
        ).fetchall()
    finally:
        await session.close()
    for c in controls:
        await update_control_status(UUID(org["organization_id"]), "eu_ai_act", c.control_id, "pass")

    posture2 = await async_client.get("/api/v1/risk-center/compliance/posture?framework=eu_ai_act", headers=h)
    assert posture2.json()["implemented"] == 2
    assert posture2.json()["score"] == 25.0
    assert posture2.json()["by_risk_type"]["hallucination"]["implemented"] == 1  # EUAI-01

    trend = await async_client.get("/api/v1/risk-center/compliance/trend?framework=eu_ai_act", headers=h)
    assert trend.status_code == 200, trend.text
    assert trend.json()["trend"][-1]["score"] == 25.0


@pytest.mark.asyncio
async def test_platform_dashboard(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "RC Dash Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    plat = await _platform_admin(async_client, f"padmin-rcd-{uuid4().hex[:8]}@zent.example")

    from src.platform.riskcenter.risk_center import add_manual_risk, compliance_posture

    await add_manual_risk(UUID(org["organization_id"]), "security", "critical", "brecha")
    await compliance_posture(UUID(org["organization_id"]), "eu_ai_act")

    dash = await async_client.get("/api/v1/platform/risk-center/dashboard", headers=plat)
    assert dash.status_code == 200, dash.text
    body = dash.json()
    assert body["open_risks"] >= 1
    assert any(t["risk_type"] == "security" for t in body["by_risk_type"])
    assert any(s["severity"] == "critical" for s in body["by_severity"])
    assert any(p["framework"] == "eu_ai_act" for p in body["posture_by_framework"])
    assert any(o["open_risks"] >= 1 for o in body["top_organizations"])
