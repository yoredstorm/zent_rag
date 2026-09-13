# =============================================================================
# Workflow Intent & Plan — capa de negocio entre lenguaje natural y Graph IR.
#
# Pipeline (misión §5):
#   Natural Language → WorkflowIntent (el LLM propone; el backend valida)
#   → WorkflowPlan (normalizado, business-level)
#   → plan_compiler (commit 5) → WorkflowGraph (el MISMO IR que ya ejecuta el
#     engine; este módulo NO ejecuta nada ni duplica el motor).
#
# Reglas:
# - El LLM nunca escribe Graph IR arbitrario: propone Intent/Plan.
# - `validate_intent()` / `validate_plan()` devuelven issues con severidad;
#   el backend decide si compila, pregunta o bloquea.
# - Los operadores de negocio se normalizan a operadores de motor conocidos.
# =============================================================================
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from enum import Enum
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.platform.workflows.business_schema import BusinessOutputField

MODEL_CONFIG = ConfigDict(extra="forbid")


class IntentValidationError(ValueError):
    """El Intent/Plan no puede compilarse sin resolver issues de severidad error."""


# ---------------------------------------------------------------------------
# Trigger
# ---------------------------------------------------------------------------
class TriggerKind(str, Enum):
    event = "event"
    schedule = "schedule"
    webhook = "webhook"
    manual = "manual"


class PlanSchedule(BaseModel):
    """Schedule amigable que mapea 1:1 al scheduler v2 existente.

    `mode=advanced` conserva `cron` para Advanced Mode. Nunca crea otro
    scheduler: `to_trigger_config()` produce la forma que ya entiende
    `engine.next_trigger_at()` / `run_due_scheduled_workflows()`.
    """

    model_config = MODEL_CONFIG

    mode: Literal["event", "interval", "daily", "weekly", "monthly", "cron", "advanced"] = "event"
    every_minutes: int | None = Field(default=None, ge=1, le=1440)
    time: str | None = Field(default=None, pattern=r"^\d{1,2}:\d{2}$")
    days: list[int] = Field(default_factory=list)  # 0=lunes … 6=domingo
    day_of_month: int | None = Field(default=None, ge=1, le=31)
    timezone: str = "UTC"
    cron: str | None = None

    @model_validator(mode="after")
    def _coherent(self) -> "PlanSchedule":
        if self.mode == "interval" and not self.every_minutes:
            raise ValueError("interval requiere every_minutes")
        if self.mode in ("daily", "weekly", "monthly") and not self.time:
            raise ValueError(f"{self.mode} requiere time")
        if self.mode == "weekly" and not self.days:
            raise ValueError("weekly requiere days (0=lunes … 6=domingo)")
        if self.mode == "weekly" and any(d < 0 or d > 6 for d in self.days):
            raise ValueError("weekly days debe estar entre 0 (lunes) y 6 (domingo)")
        if self.mode == "monthly" and not self.day_of_month:
            raise ValueError("monthly requiere day_of_month")
        if self.mode in ("cron", "advanced") and not self.cron:
            raise ValueError("cron/advanced requiere cron")
        return self

    def to_trigger_config(self) -> dict[str, Any]:
        """Forma persistible en `workflows.trigger_config` (scheduler v2)."""
        if self.mode == "interval":
            return {"every_minutes": int(self.every_minutes or 5), "timezone": self.timezone}
        if self.mode == "daily":
            return {"daily": {"time": self.time}, "timezone": self.timezone}
        if self.mode == "weekly":
            return {
                "weekly": {"days": sorted(set(self.days)), "time": self.time},
                "timezone": self.timezone,
            }
        if self.mode == "monthly":
            return {"monthly": {"day": self.day_of_month, "time": self.time}, "timezone": self.timezone}
        if self.mode in ("cron", "advanced"):
            return {"cron": {"expr": self.cron, "timezone": self.timezone}}
        return {}

    @classmethod
    def from_trigger_config(cls, cfg: dict[str, Any] | None) -> "PlanSchedule | None":
        """Revierte `trigger_config` (legacy o v2) a la vista amigable."""
        data = dict(cfg or {})
        tz = str(data.get("timezone") or "UTC")
        if data.get("every_minutes"):
            return cls(mode="interval", every_minutes=int(data["every_minutes"]), timezone=tz)
        daily = data.get("daily")
        if isinstance(daily, dict) and daily.get("time"):
            return cls(mode="daily", time=str(daily["time"]), timezone=tz)
        weekly = data.get("weekly")
        if isinstance(weekly, dict):
            days = [int(d) for d in (weekly.get("days") or []) if str(d).isdigit()]
            return cls(mode="weekly", days=days, time=str(weekly.get("time") or "09:00"), timezone=tz)
        monthly = data.get("monthly")
        if isinstance(monthly, dict) and monthly.get("day"):
            return cls(
                mode="monthly",
                day_of_month=int(monthly["day"]),
                time=str(monthly.get("time") or "09:00"),
                timezone=tz,
            )
        cron = data.get("cron")
        if isinstance(cron, dict) and cron.get("expr"):
            return cls(mode="cron", cron=str(cron["expr"]), timezone=str(cron.get("timezone") or tz))
        return None

    def describe(self, *, include_timezone: bool = False) -> str:
        """Frase humana para el preview (misión §13)."""
        tz = f" ({self.timezone})" if include_timezone and self.timezone not in ("", "UTC") else ""
        if self.mode == "interval":
            minutes = int(self.every_minutes or 0)
            if minutes % 60 == 0:
                hours = minutes // 60
                base = "Cada hora" if hours == 1 else f"Cada {hours} horas"
            elif minutes == 1:
                base = "Cada minuto"
            else:
                base = f"Cada {minutes} minutos"
            return base + tz
        if self.mode == "daily":
            return f"Todos los días a las {_friendly_time(self.time)}{tz}"
        if self.mode == "weekly":
            return f"{_friendly_days(self.days)} a las {_friendly_time(self.time)}{tz}"
        if self.mode == "monthly":
            return f"El día {self.day_of_month} de cada mes a las {_friendly_time(self.time)}{tz}"
        if self.mode in ("cron", "advanced"):
            return f"Según cron: {self.cron} (avanzado)"
        if self.mode == "event":
            return "Cuando ocurra algo"
        return "Cuando ocurra algo"


def _friendly_time(raw: str | None) -> str:
    value = str(raw or "00:00")
    try:
        hh_s, mm = value.split(":", 1)
        hh = int(hh_s)
    except (ValueError, AttributeError):
        return value
    suffix = "a. m." if hh < 12 else "p. m."
    hour12 = hh % 12 or 12
    return f"{hour12}:{mm} {suffix}"


def _friendly_days(days: list[int]) -> str:
    names = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    ordered = sorted({d for d in days if 0 <= d <= 6})
    if not ordered:
        return "Algunos días"
    if ordered == list(range(5)):
        return "Solo de lunes a viernes"
    if ordered == [0, 1, 2, 3, 4, 5, 6]:
        return "Todos los días"
    if len(ordered) == 1:
        return f"Cada {names[ordered[0]]}"
    return "Los " + ", ".join(names[d] for d in ordered[:-1]) + f" y {names[ordered[-1]]}"


class PlanTrigger(BaseModel):
    model_config = MODEL_CONFIG

    kind: TriggerKind
    event_type: str | None = Field(default=None, max_length=120)
    schedule: PlanSchedule | None = None
    description: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def _coherent(self) -> "PlanTrigger":
        if self.kind == TriggerKind.event and not self.event_type:
            raise ValueError("trigger event requiere event_type")
        if self.kind == TriggerKind.schedule and self.schedule is None:
            raise ValueError("trigger schedule requiere schedule")
        return self


# ---------------------------------------------------------------------------
# Condiciones (Condition Builder, misión §9)
# ---------------------------------------------------------------------------
class ConditionOperator(str, Enum):
    eq = "eq"
    neq = "neq"
    gt = "gt"
    gte = "gte"
    lt = "lt"
    lte = "lte"
    contains = "contains"
    not_contains = "not_contains"
    starts_with = "starts_with"
    ends_with = "ends_with"
    is_empty = "is_empty"
    not_empty = "not_empty"
    changed = "changed"


OPERATOR_LABELS: dict[str, str] = {
    "eq": "es",
    "neq": "no es",
    "gt": "es mayor que",
    "gte": "es al menos",
    "lt": "es menor que",
    "lte": "es como máximo",
    "contains": "contiene",
    "not_contains": "no contiene",
    "starts_with": "empieza con",
    "ends_with": "termina con",
    "is_empty": "está vacío",
    "not_empty": "no está vacío",
    "changed": "cambió",
}

# Operadores sin valor de comparación.
VALUELESS_OPERATORS: frozenset[str] = frozenset({"is_empty", "not_empty", "changed"})

# Mapeo al evaluador del motor. Los operadores nuevos (`not_contains`,
# `starts_with`, `ends_with`, `is_empty`, `not_empty`, `changed`) se soportan en
# el Condition Builder (commit 3) extendiendo `_eval_condition`; mientras tanto
# el compilador de planes solo emite operadores ya soportados.
CANONICAL_TO_ENGINE: dict[str, str] = {
    "eq": "==",
    "neq": "!=",
    "gt": ">",
    "gte": ">=",
    "lt": "<",
    "lte": "<=",
    "contains": "contains",
    "not_contains": "not_contains",
    "starts_with": "starts_with",
    "ends_with": "ends_with",
    "is_empty": "is_empty",
    "not_empty": "not_empty",
    "changed": "changed",
}
ENGINE_TO_CANONICAL: dict[str, str] = {v: k for k, v in CANONICAL_TO_ENGINE.items()}

_OPERATOR_ALIASES: dict[str, str] = {
    "es": "eq",
    "es igual a": "eq",
    "sea igual a": "eq",
    "igual a": "eq",
    "es exactamente": "eq",
    "no es": "neq",
    "no es igual a": "neq",
    "es distinto de": "neq",
    "distinto de": "neq",
    "diferente de": "neq",
    "es mayor que": "gt",
    "sea mayor que": "gt",
    "mayor que": "gt",
    "supera": "gt",
    "supera a": "gt",
    "es mas de": "gt",
    "es al menos": "gte",
    "es por lo menos": "gte",
    "mayor o igual que": "gte",
    "es menor que": "lt",
    "sea menor que": "lt",
    "menor que": "lt",
    "esta por debajo de": "lt",
    "es como maximo": "lte",
    "es a lo sumo": "lte",
    "menor o igual que": "lte",
    "contiene": "contains",
    "incluye": "contains",
    "no contiene": "not_contains",
    "no incluye": "not_contains",
    "empieza con": "starts_with",
    "empieza por": "starts_with",
    "comienza con": "starts_with",
    "termina con": "ends_with",
    "termina en": "ends_with",
    "acaba en": "ends_with",
    "esta vacio": "is_empty",
    "es vacio": "is_empty",
    "no esta vacio": "not_empty",
    "tiene valor": "not_empty",
    "cambio": "changed",
    "cambia": "changed",
}


def _norm_text(raw: str) -> str:
    text = unicodedata.normalize("NFKD", str(raw or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", text).strip()


def normalize_operator(raw: str | ConditionOperator) -> ConditionOperator:
    """Acepta un operador canónico o un alias humano en español/inglés simple."""
    if isinstance(raw, ConditionOperator):
        return raw
    text = _norm_text(raw).replace("_", " ")
    if text in {member.value for member in ConditionOperator}:
        return ConditionOperator(text)
    alias = _OPERATOR_ALIASES.get(text)
    if alias:
        return ConditionOperator(alias)
    raise ValueError(
        f"operador desconocido: '{raw}'. Usa: {', '.join(OPERATOR_LABELS.values())}"
    )


def operator_label(raw: str | ConditionOperator) -> str:
    return OPERATOR_LABELS[normalize_operator(raw).value]


class PlanFieldRef(BaseModel):
    """Referencia de negocio a un dato. `ref` ({{nodes...}}) es interno y solo
    aparece tras compilar; Simple Mode nunca lo muestra."""

    model_config = MODEL_CONFIG

    source: str = Field(min_length=1, max_length=80)  # clave del data source / paso
    field: str = Field(min_length=1, max_length=80)
    label: str | None = Field(default=None, max_length=160)
    ref: str | None = Field(default=None, max_length=300)

    def describe(self) -> str:
        source_label = self.source
        field_label = self.label or self.field
        return f"{source_label} → {field_label}"


class PlanCondition(BaseModel):
    model_config = MODEL_CONFIG

    kind: Literal["condition"] = "condition"
    field: PlanFieldRef
    operator: ConditionOperator
    value: Any = None
    description: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def _coherent(self) -> "PlanCondition":
        if self.operator.value in VALUELESS_OPERATORS:
            self.value = None
        return self


ConditionNode = Annotated[Union[PlanCondition, "ConditionGroup"], Field(discriminator="kind")]


class ConditionGroup(BaseModel):
    """Grupo AND/OR anidado (misión §9: nested groups)."""

    model_config = MODEL_CONFIG

    kind: Literal["group"] = "group"
    op: Literal["and", "or"] = "and"
    children: list[ConditionNode] = Field(default_factory=list)
    description: str | None = Field(default=None, max_length=300)

    def describe(self) -> str:
        if not self.children:
            return ""
        separator = " y " if self.op == "and" else " o "
        parts = []
        for child in self.children:
            if isinstance(child, ConditionGroup):
                nested = child.describe()
                if nested:
                    parts.append(f"({nested})")
            else:
                label = OPERATOR_LABELS[child.operator.value]
                field = child.field.label or child.field.field
                if child.operator.value in VALUELESS_OPERATORS:
                    parts.append(f"{field} {label}")
                else:
                    parts.append(f"{field} {label} {child.value}")
        return separator.join(parts)


ConditionGroup.model_rebuild()


# ---------------------------------------------------------------------------
# Destinatarios y acciones (Notification Builder, misión §14)
# ---------------------------------------------------------------------------
class PlanRecipient(BaseModel):
    model_config = MODEL_CONFIG

    kind: Literal["person", "team", "email", "channel", "webhook"] = "team"
    value: str = Field(min_length=1, max_length=200)
    label: str | None = Field(default=None, max_length=160)

    @model_validator(mode="after")
    def _coherent(self) -> "PlanRecipient":
        if self.kind == "email" and "@" not in self.value:
            raise ValueError(f"destinatario email inválido: '{self.value}'")
        return self

    def describe(self) -> str:
        return self.label or self.value


class PlanAction(BaseModel):
    """Acción de negocio. `params` es la configuración tipada por acción
    (la UI Simple la llena con BusinessParameterSchema, no con JSON)."""

    model_config = MODEL_CONFIG

    kind: Literal[
        "notify",
        "agent_analysis",
        "marketplace_action",
        "api_call",
        "business_result",
        "human_approval",
        "stop",
    ]
    description: str | None = Field(default=None, max_length=300)
    channel: Literal["zent", "email", "slack", "teams", "whatsapp", "webhook"] | None = None
    recipients: list[PlanRecipient] = Field(default_factory=list)
    subject: str | None = Field(default=None, max_length=300)
    message: str | None = Field(default=None, max_length=4000)
    action_id: str | None = Field(default=None, max_length=120)
    install_id: str | None = Field(default=None, max_length=80)
    params: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _coherent(self) -> "PlanAction":
        if self.kind == "marketplace_action" and not self.action_id:
            raise ValueError("marketplace_action requiere action_id")
        return self


class PlanAnalysis(BaseModel):
    """Paso de análisis con agente/knowledge/datos y output opcional estructurado
    (misión §16). Los campos del output_schema quedan disponibles al Data Picker
    vía `output_contract`."""

    model_config = MODEL_CONFIG

    kind: Literal["agent", "knowledge_query", "data_query"] = "agent"
    description: str | None = Field(default=None, max_length=300)
    agent_id: str | None = Field(default=None, max_length=80)
    agent_name: str | None = Field(default=None, max_length=160)
    prompt: str | None = Field(default=None, max_length=4000)
    context: list[Literal["event", "previous_result", "knowledge", "business_data"]] = Field(
        default_factory=list
    )
    output_schema: dict[str, Any] | None = None
    output_contract: list[BusinessOutputField] = Field(default_factory=list)

    @model_validator(mode="after")
    def _coherent(self) -> "PlanAnalysis":
        if self.kind == "agent" and not self.prompt and not self.agent_id and not self.agent_name:
            raise ValueError("analysis agent requiere prompt, agent_id o agent_name")
        return self


class PlanDataSource(BaseModel):
    """Fuente de datos nombrada por el usuario (misión §4 y §10)."""

    model_config = MODEL_CONFIG

    key: str = Field(min_length=1, max_length=80)
    kind: Literal["database", "knowledge_base", "integration", "event", "agent", "unknown"] = "unknown"
    label: str | None = Field(default=None, max_length=160)
    ref: str | None = Field(default=None, max_length=200)
    fields: list[BusinessOutputField] = Field(default_factory=list)
    sample: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Intent y Plan
# ---------------------------------------------------------------------------
class WorkflowIntent(BaseModel):
    """Lo que el usuario quiso decir. El LLM propone; el backend valida.

    Todo campo desconocido o ambiguo va a `questions` en lugar de inventarse.
    """

    model_config = MODEL_CONFIG

    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=600)
    trigger: PlanTrigger
    conditions: list[PlanCondition] = Field(default_factory=list)
    data_sources: list[PlanDataSource] = Field(default_factory=list)
    actions: list[PlanAction] = Field(default_factory=list)
    agents: list[str] = Field(default_factory=list)
    schedule: PlanSchedule | None = None
    recipients: list[PlanRecipient] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    risk: Literal["info", "normal", "elevated", "critical"] = "normal"
    estimated_cost: float | None = Field(default=None, ge=0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    raw_prompt: str | None = Field(default=None, max_length=4000)


class WorkflowPlan(BaseModel):
    """Representación business-level que consume el plan_compiler.

    No es un IR paralelo: es un contrato de entrada que compila a
    `WorkflowGraph` (commit 5) y se ejecuta con `engine.run_workflow()`.
    """

    model_config = MODEL_CONFIG

    plan_version: int = 1
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=600)
    trigger: PlanTrigger
    conditions: ConditionGroup | None = None
    data_sources: list[PlanDataSource] = Field(default_factory=list)
    analysis: list[PlanAnalysis] = Field(default_factory=list)
    actions: list[PlanAction] = Field(default_factory=list)
    schedule: PlanSchedule | None = None
    recipients: list[PlanRecipient] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    risk: Literal["info", "normal", "elevated", "critical"] = "normal"
    estimated_cost: float | None = Field(default=None, ge=0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    intent: WorkflowIntent | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PlanValidationIssue(BaseModel):
    """Issue de validación/readiness con severidad. La UI Simple muestra los
    `warning` como checklist y los `error` como bloqueo de publicación."""

    model_config = MODEL_CONFIG

    code: str = Field(min_length=1, max_length=80)
    severity: Literal["error", "warning", "info"] = "error"
    message: str = Field(min_length=1, max_length=500)
    hint: str | None = Field(default=None, max_length=500)
    field: str | None = Field(default=None, max_length=80)


def _iter_condition_issues(node: ConditionNode, path: str) -> list[PlanValidationIssue]:
    issues: list[PlanValidationIssue] = []
    if isinstance(node, ConditionGroup):
        if not node.children:
            issues.append(
                PlanValidationIssue(
                    code="condition.empty_group",
                    severity="warning",
                    message="Hay un grupo de condiciones sin condiciones.",
                    field=path,
                )
            )
        for idx, child in enumerate(node.children):
            issues.extend(_iter_condition_issues(child, f"{path}.{idx}"))
    else:
        if not node.field.source or not node.field.field:
            issues.append(
                PlanValidationIssue(
                    code="condition.missing_field",
                    severity="error",
                    message="Falta elegir el dato que se va a comparar.",
                    field=path,
                )
            )
        if node.operator.value not in VALUELESS_OPERATORS and node.value is None:
            issues.append(
                PlanValidationIssue(
                    code="condition.missing_value",
                    severity="error",
                    message=f"Falta el valor de la condición '{node.field.describe()}'.",
                    field=path,
                )
            )
    return issues


def validate_intent(intent: WorkflowIntent) -> list[PlanValidationIssue]:
    """El backend valida lo que el LLM propuso (misión §4 y §19)."""
    issues: list[PlanValidationIssue] = []
    for idx, condition in enumerate(intent.conditions):
        issues.extend(_iter_condition_issues(condition, f"conditions.{idx}"))

    for idx, action in enumerate(intent.actions):
        path = f"actions.{idx}"
        if action.kind == "notify":
            if action.channel is None:
                issues.append(
                    PlanValidationIssue(
                        code="notify.missing_channel",
                        severity="warning",
                        message="Falta elegir por dónde avisar.",
                        hint="Zent, correo, Slack, Teams, WhatsApp o webhook.",
                        field=path,
                    )
                )
            if not action.recipients and not intent.recipients:
                issues.append(
                    PlanValidationIssue(
                        code="notify.missing_recipients",
                        severity="warning",
                        message="Falta elegir a quién avisar.",
                        field=path,
                    )
                )

    if intent.trigger.kind == TriggerKind.schedule and intent.schedule is None and intent.trigger.schedule is None:
        issues.append(
            PlanValidationIssue(
                code="schedule.missing",
                severity="error",
                message="Falta definir cuándo debe ejecutarse.",
            )
        )
    if not intent.actions and not intent.agents:
        issues.append(
            PlanValidationIssue(
                code="actions.missing",
                severity="error",
                message="No hay ninguna acción que Zent pueda ejecutar.",
            )
        )
    if intent.agents and not any(a.kind in ("agent_analysis",) for a in intent.actions):
        issues.append(
            PlanValidationIssue(
                code="analysis.agents_without_action",
                severity="warning",
                message="Mencionaste un agente pero no definiste qué debe analizar.",
            )
        )
    if intent.confidence and intent.confidence < 0.5:
        issues.append(
            PlanValidationIssue(
                code="intent.low_confidence",
                severity="warning",
                message="Entendí esto con dudas: revisa el resumen antes de continuar.",
            )
        )
    return issues


def validate_plan(plan: WorkflowPlan) -> list[PlanValidationIssue]:
    issues: list[PlanValidationIssue] = []
    if plan.conditions is not None:
        issues.extend(_iter_condition_issues(plan.conditions, "conditions"))
    for idx, action in enumerate(plan.actions):
        path = f"actions.{idx}"
        if action.kind == "notify":
            if action.channel is None:
                issues.append(
                    PlanValidationIssue(
                        code="notify.missing_channel",
                        severity="warning",
                        message="Falta elegir por dónde avisar.",
                        field=path,
                    )
                )
            if not action.recipients and not plan.recipients:
                issues.append(
                    PlanValidationIssue(
                        code="notify.missing_recipients",
                        severity="warning",
                        message="Falta elegir a quién avisar.",
                        field=path,
                    )
                )
        if action.kind == "marketplace_action" and not action.action_id:
            issues.append(
                PlanValidationIssue(
                    code="action.missing_action_id",
                    severity="error",
                    message="Falta elegir la acción de la integración.",
                    field=path,
                )
            )
        if action.kind == "api_call" and not action.params.get("url"):
            issues.append(
                PlanValidationIssue(
                    code="action.api_missing_url",
                    severity="error",
                    message="La llamada API necesita una dirección.",
                    field=path,
                )
            )
    for idx, analysis in enumerate(plan.analysis):
        if analysis.kind == "agent" and not analysis.agent_id and not analysis.agent_name:
            issues.append(
                PlanValidationIssue(
                    code="analysis.missing_agent",
                    severity="warning",
                    message="Falta elegir el agente que analiza.",
                    field=f"analysis.{idx}",
                )
            )
    if plan.trigger.kind == TriggerKind.event and not plan.trigger.event_type:
        issues.append(
            PlanValidationIssue(
                code="trigger.missing_event",
                severity="error",
                message="Falta elegir qué evento inicia la automatización.",
            )
        )
    return issues


def intent_to_plan(intent: WorkflowIntent) -> WorkflowPlan:
    """Normaliza el Intent a WorkflowPlan (pura, sin I/O).

    Lanza `IntentValidationError` si hay issues de severidad `error`; los
    `warning` viajan en `plan.questions` para que la UI pregunte solo lo
    imprescindible (misión §6).
    """
    issues = validate_intent(intent)
    errors = [i for i in issues if i.severity == "error"]
    if errors:
        raise IntentValidationError("; ".join(i.message for i in errors))

    warnings = [i.message for i in issues if i.severity == "warning"]
    actions = [a for a in intent.actions if a.kind != "agent_analysis"]
    analysis = [
        PlanAnalysis(
            kind="agent",
            description=a.description or "Analizar con un agente",
            agent_id=a.params.get("agent_id") if isinstance(a.params.get("agent_id"), str) else None,
            agent_name=a.params.get("agent_name") if isinstance(a.params.get("agent_name"), str) else None,
            prompt=a.message or a.description,
            context=["event"],
        )
        for a in intent.actions
        if a.kind == "agent_analysis"
    ]
    for agent_ref in intent.agents:
        if not any(a.agent_id == agent_ref or a.agent_name == agent_ref for a in analysis):
            analysis.append(
                PlanAnalysis(
                    kind="agent",
                    description="Analizar con un agente",
                    agent_id=agent_ref if _looks_like_uuid(agent_ref) else None,
                    agent_name=None if _looks_like_uuid(agent_ref) else agent_ref,
                    prompt=None,
                    context=["event"],
                )
            )

    recipients = list(intent.recipients)
    for action in actions:
        for recipient in action.recipients:
            if recipient not in recipients:
                recipients.append(recipient)

    conditions = None
    if intent.conditions:
        conditions = ConditionGroup(op="and", children=list(intent.conditions))

    questions = list(dict.fromkeys([*intent.questions, *warnings]))
    return WorkflowPlan(
        name=intent.name,
        description=intent.description,
        trigger=intent.trigger,
        conditions=conditions,
        data_sources=list(intent.data_sources),
        analysis=analysis,
        actions=actions,
        schedule=intent.schedule or intent.trigger.schedule,
        recipients=recipients,
        questions=questions,
        risk=intent.risk,
        estimated_cost=intent.estimated_cost,
        confidence=intent.confidence,
        intent=intent,
        metadata={"source": "intent"},
    )


def _looks_like_uuid(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F-]{27}", str(value or "")))


# ---------------------------------------------------------------------------
# Natural-language patch (misión §21; implementación en commit 6)
# ---------------------------------------------------------------------------
class PatchOperation(BaseModel):
    model_config = MODEL_CONFIG

    op: Literal[
        "set_value",
        "set_field",
        "change_channel",
        "add_recipient",
        "remove_recipient",
        "change_schedule",
        "rename",
        "replace_agent",
        "add_action",
        "remove_action",
    ]
    target: str | None = Field(default=None, max_length=200)
    value: Any = None
    description: str | None = Field(default=None, max_length=300)


class SemanticWorkflowPatch(BaseModel):
    """Diff semántico propuesto por el LLM. Se valida y se muestra antes de
    aplicar (nunca regenera el workflow completo)."""

    model_config = MODEL_CONFIG

    patch_version: int = 1
    summary: str = Field(min_length=1, max_length=400)
    operations: list[PatchOperation] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    questions: list[str] = Field(default_factory=list)
    base_plan_hash: str | None = Field(default=None, max_length=80)
    raw_prompt: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def _requires_operations(self) -> "SemanticWorkflowPatch":
        if not self.operations:
            raise ValueError("el patch necesita al menos una operación")
        return self


def plan_fingerprint(plan: WorkflowPlan) -> str:
    """Hash estable del plan para detectar patches sobre una versión vieja."""
    canonical = json.dumps(plan.model_dump(mode="json"), sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "CANONICAL_TO_ENGINE",
    "ENGINE_TO_CANONICAL",
    "OPERATOR_LABELS",
    "VALUELESS_OPERATORS",
    "ConditionGroup",
    "ConditionNode",
    "ConditionOperator",
    "IntentValidationError",
    "PatchOperation",
    "PlanAction",
    "PlanAnalysis",
    "PlanCondition",
    "PlanDataSource",
    "PlanFieldRef",
    "PlanRecipient",
    "PlanSchedule",
    "PlanTrigger",
    "PlanValidationIssue",
    "SemanticWorkflowPatch",
    "TriggerKind",
    "WorkflowIntent",
    "WorkflowPlan",
    "intent_to_plan",
    "normalize_operator",
    "operator_label",
    "plan_fingerprint",
    "validate_intent",
    "validate_plan",
]
