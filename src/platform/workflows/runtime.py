# =============================================================================
# Phase 32A — Workflow Graph Runtime (executor DAG)
#
# Ejecuta WorkflowGraph con semántica de grafo: entrypoints, edges con
# condiciones, joins (todos los predecesores), merge (primer predecesor),
# for_each (subgrafo acotado), retries por nodo, timeouts, error policies,
# simulación (dry-run), permisos por capability, idempotencia y aprobaciones.
# =============================================================================
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)


@dataclass(frozen=True)
class ExecutionContext:
    """Contexto explícito de ejecución — nunca se resuelve ownership solo con
    el UUID del workflow; todo corre bajo org/workspace/actor verificado."""

    organization_id: UUID
    workflow_id: UUID
    run_id: UUID
    actor_type: str
    trigger_type: str
    permissions: frozenset[str]
    correlation_id: str | None = None
    workspace_id: UUID | None = None
    actor_id: UUID | None = None
    simulate: bool = False


@dataclass
class NodeExecution:
    status: str = "pending"  # succeeded | failed | skipped | simulated | denied | approved
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    retries: int = 0
    duration_ms: int = 0
    simulated: bool = False
    planned: dict[str, Any] = field(default_factory=dict)
    control: str | None = None
    cost_ms: float = 0.0


@dataclass
class RunExecutionResult:
    status: str = "succeeded"  # succeeded | failed | pending_approval | simulated | stopped
    node_executions: dict[str, NodeExecution] = field(default_factory=dict)
    error: str | None = None
    planned_effects: list[dict[str, Any]] = field(default_factory=list)
    duration_ms: int = 0
    cost_ms: float = 0.0
    stopped: bool = False


def _ensure_metrics() -> None:
    try:
        from prometheus_client import Counter, Histogram

        globals()["_workflow_runs_total"] = Counter(
            "workflow_runs_total", "Runs de workflow terminados", ["run_status"]
        )
        globals()["_workflow_nodes_total"] = Counter(
            "workflow_nodes_total", "Nodos de workflow ejecutados", ["node_type", "status"]
        )
        globals()["_workflow_node_latency"] = Histogram(
            "workflow_node_latency_seconds", "Latencia de nodos de workflow", ["node_type"]
        )
    except Exception:  # noqa: BLE001
        globals()["_workflow_runs_total"] = None
        globals()["_workflow_nodes_total"] = None
        globals()["_workflow_node_latency"] = None


_workflow_runs_total: Any = None
_workflow_nodes_total: Any = None
_workflow_node_latency: Any = None
_ensure_metrics()


def _emit_run_metric(status: str) -> None:
    try:
        if _workflow_runs_total is not None:
            _workflow_runs_total.labels(run_status=status).inc()
    except Exception:  # noqa: BLE001
        pass


def _emit_node_metric(node_type: str, status: str, duration_ms: int) -> None:
    try:
        if _workflow_nodes_total is not None:
            _workflow_nodes_total.labels(node_type=node_type, status=status).inc()
        if duration_ms and _workflow_node_latency is not None:
            _workflow_node_latency.labels(node_type=node_type).observe(duration_ms / 1000.0)
    except Exception:  # noqa: BLE001
        pass


async def _persist_node_step(
    ctx: ExecutionContext,
    node_id: str,
    node_type: str,
    step_index: int,
    status: str,
    config: dict,
    output: dict,
    error: str | None,
    retries: int,
    attempt: int,
    started: datetime,
    duration_ms: int,
    idempotency_key: str | None,
) -> None:
    session = await get_async_session()
    try:
        await session.execute(
            text(
            """
            INSERT INTO workflow_run_steps
                (id, run_id, step_index, step_type, node_id, node_type, status,
                 input, output, error, retries, attempt, idempotency_key,
                 started_at, completed_at, duration_ms)
            VALUES (gen_random_uuid(), :rid, :idx, :stype, :nid, :ntype, :status,
                    CAST(:input AS jsonb), CAST(:output AS jsonb), :error, :retries,
                    :attempt, :ikey, :s_at, NOW(), :dur)
            ON CONFLICT DO NOTHING
            """
            ),
            {
                "rid": ctx.run_id,
            "idx": step_index,
            "stype": str(node_type)[:20],
            "nid": node_id,
            "ntype": str(node_type)[:40],
            "status": str(status)[:20],
            "input": json.dumps(config or {}),
            "output": json.dumps(output or {}),
            "error": error,
            "retries": retries,
            "attempt": attempt,
            "ikey": idempotency_key,
            "s_at": started,
            "dur": duration_ms,
        },
        )
        await session.commit()
    finally:
        await session.close()


async def _load_cached_steps(ctx: ExecutionContext) -> dict[str, tuple[str, dict, str | None, int]]:
    """Recupera ejecuciones previas del run (resume tras aprobación)."""
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT node_id, status, output, error, retries FROM workflow_run_steps "
                    "WHERE run_id = :rid AND node_id IS NOT NULL ORDER BY step_index"
                ),
                {"rid": ctx.run_id},
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        r.node_id: (str(r.status), dict(r.output or {}), r.error, int(r.retries or 0))
        for r in rows
    }


async def execute_graph(
    graph,
    ctx: ExecutionContext,
    payload: dict[str, Any],
    *,
    resume: bool = False,
    step_index_start: int = 0,
) -> RunExecutionResult:
    """Ejecuta el grafo completo. `resume` reutiliza pasos persistidos
    (aprobación humana). Devuelve resultados por nodo + estado global."""
    from src.platform.workflows.ir import WorkflowGraphError, validate_graph
    from src.platform.workflows.nodes import NodeContext, registry

    try:
        validate_graph(graph)
    except WorkflowGraphError as exc:
        return RunExecutionResult(status="failed", error=f"grafo inválido: {exc}")

    node_map = graph.node_map
    outgoing: dict[str, list[Any]] = {nid: [] for nid in node_map}
    incoming: dict[str, list[Any]] = {nid: [] for nid in node_map}
    branch_of: dict[str, str] = {}  # nodo del subgrafo for_each → for_each padre
    for edge in graph.edges:
        outgoing.setdefault(edge.from_node, []).append(edge)
        incoming.setdefault(edge.to_node, []).append(edge)
        src = node_map.get(edge.from_node)
        if src is not None and src.type == "for_each" and edge.from_port == "out":
            branch_of[edge.to_node] = edge.from_node

    cached = await _load_cached_steps(ctx) if resume else {}

    executions: dict[str, NodeExecution] = {}
    resolved: set[str] = set()
    executed_edges: set[str] = set()
    skipped_edges: set[str] = set()
    planned_effects: list[dict[str, Any]] = []
    total_cost = 0.0
    run_status = "succeeded"
    run_error: str | None = None
    step_index = step_index_start
    variables: dict[str, Any] = dict(graph.variables or {})
    trigger = payload or {}
    node_outputs_for_refs: dict[str, dict[str, Any]] = {}
    total_started = time.monotonic()

    def node_outcome(node_id: str, status: str, output: dict | None = None, error: str | None = None) -> None:
        executions[node_id] = NodeExecution(status=status, output=output or {}, error=error)
        resolved.add(node_id)
        node_outputs_for_refs[node_id] = {"output": output or {}}

    async def persist(node_id: str, node_type: str, config: dict, exec_: NodeExecution, virtual: bool) -> None:
        nonlocal step_index, planned_effects, total_cost
        if virtual:
            return
        total_cost += exec_.cost_ms
        await _persist_node_step(
            ctx, node_id, node_type, step_index, exec_.status, config,
            exec_.output, exec_.error, exec_.retries, 0,
            datetime.now(timezone.utc), exec_.duration_ms,
            f"{ctx.correlation_id or ctx.run_id}:{node_id}:0",
        )
        step_index += 1
        if exec_.simulated and exec_.planned:
            planned_effects.append({"node_id": node_id, "node_type": node_type, "planned": exec_.planned})

    async def run_node(node_id: str) -> None:
        nonlocal run_status, run_error
        node = node_map[node_id]
        node_def = registry.get(node.type)
        started = datetime.now(timezone.utc)

        # Resume tras aprobación: reutiliza nodos ya OK sin re-ejecutar.
        cached_entry = cached.get(node_id)
        if cached_entry is not None and cached_entry[0] in ("succeeded", "approved", "simulated"):
            status, out, err, retries = cached_entry
            exec_ = NodeExecution(status=status, output=out, error=err, retries=retries,
                                  simulated=status == "simulated")
            await persist(node_id, node.type, node.config, exec_, False)
            executions[node_id] = exec_
            resolved.add(node_id)
            node_outputs_for_refs[node_id] = {"output": out}
            return

        virtual = bool((node.metadata or {}).get("virtual"))
        if node_def is None:
            exec_ = NodeExecution(status="failed", error=f"tipo de nodo desconocido: {node.type}")
            await persist(node_id, node.type, node.config, exec_, virtual)
            node_outcome(node_id, "failed", exec_.output, exec_.error)
            run_status, run_error = "failed", exec_.error
            return
        if virtual or node.type == "end":
            exec_ = NodeExecution(status="succeeded", output={"end": True})
            await persist(node_id, node.type, node.config, exec_, True)
            node_outcome(node_id, "succeeded", exec_.output)
            return

        # Entradas por puerto resueltas.
        inputs: dict[str, dict[str, Any]] = {}
        for edge in incoming.get(node_id, []):
            if edge.id in executed_edges and edge.from_node in executions:
                inputs.setdefault(edge.to_port, {})[edge.from_node] = executions[edge.from_node]

        rctx = NodeContext(
            execution=ctx,
            node=node,
            node_type=node_def,
            node_id=node_id,
            inputs=inputs,
            trigger=trigger,
            payload=payload,
            variables=variables,
            node_outputs=node_outputs_for_refs,
            idempotency_key=None,
            simulate=ctx.simulate,
            cached=cached,
            legacy_index_map=dict(graph.metadata.get("legacy_index_map") or {}),
            run_branch=(lambda branch, item: _run_branch(branch, item, node_id)) if node.type == "for_each" else None,
        )

        # Permisos por capability.
        denied_perm = None
        for cap in node_def.capabilities:
            try:
                from src.platform.workflows.nodes import capability_permission

                perm = capability_permission(cap)
            except Exception:  # noqa: BLE001
                perm = None
            if perm and perm not in ctx.permissions:
                denied_perm = perm
                break
        if denied_perm is not None:
            exec_ = NodeExecution(status="denied", error=f"permiso insuficiente: {denied_perm}")
            _emit_node_metric(node.type, "denied", 0)
            await persist(node_id, node.type, node.config, exec_, virtual)
            node_outcome(node_id, "denied", exec_.output, exec_.error)
            run_status, run_error = "failed", exec_.error
            return

        # Ejecución con retries + timeout.
        max_attempts = max(1, int((node.retry_policy or {}).get("max_attempts", 1) or 1))
        timeout_ms = max(1, int(node.timeout_ms or 60_000))
        handler = node_def.execute
        last_error: str | None = None
        exec_ = None
        attempt = 0
        while attempt < max_attempts:
            attempt += 1
            rctx.idempotency_key = f"{ctx.correlation_id or ctx.run_id}:{node_id}:{attempt}"
            if attempt > 1 and "fail_once" in (rctx.node.config or {}):
                import dataclasses

                rctx.node = dataclasses.replace(
                    rctx.node,
                    config={k: v for k, v in rctx.node.config.items() if k != "fail_once"},
                )
            try:
                outcome = await asyncio.wait_for(handler(rctx), timeout=timeout_ms / 1000.0)
            except asyncio.TimeoutError:
                last_error = f"timeout tras {timeout_ms}ms"
                outcome = None
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)[:300]
                outcome = None
            if outcome is not None and outcome.error is None:
                exec_ = NodeExecution(
                    status="simulated" if outcome.simulated else "succeeded",
                    output=dict(outcome.output or {}),
                    retries=attempt - 1,
                    duration_ms=int((datetime.now(timezone.utc) - started).total_seconds() * 1000),
                    simulated=bool(outcome.simulated),
                    planned=dict(outcome.planned or {}),
                    control=outcome.control,
                    cost_ms=float(outcome.cost_ms or 0.0),
                )
                break
            if outcome is not None and outcome.error:
                last_error = outcome.error
        if exec_ is None:
            exec_ = NodeExecution(status="failed", error=last_error, retries=attempt - 1)
        # Semántica legacy: condición evaluada falsa → nodo "skipped".
        if (
            node.type == "condition"
            and exec_.status == "succeeded"
            and exec_.output.get("result") is False
        ):
            exec_.status = "skipped"
        _emit_node_metric(node.type, exec_.status, exec_.duration_ms)
        await persist(node_id, node.type, node.config, exec_, virtual)
        node_outcome(node_id, exec_.status, exec_.output, exec_.error)

        if exec_.status == "failed":
            policy = node.error_policy or "fail"
            if policy in ("continue", "continue_on_error"):
                return  # sigue el flujo (edges propagados como ejecutados)
            run_status = "failed"
            run_error = exec_.error or "error de nodo"
            return
        if exec_.control == "stop_success":
            run_status = "stopped"
            return
        if exec_.control == "stop_fail":
            run_status = "failed"
            run_error = str(exec_.output.get("message") or "stop solicitado")
            return
        if exec_.control == "wait_approval":
            run_status = "pending_approval"
            return

    async def propagate(node_id: str) -> None:
        """Marca edges salientes resolubles (ejecutados o saltados); los tipos
        condition/for_each eligen puerto según resultado. No ejecuta nodos:
        el scheduler de waves dispara los targets listos."""
        node = node_map[node_id]
        exec_ = executions.get(node_id)
        if exec_ is None:
            return
        if node.type == "condition":
            result = bool((exec_.output or {}).get("result"))
            taken = "then" if result else "else"
            for edge in outgoing.get(node_id, []):
                if edge.from_port == taken:
                    executed_edges.add(edge.id)
                else:
                    skipped_edges.add(edge.id)
        elif node.type == "for_each":
            for edge in outgoing.get(node_id, []):
                if edge.from_port == "done":
                    executed_edges.add(edge.id)
                else:
                    skipped_edges.add(edge.id)
        else:
            for edge in outgoing.get(node_id, []):
                if edge.from_port == "out":
                    executed_edges.add(edge.id)
                else:
                    skipped_edges.add(edge.id)

    async def _run_branch(branch: list[str], item: Any, parent_id: str) -> dict[str, NodeExecution]:
        """Ejecuta el subgrafo de un for_each para un ítem (acotado por handler)."""
        outcomes: dict[str, NodeExecution] = {}
        for bid in branch:
            node = node_map.get(bid)
            if node is None or node.type == "end" or (node.metadata or {}).get("virtual"):
                outcomes[bid] = NodeExecution(status="succeeded", output={"end": True})
                continue
            node_def = registry.get(node.type)
            if node_def is None:
                outcomes[bid] = NodeExecution(status="failed", error=f"tipo desconocido: {node.type}")
                continue
            started = datetime.now(timezone.utc)
            inputs = {"in": {parent_id: NodeExecution(output={"item": item})}}
            rctx = NodeContext(
                execution=ctx,
                node=node,
                node_type=node_def,
                node_id=bid,
                inputs=inputs,
                trigger=trigger,
                payload=payload,
                variables=variables,
                node_outputs=node_outputs_for_refs,
                idempotency_key=None,
                simulate=ctx.simulate,
                cached={},
                legacy_index_map=dict(graph.metadata.get("legacy_index_map") or {}),
                run_branch=None,
            )
            try:
                exec_ = await _run_node_once(ctx, node_def, rctx, started)
            except Exception as exc:  # noqa: BLE001
                exec_ = NodeExecution(status="failed", error=str(exc)[:200])
            outcomes[bid] = exec_
        return outcomes

    # --- Scheduler principal (determinístico, waves por orden de id) --------
    processed: set[str] = set()
    entry_set = set(graph.entrypoints)
    ordered_ids = list(graph.entrypoints) + sorted(
        (n for n in node_map if n not in entry_set), key=lambda x: x
    )
    guard = 0
    while run_status == "succeeded":
        advanced = False
        for node_id in ordered_ids:
            if node_id in resolved or node_id in processed or node_id in branch_of:
                continue
            node = node_map[node_id]
            if node.type == "merge":
                ready = any(inc.id in executed_edges for inc in incoming.get(node_id, []))
            elif node_id in entry_set and not incoming.get(node_id):
                ready = True
            else:
                ready = _ready_check(incoming, executed_edges, skipped_edges, node_id)
            if not ready:
                continue
            await run_node(node_id)
            processed.add(node_id)
            await propagate(node_id)
            advanced = True
            if run_status != "succeeded":
                break
        if run_status != "succeeded":
            break
        if not advanced:
            # Cascada de skip: nodos muertos (todos sus entrantes saltados o
            # terminales virtuales sin dependencia) cierran sus edges como
            # skipped para no bloquear joins posteriores.
            dead = [
                nid
                for nid in node_map
                if nid not in resolved
                and nid not in branch_of
                and all(
                    inc.id in skipped_edges
                    for inc in incoming.get(nid, [])
                )
                and (
                    bool(incoming.get(nid))
                    or nid not in entry_set
                )
            ]
            if dead:
                for nid in dead:
                    executions[nid] = NodeExecution(status="skipped", output={})
                    resolved.add(nid)
                    _emit_node_metric(node_map[nid].type, "skipped", 0)
                    for edge in outgoing.get(nid, []):
                        skipped_edges.add(edge.id)
                advanced = True
                continue
            # Nodos sueltos sin predecesores ni entrypoint → skipped (no romper).
            for node_id in node_map:
                if node_id not in resolved and node_id not in branch_of:
                    executions[node_id] = NodeExecution(status="skipped", output={})
                    resolved.add(node_id)
                    _emit_node_metric(node_map[node_id].type, "skipped", 0)
            break
        guard += 1
        if guard > 10_000:
            run_status = "failed"
            run_error = "ejecución excedió iteraciones (¿grafo con ciclos?)"
            break

    # Nodos del subgrafo for_each y no ejecutados → skipped de cierre.
    for node_id, _node in node_map.items():
        if node_id not in resolved and node_id not in branch_of:
            if run_status in ("failed", "pending_approval", "stopped"):
                executions[node_id] = NodeExecution(status="skipped", output={})
                resolved.add(node_id)
    _emit_run_metric(run_status if run_status != "pending_approval" else "pending_approval")
    return RunExecutionResult(
        status=run_status,
        node_executions=executions,
        error=run_error,
        planned_effects=planned_effects,
        duration_ms=int((time.monotonic() - total_started) * 1000),
        cost_ms=total_cost,
        stopped=run_status == "stopped",
    )


def _ready_check(
    incoming: dict[str, list[Any]],
    executed_edges: set[str],
    skipped_edges: set[str],
    node_id: str,
) -> bool:
    """Nodo listo ⇔ todos sus edges entrantes resueltos y ≥1 ejecutado."""
    if not incoming.get(node_id):
        return False
    for inc in incoming.get(node_id, []):
        if inc.id not in executed_edges and inc.id not in skipped_edges:
            return False
    return any(inc.id in executed_edges for inc in incoming.get(node_id, []))


async def _run_node_once(ctx: ExecutionContext, node_def, rctx, started: datetime) -> NodeExecution:
    """Ejecución simple (sin persistencia) para subgrafos de for_each."""
    handler = node_def.execute
    node = rctx.node
    max_attempts = max(1, int((node.retry_policy or {}).get("max_attempts", 1) or 1))
    timeout_ms = max(1, int(node.timeout_ms or 60_000))
    last_error: str | None = None
    outcome = None
    attempt = 0
    while attempt < max_attempts:
        attempt += 1
        rctx.idempotency_key = f"{ctx.run_id}:{node.id}:{attempt}"
        if attempt > 1 and "fail_once" in (rctx.node.config or {}):
            import dataclasses

            rctx.node = dataclasses.replace(
                rctx.node,
                config={k: v for k, v in rctx.node.config.items() if k != "fail_once"},
            )
        try:
            outcome = await asyncio.wait_for(handler(rctx), timeout=timeout_ms / 1000.0)
        except asyncio.TimeoutError:
            last_error = f"timeout tras {timeout_ms}ms"
            outcome = None
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)[:300]
            outcome = None
        if outcome is not None and outcome.error is None:
            break
        if outcome is not None and outcome.error:
            last_error = outcome.error
    if outcome is None:
        return NodeExecution(status="failed", error=last_error, retries=attempt - 1)
    return NodeExecution(
        status="simulated" if outcome.simulated else "succeeded",
        output=dict(outcome.output or {}),
        retries=attempt - 1,
        duration_ms=int((datetime.now(timezone.utc) - started).total_seconds() * 1000),
        simulated=bool(outcome.simulated),
        planned=dict(outcome.planned or {}),
        control=outcome.control,
        cost_ms=float(outcome.cost_ms or 0.0),
    )

