"""Contratos versionados del composer universal.

MissionSpec → CapabilityPlan → SolutionBlueprint → ValidatedWorkflowGraph →
MaterializationPlan. Reutiliza `SolutionV1`, `WorkflowGraph` y el Architect
existente; no crea un segundo planner ni un catálogo paralelo.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from src.platform.studio.contracts import SolutionV1
from src.platform.workflows.ir import WorkflowGraph, validate_graph

MISSION_SCHEMA = "zent.mission/v1"
CAPABILITY_PLAN_SCHEMA = "zent.capability_plan/v1"
VALIDATED_GRAPH_SCHEMA = "zent.validated_workflow_graph/v1"
MATERIALIZATION_SCHEMA = "zent.materialization_plan/v1"

CompileMode = Literal["auto", "template", "compose", "hybrid"]


class MissionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_id: Literal["zent.mission/v1"] = Field(default=MISSION_SCHEMA, alias="schema")
    brief: str = Field(min_length=3, max_length=6000)
    language: str = "es"
    mode: CompileMode = "auto"
    roles: list[str] = Field(default_factory=list)
    agents: list[str] = Field(default_factory=list)
    workflows: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    knowledge: list[str] = Field(default_factory=list)
    channels: list[str] = Field(default_factory=list)
    policies: list[str] = Field(default_factory=list)
    outcomes: list[str] = Field(default_factory=list)
    budget: dict[str, Any] = Field(default_factory=dict)


class CapabilityPlanItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capability_ref: str
    required: bool = False
    status: str = "optional_missing"
    binding_ref: str | None = None
    reason: str = ""


class CapabilityPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_id: Literal["zent.capability_plan/v1"] = Field(
        default=CAPABILITY_PLAN_SCHEMA, alias="schema"
    )
    items: list[CapabilityPlanItem] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)


#: Alias explícito del contrato existente. No se crea un segundo blueprint.
SolutionBlueprint = SolutionV1


class ValidatedWorkflowGraph(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_id: Literal["zent.validated_workflow_graph/v1"] = Field(
        default=VALIDATED_GRAPH_SCHEMA, alias="schema"
    )
    graph: dict[str, Any] | None = None
    graph_hash: str = ""
    valid: bool = False
    errors: list[str] = Field(default_factory=list)


class MaterializationStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order: int
    action: str
    module: str
    required: bool = True


class MaterializationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_id: Literal["zent.materialization_plan/v1"] = Field(
        default=MATERIALIZATION_SCHEMA, alias="schema"
    )
    steps: list[MaterializationStep] = Field(default_factory=list)
    resources: dict[str, Any] = Field(default_factory=dict)
    estimated_cost: dict[str, Any] = Field(default_factory=dict)


def validate_materialization_graph(graph: dict[str, Any] | None) -> ValidatedWorkflowGraph:
    if not graph:
        return ValidatedWorkflowGraph(valid=False, errors=["sin grafo compilado"])
    try:
        validate_graph(WorkflowGraph.from_dict(graph))
    except Exception as exc:  # noqa: BLE001
        return ValidatedWorkflowGraph(valid=False, errors=[str(exc)[:300]])
    from src.platform.workflows.release_policy import graph_fingerprint

    return ValidatedWorkflowGraph(
        graph=graph,
        graph_hash=graph_fingerprint(graph),
        valid=True,
    )


__all__ = [
    "CAPABILITY_PLAN_SCHEMA",
    "CompileMode",
    "CapabilityPlan",
    "CapabilityPlanItem",
    "MATERIALIZATION_SCHEMA",
    "MISSION_SCHEMA",
    "MaterializationPlan",
    "MaterializationStep",
    "MissionSpec",
    "SolutionBlueprint",
    "VALIDATED_GRAPH_SCHEMA",
    "ValidatedWorkflowGraph",
    "validate_materialization_graph",
]
