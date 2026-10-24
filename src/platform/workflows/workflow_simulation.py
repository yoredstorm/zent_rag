# =============================================================================
# Workflow Simulation & Certification (Prompt 06).
#
# Reutiliza execute_graph(simulate=True) y WorkflowGraph v2. No hay segundo
# motor: ejecuta nodos deterministas reales, sustituye efectos externos por
# dobles fijados (pinned) y valida contratos/estado/eventos de los escenarios.
# =============================================================================
from __future__ import annotations

import copy
import json
import time
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from src.infrastructure.observability.logging_config import get_logger
from src.platform.workflows.architect_compiler import compile_semantic_plan
from src.platform.workflows.architect_models import (
    PlanIssue,
    SemanticPlan,
    normalize_semantic_plan,
)
from src.platform.workflows.architect_validator import validate_semantic_plan
from src.platform.workflows.effect_verification import (
    EXTERNAL_EFFECT_NODE_TYPES,
    EXTERNAL_READ_NODE_TYPES,
)
from src.platform.workflows.ir import WorkflowGraph, validate_graph
from src.platform.workflows.runtime import ExecutionContext, execute_graph

logger = get_logger(__name__)

MODEL_CONFIG = ConfigDict(extra="forbid")
SIMULATION_SCHEMA = "zent.workflow.simulation/v1"
CERTIFICATION_SCHEMA = "zent.workflow.certification/v1"

_RISKY_NODE_TYPES = EXTERNAL_EFFECT_NODE_TYPES | EXTERNAL_READ_NODE_TYPES


class ScenarioEvent(BaseModel):
    model_config = MODEL_CONFIG

    event_type: str = Field(min_length=1, max_length=160)
    payload: dict[str, Any] = Field(default_factory=dict)
    correlation: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = Field(default=None, max_length=200)
    port: Literal["out", "timeout"] = "out"


class ScenarioResponse(BaseModel):
    model_config = MODEL_CONFIG

    step_id: str | None = Field(default=None, max_length=80)
    capability_ref: str | None = Field(default=None, max_length=200)
    action_id: str | None = Field(default=None, max_length=200)
    output: dict[str, Any] = Field(default_factory=dict)
    error: str | None = Field(default=None, max_length=300)
    effects: list[str] = Field(default_factory=list, max_length=20)


class SimulationScenario(BaseModel):
    model_config = MODEL_CONFIG

    scenario_id: str = Field(min_length=1, max_length=80)
    name: str = Field(default="", max_length=200)
    initial_inputs: dict[str, Any] = Field(default_factory=dict)
    events: list[ScenarioEvent] = Field(default_factory=list, max_length=30)
    responses: list[ScenarioResponse] = Field(default_factory=list, max_length=40)
    expected_state: dict[str, Any] = Field(default_factory=dict)
    expected_outputs: dict[str, Any] = Field(default_factory=dict)
    expected_result: Literal["PASSED", "FAILED", "WAITING", "UNVERIFIED"] = "PASSED"
    allowed_effects: list[str] = Field(default_factory=list, max_length=30)
    forbidden_effects: list[str] = Field(default_factory=list, max_length=30)
    max_segments: int = Field(default=20, ge=1, le=100)


class SimulationIssue(BaseModel):
    model_config = MODEL_CONFIG

    code: str
    severity: Literal["error", "warning", "info"] = "error"
    node_id: str | None = None
    step_id: str | None = None
    message: str
    expected: str | None = None
    received: str | None = None
    action_required: str | None = None


class SimulationReport(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_id: str = SIMULATION_SCHEMA
    simulation_id: str
    workflow_version: int | None = None
    scenario_id: str
    scenario_name: str = ""
    result: Literal["PASSED", "FAILED", "BLOCKED", "UNVERIFIED"] = "BLOCKED"
    static_validation: list[SimulationIssue] = Field(default_factory=list)
    executed_nodes: list[dict[str, Any]] = Field(default_factory=list)
    failed_nodes: list[dict[str, Any]] = Field(default_factory=list)
    branch_coverage: dict[str, Any] = Field(default_factory=dict)
    input_contract_errors: list[SimulationIssue] = Field(default_factory=list)
    output_contract_errors: list[SimulationIssue] = Field(default_factory=list)
    unresolved_references: list[SimulationIssue] = Field(default_factory=list)
    missing_dependencies: list[dict[str, Any]] = Field(default_factory=list)
    unexpected_effects: list[dict[str, Any]] = Field(default_factory=list)
    state_transitions: list[dict[str, Any]] = Field(default_factory=list)
    timeline: list[dict[str, Any]] = Field(default_factory=list)
    cost_estimate: dict[str, Any] = Field(default_factory=dict)
    repair_suggestions: list[dict[str, Any]] = Field(default_factory=list)
    unverified_nodes: list[str] = Field(default_factory=list)
    trace: dict[str, Any] = Field(default_factory=dict)


class CertificationReport(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_id: str = CERTIFICATION_SCHEMA
    certification_id: str
    workflow_version: int | None = None
    state: Literal[
        "DRAFT",
        "NEEDS_CONFIGURATION",
        "VALIDATING",
        "FAILED_VALIDATION",
        "SIMULATION_PASSED",
        "AWAITING_APPROVAL",
        "READY_TO_PUBLISH",
    ] = "DRAFT"
    static_validation: list[SimulationIssue] = Field(default_factory=list)
    scenarios: list[SimulationReport] = Field(default_factory=list)
    partial: bool = False
    publishable: bool = False
    repair_suggestions: list[dict[str, Any]] = Field(default_factory=list)
    trace: dict[str, Any] = Field(default_factory=dict)


def _issue(
    code: str,
    message: str,
    *,
    severity: Literal["error", "warning", "info"] = "error",
    node_id: str | None = None,
    step_id: str | None = None,
    expected: str | None = None,
    received: str | None = None,
    action_required: str | None = None,
) -> SimulationIssue:
    return SimulationIssue(
        code=code,
        severity=severity,
        node_id=node_id,
        step_id=step_id,
        message=message[:400],
        expected=expected,
        received=received,
        action_required=action_required,
    )


def _plan_issues(issues: list[PlanIssue]) -> list[SimulationIssue]:
    return [
        SimulationIssue(
            code=issue.code,
            severity=issue.severity,
            step_id=issue.step_id,
            message=issue.message,
            expected=issue.expected,
            received=issue.received,
            action_required=issue.action_required,
        )
        for issue in issues
    ]


def _contract_missing(output: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    if not isinstance(schema, dict):
        return []
    required = [str(item) for item in (schema.get("required") or [])]
    missing = [key for key in required if key not in output]
    properties = schema.get("properties") or {}
    if not required and isinstance(properties, dict) and properties:
        # Si el contrato declara propiedades y la respuesta simulada está vacía,
        # no se asume que el proveedor devolvió un objeto válido.
        if not output:
            return ["<respuesta vacía>"]
    return missing


def _response_for_node(
    node: dict[str, Any], responses: list[ScenarioResponse]
) -> ScenarioResponse | None:
    config = node.get("config") or {}
    architect = (node.get("metadata") or {}).get("architect") or {}
    step_id = str(architect.get("step_id") or "")
    capability = str(config.get("capability") or "")
    action_id = str(config.get("action_id") or "")
    for response in responses:
        if response.step_id and response.step_id == step_id:
            return response
        if response.capability_ref and response.capability_ref == capability:
            return response
        if response.action_id and response.action_id == action_id:
            return response
    return None


class WorkflowSimulationRunner:
    """Ejecuta escenarios sobre un WorkflowGraph v2 con simulaciones aisladas."""

    def __init__(
        self,
        graph: dict[str, Any],
        *,
        capabilities: dict[str, Any] | None = None,
        steps_map: dict[str, str] | None = None,
        organization_id: UUID | None = None,
        workspace_id: UUID | None = None,
        permissions: frozenset[str] | None = None,
        workflow_version: int | None = None,
        static_issues: list[SimulationIssue] | None = None,
    ) -> None:
        self.graph = graph
        self.capabilities = capabilities or {}
        self.steps_map = steps_map or {}
        self.organization_id = organization_id or uuid4()
        self.workspace_id = workspace_id
        self.permissions = permissions or frozenset()
        self.workflow_version = workflow_version or int(
            graph.get("workflow_version") or 2
        )
        self.static_issues = static_issues or []
        self.node_map = {str(item.get("id")): item for item in graph.get("nodes") or []}
        self._index = self.capabilities.get("capability_index") or {}

    def _external_pins(
        self, scenario: SimulationScenario
    ) -> tuple[dict[str, dict], dict[str, str], list[str], list[SimulationIssue]]:
        pinned: dict[str, dict] = {}
        failures: dict[str, str] = {}
        unverified: list[str] = []
        output_errors: list[SimulationIssue] = []
        for node_id, node in self.node_map.items():
            node_type = str(node.get("type") or "")
            if node_type not in _RISKY_NODE_TYPES:
                continue
            response = _response_for_node(node, scenario.responses)
            config = node.get("config") or {}
            ref = str(config.get("capability") or config.get("action_id") or "")
            step_id = str(((node.get("metadata") or {}).get("architect") or {}).get("step_id") or "")
            if response is None:
                pinned[node_id] = {
                    "simulated": True,
                    "unverified_external_effect": True,
                }
                unverified.append(node_id)
                continue
            if response.error:
                failures[node_id] = response.error
                continue
            output = dict(response.output)
            pinned[node_id] = output
            descriptor = self._index.get(ref) if ref else None
            if descriptor:
                missing = _contract_missing(
                    output, descriptor.get("output_schema") or {}
                )
                if missing:
                    output_errors.append(
                        _issue(
                            "simulation.output_contract",
                            f"La respuesta simulada de {ref} no cumple el contrato de salida.",
                            node_id=node_id,
                            step_id=step_id or None,
                            expected=", ".join(missing[:8]),
                            received=str(sorted(output.keys())[:8]),
                        )
                    )
        return pinned, failures, unverified, output_errors

    @staticmethod
    def _executions_preload(
        executions: dict[str, Any], *, exclude: set[str] | None = None
    ) -> dict[str, tuple[str, dict, str | None, int]]:
        excluded = exclude or set()
        return {
            node_id: (
                exec_.status,
                dict(exec_.output or {}),
                exec_.error,
                int(exec_.retries or 0),
            )
            for node_id, exec_ in executions.items()
            if node_id not in excluded
            and exec_.status in (
                "succeeded",
                "simulated",
                "approved",
                "failed",
                "denied",
            )
        }

    @staticmethod
    def _loop_body_ids(graph: dict[str, Any], loop_node_id: str, target: str) -> set[str]:
        edges = list(graph.get("edges") or [])
        forward: dict[str, set[str]] = {}
        backward: dict[str, set[str]] = {}
        for edge in edges:
            forward.setdefault(str(edge["from_node"]), set()).add(str(edge["to_node"]))
            backward.setdefault(str(edge["to_node"]), set()).add(str(edge["from_node"]))

        def walk(start: str, adjacency: dict[str, set[str]]) -> set[str]:
            found: set[str] = set()
            stack = [start]
            while stack:
                current = stack.pop()
                for nxt in adjacency.get(current, set()):
                    if nxt not in found:
                        found.add(nxt)
                        stack.append(nxt)
            return found

        from_target = walk(target, forward)
        to_loop = walk(loop_node_id, backward)
        return (from_target & to_loop) | {target, loop_node_id}

    async def run_scenario(self, scenario: SimulationScenario) -> SimulationReport:
        started = time.monotonic()
        simulation_id = f"sim_{uuid4().hex}"
        pinned, failures, unverified, output_errors = self._external_pins(scenario)
        pinned_failure_ids = set(failures)
        ctx = ExecutionContext(
            organization_id=self.organization_id,
            workflow_id=uuid4(),
            run_id=uuid4(),
            actor_type="simulation",
            trigger_type="simulation",
            permissions=self.permissions,
            simulate=True,
            simulation_state={},
            simulation_loops={},
        )
        all_executions: dict[str, Any] = {}
        timeline: list[dict[str, Any]] = []
        state_transitions: list[dict[str, Any]] = []
        preloaded: dict[str, tuple[str, dict, str | None, int]] | None = None
        preload_ports: dict[str, str] = {}
        event_index = 0
        seen_event_keys: set[str] = set()
        last_result: Any = None
        observed_waiting = False
        observed_failed = False
        segment_count = 0

        while segment_count < scenario.max_segments:
            segment_count += 1
            result = await execute_graph(
                WorkflowGraph.from_dict(self.graph),
                ctx,
                scenario.initial_inputs,
                preloaded=preloaded,
                pinned=pinned,
                pinned_failures=failures,
                resolve_preload_edges=bool(preloaded),
                preload_ports=preload_ports or None,
                persist_execution=False,
            )
            last_result = result
            all_executions.update(result.node_executions)
            state_transitions.append(
                {
                    "segment": segment_count,
                    "state": copy.deepcopy(ctx.simulation_state or {}),
                }
            )
            timeline.append(
                {
                    "segment": segment_count,
                    "status": result.status,
                    "nodes": sorted(result.node_executions),
                    "error": result.error,
                }
            )
            if result.status == "failed":
                observed_failed = True
                break
            if result.status == "waiting":
                observed_waiting = True
                if event_index >= len(scenario.events):
                    break
                event = scenario.events[event_index]
                event_index += 1
                key = event.idempotency_key or ""
                if key and key in seen_event_keys:
                    timeline.append(
                        {
                            "segment": segment_count,
                            "event": event.event_type,
                            "duplicate": True,
                        }
                    )
                    # Un signal duplicado no re-ejecuta el workflow.
                    continue
                if key:
                    seen_event_keys.add(key)
                waiting = result.waiting or {}
                expected_event = str(waiting.get("event_type") or "")
                timeout_event = event.event_type == "workflow.wait.timeout" or event.port == "timeout"
                if event.event_type not in ("", expected_event) and not timeout_event:
                    timeline.append(
                        {
                            "segment": segment_count,
                            "event": event.event_type,
                            "mismatch": expected_event,
                        }
                    )
                    break
                wait_node = str(result.wait_node_id or "")
                wait_exec = all_executions.get(wait_node)
                if wait_exec is not None:
                    wait_exec.status = "succeeded"
                    wait_exec.control = None
                    wait_exec.output = {
                        **dict(wait_exec.output or {}),
                        **dict(event.payload),
                        "event_type": event.event_type,
                        "port": "timeout" if timeout_event else "out",
                        "signal_received": True,
                    }
                preload_ports = {wait_node: "timeout" if timeout_event else "out"}
                preloaded = self._executions_preload(all_executions)
                timeline.append(
                    {
                        "segment": segment_count,
                        "event": event.event_type,
                        "resumed_wait": wait_node,
                        "port": preload_ports.get(wait_node, "out"),
                    }
                )
                observed_waiting = False
                continue
            if result.status in ("pending_approval",):
                observed_waiting = True
                if event_index >= len(scenario.events):
                    break
                event = scenario.events[event_index]
                event_index += 1
                wait_node = str(result.wait_node_id or "")
                wait_exec = all_executions.get(wait_node)
                if wait_exec is not None:
                    wait_exec.status = "succeeded"
                    wait_exec.control = None
                    wait_exec.output = {
                        **dict(wait_exec.output or {}),
                        **dict(event.payload),
                        "event_type": event.event_type,
                        "approved": True,
                    }
                preload_ports = {wait_node: "out"}
                preloaded = self._executions_preload(all_executions)
                timeline.append(
                    {
                        "segment": segment_count,
                        "event": event.event_type,
                        "resumed_approval": wait_node,
                    }
                )
                observed_waiting = False
                continue
            if result.status == "looping":
                loop_node = str(result.loop_node_id or "")
                loop_spec = result.looping or {}
                target = str(loop_spec.get("target") or "")
                body = self._loop_body_ids(self.graph, loop_node, target)
                preloaded = self._executions_preload(all_executions, exclude=body)
                preload_ports = {}
                timeline.append(
                    {
                        "segment": segment_count,
                        "loop": loop_node,
                        "target": target,
                        "iteration": loop_spec.get("iteration"),
                    }
                )
                continue
            break
        else:
            timeline.append({"status": "max_segments", "max": scenario.max_segments})

        # Un signal duplicado no vuelve a ejecutar el workflow: se ignora y se
        # registra en el timeline, no se convierte en evento pendiente.
        while event_index < len(scenario.events):
            event = scenario.events[event_index]
            key = event.idempotency_key or ""
            if not key or key not in seen_event_keys:
                break
            event_index += 1
            timeline.append(
                {
                    "event": event.event_type,
                    "duplicate_ignored": True,
                }
            )

        executed_nodes = [
            {
                "node_id": node_id,
                "type": self.node_map.get(node_id, {}).get("type"),
                "status": exec_.status,
                "error": exec_.error,
                "simulated": bool(
                    exec_.simulated
                    or exec_.status == "simulated"
                    or node_id in pinned_failure_ids
                ),
                "output": dict(exec_.output or {}),
            }
            for node_id, exec_ in all_executions.items()
        ]
        failed_nodes = [item for item in executed_nodes if item["status"] == "failed"]
        observed_status = (
            "FAILED"
            if observed_failed or failed_nodes
            else "WAITING"
            if observed_waiting
            else "PASSED"
            if last_result is not None and last_result.status in ("succeeded", "stopped")
            else "UNVERIFIED"
        )
        issues: list[SimulationIssue] = []
        if unverified:
            issues.append(
                _issue(
                    "simulation.unverified_external_effect",
                    "Hay nodos externos sin doble de prueba; no se asume éxito.",
                    severity="warning",
                    expected="respuesta simulada por contrato",
                    received=", ".join(sorted(unverified)[:8]),
                )
            )
        if scenario.expected_result != observed_status:
            issues.append(
                _issue(
                    "simulation.expected_result_mismatch",
                    "El resultado observado no coincide con el esperado.",
                    expected=scenario.expected_result,
                    received=observed_status,
                )
            )
        if event_index < len(scenario.events) and scenario.expected_result == "PASSED":
            issues.append(
                _issue(
                    "simulation.events_unconsumed",
                    "El escenario dejó eventos sin consumir.",
                    expected=f"{event_index + 1} eventos consumidos",
                    received=f"{len(scenario.events) - event_index} pendientes",
                )
            )
        if scenario.expected_state:
            state = ctx.simulation_state or {}
            for path, expected in scenario.expected_state.items():
                current: Any = state
                for part in str(path).split("."):
                    current = current.get(part) if isinstance(current, dict) else None
                if current != expected:
                    issues.append(
                        _issue(
                            "simulation.state_mismatch",
                            f"El estado «{path}» no coincide.",
                            expected=str(expected)[:200],
                            received=str(current)[:200],
                        )
                    )
        if scenario.expected_outputs:
            for key, expected in scenario.expected_outputs.items():
                node_key = self.steps_map.get(key, key)
                found = next(
                    (
                        item
                        for item in executed_nodes
                        if node_key in (item.get("node_id"), (item.get("output") or {}).get("architect_step_id"))
                    ),
                    None,
                )
                if found is not None and found.get("output") != expected:
                    issues.append(
                        _issue(
                            "simulation.output_mismatch",
                            f"La salida esperada «{key}» no coincide.",
                            node_id=str(found.get("node_id") or ""),
                            expected=str(expected)[:200],
                            received=str(found.get("output"))[:200],
                        )
                    )
        unexpected_effects: list[dict[str, Any]] = []
        for response in scenario.responses:
            for effect in response.effects:
                if effect in scenario.forbidden_effects or (
                    scenario.allowed_effects and effect not in scenario.allowed_effects
                ):
                    unexpected_effects.append(
                        {
                            "effect": effect,
                            "step_id": response.step_id,
                            "capability_ref": response.capability_ref,
                            "reason": "effect not allowed",
                        }
                    )
        for node in executed_nodes:
            if node.get("simulated") and (node.get("output") or {}).get(
                "unverified_external_effect"
            ):
                continue
        failures = (
            [item for item in issues if item.severity == "error"]
            + output_errors
            + [item for item in self.static_issues if item.severity == "error"]
        )
        static_errors = [
            item for item in self.static_issues if item.severity == "error"
        ]
        if static_errors:
            result_status: Literal["PASSED", "FAILED", "BLOCKED", "UNVERIFIED"] = "BLOCKED"
        elif unexpected_effects:
            result_status = "FAILED"
        elif observed_failed or scenario.expected_result == "FAILED" and observed_status == "FAILED":
            result_status = "FAILED" if observed_status == "FAILED" else "FAILED"
        elif unverified or observed_status == "UNVERIFIED":
            result_status = "UNVERIFIED"
        elif failures:
            result_status = "FAILED"
        else:
            result_status = "PASSED"
        if scenario.expected_result == "FAILED" and observed_status == "FAILED":
            result_status = "PASSED"
        if scenario.expected_result == "WAITING" and observed_status == "WAITING":
            result_status = "PASSED"
        cost_ms = sum(float(getattr(exec_, "cost_ms", 0) or 0) for exec_ in all_executions.values())
        repair = [
            {
                "code": issue.code,
                "node_id": issue.node_id,
                "step_id": issue.step_id,
                "message": issue.message,
                "action_required": issue.action_required,
            }
            for issue in [*self.static_issues, *output_errors, *issues]
            if issue.severity == "error"
        ]
        input_contract_errors = [
            issue
            for issue in self.static_issues
            if issue.code
            in (
                "missing.capability_input",
                "contract.input_unknown",
                "contract.params_invalid",
                "contract.literal_type",
                "contract.version_mismatch",
            )
        ]
        output_contract_errors = [
            *output_errors,
            *[
                issue
                for issue in self.static_issues
                if issue.code in ("contract.output_unknown", "contract.outputs_missing")
            ],
        ]
        return SimulationReport(
            simulation_id=simulation_id,
            workflow_version=self.workflow_version,
            scenario_id=scenario.scenario_id,
            scenario_name=scenario.name,
            result=result_status,
            static_validation=self.static_issues,
            executed_nodes=executed_nodes,
            failed_nodes=failed_nodes,
            branch_coverage=self._branch_coverage(executed_nodes),
            input_contract_errors=input_contract_errors,
            output_contract_errors=output_contract_errors,
            unresolved_references=[
                issue
                for issue in self.static_issues
                if issue.code.startswith("contract.")
            ],
            missing_dependencies=[
                {"code": issue.code, "requirement": issue.expected}
                for issue in self.static_issues
                if issue.code.startswith("missing.") or issue.code.startswith("capability.")
            ],
            unexpected_effects=unexpected_effects,
            state_transitions=state_transitions,
            timeline=timeline,
            cost_estimate={
                "unit": "ms_runtime_cost",
                "total_ms": round(cost_ms, 3),
                "segments": segment_count,
            },
            repair_suggestions=repair,
            unverified_nodes=sorted(unverified),
            trace={
                "simulated": True,
                "segments": segment_count,
                "events_consumed": event_index,
                "last_status": getattr(last_result, "status", None),
                "duration_ms": int((time.monotonic() - started) * 1000),
                "read_only": True,
            },
        )

    def _branch_coverage(self, executed_nodes: list[dict[str, Any]]) -> dict[str, Any]:
        branches: dict[str, Any] = {}
        for node_id, node in self.node_map.items():
            if str(node.get("type")) not in ("condition", "ai_decision", "wait_event"):
                continue
            execution = next(
                (item for item in executed_nodes if item.get("node_id") == node_id),
                None,
            )
            if execution is None:
                branches[node_id] = {"taken": [], "status": "not_executed"}
                continue
            output = execution.get("output") or {}
            if node.get("type") == "wait_event":
                taken = [str(output.get("port") or "out")]
            else:
                taken = ["then" if output.get("result") else "else"]
            branches[node_id] = {
                "taken": taken,
                "status": execution.get("status"),
            }
        return branches


async def simulate_semantic_plan(
    plan: dict[str, Any],
    capabilities: dict[str, Any],
    scenarios: list[SimulationScenario],
    *,
    organization_id: UUID,
    workspace_id: UUID | None = None,
    permissions: frozenset[str] | None = None,
) -> CertificationReport:
    """Validación estática + simulación de escenarios sobre el plan canónico."""
    semantic: SemanticPlan = normalize_semantic_plan(SemanticPlan.model_validate(plan))
    issues = validate_semantic_plan(semantic, capabilities, permissions=permissions)
    static = _plan_issues(issues)
    compiled = compile_semantic_plan(semantic, capabilities)
    graph = compiled.get("graph")
    graph_issues: list[SimulationIssue] = []
    if graph is not None:
        try:
            validate_graph(WorkflowGraph.from_dict(graph))
        except Exception as exc:  # noqa: BLE001
            graph_issues.append(
                _issue("simulation.invalid_graph", f"Grafo inválido: {str(exc)[:240]}")
            )
    static.extend(graph_issues)
    if any(issue.severity == "error" for issue in static) or graph is None:
        return CertificationReport(
            certification_id=f"cert_{uuid4().hex}",
            state="FAILED_VALIDATION",
            static_validation=static,
            scenarios=[],
            partial=False,
            publishable=False,
            repair_suggestions=[
                {
                    "code": issue.code,
                    "step_id": issue.step_id,
                    "message": issue.message,
                    "action_required": issue.action_required,
                }
                for issue in static
                if issue.severity == "error"
            ],
            trace={"static_errors": sum(1 for item in static if item.severity == "error")},
        )
    runner = WorkflowSimulationRunner(
        graph,
        capabilities=capabilities,
        steps_map=compiled.get("steps_map") or {},
        organization_id=organization_id,
        workspace_id=workspace_id,
        permissions=permissions,
        workflow_version=int(graph.get("workflow_version") or 2),
        static_issues=static,
    )
    reports = [await runner.run_scenario(scenario) for scenario in scenarios]
    partial = any(report.result in ("UNVERIFIED", "BLOCKED") for report in reports)
    failed = any(report.result == "FAILED" for report in reports)
    needs_configuration = any(
        issue.code.startswith(("missing.", "capability.", "permission."))
        for issue in static
    )
    if failed or not reports:
        state = "FAILED_VALIDATION" if failed else "VALIDATING"
    elif needs_configuration:
        state = "NEEDS_CONFIGURATION"
    elif partial:
        state = "SIMULATION_PASSED"
    else:
        has_approval = any(
            step.type in ("human_approval", "capability_call")
            and (
                step.type == "human_approval"
                or bool(step.params.get("requires_approval"))
            )
            for step in semantic.steps
        )
        capability_index = capabilities.get("capability_index") or {}
        has_financial = False
        for step in semantic.steps:
            if step.type not in (
                "capability_call",
                "integration_action",
                "compensation",
            ):
                continue
            ref = str(
                step.params.get("capability")
                or step.params.get("action_id")
                or ""
            )
            descriptor = capability_index.get(ref) or {}
            if (
                "financial" in (descriptor.get("side_effects") or [])
                or descriptor.get("risk_level") == "critical"
                or bool((descriptor.get("metadata") or {}).get("requires_approval"))
            ):
                has_financial = True
                break
        state = "AWAITING_APPROVAL" if (has_approval or has_financial) else "READY_TO_PUBLISH"
    return CertificationReport(
        certification_id=f"cert_{uuid4().hex}",
        workflow_version=int(graph.get("workflow_version") or 2),
        state=state,
        static_validation=static,
        scenarios=reports,
        partial=partial,
        publishable=state == "READY_TO_PUBLISH",
        repair_suggestions=[
            suggestion
            for report in reports
            for suggestion in report.repair_suggestions
        ][:20],
        trace={
            "static_errors": sum(1 for item in static if item.severity == "error"),
            "scenarios": len(reports),
            "passed": sum(1 for report in reports if report.result == "PASSED"),
            "unverified": sum(1 for report in reports if report.result == "UNVERIFIED"),
            "failed": sum(1 for report in reports if report.result == "FAILED"),
            "read_only": True,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    )


class RepairAttempt(BaseModel):
    model_config = MODEL_CONFIG

    attempt: int
    accepted: bool
    before_state: str
    after_state: str
    error_count_before: int
    error_count_after: int
    instruction: str
    patch_summary: str | None = None
    reason: str | None = None


async def simulate_with_repair(
    plan: dict[str, Any],
    capabilities: dict[str, Any],
    scenarios: list[SimulationScenario],
    *,
    organization_id: UUID,
    workspace_id: UUID | None = None,
    permissions: frozenset[str] | None = None,
    provider: Any = None,
    model: str | None = None,
    max_repairs: int = 2,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Simula, pide patches semánticos acotados y revalida; nunca desactiva checks.

    El patch se aplica al plan en memoria, no a un workflow publicado. Si el
    resultado empeora los errores estáticos, se rechaza el intento.
    """
    from src.platform.workflows.architect import patch_workflow_plan

    current_plan = copy.deepcopy(plan)
    certification = await simulate_semantic_plan(
        current_plan,
        capabilities,
        scenarios,
        organization_id=organization_id,
        workspace_id=workspace_id,
        permissions=permissions,
    )
    attempts: list[RepairAttempt] = []
    max_repairs = max(0, min(int(max_repairs), 3))
    for attempt in range(1, max_repairs + 1):
        if certification.state in ("READY_TO_PUBLISH", "AWAITING_APPROVAL"):
            break
        suggestions = certification.repair_suggestions[:10]
        if not suggestions:
            break
        blocked_codes = {
            "permission.capability",
            "permission.integration",
            "permission.agents",
            "capability.unavailable",
            "missing.managed_db",
            "missing.integration",
            "missing.knowledge_bases",
            "missing.agents",
        }
        if any(item.get("code") in blocked_codes for item in suggestions):
            attempts.append(
                RepairAttempt(
                    attempt=attempt,
                    accepted=False,
                    before_state=certification.state,
                    after_state=certification.state,
                    error_count_before=len(suggestions),
                    error_count_after=len(suggestions),
                    instruction="<reparación detenida: requiere configuración humana>",
                    reason=(
                        "El fallo requiere credenciales, permisos, instalación o datos "
                        "reales; se detiene la reparación automática."
                    ),
                )
            )
            break
        instruction = (
            "Repara solo los errores estructurados de simulación. No desactives "
            "validaciones, no elimines ramas críticas, no reduzcas controles de "
            "seguridad, no inventes permisos ni credenciales. Errores: "
            + json.dumps(suggestions, ensure_ascii=False)[:6000]
        )
        try:
            patched = await patch_workflow_plan(
                organization_id,
                current_plan,
                instruction,
                workspace_id=workspace_id,
                permissions=permissions,
                provider=provider,
                model=model,
                capabilities=capabilities,
                session_id=session_id,
            )
        except Exception as exc:  # noqa: BLE001 — reparación best-effort
            attempts.append(
                RepairAttempt(
                    attempt=attempt,
                    accepted=False,
                    before_state=certification.state,
                    after_state=certification.state,
                    error_count_before=sum(
                        1
                        for report in certification.scenarios
                        for issue in report.repair_suggestions
                    ),
                    error_count_after=0,
                    instruction="<patch request>",
                    reason=f"patch falló: {str(exc)[:200]}",
                )
            )
            break
        next_plan = patched.get("plan")
        if not isinstance(next_plan, dict):
            break
        next_certification = await simulate_semantic_plan(
            next_plan,
            capabilities,
            scenarios,
            organization_id=organization_id,
            workspace_id=workspace_id,
            permissions=permissions,
        )
        before_errors = sum(
            1
            for report in certification.scenarios
            for issue in report.repair_suggestions
        )
        after_errors = sum(
            1
            for report in next_certification.scenarios
            for issue in report.repair_suggestions
        )
        accepted = (
            after_errors <= before_errors
            and len(
                [
                    issue
                    for issue in next_certification.static_validation
                    if issue.severity == "error"
                ]
            )
            <= len(
                [
                    issue
                    for issue in certification.static_validation
                    if issue.severity == "error"
                ]
            )
        )
        attempts.append(
            RepairAttempt(
                attempt=attempt,
                accepted=accepted,
                before_state=certification.state,
                after_state=next_certification.state,
                error_count_before=before_errors,
                error_count_after=after_errors,
                instruction=instruction[:400],
                patch_summary=str((patched.get("patch") or {}).get("summary") or ""),
                reason=None if accepted else "el patch no mejoró la certificación",
            )
        )
        if not accepted:
            break
        current_plan = next_plan
        certification = next_certification
    return {
        "certification": certification.model_dump(mode="json"),
        "plan": current_plan,
        "attempts": [item.model_dump(mode="json") for item in attempts],
        "changed": current_plan != plan,
    }


__all__ = [
    "CERTIFICATION_SCHEMA",
    "CertificationReport",
    "RepairAttempt",
    "SIMULATION_SCHEMA",
    "ScenarioEvent",
    "ScenarioResponse",
    "SimulationIssue",
    "SimulationReport",
    "SimulationScenario",
    "WorkflowSimulationRunner",
    "simulate_semantic_plan",
    "simulate_with_repair",
]
