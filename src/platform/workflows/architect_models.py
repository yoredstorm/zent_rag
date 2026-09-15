# =============================================================================
# Workflow Architect — modelos semánticos (First delivery).
#
# El LLM propone ArchitectIntent + SemanticPlan (lenguaje de negocio, sin ids
# de nodo ni mustache); el código compila y valida. Modelos pydantic estrictos.
# =============================================================================
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

MODEL_CONFIG = ConfigDict(extra="forbid")

PLAN_STEP_TYPES = (
    "trigger_event",
    "trigger_schedule",
    "trigger_manual",
    "business_query",
    "knowledge_query",
    "agent_analysis",
    "decision",
    "filter",
    "for_each",
    "join",
    "merge",
    "human_approval",
    "notify",
    "integration_action",
    "business_result",
    "stop",
)

TRIGGER_STEP_TYPES = ("trigger_event", "trigger_schedule", "trigger_manual")

KNOWLEDGE_OPERATIONS = (
    "search",
    "answer",
    "find_evidence",
    "extract_facts",
    "compare",
    "check_conflicts",
    "investigate",
)


class PlanAssumption(BaseModel):
    """Supuesto del plan; `impact=high` obliga a confirmar antes de publicar."""

    model_config = MODEL_CONFIG

    statement: str = Field(min_length=1, max_length=400)
    impact: Literal["low", "high"] = "low"
    needs_confirmation: bool = False

    @property
    def requires_question(self) -> bool:
        return self.impact == "high" or self.needs_confirmation


class WhenClause(BaseModel):
    """Rama de una decisión: el paso corre si el `outcome` se cumple."""

    model_config = MODEL_CONFIG

    step: str = Field(min_length=1, max_length=80)
    outcome: bool = True


class PlanInputRef(BaseModel):
    """Referencia de negocio a la salida de otro paso (sin mustache)."""

    model_config = MODEL_CONFIG

    step: str = Field(min_length=1, max_length=80)
    field: str = Field(default="output", min_length=1, max_length=80)
    label: str | None = Field(default=None, max_length=160)


class PlanStep(BaseModel):
    """Paso semántico: qué hace, de quién depende, qué necesita, por qué."""

    model_config = MODEL_CONFIG

    id: str = Field(min_length=1, max_length=80)
    type: Literal[PLAN_STEP_TYPES]
    goal: str = Field(min_length=1, max_length=400)
    depends_on: list[str] = Field(default_factory=list)
    when: WhenClause | None = None
    inputs: list[PlanInputRef] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)
    reason_summary: str = Field(default="", max_length=400)
    optional: bool = False


class ArchitectIntent(BaseModel):
    """Lo que el usuario quiere lograr, validado (brief §5)."""

    model_config = MODEL_CONFIG

    goal: str = Field(min_length=1, max_length=600)
    trigger_intent: dict[str, Any] = Field(default_factory=dict)
    inputs_needed: list[str] = Field(default_factory=list, max_length=20)
    data_needs: list[str] = Field(default_factory=list, max_length=20)
    knowledge_needs: list[str] = Field(default_factory=list, max_length=20)
    reasoning_needs: list[str] = Field(default_factory=list, max_length=20)
    conditions: list[str] = Field(default_factory=list, max_length=20)
    actions: list[str] = Field(default_factory=list, max_length=20)
    approval_needs: list[str] = Field(default_factory=list, max_length=10)
    schedule: dict[str, Any] | None = None
    output: list[str] = Field(default_factory=list, max_length=10)
    constraints: list[str] = Field(default_factory=list, max_length=10)
    uncertainties: list[str] = Field(default_factory=list, max_length=10)
    missing_information: list[str] = Field(default_factory=list, max_length=10)
    assumptions: list[PlanAssumption] = Field(default_factory=list, max_length=10)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    raw_prompt: str | None = Field(default=None, max_length=4000)


class SemanticPlan(BaseModel):
    """Plan de negocio compilable (brief §6). Sin ids de nodo ni posiciones."""

    model_config = MODEL_CONFIG

    goal: str = Field(min_length=1, max_length=600)
    steps: list[PlanStep] = Field(min_length=1, max_length=40)
    assumptions: list[PlanAssumption] = Field(default_factory=list, max_length=10)
    uncertainties: list[str] = Field(default_factory=list, max_length=10)
    notes: list[str] = Field(default_factory=list, max_length=10)


class PlanIssue(BaseModel):
    """Hallazgo del validator: error bloquea el grafo; warning pide revisión."""

    model_config = MODEL_CONFIG

    code: str = Field(min_length=1, max_length=80)
    severity: Literal["error", "warning", "info"] = "warning"
    step_id: str | None = Field(default=None, max_length=80)
    message: str = Field(min_length=1, max_length=400)
    requirement: str | None = Field(default=None, max_length=120)


__all__ = [
    "ArchitectIntent",
    "KNOWLEDGE_OPERATIONS",
    "MODEL_CONFIG",
    "PLAN_STEP_TYPES",
    "PlanAssumption",
    "PlanInputRef",
    "PlanIssue",
    "PlanStep",
    "SemanticPlan",
    "TRIGGER_STEP_TYPES",
    "WhenClause",
]
