# =============================================================================
# Workflow Business UX (commit 1) — schemas de negocio: parámetros, outputs,
# Intent, Plan, condiciones, schedules y patches semánticos.
# =============================================================================
from __future__ import annotations

import pytest

from src.platform.workflows.business_schema import (
    BusinessOutputField,
    BusinessParameterSchema,
    NodeBusinessSchema,
    NodeOutputContract,
)
from src.platform.workflows.intent import (
    CANONICAL_TO_ENGINE,
    ENGINE_TO_CANONICAL,
    ConditionGroup,
    ConditionOperator,
    IntentValidationError,
    PatchOperation,
    PlanAction,
    PlanCondition,
    PlanDataSource,
    PlanFieldRef,
    PlanRecipient,
    PlanSchedule,
    PlanTrigger,
    SemanticWorkflowPatch,
    TriggerKind,
    WorkflowIntent,
    intent_to_plan,
    normalize_operator,
    operator_label,
    plan_fingerprint,
    validate_intent,
    validate_plan,
)


# ---------------------------------------------------------------------------
# BusinessParameterSchema
# ---------------------------------------------------------------------------
def test_parameter_schema_secret_and_levels() -> None:
    secret = BusinessParameterSchema(key="api_key", label="Clave", type="secret")
    assert secret.secret is True

    basic = BusinessParameterSchema(key="to", label="Para", type="email")
    guided = BusinessParameterSchema(key="subject", label="Asunto", min_level="guided")
    advanced = BusinessParameterSchema(key="json_body", label="Body (JSON)", type="textarea", advanced=True)

    assert advanced.min_level == "advanced"
    assert basic.visible_at("simple") and basic.visible_at("advanced")
    assert not guided.visible_at("simple") and guided.visible_at("guided")
    assert not advanced.visible_at("simple") and not advanced.visible_at("guided")
    assert advanced.visible_at("advanced")


def test_parameter_schema_dynamic_options_inferred() -> None:
    agent = BusinessParameterSchema(key="agent_id", label="Agente", type="agent")
    assert agent.dynamic_options == "agent"
    assert agent.is_data_bound

    ref = BusinessParameterSchema(key="total", label="Total", type="money", data_source="sales")
    assert ref.is_data_bound


def test_node_business_schema_filters_by_level_and_secret() -> None:
    schema = NodeBusinessSchema(
        node_type="notify",
        label="Avisar",
        parameters=[
            BusinessParameterSchema(key="channel", label="Canal", type="enum"),
            BusinessParameterSchema(key="json", label="Data (JSON)", type="textarea", advanced=True),
            BusinessParameterSchema(key="smtp_password", label="Password SMTP", type="secret"),
        ],
    )
    simple = schema.parameters_for("simple")
    assert [p.key for p in simple] == ["channel"]
    all_params = schema.parameters_for("advanced", include_secret=True)
    assert [p.key for p in all_params] == ["channel", "json", "smtp_password"]


def test_output_contract_roundtrip() -> None:
    contract = NodeOutputContract(
        node_type="query_business_data",
        source="sample",
        sample={"total": 1200.5},
        outputs=[
            BusinessOutputField(key="total", label="Total", type="money", example=100.0),
            BusinessOutputField(key="customer", label="Cliente", type="text"),
        ],
    )
    dumped = contract.model_dump()
    assert dumped["outputs"][0]["key"] == "total"
    assert dumped["sample"]["total"] == 1200.5


# ---------------------------------------------------------------------------
# Operadores de negocio
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("es", "eq"),
        ("no es", "neq"),
        ("es mayor que", "gt"),
        ("sea menor que", "lt"),
        ("es al menos", "gte"),
        ("es como máximo", "lte"),
        ("contiene", "contains"),
        ("no contiene", "not_contains"),
        ("empieza con", "starts_with"),
        ("termina con", "ends_with"),
        ("está vacío", "is_empty"),
        ("no está vacío", "not_empty"),
        ("cambió", "changed"),
        ("gt", "gt"),
    ],
)
def test_operator_aliases(raw: str, expected: str) -> None:
    assert normalize_operator(raw) is ConditionOperator(expected)
    assert operator_label(raw)  # etiqueta humana no vacía


def test_operator_maps_to_engine() -> None:
    assert CANONICAL_TO_ENGINE["gt"] == ">"
    assert CANONICAL_TO_ENGINE["eq"] == "=="
    assert ENGINE_TO_CANONICAL[">="] == "gte"
    with pytest.raises(ValueError):
        normalize_operator("más o menos igual")


def test_condition_valueless_clears_value() -> None:
    cond = PlanCondition(
        field=PlanFieldRef(source="inventario", field="stock", label="Stock disponible"),
        operator=ConditionOperator.is_empty,
        value="ignorado",
    )
    assert cond.value is None


def test_nested_condition_group_roundtrip() -> None:
    payload = {
        "kind": "group",
        "op": "and",
        "children": [
            {
                "kind": "condition",
                "field": {"source": "ventas", "field": "total", "label": "Total"},
                "operator": "gt",
                "value": 20000,
            },
            {
                "kind": "group",
                "op": "or",
                "children": [
                    {
                        "kind": "condition",
                        "field": {"source": "cliente", "field": "es_nuevo", "label": "Cliente nuevo"},
                        "operator": "eq",
                        "value": True,
                    },
                    {
                        "kind": "condition",
                        "field": {"source": "cliente", "field": "ruc", "label": "RUC"},
                        "operator": "is_empty",
                    },
                ],
            },
        ],
    }
    group = ConditionGroup.model_validate(payload)
    assert len(group.children) == 2
    assert isinstance(group.children[1], ConditionGroup)
    assert group.children[1].op == "or"
    assert "Total es mayor que 20000" in group.describe()
    assert "(Cliente nuevo es True o RUC está vacío)" in group.describe()
    assert group.model_dump()["kind"] == "group"


# ---------------------------------------------------------------------------
# Schedules amigables
# ---------------------------------------------------------------------------
def test_schedule_daily_to_trigger_config_and_describe() -> None:
    schedule = PlanSchedule(mode="daily", time="08:00", timezone="America/Lima")
    assert schedule.to_trigger_config() == {
        "daily": {"time": "08:00"},
        "timezone": "America/Lima",
    }
    assert schedule.describe() == "Todos los días a las 8:00 a. m."


def test_schedule_weekly_and_monthly_describe() -> None:
    weekly = PlanSchedule(mode="weekly", days=[0, 1, 2, 3, 4], time="09:00")
    assert weekly.to_trigger_config()["weekly"]["days"] == [0, 1, 2, 3, 4]
    assert weekly.describe() == "Solo de lunes a viernes a las 9:00 a. m."

    monthly = PlanSchedule(mode="monthly", day_of_month=1, time="00:00")
    assert monthly.to_trigger_config()["monthly"] == {"day": 1, "time": "00:00"}
    assert monthly.describe() == "El día 1 de cada mes a las 12:00 a. m."


def test_schedule_from_trigger_config_legacy_and_v2() -> None:
    interval = PlanSchedule.from_trigger_config({"every_minutes": 15})
    assert interval is not None and interval.mode == "interval"

    weekly = PlanSchedule.from_trigger_config(
        {"weekly": {"days": [0, 2, 4], "time": "18:30"}, "timezone": "America/Lima"}
    )
    assert weekly is not None
    assert weekly.mode == "weekly" and weekly.days == [0, 2, 4]
    assert weekly.timezone == "America/Lima"

    assert PlanSchedule.from_trigger_config({}) is None


def test_schedule_validation_errors() -> None:
    with pytest.raises(ValueError):
        PlanSchedule(mode="weekly", time="09:00")  # sin days
    with pytest.raises(ValueError):
        PlanSchedule(mode="interval")  # sin every_minutes
    with pytest.raises(ValueError):
        PlanSchedule(mode="cron")  # sin cron


def test_trigger_coherence() -> None:
    with pytest.raises(ValueError):
        PlanTrigger(kind=TriggerKind.event)
    with pytest.raises(ValueError):
        PlanTrigger(kind=TriggerKind.schedule)

    trigger = PlanTrigger(
        kind=TriggerKind.schedule,
        schedule=PlanSchedule(mode="daily", time="08:00", timezone="America/Lima"),
    )
    assert trigger.schedule is not None


# ---------------------------------------------------------------------------
# Intent → Plan
# ---------------------------------------------------------------------------
def _sale_intent(**overrides) -> WorkflowIntent:
    data = {
        "name": "Avisar ventas grandes",
        "description": "Cuando una venta supera S/ 20,000 avisar al gerente comercial.",
        "trigger": PlanTrigger(kind=TriggerKind.event, event_type="sales.closed"),
        "conditions": [
            PlanCondition(
                field=PlanFieldRef(source="Ventas", field="total", label="Total"),
                operator=normalize_operator("es mayor que"),
                value=20000,
            )
        ],
        "data_sources": [
            PlanDataSource(key="Ventas", kind="database", label="Consulta de ventas", ref="catalog:ventas"),
        ],
        "actions": [
            PlanAction(
                kind="agent_analysis",
                description="Comprobar si el cliente es nuevo",
                params={"agent_name": "Agente de clientes"},
            ),
            PlanAction(
                kind="notify",
                channel="email",
                recipients=[PlanRecipient(kind="team", value="gerencia-comercial", label="Gerencia comercial")],
                subject="Venta importante",
                message="Producto: {{Producto → Nombre}}",
            ),
        ],
        "recipients": [PlanRecipient(kind="team", value="gerencia-comercial", label="Gerencia comercial")],
        "confidence": 0.9,
        "raw_prompt": "Cuando tengamos una venta mayor a S/ 20,000 avisa al gerente comercial...",
    }
    data.update(overrides)
    return WorkflowIntent(**data)  # type: ignore[arg-type]


def test_intent_validation_has_no_errors_for_complete_intent() -> None:
    issues = validate_intent(_sale_intent())
    assert [i for i in issues if i.severity == "error"] == []


def test_intent_validation_warns_missing_recipient_and_channel() -> None:
    intent = _sale_intent(
        actions=[PlanAction(kind="notify")],
        recipients=[],
        confidence=0.3,
    )
    codes = {i.code for i in validate_intent(intent)}
    assert {"notify.missing_channel", "notify.missing_recipients", "intent.low_confidence"} <= codes


def test_intent_to_plan_compiles_business_shape() -> None:
    plan = intent_to_plan(_sale_intent())
    assert plan.trigger.kind == TriggerKind.event
    assert plan.conditions is not None
    assert plan.conditions.op == "and"
    assert len(plan.analysis) == 1
    assert plan.analysis[0].agent_name == "Agente de clientes"
    assert [a.kind for a in plan.actions] == ["notify"]
    assert plan.recipients[0].label == "Gerencia comercial"
    assert plan.questions == []
    assert plan.confidence == 0.9


def test_intent_to_plan_raises_on_blocking_errors() -> None:
    intent = _sale_intent(actions=[], agents=[], data_sources=[])
    with pytest.raises(IntentValidationError):
        intent_to_plan(intent)


def test_plan_fingerprint_is_stable_and_sensitive() -> None:
    plan_a = intent_to_plan(_sale_intent())
    plan_b = intent_to_plan(_sale_intent())
    assert plan_fingerprint(plan_a) == plan_fingerprint(plan_b)

    plan_c = intent_to_plan(_sale_intent(name="Otro nombre"))
    assert plan_fingerprint(plan_c) != plan_fingerprint(plan_a)


def test_validate_plan_readiness_warning() -> None:
    plan = intent_to_plan(
        _sale_intent(
            actions=[PlanAction(kind="notify", channel="email")],
            recipients=[],
        )
    )
    codes = {i.code for i in validate_plan(plan)}
    assert "notify.missing_recipients" in codes


def test_recipient_email_validation() -> None:
    with pytest.raises(ValueError):
        PlanRecipient(kind="email", value="no-es-un-email")
    ok = PlanRecipient(kind="email", value="compras@zent.pe")
    assert ok.describe() == "compras@zent.pe"


# ---------------------------------------------------------------------------
# Patch semántico (schema)
# ---------------------------------------------------------------------------
def test_semantic_patch_requires_operations() -> None:
    with pytest.raises(ValueError):
        SemanticWorkflowPatch(summary="Cambiar el umbral")


def test_semantic_patch_parses_natural_edit() -> None:
    patch = SemanticWorkflowPatch(
        summary="Cambiar umbral de 10 a 5 y avisar también al gerente",
        operations=[
            PatchOperation(op="set_value", target="conditions.0.value", value=5, description="Cambia 10 por 5"),
            PatchOperation(
                op="add_recipient",
                target="actions.0.recipients",
                value={"kind": "team", "value": "gerencia"},
                description="Avisa también al gerente",
            ),
        ],
        confidence=0.8,
        raw_prompt="Cambia 10 por 5 y avisa también al gerente",
    )
    assert len(patch.operations) == 2
    assert patch.operations[0].value == 5
    assert patch.operations[1].op == "add_recipient"
