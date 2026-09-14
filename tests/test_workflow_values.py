# =============================================================================
# Workflow Semantic Core — Fase 2: adaptadores raw↔WorkflowValue y provenance
# real en las contribuciones de nodos.
#
# Unit tests puros: mapeo de tipos, provenance estándar y builders de
# contribución por tipo de nodo.
# =============================================================================
from __future__ import annotations

from uuid import uuid4

from src.platform.workflows.context import TriggerSnapshot, WorkflowContext, WorkflowIdentity
from src.platform.workflows.contributions import ContextMerger
from src.platform.workflows.nodes import (
    _agent_output_contribution,
    _api_call_contribution,
    _business_node_contribution,
    _business_result_contribution,
    _kb_query_contribution,
    _marketplace_contribution,
    _query_business_data_contribution,
)
from src.platform.workflows.runtime import ExecutionContext
from src.platform.workflows.values import WorkflowValue, node_provenance


def _rctx(node_id: str, node_type: str, config: dict | None = None):
    from src.platform.workflows.ir import WorkflowNode
    from src.platform.workflows.nodes import NodeContext, NodeTypeDef

    execution = ExecutionContext(
        organization_id=uuid4(),
        workflow_id=uuid4(),
        run_id=uuid4(),
        actor_type="user",
        trigger_type="manual",
        permissions=frozenset(),
        workspace_id=uuid4(),
    )
    return NodeContext(
        execution=execution,
        node=WorkflowNode(id=node_id, type=node_type, label=node_type, config=config or {}),
        node_type=NodeTypeDef(
            node_type=node_type,
            version=1,
            label=node_type,
            category="data",
            risk_level="normal",
            capabilities=frozenset(),
        ),
        node_id=node_id,
        inputs={},
        trigger={},
        payload={},
        variables={},
        node_outputs={},
        idempotency_key=None,
    )


def _context() -> WorkflowContext:
    return WorkflowContext(
        identity=WorkflowIdentity(organization_id=uuid4(), workflow_id=uuid4(), run_id=uuid4()),
        trigger=TriggerSnapshot(source="manual"),
    )


# ---------------------------------------------------------------------------
# Adaptadores y provenance
# ---------------------------------------------------------------------------
def test_value_from_raw_maps_ir_and_business_types() -> None:
    assert WorkflowValue.from_raw(3, value_type="integer").value_type == "number"
    assert WorkflowValue.from_raw("x", value_type="text").value_type == "string"
    assert WorkflowValue.from_raw([{"a": 1}]).value_type == "record_list"
    assert WorkflowValue.from_raw(100, value_type="money").value_type == "money"


def test_value_from_raw_rejects_unknown_type() -> None:
    try:
        WorkflowValue.from_raw("x", value_type="inventado")
    except ValueError as exc:
        assert "value_type inválido" in str(exc)
    else:  # pragma: no cover - el tipo inválido debe fallar
        raise AssertionError("value_type inválido debió fallar")


def test_node_provenance_defaults() -> None:
    provenance = node_provenance("n1", "kb_query", origin_kind="knowledge", source_id="ws-1")
    assert provenance.node_id == "n1"
    assert provenance.origin_kind == "knowledge"
    assert provenance.source_id == "ws-1"
    assert provenance.timestamp is not None
    assert provenance.to_dict()["timestamp"] is not None


# ---------------------------------------------------------------------------
# Builders de contribución
# ---------------------------------------------------------------------------
def test_kb_query_contribution_knowledge_slot() -> None:
    rctx = _rctx("kb1", "kb_query", {"query": "política de stock"})
    contribution = _kb_query_contribution(
        rctx, query="política de stock", chunks=[{"title": "policy", "text": "x"}], count=1
    )
    write = contribution.writes[0]
    assert write.section == "knowledge"
    assert write.value_type == "knowledge_answer"
    assert write.value["count"] == 1
    assert write.provenance is not None and write.provenance.origin_kind == "knowledge"

    context = _context()
    report = ContextMerger().apply(context, node_id="kb1", node_type="kb_query", contribution=contribution)
    assert report.applied
    assert context.knowledge["kb1"]["value"]["query"] == "política de stock"


def test_query_business_data_contribution_rows_confidence() -> None:
    rctx = _rctx("qbd", "query_business_data", {"ask": "stock disponible"})
    contribution = _query_business_data_contribution(
        rctx,
        {
            "answer": "hay 3 productos",
            "rows": [{"producto": "A", "stock": 3}],
            "columns": ["producto", "stock"],
            "query_id": "q-1",
            "metrics": {"answerable": True, "latency_ms": 12.0},
        },
    )
    write = contribution.writes[0]
    assert write.section == "data"
    assert write.value_type == "record_list"
    assert write.provenance is not None
    assert write.provenance.source_id == "q-1"
    assert write.provenance.confidence == 1.0


def test_query_business_data_contribution_without_rows_is_knowledge_answer() -> None:
    rctx = _rctx("qbd2", "query_business_data", {"ask": "política"})
    contribution = _query_business_data_contribution(rctx, {"answer": "según el manual"})
    assert contribution.writes[0].value_type == "knowledge_answer"


def test_api_call_contribution_records_source_url() -> None:
    rctx = _rctx("api1", "api_call", {"url": "https://api.example/stock"})
    contribution = _api_call_contribution(
        rctx, url="https://api.example/stock", status_code=200, ok=True, extracted=7
    )
    write = contribution.writes[0]
    assert write.section == "data"
    assert write.value["status_code"] == 200
    assert write.provenance is not None
    assert write.provenance.source_id == "https://api.example/stock"
    assert write.provenance.origin_kind == "datasource"


def test_marketplace_contribution_includes_evidence_ref() -> None:
    evidence_id = uuid4()
    rctx = _rctx("mkt1", "marketplace_action", {"action_id": "peru.taxpayer.lookup"})
    contribution = _marketplace_contribution(
        rctx,
        action_id="peru.taxpayer.lookup",
        data={"razon_social": "ACME"},
        evidence_id=evidence_id,
    )
    sections = [write.section for write in contribution.writes]
    assert sections == ["data", "evidence"]
    assert contribution.writes[1].value["evidence_id"] == str(evidence_id)
    assert contribution.writes[1].provenance is not None
    assert contribution.writes[1].provenance.evidence_id == evidence_id


def test_business_result_contribution_is_artifact() -> None:
    rctx = _rctx("br1", "business_result", {"title": "Resumen diario"})
    contribution = _business_result_contribution(rctx, result_id="r-1", title="Resumen diario")
    write = contribution.writes[0]
    assert write.section == "artifacts"
    assert write.value_type == "artifact"
    assert write.value == {"id": "r-1", "title": "Resumen diario", "kind": "business_result"}


def test_business_node_contribution_includes_action_evidence() -> None:
    rctx = _rctx("bn1", "business_node", {"title": "Verificación"})
    evidence_id = str(uuid4())
    contribution = _business_node_contribution(
        rctx,
        title="Verificación",
        outputs={"title": "Verificación", "action_0": {"ok": True}},
        evidence_ids=[evidence_id],
    )
    sections = [write.section for write in contribution.writes]
    assert sections == ["data", "evidence"]
    assert contribution.writes[0].value["outputs"] == {"action_0": {"ok": True}}


def test_agent_output_contribution_uses_agent_provenance() -> None:
    rctx = _rctx("llm1", "llm", {"agent_id": str(uuid4()), "agent_name": "Riesgos"})
    contribution = _agent_output_contribution(
        {"risk": "high", "reason": "mora", "confidence": 0.7}, rctx
    )
    assert contribution is not None
    write = contribution.writes[0]
    assert write.section == "decisions"
    assert write.provenance is not None
    assert write.provenance.origin_kind == "agent"
    assert write.provenance.confidence == 0.7
