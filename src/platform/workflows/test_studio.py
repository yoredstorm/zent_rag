# =============================================================================
# Workflow Test Studio — nivel decidido por el servidor.
#
# Preview no ejecuta. Simulación usa el runner existente. Sandbox/provider se
# degradan explícitamente si no hay adaptador real; nunca se emite
# PROVIDER_VERIFIED por un fake. El reporte se persiste con hashes.
# =============================================================================
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text

from src.infrastructure.postgres.session import get_async_session
from src.platform.workflows.ir import WorkflowGraph, validate_graph
from src.platform.workflows.test_report import (
    LEVELS,
    draft_to_scenario,
    explain_report,
    graph_fingerprint,
    mask_value,
)
from src.platform.workflows.workflow_simulation import WorkflowSimulationRunner

TEST_REPORT_SCHEMA = "zent.workflow.test-report/v1"
PROVIDER_VERIFIED = "PROVIDER_VERIFIED"


@dataclass(frozen=True)
class LevelDecision:
    requested: str
    effective: str
    capped_reason: str | None = None
    sandbox_ready: bool = False
    provider_ready: bool = False

    def public(self) -> dict[str, Any]:
        return {
            "requested_level": self.requested,
            "effective_level": self.effective,
            "capped_reason": self.capped_reason,
            "sandbox_ready": self.sandbox_ready,
            "provider_ready": self.provider_ready,
        }


def decide_test_level(
    requested: str,
    *,
    sandbox_ready: bool = False,
    provider_ready: bool = False,
) -> LevelDecision:
    """El servidor solo baja el nivel; jamás inventa un proveedor."""
    level = str(requested or "simulation").strip().lower()
    if level not in LEVELS:
        raise ValueError(f"test_level inválido: {requested}")
    if level in {"preview", "simulation"}:
        return LevelDecision(level, level, sandbox_ready=sandbox_ready)
    if level == "sandbox" and sandbox_ready:
        return LevelDecision(level, level, sandbox_ready=True)
    if level == "provider" and provider_ready:
        return LevelDecision(level, level, provider_ready=True)
    return LevelDecision(
        level,
        "simulation",
        capped_reason=(
            "sandbox_adapter_unavailable"
            if level == "sandbox"
            else "provider_adapter_unavailable"
        ),
        sandbox_ready=sandbox_ready,
        provider_ready=provider_ready,
    )


def _scope_hash(value: Any) -> str:
    blob = json.dumps(value or {}, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def report_hashes(workflow: dict[str, Any], graph: dict[str, Any]) -> dict[str, str]:
    meta = graph.get("metadata") if isinstance(graph.get("metadata"), dict) else {}
    role_refs = [
        str((node.get("config") or {}).get("agent_id") or "")
        for node in graph.get("nodes") or []
        if isinstance(node, dict)
        and (node.get("config") or {}).get("agent_id")
    ]
    binding_refs = meta.get("bindings") or meta.get("data_mapping") or {}
    graph_hash = graph_fingerprint(graph)
    return {
        "graph_hash": graph_hash,
        "plan_hash": str(meta.get("semantic_plan_hash") or graph_hash),
        "role_hash": _scope_hash(sorted(set(role_refs))),
        "binding_hash": _scope_hash(binding_refs),
    }


async def save_test_report(
    *,
    organization_id: UUID,
    workspace_id: UUID | None,
    workflow_id: UUID,
    report: dict[str, Any],
    scenario: dict[str, Any],
    created_by: UUID | None,
) -> dict[str, Any]:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO workflow_test_reports "
                    "(organization_id, workspace_id, workflow_id, requested_level, "
                    "effective_level, result, graph_hash, plan_hash, role_hash, binding_hash, "
                    "scenario, report, created_by) VALUES "
                    "(:oid, :ws, :wid, :requested, :effective, :result, :graph_hash, "
                    ":plan_hash, :role_hash, :binding_hash, CAST(:scenario AS jsonb), "
                    "CAST(:report AS jsonb), :by) RETURNING id, created_at"
                ),
                {
                    "oid": organization_id,
                    "ws": workspace_id,
                    "wid": workflow_id,
                    "requested": report["requested_level"],
                    "effective": report["effective_level"],
                    "result": report["result"],
                    "graph_hash": report["hashes"]["graph_hash"],
                    "plan_hash": report["hashes"]["plan_hash"],
                    "role_hash": report["hashes"]["role_hash"],
                    "binding_hash": report["hashes"]["binding_hash"],
                    "scenario": json.dumps(scenario, default=str),
                    "report": json.dumps(report, default=str),
                    "by": created_by,
                },
            )
        ).fetchone()
        await session.commit()
    finally:
        await session.close()
    return {
        "report_id": str(row.id),
        "created_at": row.created_at.isoformat() if row and row.created_at else None,
    }


async def list_test_reports(
    organization_id: UUID,
    workflow_id: UUID,
    *,
    workspace_id: UUID | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    from sqlalchemy import text

    clauses = ["organization_id = :oid", "workflow_id = :wid"]
    params: dict[str, Any] = {
        "oid": organization_id,
        "wid": workflow_id,
        "lim": min(max(int(limit), 1), 100),
    }
    if workspace_id is not None:
        clauses.append("(workspace_id = :ws OR workspace_id IS NULL)")
        params["ws"] = workspace_id
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT id, requested_level, effective_level, result, graph_hash, "
                    "plan_hash, role_hash, binding_hash, report, created_at "
                    "FROM workflow_test_reports WHERE "
                    + " AND ".join(clauses)
                    + " ORDER BY created_at DESC LIMIT :lim"
                ),
                params,
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "items": [
            {
                "report_id": str(row.id),
                "requested_level": row.requested_level,
                "effective_level": row.effective_level,
                "result": row.result,
                "hashes": {
                    "graph_hash": row.graph_hash,
                    "plan_hash": row.plan_hash,
                    "role_hash": row.role_hash,
                    "binding_hash": row.binding_hash,
                },
                "report": row.report,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ]
    }


async def execute_workflow_test(
    *,
    organization_id: UUID,
    workspace_id: UUID | None,
    workflow: dict[str, Any],
    workflow_id: UUID,
    requested_level: str,
    scenario_draft: dict[str, Any],
    permissions: frozenset[str],
    created_by: UUID | None = None,
) -> dict[str, Any]:
    graph = workflow.get("graph") if isinstance(workflow.get("graph"), dict) else {}
    graph = dict(graph or {})
    try:
        validate_graph(WorkflowGraph.from_dict(graph))
    except Exception as exc:  # noqa: BLE001 — un grafo inválido es reporte BLOCKED
        decision = decide_test_level(requested_level)
        report = {
            "schema": TEST_REPORT_SCHEMA,
            "test_report_id": f"test_{uuid4().hex}",
            "workflow_id": str(workflow_id),
            "requested_level": decision.requested,
            "effective_level": decision.effective,
            "capped_reason": decision.capped_reason,
            "provider_verified": False,
            "result": "BLOCKED",
            "state": "BLOCKED",
            "hashes": report_hashes(workflow, graph),
            "scenario": mask_value(scenario_draft),
            "timeline": [],
            "executed_nodes": [],
            "why": f"Grafo inválido: {str(exc)[:240]}",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        persisted = await save_test_report(
            organization_id=organization_id,
            workspace_id=workspace_id,
            workflow_id=workflow_id,
            report=report,
            scenario=scenario_draft,
            created_by=created_by,
        )
        report.update(persisted)
        return report

    from src.platform.workflows.verification import (
        VerificationError,
        resolve_readiness,
        run_verification,
    )

    readiness = await resolve_readiness(organization_id, workspace_id, graph)
    decision = decide_test_level(
        requested_level,
        sandbox_ready=readiness.sandbox_ready,
        provider_ready=readiness.provider_ready,
    )
    hashes = report_hashes(workflow, graph)
    if decision.effective == "preview":
        report = {
            "schema": TEST_REPORT_SCHEMA,
            "test_report_id": f"test_{uuid4().hex}",
            "workflow_id": str(workflow_id),
            "requested_level": decision.requested,
            "effective_level": decision.effective,
            "capped_reason": decision.capped_reason,
            "provider_verified": False,
            "result": "PREVIEW",
            "state": "PREVIEW_ONLY",
            "hashes": hashes,
            "scenario": mask_value(scenario_draft),
            "timeline": [],
            "executed_nodes": [],
            "why": "Preview teórico: no ejecuta nodos ni efectos.",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    else:
        verification: dict[str, Any] | None = None
        if decision.effective in ("sandbox", "provider"):
            try:
                verification = await run_verification(
                    organization_id,
                    workflow_id,
                    graph,
                    level=decision.effective,
                    workspace_id=workspace_id,
                    scenarios=[scenario_draft],
                    issued_by=created_by,
                )
                result = "PASSED"
                state = verification["state"]
            except VerificationError as exc:
                result = "UNVERIFIED"
                state = "UNVERIFIED"
                verification = {"error": exc.code, "details": exc.details}
        else:
            scenario = draft_to_scenario(
                {
                    **scenario_draft,
                    "scenario_id": str(scenario_draft.get("scenario_id") or uuid4().hex[:12]),
                }
            )
            runner = WorkflowSimulationRunner(
                graph,
                capabilities={},
                steps_map={},
                organization_id=organization_id,
                workspace_id=workspace_id,
                permissions=permissions,
                workflow_version=int(graph.get("workflow_version") or 2),
            )
            simulation = await runner.run_scenario(scenario)
            result = simulation.result
            state = simulation.result
            if decision.requested == "provider" and decision.effective != "provider":
                result = "UNVERIFIED"
        report = {
            "schema": TEST_REPORT_SCHEMA,
            "test_report_id": f"test_{uuid4().hex}",
            "workflow_id": str(workflow_id),
            "requested_level": decision.requested,
            "effective_level": decision.effective,
            "capped_reason": decision.capped_reason,
            "provider_verified": bool(
                decision.effective == "provider"
                and verification
                and verification.get("state") == "PROVIDER_VERIFIED"
            ),
            "result": result,
            "state": state,
            "hashes": hashes,
            "scenario": mask_value(scenario_draft),
            "verification": verification,
            "readiness": {
                "sandbox_ready": readiness.sandbox_ready,
                "provider_ready": readiness.provider_ready,
                "reasons": readiness.reasons,
                "provider_refs": readiness.provider_refs,
            },
            "simulation": simulation.model_dump(mode="json")
            if decision.effective not in ("sandbox", "provider")
            else None,
            "timeline": list(simulation.timeline or [])
            if decision.effective not in ("sandbox", "provider")
            else [],
            "executed_nodes": list(simulation.executed_nodes or [])
            if decision.effective not in ("sandbox", "provider")
            else [],
            "explain": explain_report(
                level=decision.effective,
                result=result,
                unverified=list(getattr(simulation, "unverified_nodes", []) or [])
                if decision.effective not in ("sandbox", "provider")
                else [],
                failed=[
                    str(item.get("node_id"))
                    for item in getattr(simulation, "failed_nodes", []) or []
                ]
                if decision.effective not in ("sandbox", "provider")
                else [],
                duration_ms=int((getattr(simulation, "trace", {}) or {}).get("duration_ms") or 0)
                if decision.effective not in ("sandbox", "provider")
                else int((verification or {}).get("duration_ms") or 0),
            ),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    persisted = await save_test_report(
        organization_id=organization_id,
        workspace_id=workspace_id,
        workflow_id=workflow_id,
        report=report,
        scenario=scenario_draft,
        created_by=created_by,
    )
    report.update(persisted)
    return report


__all__ = [
    "LevelDecision",
    "PROVIDER_VERIFIED",
    "TEST_REPORT_SCHEMA",
    "decide_test_level",
    "execute_workflow_test",
    "list_test_reports",
    "report_hashes",
    "save_test_report",
]
