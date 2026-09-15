# =============================================================================
# Workflow Semantic Core — Fase 1: WorkflowContext, contribuciones y merge.
#
# Unit tests puros (sin DB): contexto, contribuciones, caps, seguridad y la
# contribución que produce un output estructurado de agente.
# =============================================================================
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from httpx import AsyncClient

from src.platform.workflows.context import (
    CONTEXT_SCHEMA_VERSION,
    TriggerSnapshot,
    WorkflowContext,
    WorkflowIdentity,
    is_writable_section,
    normalize_section,
)
from src.platform.workflows.contributions import (
    ContextMerger,
    ContextWrite,
    NodeContribution,
)
from src.platform.workflows.runtime import ExecutionContext
from src.platform.workflows.values import (
    Provenance,
    WorkflowValue,
    infer_value_type,
    jsonable,
)
from tests.test_workflows import _create_org, _headers, _owner_session


def _identity() -> WorkflowIdentity:
    return WorkflowIdentity(
        organization_id=uuid4(),
        workflow_id=uuid4(),
        run_id=uuid4(),
        actor_type="user",
        correlation_id="corr-1",
    )


def _context() -> WorkflowContext:
    return WorkflowContext(
        identity=_identity(),
        trigger=TriggerSnapshot(source="event", event_type="sale.created", payload={"sale_id": "s-1"}),
    )


def _execution() -> ExecutionContext:
    return ExecutionContext(
        organization_id=uuid4(),
        workflow_id=uuid4(),
        run_id=uuid4(),
        actor_type="user",
        trigger_type="event",
        permissions=frozenset({"workflows:run"}),
        correlation_id="corr-9",
    )


# ---------------------------------------------------------------------------
# Contexto
# ---------------------------------------------------------------------------
def test_snapshot_excludes_security_by_default() -> None:
    context = _context()
    context.security["permissions"] = ["workflows:run", "agents:execute"]
    context.data["ventas"] = {"value": {"total": 54000}, "value_type": "record"}

    snapshot = context.snapshot()
    assert "security" not in snapshot
    assert snapshot["data"]["ventas"]["value"]["total"] == 54000
    assert snapshot["identity"]["organization_id"] == str(context.identity.organization_id)

    runtime_view = context.to_dict(sections=("security",), include_runtime=True)
    assert runtime_view["security"]["permissions"] == ["workflows:run", "agents:execute"]


def test_from_execution_copies_identity_and_trigger() -> None:
    execution = _execution()
    context = WorkflowContext.from_execution(execution, payload={"message": "hola"}, event_type="sale.created")

    assert context.schema_version == CONTEXT_SCHEMA_VERSION
    assert context.identity.organization_id == execution.organization_id
    assert context.identity.run_id == execution.run_id
    assert context.identity.correlation_id == "corr-9"
    assert context.trigger.source == "sale.created"
    assert context.trigger.event_type == "sale.created"
    assert context.trigger.payload == {"message": "hola"}
    assert context.trigger.occurred_at is not None


def test_normalize_section_aliases_and_writable() -> None:
    assert normalize_section("evidence") == "evidence_refs"
    assert normalize_section("claims") == "claim_refs"
    assert normalize_section("entities") == "entity_refs"
    assert normalize_section("security") == "security"
    assert normalize_section("nope") is None
    assert is_writable_section("data") is True
    assert is_writable_section("security") is False
    assert is_writable_section("identity") is False


def test_values_inference_and_jsonable() -> None:
    assert infer_value_type(True) == "boolean"
    assert infer_value_type(3) == "number"
    assert infer_value_type("x") == "string"
    assert infer_value_type({"a": 1}) == "record"
    assert infer_value_type([{"a": 1}]) == "record_list"
    assert infer_value_type([1, 2]) == "json"
    fixed_id = uuid4()
    assert jsonable(fixed_id) == str(fixed_id)
    fixed = datetime(2026, 9, 14, tzinfo=timezone.utc)
    assert jsonable(fixed) == fixed.isoformat()
    try:
        WorkflowValue(value="x", value_type="inventado")
    except ValueError as exc:
        assert "value_type inválido" in str(exc)
    else:  # pragma: no cover - el tipo inválido debe fallar
        raise AssertionError("value_type inválido debió fallar")


# ---------------------------------------------------------------------------
# Merge de contribuciones
# ---------------------------------------------------------------------------
def test_merge_appends_refs_and_dedupes() -> None:
    context = _context()
    merger = ContextMerger()
    evidence_id = uuid4()
    contribution = NodeContribution(
        writes=(
            ContextWrite(section="evidence", value={"evidence_id": str(evidence_id), "label": "policy.pdf"}),
            ContextWrite(section="evidence", value={"evidence_id": str(evidence_id), "label": "duplicado"}),
            ContextWrite(section="claims", value={"claim_id": str(uuid4()), "status": "proposed", "text": "Descuento 15%"}),
        )
    )
    report = merger.apply(context, node_id="n1", node_type="kb_query", contribution=contribution)

    assert len(report.applied) == 3
    assert report.applied[1]["deduplicated"] is True
    assert report.rejected == []
    assert len(context.evidence_refs) == 1
    assert context.evidence_refs[0]["provenance"]["node_id"] == "n1"
    assert context.evidence_refs[0]["provenance"]["timestamp"] is not None
    assert context.claim_refs[0]["value"]["status"] == "proposed"


def test_merge_slots_last_write_and_variables() -> None:
    context = _context()
    merger = ContextMerger()
    contribution = NodeContribution(
        writes=(
            ContextWrite(section="data", key="ventas", value={"total": 100}, value_type="record", label="Ventas"),
            ContextWrite(section="data", key="ventas", value={"total": 200}, value_type="record"),
            ContextWrite(section="variables", key="umbral", value=10),
            ContextWrite(section="variables", value=5),
        )
    )
    report = merger.apply(context, node_id="n2", node_type="query_business_data", contribution=contribution)

    assert context.data["ventas"]["value"]["total"] == 200
    assert context.variables["umbral"] == 10
    assert report.rejected == [{"index": 3, "section": "variables", "reason": "missing_key"}]


def test_merge_rejects_runtime_only_and_undeclared_sections() -> None:
    context = _context()
    merger = ContextMerger()
    contribution = NodeContribution(
        writes=(
            ContextWrite(section="security", value={"permissions": ["admin"]}),
            ContextWrite(section="evidence", value={"evidence_id": str(uuid4())}),
        )
    )

    report = merger.apply(
        context,
        node_id="n3",
        node_type="llm",
        contribution=contribution,
        allowed_sections=("data",),
    )

    reasons = [item["reason"] for item in report.rejected]
    assert reasons == ["section_not_writable", "section_not_declared"]
    assert context.security == {}
    assert context.evidence_refs == []


def test_merge_caps_section_values() -> None:
    context = _context()
    merger = ContextMerger(max_values_per_section=1)
    contribution = NodeContribution(
        writes=(
            ContextWrite(section="evidence", value={"evidence_id": str(uuid4())}),
            ContextWrite(section="evidence", value={"evidence_id": str(uuid4())}),
        )
    )
    report = merger.apply(context, node_id="n4", node_type="kb_query", contribution=contribution)

    assert len(context.evidence_refs) == 1
    assert report.rejected == [{"index": 1, "section": "evidence_refs", "reason": "section_full"}]


def test_merge_rejects_oversized_write() -> None:
    context = _context()
    merger = ContextMerger(max_write_chars=50)
    contribution = NodeContribution(
        writes=(ContextWrite(section="data", key="grande", value={"texto": "x" * 500}),)
    )
    report = merger.apply(context, node_id="n5", node_type="api_call", contribution=contribution)

    assert context.data == {}
    assert report.rejected[0]["reason"] == "value_too_large"


def test_merge_report_serializes() -> None:
    report = ContextMerger().apply(_context(), node_id="n6", node_type="notify", contribution=None)
    payload = report.to_dict()
    assert payload["node_id"] == "n6"
    assert payload["applied"] == [] and payload["rejected"] == []


# ---------------------------------------------------------------------------
# Nodo llm: output schema → contribución de decisión
# ---------------------------------------------------------------------------
def _llm_node_context(context: WorkflowContext):
    from src.platform.workflows.ir import WorkflowNode
    from src.platform.workflows.nodes import NodeContext, NodeTypeDef

    execution = _execution()
    return NodeContext(
        execution=execution,
        node=WorkflowNode(id="riesgo", type="llm", label="Analizar riesgo", config={"agent_name": "Riesgos"}),
        node_type=NodeTypeDef(
            node_type="llm",
            version=1,
            label="Preguntar a un agente",
            category="ai",
            risk_level="normal",
            capabilities=frozenset(),
        ),
        node_id="riesgo",
        inputs={},
        trigger={"sale_id": "s-1"},
        payload={"sale_id": "s-1"},
        variables={},
        node_outputs={},
        idempotency_key=None,
        context=context,
    )


def test_structured_agent_output_produces_decision_contribution() -> None:
    from src.platform.workflows.nodes import NodeOutcome, _apply_output_schema

    context = _context()
    rctx = _llm_node_context(context)
    schema = {
        "type": "object",
        "properties": {
            "risk": {"type": "string"},
            "reason": {"type": "string"},
            "recommendation": {"type": "string"},
        },
    }
    outcome = NodeOutcome(
        output={"text": '{"risk": "high", "reason": "cliente moroso", "recommendation": "revisar crédito"}'}
    )
    result = _apply_output_schema({"output_schema": schema}, outcome, rctx)

    assert result.output["structured"] is True
    assert result.contribution is not None
    first = result.contribution.writes[0]
    assert first.section == "decisions"
    assert first.value["risk"] == "high"
    assert first.value["reason"] == "cliente moroso"
    assert first.value["recommendation"] == "revisar crédito"
    assert first.value["decision_result"]["decision"] == "high"
    assert first.value["decision_result"]["status"] == "ok"

    report = ContextMerger().apply(
        context, node_id="riesgo", node_type="llm", contribution=result.contribution
    )
    assert report.applied and context.decisions[0]["value"]["risk"] == "high"
    assert context.decisions[0]["provenance"]["node_type"] == "llm"


def test_structured_output_without_context_keeps_backwards_compatibility() -> None:
    from src.platform.workflows.nodes import NodeOutcome, _apply_output_schema

    schema = {"type": "object", "properties": {"risk": {"type": "string"}}}
    outcome = NodeOutcome(output={"text": '{"risk": "low"}'})
    result = _apply_output_schema({"output_schema": schema}, outcome)

    assert result.output["structured"] is True
    assert result.contribution is None


def test_provenance_serializes_workspace_and_confidence() -> None:
    workspace_id = uuid4()
    provenance = Provenance(
        origin_kind="knowledge",
        node_id="n7",
        source_id="doc-1",
        workspace_id=workspace_id,
        confidence=0.8,
    )
    payload = provenance.to_dict()
    assert payload["workspace_id"] == str(workspace_id)
    assert payload["origin_kind"] == "knowledge"
    assert payload["confidence"] == 0.8


# ---------------------------------------------------------------------------
# API: el run expone result.context (integración runtime/engine)
# ---------------------------------------------------------------------------
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
async def test_run_response_includes_shared_context(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Semantic Context")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    graph = _graph(
        [
            _node("trigger", "trigger_webhook"),
            _node("umbral", "set_variable", {"name": "umbral", "value": "10"}),
            _node("avisar", "notify", {"channel": "in_app", "title": "Alerta", "message": "ok"}),
        ],
        [_edge("e1", "trigger", "umbral"), _edge("e2", "umbral", "avisar")],
        ["trigger"],
    )
    created = await async_client.post(
        "/api/v1/workflows",
        headers={**h, "Idempotency-Key": f"ctx-c-{uuid4().hex}"},
        json={"name": "Context WF", "trigger_type": "webhook", "graph": graph, "workflow_version": 2},
    )
    assert created.status_code == 200, created.text
    wid = created.json()["workflow_id"]

    result = await async_client.post(
        f"/api/v1/workflows/{wid}/run",
        headers={**h, "Idempotency-Key": f"ctx-r-{uuid4().hex}"},
        json={"payload": {"message": "hola"}, "simulate": True},
    )
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["status"] == "simulated", body

    context = body["result"]["context"]
    assert context["identity"]["workflow_id"] == wid
    assert context["identity"]["organization_id"] == org["organization_id"]
    assert context["trigger"]["payload"] == {"message": "hola"}
    assert context["variables"]["umbral"] == 10
    assert context["execution"]["nodes"]["avisar"]["status"] == "simulated"
    assert "security" not in context

    # Outputs crudos intactos (compatibilidad).
    raw = body["result"]["structured_output"]["nodes"]["umbral"]["output"]
    assert raw["variable"] == "umbral"
    assert raw["value"] == 10
