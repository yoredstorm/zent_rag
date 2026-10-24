# =============================================================================
# Universal Studio contracts — zent.role/v1 and zent.solution/v1.
#
# A RoleProfile is identity + boundaries, not a runtime. An Agent is the
# reasoning/tool instance. A Workflow is the executable process. A Solution is
# a reusable composition. No contract contains tenant IDs, credentials,
# provider secrets or physical binding IDs.
# =============================================================================
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ROLE_SCHEMA = "zent.role/v1"
SOLUTION_SCHEMA = "zent.solution/v1"
SESSION_SCHEMA = "zent.session.ref/v1"

MODEL_CONFIG = ConfigDict(extra="forbid", populate_by_name=True)

AutonomyLevel = Literal[
    "answer_only",
    "propose_actions",
    "execute_reversible",
    "require_approval",
]
RiskClass = Literal["low", "medium", "high", "regulated"]

_SLUG_RE = re.compile(r"^[a-z][a-z0-9_-]{1,79}$")
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
_CAP_RE = re.compile(r"^[a-z][a-z0-9_.:-]{1,159}$")
_FORBIDDEN_KEYS = {
    "password",
    "passwd",
    "api_key",
    "apikey",
    "secret",
    "client_secret",
    "token",
    "access_token",
    "refresh_token",
    "private_key",
    "connection_string",
    "dsn",
    "credentials",
    "authorization",
    "organization_id",
    "workspace_id",
    "tenant_id",
    "install_id",
    "installation_id",
    "credential_ref",
    "provider_id",
    "model_id",
    "binding_id",
    "physical_id",
    "agent_id",
    "workflow_id",
}


def scan_contract_secrets(value: Any, *, path: str = "") -> list[str]:
    """Reject secrets and tenant-local IDs anywhere in a portable contract."""
    issues: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            key_l = str(key).lower()
            child_path = f"{path}.{key}" if path else str(key)
            if (
                key_l in _FORBIDDEN_KEYS
                or key_l.endswith("_token")
                or any(
                    marker in key_l
                    for marker in (
                        "password",
                        "secret",
                        "api_key",
                        "private_key",
                        "credential",
                    )
                )
            ):
                issues.append(f"clave prohibida en contrato: {child_path}")
            issues.extend(scan_contract_secrets(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value[:200]):
            issues.extend(scan_contract_secrets(child, path=f"{path}[{index}]"))
    elif isinstance(value, str):
        if re.search(r"postgres(?:ql)?://|mysql://|mongodb(\+srv)?://|redis://", value, re.I):
            issues.append(f"connection string en {path or '<root>'}")
    return issues


class RoleCompetency(BaseModel):
    model_config = MODEL_CONFIG

    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=400)
    level: Literal["basic", "intermediate", "advanced"] = "intermediate"


class Outcome(BaseModel):
    model_config = MODEL_CONFIG

    name: str = Field(min_length=1, max_length=160)
    metric: str = Field(min_length=1, max_length=120)
    target: str = Field(default="", max_length=120)
    window: str = Field(default="", max_length=80)


class RubricCriterion(BaseModel):
    model_config = MODEL_CONFIG

    criterion: str = Field(min_length=1, max_length=200)
    weight: float = Field(default=0.0, ge=0.0, le=1.0)
    pass_condition: str = Field(default="", max_length=300)


class KnowledgeScope(BaseModel):
    model_config = MODEL_CONFIG

    kinds: list[str] = Field(default_factory=list, max_length=20)
    domains: list[str] = Field(default_factory=list, max_length=20)
    tags: list[str] = Field(default_factory=list, max_length=30)
    notes: str = Field(default="", max_length=400)

    @field_validator("kinds", "domains", "tags", mode="before")
    @classmethod
    def _lists(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        return value


class MemoryPolicy(BaseModel):
    model_config = MODEL_CONFIG

    scope: Literal[
        "none",
        "session",
        "participant",
        "workspace",
        "long_term",
        "durable_business_state",
        "long_term_consent",
    ] = "session"
    retention_days: int | None = Field(default=None, ge=0, le=3650)
    consent_required: bool = False
    pii_masking: bool = True


class HumanHandoff(BaseModel):
    model_config = MODEL_CONFIG

    triggers: list[str] = Field(default_factory=list, max_length=20)
    destination: Literal["human", "specialist", "emergency", "none"] = "human"
    message: str = Field(default="", max_length=400)

    @field_validator("triggers", mode="before")
    @classmethod
    def _triggers(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        return value


class SafetyPolicy(BaseModel):
    model_config = MODEL_CONFIG

    no_medical_diagnosis: bool = False
    no_psychotherapy_claim: bool = False
    no_legal_advice: bool = False
    no_financial_advice: bool = False
    no_automatic_irreversible_action: bool = True
    crisis_escalation: bool = False
    consent_required: bool = False
    disclaimer: str = Field(default="", max_length=600)


class RoleProfileV1(BaseModel):
    """Portable role identity. No runtime credentials or physical IDs."""

    model_config = MODEL_CONFIG

    schema_id: Literal["zent.role/v1"] = Field(default=ROLE_SCHEMA, alias="schema")
    # Local record pointer for API/UI only. It is excluded from every portable
    # dump and rejected/removed on import.
    record_id: str = Field(default="", exclude=True)
    role_id: str = Field(min_length=2, max_length=80)
    version: str = Field(default="1.0.0", max_length=20)
    status: Literal["draft", "active", "archived"] = "draft"
    name: str = Field(default="", max_length=150)
    display_name: str = Field(default="", max_length=150)
    description: str = Field(default="", max_length=1200)
    mission: str = Field(min_length=1, max_length=1200)
    audience: list[str] = Field(default_factory=list, max_length=20)
    tone: list[str] = Field(default_factory=list, max_length=12)
    competencies: list[RoleCompetency] = Field(default_factory=list, max_length=40)
    constraints: list[str] = Field(default_factory=list, max_length=40)
    allowed_capabilities: list[str] = Field(default_factory=list, max_length=80)
    denied_capabilities: list[str] = Field(default_factory=list, max_length=80)
    allowed_tools: list[str] = Field(default_factory=list, max_length=40)
    knowledge_scope: KnowledgeScope = Field(default_factory=KnowledgeScope)
    memory_policy: MemoryPolicy = Field(default_factory=MemoryPolicy)
    autonomy_level: AutonomyLevel = "propose_actions"
    human_handoff: HumanHandoff = Field(default_factory=HumanHandoff)
    expected_outcomes: list[Outcome] = Field(default_factory=list, max_length=20)
    evaluation_rubric: list[RubricCriterion] = Field(default_factory=list, max_length=20)
    risk_class: RiskClass = "low"
    locales: list[str] = Field(default_factory=lambda: ["es"], max_length=20)
    compliance_tags: list[str] = Field(default_factory=list, max_length=30)
    safety: SafetyPolicy = Field(default_factory=SafetyPolicy)

    @field_validator(
        "audience",
        "tone",
        "constraints",
        "locales",
        "compliance_tags",
        mode="before",
    )
    @classmethod
    def _string_lists(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        return value

    @field_validator("competencies", mode="before")
    @classmethod
    def _competencies(cls, value: Any) -> Any:
        if value is None:
            return []
        if isinstance(value, list):
            return [
                {"name": item} if isinstance(item, str) else item for item in value
            ]
        return value

    @field_validator("expected_outcomes", mode="before")
    @classmethod
    def _outcomes(cls, value: Any) -> Any:
        if value is None:
            return []
        if isinstance(value, str):
            return [{"name": value, "metric": value}]
        if isinstance(value, list):
            return [
                {"name": item, "metric": item} if isinstance(item, str) else item
                for item in value
            ]
        return value

    @field_validator("evaluation_rubric", mode="before")
    @classmethod
    def _rubric(cls, value: Any) -> Any:
        if value is None:
            return []
        if isinstance(value, str):
            return [{"criterion": value}]
        if isinstance(value, list):
            return [
                {"criterion": item} if isinstance(item, str) else item
                for item in value
            ]
        return value

    @field_validator("role_id")
    @classmethod
    def _role_id(cls, value: str) -> str:
        if not _SLUG_RE.match(value):
            raise ValueError("role_id debe ser un slug estable: a-z, 0-9, _ o -")
        return value

    @field_validator("version")
    @classmethod
    def _version(cls, value: str) -> str:
        if not _VERSION_RE.match(value):
            raise ValueError("version debe ser semver MAJOR.MINOR.PATCH")
        return value

    @field_validator("allowed_capabilities", "denied_capabilities")
    @classmethod
    def _capabilities(cls, values: list[str]) -> list[str]:
        out: list[str] = []
        for value in values:
            if not _CAP_RE.match(value):
                raise ValueError(f"capability ref inválida: {value}")
            out.append(value)
        return out

    @model_validator(mode="after")
    def _safety_invariants(self) -> "RoleProfileV1":
        if not self.name and not self.display_name:
            raise ValueError("name o display_name es obligatorio")
        if self.display_name:
            self.name = self.display_name
        else:
            self.display_name = self.name
        issues = scan_contract_secrets(self.model_dump(by_alias=True))
        if issues:
            raise ValueError("; ".join(issues[:6]))
        if self.risk_class == "regulated" and not self.human_handoff.triggers:
            raise ValueError("un rol regulated necesita human_handoff.triggers")
        if self.risk_class == "regulated" and self.autonomy_level in (
            "execute_reversible",
            "require_approval",
        ) and not self.safety.no_automatic_irreversible_action:
            raise ValueError("un rol regulated no puede desactivar la protección irreversible")
        if self.role_id.startswith("wellness"):
            if not self.safety.no_medical_diagnosis or not self.safety.no_psychotherapy_claim:
                raise ValueError("bienestar requiere no_medical_diagnosis y no_psychotherapy_claim")
            if not self.safety.crisis_escalation:
                raise ValueError("bienestar requiere crisis_escalation")
            if self.human_handoff.destination == "none":
                raise ValueError("bienestar requiere un destino de derivación")
        return self


class SolutionRoleRef(BaseModel):
    model_config = MODEL_CONFIG

    role_ref: str = Field(min_length=2, max_length=80)
    version: str = Field(default="1.0.0", max_length=20)
    required: bool = True


class SolutionAgentRef(BaseModel):
    model_config = MODEL_CONFIG

    agent_ref: str = Field(min_length=2, max_length=80)
    role_ref: str = Field(default="", max_length=80)
    name: str = Field(default="", max_length=150)
    workflow_refs: list[str] = Field(default_factory=list, max_length=20)
    capability_refs: list[str] = Field(default_factory=list, max_length=40)


class SolutionWorkflowRef(BaseModel):
    model_config = MODEL_CONFIG

    workflow_ref: str = Field(min_length=2, max_length=80)
    name: str = Field(default="", max_length=150)
    role_refs: list[str] = Field(default_factory=list, max_length=20)
    agent_refs: list[str] = Field(default_factory=list, max_length=20)
    capability_refs: list[str] = Field(default_factory=list, max_length=40)
    trigger: dict[str, Any] = Field(default_factory=dict)
    requirements: list[str] = Field(default_factory=list, max_length=30)


class CapabilityRequirement(BaseModel):
    model_config = MODEL_CONFIG

    capability_ref: str = Field(min_length=2, max_length=160)
    required: bool = True
    purpose: str = Field(default="", max_length=300)


class KnowledgeRequirement(BaseModel):
    model_config = MODEL_CONFIG

    kind: str = Field(default="knowledge_base", max_length=40)
    logical_ref: str = Field(default="", max_length=160)
    required: bool = True
    purpose: str = Field(default="", max_length=300)


class InstallStep(BaseModel):
    model_config = MODEL_CONFIG

    order: int = Field(default=1, ge=1, le=100)
    action: str = Field(min_length=1, max_length=120)
    module: str = Field(default="", max_length=80)
    description: str = Field(default="", max_length=400)
    required: bool = True


class SessionRefV1(BaseModel):
    """Tells apart the three things called "session" without merging them."""

    model_config = MODEL_CONFIG

    schema_id: Literal["zent.session.ref/v1"] = Field(default=SESSION_SCHEMA, alias="schema")
    kind: Literal["conversation", "design", "workflow_instance"]
    session_id: str = Field(min_length=1, max_length=80)
    conversation_id: str | None = Field(default=None, max_length=80)
    design_session_id: str | None = Field(default=None, max_length=80)
    workflow_instance_id: str | None = Field(default=None, max_length=80)
    role_ref: str | None = Field(default=None, max_length=80)
    agent_ref: str | None = Field(default=None, max_length=80)
    status: str = Field(default="active", max_length=40)


class SolutionV1(BaseModel):
    model_config = MODEL_CONFIG

    schema_id: Literal["zent.solution/v1"] = Field(default=SOLUTION_SCHEMA, alias="schema")
    record_id: str = Field(default="", exclude=True)
    solution_id: str = Field(min_length=2, max_length=80)
    version: str = Field(default="1.0.0", max_length=20)
    status: Literal["draft", "active", "archived"] = "draft"
    name: str = Field(min_length=1, max_length=150)
    description: str = Field(default="", max_length=1200)
    roles: list[SolutionRoleRef] = Field(default_factory=list, max_length=20)
    agents: list[SolutionAgentRef] = Field(default_factory=list, max_length=30)
    workflows: list[SolutionWorkflowRef] = Field(default_factory=list, max_length=30)
    capabilities: list[CapabilityRequirement] = Field(default_factory=list, max_length=80)
    knowledge: list[KnowledgeRequirement] = Field(default_factory=list, max_length=40)
    channels: list[str] = Field(default_factory=list, max_length=20)
    requirements: list[str] = Field(default_factory=list, max_length=40)
    installation: list[InstallStep] = Field(default_factory=list, max_length=30)
    expected_outcomes: list[Outcome] = Field(default_factory=list, max_length=20)
    risk_class: RiskClass = "low"
    compliance_tags: list[str] = Field(default_factory=list, max_length=30)
    locales: list[str] = Field(default_factory=lambda: ["es"], max_length=20)

    @field_validator("solution_id")
    @classmethod
    def _solution_id(cls, value: str) -> str:
        if not _SLUG_RE.match(value):
            raise ValueError("solution_id debe ser un slug estable")
        return value

    @field_validator("version")
    @classmethod
    def _version(cls, value: str) -> str:
        if not _VERSION_RE.match(value):
            raise ValueError("version debe ser semver")
        return value

    @model_validator(mode="after")
    def _relations(self) -> "SolutionV1":
        issues = scan_contract_secrets(self.model_dump(by_alias=True))
        if issues:
            raise ValueError("; ".join(issues[:6]))
        role_refs = {role.role_ref for role in self.roles}
        if len(role_refs) != len(self.roles):
            raise ValueError("roles duplicados en la solución")
        agent_refs = {agent.agent_ref for agent in self.agents}
        if len(agent_refs) != len(self.agents):
            raise ValueError("agents duplicados en la solución")
        workflow_refs = {workflow.workflow_ref for workflow in self.workflows}
        if len(workflow_refs) != len(self.workflows):
            raise ValueError("workflows duplicados en la solución")
        for agent in self.agents:
            if agent.role_ref and agent.role_ref not in role_refs:
                raise ValueError(f"agent {agent.agent_ref} referencia un rol inexistente")
            missing = set(agent.workflow_refs) - workflow_refs
            if missing:
                raise ValueError(f"agent {agent.agent_ref} referencia workflows inexistentes: {missing}")
        for workflow in self.workflows:
            missing_roles = set(workflow.role_refs) - role_refs
            if missing_roles:
                raise ValueError(f"workflow {workflow.workflow_ref} referencia roles inexistentes: {missing_roles}")
            missing_agents = set(workflow.agent_refs) - agent_refs
            if missing_agents:
                raise ValueError(f"workflow {workflow.workflow_ref} referencia agentes inexistentes: {missing_agents}")
        if self.risk_class == "regulated" and not self.requirements:
            raise ValueError("una solución regulated debe declarar requisitos")
        return self


def role_from_legacy_payload(data: dict[str, Any]) -> RoleProfileV1:
    """Accept DB rows or API payloads without weakening the contract."""
    payload = dict(data)
    payload.pop("id", None)
    payload.pop("record_id", None)
    payload.pop("organization_id", None)
    payload.pop("workspace_id", None)
    payload.pop("created_by", None)
    payload.pop("created_at", None)
    payload.pop("updated_at", None)
    payload.pop("revision", None)
    if "schema" not in payload and payload.get("schema_id"):
        payload["schema"] = payload["schema_id"]
    payload.pop("schema_id", None)
    return RoleProfileV1.model_validate(payload)


def solution_from_legacy_payload(data: dict[str, Any]) -> SolutionV1:
    payload = dict(data)
    for key in (
        "id",
        "record_id",
        "organization_id",
        "workspace_id",
        "created_by",
        "created_at",
        "updated_at",
        "revision",
    ):
        payload.pop(key, None)
    if "schema" not in payload and payload.get("schema_id"):
        payload["schema"] = payload["schema_id"]
    payload.pop("schema_id", None)
    return SolutionV1.model_validate(payload)


__all__ = [
    "ROLE_SCHEMA",
    "SESSION_SCHEMA",
    "SOLUTION_SCHEMA",
    "AutonomyLevel",
    "CapabilityRequirement",
    "HumanHandoff",
    "InstallStep",
    "KnowledgeRequirement",
    "KnowledgeScope",
    "MemoryPolicy",
    "Outcome",
    "RiskClass",
    "RoleCompetency",
    "RoleProfileV1",
    "RubricCriterion",
    "SafetyPolicy",
    "SessionRefV1",
    "SolutionAgentRef",
    "SolutionRoleRef",
    "SolutionV1",
    "SolutionWorkflowRef",
    "role_from_legacy_payload",
    "scan_contract_secrets",
    "solution_from_legacy_payload",
]
