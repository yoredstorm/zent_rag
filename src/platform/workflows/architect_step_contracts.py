# =============================================================================
# Workflow Architect — contratos tipados de params por tipo de paso (Prompt 04).
#
# El PlanStep sigue siendo compatible con planes persistidos (params dict), pero
# los tipos principales se validan contra estos modelos antes de compilar. Los
# modelos aceptan claves extra para no romper planes históricos; las claves
# conocidas dejan de ser `Any` sin contrato.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

CONTRACT_CONFIG = ConfigDict(extra="allow")


@dataclass(frozen=True)
class StepParamIssue:
    code: str
    field: str
    expected: str
    received: str
    message: str


class CapabilityCallParams(BaseModel):
    model_config = CONTRACT_CONFIG

    capability: str = Field(min_length=1, max_length=200)
    inputs: dict[str, Any] = Field(default_factory=dict)
    contract_version: int | None = Field(default=None, ge=1, le=1_000_000)
    outputs_expected: list[str] = Field(default_factory=list, max_length=20)
    idempotency: Literal["required", "best_effort", "none"] = "best_effort"


class IntegrationActionParams(BaseModel):
    model_config = CONTRACT_CONFIG

    action_id: str = Field(min_length=1, max_length=200)
    install_id: str = Field(default="", max_length=120)
    inputs: dict[str, Any] = Field(default_factory=dict)
    contract_version: int | None = Field(default=None, ge=1, le=1_000_000)
    outputs_expected: list[str] = Field(default_factory=list, max_length=20)
    idempotency: Literal["required", "best_effort", "none"] = "best_effort"


class WaitParams(BaseModel):
    model_config = CONTRACT_CONFIG

    preset: Literal["message", "webhook", "payment", "timer", "human", "signal"] = "message"
    event_type: str = Field(default="", max_length=160)
    correlation: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int | None = Field(default=None, ge=1, le=86_400 * 30)
    on_timeout: Literal["branch", "expire", "fail", "continue"] | None = None
    expected_payload_schema: dict[str, Any] = Field(default_factory=dict)


class LoopParams(BaseModel):
    model_config = CONTRACT_CONFIG

    target: str = Field(min_length=1, max_length=80)
    max_iterations: int = Field(default=20, ge=1, le=100)
    exit_condition: dict[str, Any] | str | None = None
    state_dependencies: list[str] = Field(default_factory=list, max_length=10)


class StateParams(BaseModel):
    model_config = CONTRACT_CONFIG

    op: Literal["get", "set", "merge", "append", "remove"] = "set"
    path: str = Field(min_length=1, max_length=200)
    value_type: str | None = Field(default=None, max_length=40)
    source_reference: dict[str, Any] | None = None
    value: Any = None


class CompensationParams(BaseModel):
    model_config = CONTRACT_CONFIG

    target_step: str = Field(min_length=1, max_length=80)
    capability: str | None = Field(default=None, max_length=200)
    action_id: str | None = Field(default=None, max_length=200)
    inputs: dict[str, Any] = Field(default_factory=dict)
    contract_version: int | None = Field(default=None, ge=1, le=1_000_000)
    idempotency: Literal["required", "best_effort", "none"] = "required"


class TriggerConversationParams(BaseModel):
    model_config = CONTRACT_CONFIG

    event_type: str = Field(default="conversation.message", max_length=160)
    filters: dict[str, Any] = Field(default_factory=dict)


class StopParams(BaseModel):
    model_config = CONTRACT_CONFIG

    status: Literal["success", "failed"] = "success"
    message: str = Field(default="", max_length=400)


class BusinessResultParams(BaseModel):
    model_config = CONTRACT_CONFIG

    title: str = Field(default="", max_length=200)
    section: str = Field(default="reports", max_length=80)
    importance: str = Field(default="INFO", max_length=20)


class HumanApprovalParams(BaseModel):
    model_config = CONTRACT_CONFIG

    action: str = Field(default="", max_length=120)
    summary: str = Field(default="", max_length=400)
    expires_minutes: int = Field(default=1440, ge=1, le=43_200)


class KnowledgeQueryParams(BaseModel):
    model_config = CONTRACT_CONFIG

    operation: str = Field(default="answer", max_length=40)
    query: str = Field(default="", max_length=500)
    knowledge_base_id: str = Field(default="", max_length=80)
    limit: int = Field(default=5, ge=1, le=50)


_PARAM_MODELS: dict[str, type[BaseModel]] = {
    "capability_call": CapabilityCallParams,
    "integration_action": IntegrationActionParams,
    "wait": WaitParams,
    "loop": LoopParams,
    "state": StateParams,
    "compensation": CompensationParams,
    "trigger_conversation": TriggerConversationParams,
    "stop": StopParams,
    "business_result": BusinessResultParams,
    "human_approval": HumanApprovalParams,
    "knowledge_query": KnowledgeQueryParams,
}


def validate_step_params(step: Any) -> tuple[BaseModel | None, list[StepParamIssue]]:
    """Valida params conocidos. No lanza: el validator convierte issues en PlanIssue."""
    model = _PARAM_MODELS.get(str(getattr(step, "type", "")))
    if model is None:
        return None, []
    params = dict(getattr(step, "params", {}) or {})
    # Los campos tipados del PlanStep son la fuente canónica cuando existen.
    for key in ("contract_version", "outputs_expected", "idempotency"):
        value = getattr(step, key, None)
        if value is not None and key not in params:
            params[key] = value
    try:
        return model.model_validate(params), []
    except ValidationError as exc:
        issues: list[StepParamIssue] = []
        for error in exc.errors()[:12]:
            loc = ".".join(str(item) for item in error.get("loc") or ())
            issues.append(
                StepParamIssue(
                    code="contract.params_invalid",
                    field=f"params.{loc}" if loc else "params",
                    expected=str(error.get("msg") or "valor válido")[:200],
                    received=str(error.get("input"))[:200],
                    message=(
                        f"params.{loc} no cumple el contrato de {model.__name__}: "
                        f"{error.get('msg')}"
                    )[:400],
                )
            )
        return None, issues


def typed_params(step: Any) -> BaseModel | None:
    model, issues = validate_step_params(step)
    return None if issues else model


__all__ = [
    "BusinessResultParams",
    "CapabilityCallParams",
    "CompensationParams",
    "HumanApprovalParams",
    "IntegrationActionParams",
    "KnowledgeQueryParams",
    "LoopParams",
    "StateParams",
    "StepParamIssue",
    "StopParams",
    "TriggerConversationParams",
    "WaitParams",
    "typed_params",
    "validate_step_params",
]
