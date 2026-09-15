# =============================================================================
# Workflow Architect — Fase 10: dataset de 50 intents + métricas.
#
# El "provider" es una plantilla determinística por caso (test double): valida
# el pipeline real (validator/compiler/readiness/clarifications) contra 50
# expectativas. Sirve de harness para futuras corridas con LLM grabado.
# =============================================================================
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.platform.workflows.architect import plan_workflow
from src.platform.workflows.architect_metrics import reset_metrics, snapshot

_CASES_PATH = Path(__file__).parent / "data" / "workflow_architect_cases.json"
CASES = json.loads(_CASES_PATH.read_text(encoding="utf-8"))["cases"]

EVAL_CAPS = {
    "available": {
        "agents": True,
        "knowledge_bases": True,
        "installed_integrations": True,
        "managed_db": True,
    },
    "agents": [
        {
            "id": "ag1",
            "name": "Analista",
            "purpose": "Analiza ventas, riesgo, contratos, políticas y proveedores",
            "tools": ["query_database"],
        }
    ],
    "knowledge_bases": ["kb1"],
    "actions": [{"action_id": "demo.echo", "display_name": "Echo", "install_id": "i1"}],
    "events": ["sales.closed", "document.processed", "invoice.overdue", "customer.created"],
    "managed_db": True,
}

_EVENT_BY_CATEGORY = {
    "sales": "sales.closed",
    "inventory": "inventory.stock.low",
    "finance": "invoice.overdue",
    "documents": "document.processed",
    "events": "sale.created",
    "customers": "customer.created",
}

_TRIGGER_NODE = {"event": "trigger_event", "schedule": "trigger_schedule", "manual": "trigger_webhook"}


def _template_intent(case: dict) -> dict:
    expect = case["expect"]
    return {
        "goal": case["prompt"],
        "trigger_intent": {"kind": expect["trigger"]},
        "reasoning_needs": ["evaluar"] if expect["agent"] else [],
        "confidence": 0.8,
    }


def _template_plan(case: dict) -> dict:
    expect = case["expect"]
    steps: list[dict] = []
    if expect["trigger"] == "event":
        steps.append(
            {
                "id": "t",
                "type": "trigger_event",
                "goal": "Cuando ocurra el evento",
                "params": {
                    "event_type": _EVENT_BY_CATEGORY.get(case["category"], "sale.created")
                },
            }
        )
    elif expect["trigger"] == "schedule":
        steps.append(
            {
                "id": "t",
                "type": "trigger_schedule",
                "goal": "Según programación",
                "params": {"daily": {"time": "08:00", "timezone": "America/Lima"}},
            }
        )
    else:
        steps.append({"id": "t", "type": "trigger_manual", "goal": "Inicio manual"})

    previous = "t"
    if expect["data"]:
        steps.append(
            {
                "id": "q",
                "type": "business_query",
                "goal": "Consultar datos de negocio",
                "depends_on": [previous],
                "params": {"ask": case["prompt"]},
            }
        )
        previous = "q"
    if expect["knowledge"]:
        steps.append(
            {
                "id": "k",
                "type": "knowledge_query",
                "goal": "Consultar conocimiento",
                "depends_on": [previous],
                "params": {
                    "operation": expect["knowledge_op"] or "answer",
                    "query": case["prompt"],
                },
            }
        )
        previous = "k"
    if expect["agent"]:
        steps.append(
            {
                "id": "a",
                "type": "agent_analysis",
                "goal": "Analizar la situación",
                "depends_on": [previous],
                "inputs": [{"step": previous, "field": "answer"}],
                "params": {"prompt": case["prompt"]},
            }
        )
        previous = "a"
    if expect["integration"]:
        steps.append(
            {
                "id": "i",
                "type": "integration_action",
                "goal": "Usar integración",
                "depends_on": [previous],
                "params": {"action_id": expect["integration"], "inputs": {"name": "demo"}},
            }
        )
        previous = "i"
    if expect["decision"]:
        steps.append(
            {
                "id": "d",
                "type": "decision",
                "goal": "Tomar una decisión",
                "depends_on": [previous],
                "inputs": (
                    [{"step": previous, "field": "requires_review"}] if expect["agent"] else []
                ),
                "params": (
                    {}
                    if expect["agent"]
                    else {"field": "trigger.stock", "operator": "<", "value": 10}
                ),
            }
        )
        previous = "d"
    if expect["approval"]:
        steps.append(
            {
                "id": "ap",
                "type": "human_approval",
                "goal": "Pedir aprobación humana",
                "depends_on": [previous],
                "when": {"step": "d", "outcome": True} if expect["decision"] else None,
                "params": {"action": "Aprobar"},
            }
        )
        previous = "ap"
    if expect["notify"]:
        steps.append(
            {
                "id": "n",
                "type": "notify",
                "goal": "Avisar",
                "depends_on": [previous],
                "params": {"channel": "in_app"},
            }
        )
    if case["id"] == "int_03":
        # "Avisa por Slack" se representa como notify con canal Slack.
        steps = [step for step in steps if step["id"] != "n"]
        steps.append(
            {
                "id": "n",
                "type": "notify",
                "goal": "Avisar por Slack",
                "depends_on": [previous],
                "params": {"channel": "slack"},
            }
        )
    if case["id"] == "int_04":
        for step in steps:
            if step["id"] == "n":
                step["params"] = {"channel": "email"}
    return {
        "goal": case["prompt"],
        "steps": steps,
        "assumptions": [],
        "uncertainties": [],
        "notes": [],
    }


class _TemplateProvider:
    """Primera llamada → intent; segunda → plan (como haría el LLM real)."""

    def __init__(self, case: dict) -> None:
        self.case = case
        self._call = 0

    async def generate(self, prompt, **kwargs):  # noqa: ANN001, ANN003
        self._call += 1
        payload = _template_intent(self.case) if self._call == 1 else _template_plan(self.case)
        return SimpleNamespace(content=json.dumps(payload), model="template")


def _node_types(graph: dict) -> set[str]:
    return {node["type"] for node in graph["nodes"]}


@pytest.mark.asyncio
async def test_architect_eval_dataset_of_50_intents() -> None:
    reset_metrics()
    failures: list[str] = []
    for case in CASES:
        expect = case["expect"]
        provider = _TemplateProvider(case)
        try:
            result = await plan_workflow(
                uuid4(),
                case["prompt"],
                capabilities=EVAL_CAPS,
                provider=provider,
                permissions=frozenset(
                    {"agents:execute", "external_actions:execute", "workflows:create"}
                ),
            )
        except Exception as exc:  # noqa: BLE001 — el dataset reporta el fallo
            failures.append(f"{case['id']}: excepción {exc}")
            continue

        graph = result["graph"]
        valid = graph is not None
        if valid != expect["expect_valid"]:
            failures.append(
                f"{case['id']}: graph={valid} esperado {expect['expect_valid']} "
                f"issues={[i['code'] for i in result['issues']]}"
            )
            continue

        if expect["requirement"]:
            requirements = {item["requirement"] for item in result["requirements"]}
            if expect["requirement"] not in requirements:
                failures.append(f"{case['id']}: falta requirement {expect['requirement']}")

        if valid:
            types = _node_types(graph)
            if _TRIGGER_NODE[expect["trigger"]] not in types:
                failures.append(f"{case['id']}: trigger incorrecto {sorted(types)}")
            if expect["agent"] and "llm" not in types:
                failures.append(f"{case['id']}: falta agente")
            if not expect["agent"] and "llm" in types:
                failures.append(f"{case['id']}: agente innecesario")
            if expect["decision"] and "condition" not in types:
                failures.append(f"{case['id']}: falta decisión")
            if expect["approval"] and "human_approval" not in types:
                failures.append(f"{case['id']}: falta aprobación")
            if expect["knowledge"]:
                kb_nodes = [n for n in graph["nodes"] if n["type"] == "kb_query"]
                if not kb_nodes:
                    failures.append(f"{case['id']}: falta knowledge")
                elif expect["knowledge_op"] and kb_nodes[0]["config"].get("operation") != expect["knowledge_op"]:
                    failures.append(
                        f"{case['id']}: operación {kb_nodes[0]['config'].get('operation')} "
                        f"≠ {expect['knowledge_op']}"
                    )
            if expect["integration"] and "marketplace_action" not in types:
                failures.append(f"{case['id']}: falta integración")
            if any("{{nodes.None" in json.dumps(node.get("config") or {}) for node in graph["nodes"]):
                failures.append(f"{case['id']}: referencia inválida")
            if result["readiness"] is None or result["simulation"] is None:
                failures.append(f"{case['id']}: falta readiness/simulation")

        if expect["clarify"] and not result["clarifications"]:
            failures.append(f"{case['id']}: falta clarificación")

    assert not failures, "\n".join(failures)

    metrics = snapshot()
    assert metrics["counters"]["workflow_architect_plans_total"] == len(CASES)
    assert metrics["counters"]["workflow_architect_compile_success_total"] == 48
    assert metrics["workflow_architect_plan_valid_rate"] > 0.9
    assert metrics["workflow_architect_clarification_rate"] > 0
    assert metrics["workflow_architect_unnecessary_agent_rate"] == 0
