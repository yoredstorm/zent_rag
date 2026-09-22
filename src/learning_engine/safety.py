# =============================================================================
# Experimentos automáticos no ejecutan side effects reales.
# =============================================================================
from __future__ import annotations

from src.core.domain.learning_cycle import ExperimentMode, ToolStep

SIDE_EFFECT_TOOLS = frozenset(
    {
        "send_email",
        "send_sms",
        "create_payment",
        "charge_payment",
        "refund_payment",
        "delete_rows",
        "update_rows",
        "insert_rows",
        "execute_sql_write",
        "mutate_database",
        "workflow_destructive",
        "send_webhook_live",
    }
)
SAFE_EXECUTIONS = frozenset({"mock", "dry_run", "simulation"})


class ExperimentSafetyError(RuntimeError):
    """El plan tocaría un sistema externo. El experimento no arranca."""


def assert_experiment_safe(mode: ExperimentMode | str, tool_plan: tuple[ToolStep, ...] | list[ToolStep]) -> None:
    parsed = ExperimentMode(mode)
    if parsed not in {ExperimentMode.GOLDEN_SET, ExperimentMode.SHADOW, ExperimentMode.REPLAY}:
        raise ExperimentSafetyError(f"mode {parsed.value} is not an offline experiment")
    if parsed == ExperimentMode.GOLDEN_SET:
        return
    for step in tool_plan:
        risky = step.side_effect or step.name in SIDE_EFFECT_TOOLS
        if risky and step.execution not in SAFE_EXECUTIONS:
            raise ExperimentSafetyError(
                f"{step.name} requires mock, dry_run, or simulation during {parsed.value}"
            )
