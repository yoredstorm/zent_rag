# =============================================================================
# Workflow Semantic Core — Fase 1: WorkflowContextAssembler.
#
# Unit tests puros: scope de secciones, seguridad (nunca `security`), budget por
# sección/total, redacción y render compacto.
# =============================================================================
from __future__ import annotations

from uuid import uuid4

from src.platform.workflows.context import TriggerSnapshot, WorkflowContext, WorkflowIdentity
from src.platform.workflows.context_assembler import (
    ContextBudget,
    WorkflowContextAssembler,
)
from src.platform.workflows.values import WorkflowValue


def _context() -> WorkflowContext:
    return WorkflowContext(
        identity=WorkflowIdentity(
            organization_id=uuid4(),
            workflow_id=uuid4(),
            run_id=uuid4(),
        ),
        trigger=TriggerSnapshot(source="event", event_type="sale.created", payload={"sale_id": "s-1"}),
    )


def _slot(value, *, value_type="record", label=None, redacted=False) -> dict:
    return WorkflowValue.from_raw(value, value_type=value_type, label=label, redacted=redacted).to_dict()


def test_assembler_respects_reads_and_never_exposes_security() -> None:
    context = _context()
    context.data["ventas"] = _slot({"total": 54000}, label="Ventas")
    context.knowledge["politica"] = _slot({"answer": "Descuento máximo 15%"}, value_type="knowledge_answer")
    context.security["permissions"] = ["admin"]

    assembled = WorkflowContextAssembler().for_agent(
        context, reads=("data", "knowledge", "security")
    )

    assert set(assembled.payload) == {"data", "knowledge"}
    assert assembled.payload["data"]["ventas"]["total"] == 54000
    assert assembled.sections_used == ("data", "knowledge")
    assert "security" not in assembled.rendered


def test_assembler_without_reads_returns_empty() -> None:
    context = _context()
    context.data["ventas"] = _slot({"total": 1})

    assembled = WorkflowContextAssembler().for_node(context, reads=())

    assert assembled.payload == {}
    assert assembled.sections_used == ()
    assert assembled.truncated == ()


def test_assembler_budget_per_section_truncates_values() -> None:
    context = _context()
    for index in range(5):
        context.data[f"slot_{index}"] = _slot({"total": index})

    assembled = WorkflowContextAssembler(
        budget=ContextBudget(max_values_per_section=2, max_chars_per_section=4_000, max_chars_total=12_000)
    ).for_agent(context, reads=("data",))

    assert len(assembled.payload["data"]) == 2
    assert "data" in assembled.truncated


def test_assembler_total_budget_drops_lowest_priority_section() -> None:
    context = _context()
    context.data["ventas"] = _slot({"total": 54000, "cliente": "ACME"})
    context.knowledge["politica"] = _slot(
        {"answer": "Descuento máximo 15% " * 5}, value_type="knowledge_answer"
    )

    assembled = WorkflowContextAssembler(
        budget=ContextBudget(max_values_per_section=20, max_chars_per_section=400, max_chars_total=120)
    ).for_agent(context, reads=("data", "knowledge"))

    assert "data" in assembled.payload
    assert "knowledge" not in assembled.payload
    assert "knowledge" in assembled.truncated


def test_assembler_redacts_flagged_values() -> None:
    context = _context()
    context.data["cliente"] = _slot({"name": "ACME"}, redacted=True)

    assembled = WorkflowContextAssembler().for_agent(context, reads=("data",))

    assert assembled.payload["data"]["cliente"] == "[redactado]"


def test_assembler_renders_compact_sections() -> None:
    context = _context()
    context.data["ventas"] = _slot({"total": 54000})
    context.evidence_refs.append(
        {"value": {"evidence_id": str(uuid4()), "label": "policy.pdf"}, "value_type": "evidence"}
    )

    assembled = WorkflowContextAssembler().for_agent(context, reads=("trigger", "data", "evidence"))

    assert "[trigger]" in assembled.rendered
    assert "[data]" in assembled.rendered
    assert "ventas" in assembled.rendered
    assert "policy.pdf" in assembled.rendered


def test_assembler_ignores_unknown_sections() -> None:
    assembled = WorkflowContextAssembler().for_agent(_context(), reads=("no_existe", "execution"))
    assert assembled.payload == {}
