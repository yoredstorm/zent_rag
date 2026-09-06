# =============================================================================
# FASE 03 (S4/S5) — Quality Gates y bloqueo de regresiones
# =============================================================================
"""Gates sobre métricas que el engine soporta; regresiones vs versión desplegada."""
import asyncio

import pytest

from src.platform.quality.gates import (
    gate_blocked,
    regression_blocked,
    sanitize_gate,
)
from src.rag.evaluation.metrics import sql_accuracy


def test_sql_accuracy_deterministic():
    assert sql_accuracy("SELECT id FROM orders", "SELECT id FROM orders") == 1.0
    assert sql_accuracy("  select   id  from orders;", "SELECT id FROM orders") == 1.0
    assert sql_accuracy("SELECT id FROM users", "SELECT id FROM orders") == 0.0
    # None cuando el caso no define expected_sql
    assert sql_accuracy("SELECT 1", None) is None


def test_gate_blocked_thresholds():
    gate = {"thresholds": {"faithfulness": 0.8, "answer_relevance": 0.7}, "max_hallucination": None, "max_regression_pct": 5.0}
    quality = {"faithfulness": 0.91, "answer_relevance": 0.62}
    reasons = asyncio.run(gate_blocked(quality, gate))
    assert any("answer_relevance" in r for r in reasons)
    assert not any("faithfulness" in r for r in reasons)

    ok = asyncio.run(gate_blocked({"faithfulness": 0.95, "answer_relevance": 0.9}, gate))
    assert ok == []


def test_gate_blocked_hallucination():
    gate = {"thresholds": {}, "max_hallucination": 0.3, "max_regression_pct": 5.0}
    assert asyncio.run(gate_blocked({"hallucination_rate": 0.4}, gate))
    assert asyncio.run(gate_blocked({"hallucination_rate": 0.1}, gate)) == []


def test_regression_blocked_detects_drop():
    gate = {"thresholds": {}, "max_hallucination": None, "max_regression_pct": 5.0}
    baseline = {"faithfulness": 0.96, "answer_relevance": 0.9}
    candidate = {"faithfulness": 0.89, "answer_relevance": 0.88}
    reasons = asyncio.run(regression_blocked(candidate, baseline, gate))
    assert any("faithfulness" in r for r in reasons)
    assert not any("answer_relevance" in r for r in reasons)


def test_regression_hallucination_increase_blocks():
    gate = {"thresholds": {}, "max_hallucination": None, "max_regression_pct": 5.0}
    baseline = {"hallucination_rate": 0.02}
    candidate = {"hallucination_rate": 0.12}
    reasons = asyncio.run(regression_blocked(candidate, baseline, gate))
    assert any("hallucination_rate" in r for r in reasons)


def test_regression_ignores_metrics_not_in_both():
    gate = {"thresholds": {}, "max_hallucination": None, "max_regression_pct": 5.0}
    assert asyncio.run(regression_blocked({"faithfulness": 0.1}, {"answer_relevance": 0.9}, gate)) == []
    assert asyncio.run(regression_blocked(None, {"faithfulness": 0.9}, gate)) == []


def test_sanitize_only_supported_metrics():
    raw = {
        "thresholds": {"faithfulness": 0.8, "not_a_metric": 0.9, "sql_accuracy": 0.7},
        "max_hallucination": 0.25,
        "max_regression_pct": 10,
    }
    clean = sanitize_gate(raw)
    assert "faithfulness" in clean["thresholds"]
    assert "sql_accuracy" in clean["thresholds"]
    assert "not_a_metric" not in clean["thresholds"]
    assert clean["max_hallucination"] == 0.25
    assert clean["max_regression_pct"] == 10.0


@pytest.mark.asyncio
async def test_gate_crud_api(trial_auth, async_client):
    # Sesión portal (owner) para org-admin: el API key de trial no es org-admin.
    from uuid import uuid4

    signup = await async_client.post(
        "/api/v1/auth/signup",
        json={"company_name": f"Gates-{uuid4().hex[:6]}", "email": f"gates-{uuid4().hex[:8]}@test.dev", "password": "StrongPass123!"},
    )
    assert signup.status_code == 200, signup.text
    data = signup.json()
    headers = {
        "Authorization": f"Bearer {data['access_token']}",
        "X-Organization-Id": data["organization_id"],
    }

    resp = await async_client.get("/api/v1/organizations/quality-gates", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "supported_metrics" in body
    assert "gate" in body

    put = await async_client.put(
        "/api/v1/organizations/quality-gates",
        headers=headers,
        json={"thresholds": {"faithfulness": 0.75, "sql_accuracy": 0.7}, "max_hallucination": 0.3, "max_regression_pct": 5},
    )
    assert put.status_code == 200, put.text
    assert put.json()["gate"]["thresholds"]["faithfulness"] == 0.75
