# =============================================================================
# Universal Studio — five real-provider Gold experiences.
#
# These are not template installs: the planner must start from natural language,
# discover the tenant's real capabilities and produce a valid graph. They are
# skipped unless RAG_CERT_REAL_LLM=1. A skip is not a PASS.
# =============================================================================
from __future__ import annotations

import json
import os
from typing import Any

import pytest
from httpx import AsyncClient

from src.platform.workflows.ir import WorkflowGraph, validate_graph
from tests.certification.workflows.gold_support import (
    ready_tenant,
    seed_knowledge_base,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("RAG_CERT_REAL_LLM") != "1",
    reason="set RAG_CERT_REAL_LLM=1 with authorized real LLM credentials",
)

GOLD_EXPERIENCES: dict[str, dict[str, Any]] = {
    "sales": {
        "prompt": (
            "Quiero un asistente que venda arroz, consulte catálogo/stock, "
            "espere mensajes, mantenga carrito, cobre por proveedor conectado "
            "y cierre una orden."
        ),
        "required_steps": {"wait", "human_approval", "capability_call"},
        "required_refs": {"catalog.products.search", "payments.checkout.create"},
        "answer": (
            "Usa catalog.products.search para catálogo, precio y stock; sales.cart.quote "
            "para el carrito; sales.order.create y payments.checkout.create con "
            "human_approval previo; espera payment.succeeded. No inventes proveedores."
        ),
    },
    "mentoring": {
        "prompt": (
            "Quiero un mentor de Python que evalúe nivel, proponga ejercicios, "
            "registre progreso y programe seguimiento."
        ),
        "required_steps": {"agent_analysis", "knowledge_query", "state"},
        "required_refs": set(),
        "answer": (
            "Usa un cuestionario corto y ejercicios prácticos; criterio: pasa tests y "
            "explica la solución; seguimiento semanal por notificación; alcance básico "
            "y POO; progreso en estado durable. No inventes integraciones."
        ),
    },
    "audit": {
        "prompt": (
            "Cuando ingrese un archivo, cruza información con fuentes autorizadas, "
            "identifica diferencias y pide aprobación antes de reportar."
        ),
        "required_steps": {"knowledge_query", "human_approval"},
        "required_refs": set(),
        "answer": (
            "Usa la base de conocimiento y la base de datos gestionada del tenant; "
            "compara los campos disponibles; si falta una fuente, deja el requisito "
            "explícito; pide human_approval antes de reportar. No inventes fuentes."
        ),
    },
    "support": {
        "prompt": (
            "Recibe un incidente, consulta KB, pregunta datos faltantes y escala "
            "a una persona si no puede resolverlo."
        ),
        "required_steps": {"knowledge_query", "agent_analysis"},
        "required_refs": set(),
        "answer": (
            "Consulta la KB; si falta un dato, pregunta una vez; si no puedes resolver, "
            "usa human_approval para escalar a una persona. No inventes políticas."
        ),
    },
    "wellness": {
        "prompt": (
            "Quiero un asistente de acompañamiento y recursos de bienestar sin "
            "diagnóstico clínico, con consentimiento y protocolo de derivación."
        ),
        "required_steps": {"agent_analysis", "knowledge_query"},
        "required_refs": set(),
        "answer": (
            "No diagnostiques ni recetes; usa la KB de recursos; pide consentimiento; "
            "si hay crisis, deriva a una persona o servicio de emergencia. No prometas "
            "curación."
        ),
    },
}


@pytest.mark.parametrize("experience", list(GOLD_EXPERIENCES))
@pytest.mark.timeout(900)
@pytest.mark.asyncio
async def test_real_llm_generates_universal_gold(
    async_client: AsyncClient, experience: str
) -> None:
    case = GOLD_EXPERIENCES[experience]
    org = await ready_tenant(
        async_client,
        f"Universal Gold {experience}",
        with_agent=True,
        with_managed_db=True,
    )
    await seed_knowledge_base(org["organization_id"])
    model = os.environ.get("RAG_CERT_PLANNER_MODEL") or os.environ.get(
        "RAG_WORKFLOW_PLANNER_MODEL"
    )
    response = await async_client.post(
        "/api/v1/workflows/architect/sessions",
        headers={
            "Authorization": f"Bearer {org['session']}",
            "X-Organization-Id": org["organization_id"],
            "Idempotency-Key": f"universal-gold-{experience}",
        },
        json={
            "prompt": case["prompt"],
            "title": f"Gold {experience}",
            **({"model": model} if model else {}),
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    proposal = body["proposal"]
    design = body["design_session"]
    # Si el planner pide una decisión de negocio, el usuario responde con
    # supuestos explícitos y el backend vuelve a planificar. Es el recorrido
    # conversacional real, no un test de una sola llamada.
    for _ in range(2):
        if proposal.get("state") in ("DRAFT_READY", "NEEDS_CONFIGURATION"):
            break
        questions = [
            str(item.get("question") or "")
            for item in (proposal.get("clarifications") or [])
            if item.get("question")
        ]
        if not questions:
            break
        answer = case.get("answer") or (
            "Usa supuestos razonables y la opción más simple: "
            + "; ".join(questions[:5])
            + ". No inventes integraciones ni credenciales."
        )
        follow = await async_client.post(
            f"/api/v1/workflows/architect/sessions/{design['id']}/messages",
            headers={
                "Authorization": f"Bearer {org['session']}",
                "X-Organization-Id": org["organization_id"],
                "Idempotency-Key": f"universal-gold-{experience}-answer-{_}",
            },
            json={"message": answer, "expected_revision": design["revision"]},
        )
        assert follow.status_code == 200, follow.text
        body = follow.json()
        proposal = body["proposal"]
        design = body["design_session"]
    plan = proposal.get("plan") or {}
    graph = proposal.get("graph")
    assert proposal.get("state") in ("DRAFT_READY", "NEEDS_CONFIGURATION"), json.dumps(
        {
            "state": proposal.get("state"),
            "issues": proposal.get("issues"),
            "clarifications": proposal.get("clarifications"),
            "requirements": proposal.get("requirements"),
        },
        ensure_ascii=False,
    )[:4000]
    assert graph is not None, proposal.get("issues")
    validate_graph(WorkflowGraph.from_dict(graph))
    steps = plan.get("steps") or []
    types = {str(step.get("type")) for step in steps}
    assert case["required_steps"] <= types, (case["required_steps"], types)
    refs = {
        str((step.get("params") or {}).get("capability"))
        for step in steps
        if step.get("type") == "capability_call"
    }
    assert case["required_refs"] <= refs, (case["required_refs"], refs)
    if experience == "wellness":
        text = json.dumps(plan, ensure_ascii=False).lower()
        assert "diagnóstico clínico" not in text or "sin diagnóstico clínico" in text
        assert any(
            step.get("type") in ("human_approval", "conversation.send")
            for step in steps
        ), types
