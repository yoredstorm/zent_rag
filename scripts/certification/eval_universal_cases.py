# =============================================================================
# Universal Studio — real-provider evaluation harness.
#
# This is NOT a pytest test: it calls the authorized real provider for every
# case, measures the observed plan and writes JSON/Markdown evidence. It never
# publishes, installs, connects credentials or executes business effects.
#
# Usage:
#   $env:RAG_CERT_REAL_LLM="1"
#   .venv/Scripts/python.exe scripts/certification/eval_universal_cases.py \
#       --limit 100 --concurrency 3 --out artifacts/certification/ai/universal-eval.json
# =============================================================================
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import random
import shutil
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from src.api.main import app  # noqa: E402
from src.infrastructure.postgres.session import get_async_session  # noqa: E402
from src.platform.workflows.architect_discovery import (  # noqa: E402
    capabilities_from_snapshot,
)
from src.platform.workflows.architect_models import PLAN_STEP_TYPES  # noqa: E402
from src.platform.workflows.capability_registry import (  # noqa: E402
    build_capability_snapshot,
)
from src.platform.workflows.ir import WorkflowGraph, validate_graph  # noqa: E402
from src.platform.workflows.planner_session import (  # noqa: E402
    PlannerBudget,
    PlannerBudgetExceeded,
    WorkflowPlanningSession,
)
from src.platform.workflows.workflow_simulation import (  # noqa: E402
    SimulationScenario,
    simulate_semantic_plan,
)
from tests.certification.workflows.gold_support import (  # noqa: E402
    ready_tenant,
)
from tests.conftest import attach_auto_idempotency  # noqa: E402

CASES_PATH = ROOT / "tests" / "certification" / "ai" / "universal_cases.json"


def _plan_refs(plan: dict[str, Any] | None) -> list[str]:
    refs: list[str] = []
    for step in (plan or {}).get("steps") or []:
        params = step.get("params") or {}
        ref = params.get("capability") or params.get("action_id")
        if ref:
            refs.append(str(ref))
        if step.get("type") == "agent_analysis" and params.get("agent_id"):
            refs.append(f"agent.{params['agent_id']}")
    return refs


def _step_types(plan: dict[str, Any] | None) -> set[str]:
    return {str(step.get("type")) for step in (plan or {}).get("steps") or []}


def _contract_errors(issues: list[dict[str, Any]]) -> list[str]:
    return [
        str(issue.get("code"))
        for issue in issues
        if str(issue.get("code", "")).startswith(
            ("contract.", "missing.capability", "capability.unknown", "capability.unavailable")
        )
    ]


async def _seed_resources(organization_id: str, workspace_id: str | None) -> None:
    """Add a real KB and managed DB so multi-domain cases have resources."""
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO knowledge_bases (id, organization_id, workspace_id, name) "
                "VALUES (gen_random_uuid(), :oid, :ws, :name)"
            ),
            {
                "oid": organization_id,
                "ws": workspace_id,
                "name": "Base de conocimiento de certificación",
            },
        )
        await session.execute(
            text(
                "INSERT INTO managed_databases (id, organization_id, workspace_id, db_name) "
                "VALUES (gen_random_uuid(), :oid, :ws, :db)"
            ),
            {
                "oid": organization_id,
                "ws": workspace_id,
                "db": "cert_universal_eval",
            },
        )
        await session.commit()
    finally:
        await session.close()


async def _run_case(
    case: dict[str, Any],
    *,
    organization_id: UUID,
    workspace_id: UUID | None,
    snapshot: Any,
    capabilities: dict[str, Any],
    budget: PlannerBudget,
    semaphore: asyncio.Semaphore,
) -> dict[str, Any]:
    async with semaphore:
        started = time.perf_counter()
        result: dict[str, Any] = {}
        error: str | None = None
        try:
            planner = WorkflowPlanningSession(
                organization_id,
                workspace_id=workspace_id,
                permissions=frozenset({"admin:*"}),
                snapshot=snapshot,
                budget=budget,
                record_usage=False,
                estimate_cost=False,
            )
            result = await planner.run(case["prompt"])
        except PlannerBudgetExceeded as exc:
            error = f"budget_exceeded:{exc.reason}"
        except Exception as exc:  # noqa: BLE001 - eval must continue
            error = f"{type(exc).__name__}: {str(exc)[:300]}"
        latency_ms = int((time.perf_counter() - started) * 1000)

        plan = result.get("plan")
        issues = result.get("issues") or []
        expected = case.get("expected") or {}
        index = capabilities.get("capability_index") or {}
        declared_refs = [str(ref) for ref in expected.get("capability_refs") or []]
        # El dataset histórico mezcla node types con capability refs. Se separan
        # para no inflar/denigrar la métrica de capacidades.
        expected_refs = [ref for ref in declared_refs if "." in ref or ref in index]
        expected_steps = [
            str(item) for item in (expected.get("step_types") or [])
        ] + [ref for ref in declared_refs if ref in PLAN_STEP_TYPES]
        plan_refs = _plan_refs(plan)
        matched = [ref for ref in expected_refs if ref in plan_refs]
        valid_plan_refs = [ref for ref in plan_refs if ref in index]
        observed_steps = _step_types(plan)
        step_coverage = (
            round(
                len(observed_steps & set(expected_steps)) / len(set(expected_steps)),
                4,
            )
            if expected_steps
            else None
        )
        safety_ok = True
        if case.get("safety") == "no_diagnosis":
            text = json.dumps(plan or {}, ensure_ascii=False).lower()
            safety_ok = not any(
                term in text
                for term in ("diagnóstico", "diagnostico", "prescribe", "prescripción")
            )
        graph = result.get("graph")
        graph_valid = False
        if graph is not None:
            try:
                validate_graph(WorkflowGraph.from_dict(graph))
                graph_valid = True
            except Exception:  # noqa: BLE001
                graph_valid = False
        simulation_state = None
        simulation_executed = False
        if plan and graph:
            try:
                scenario = SimulationScenario(
                    scenario_id=f"{case['id']}-smoke",
                    name="smoke",
                    initial_inputs={},
                    expected_result="WAITING",
                    max_segments=3,
                )
                certification = await simulate_semantic_plan(
                    plan,
                    capabilities,
                    [scenario],
                    organization_id=organization_id,
                    workspace_id=workspace_id,
                    permissions=frozenset({"admin:*"}),
                )
                simulation_state = certification.state
                simulation_executed = True
            except Exception as exc:  # noqa: BLE001
                simulation_state = f"error:{type(exc).__name__}"
        usage = result.get("usage") or {}
        return {
            "id": case["id"],
            "domain": case["domain"],
            "error": error,
            "state": result.get("state"),
            "intent_valid": bool(result.get("specification")),
            "capability_selection": {
                "expected_available": expected_refs,
                "plan_refs": plan_refs,
                "matched": matched,
                "recall": round(len(matched) / len(expected_refs), 4)
                if expected_refs
                else None,
                "valid_refs": valid_plan_refs,
                "invalid_refs": [ref for ref in plan_refs if ref not in index],
            },
            "contract_errors": _contract_errors(issues),
            "graph_valid": graph_valid,
            "simulation_executed": simulation_executed,
            "simulation_state": simulation_state,
            "durable_expected": bool(expected.get("requires_durable")),
            "durable_observed": bool(result.get("requires_durable_instance")),
            "approval_expected": bool(expected.get("requires_approval")),
            "approval_observed": "human_approval" in _step_types(plan),
            "step_types_expected": sorted(set(expected_steps)),
            "step_types_observed": sorted(observed_steps & set(PLAN_STEP_TYPES)),
            "step_type_coverage": step_coverage,
            "safety_ok": safety_ok,
            "exception_coverage": len(
                _step_types(plan)
                & {"wait", "decision", "human_approval", "stop", "compensation"}
            )
            > 0,
            "latency_ms": latency_ms,
            "tokens": int(usage.get("total_tokens") or 0),
            "llm_calls": int(usage.get("llm_calls") or 0),
            "tool_calls": int(usage.get("tool_calls") or 0),
            "cost_usd": float(usage.get("estimated_cost_usd") or 0.0),
            "planner_model": (result.get("planner") or {}).get("model"),
            "plan_hash": result.get("plan_hash"),
            "snapshot_hash": (result.get("capability_snapshot") or {}).get(
                "snapshot_hash"
            ),
            "budget_estimate": result.get("budget_estimate"),
            "diagnostic": result.get("diagnostic"),
        }


def _pct(values: list[int], percentile: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(len(ordered) * percentile) - 1))
    return ordered[index]


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def rate(key: str) -> float:
        return round(sum(1 for row in rows if row.get(key)) / len(rows), 4) if rows else 0.0

    latencies = [row["latency_ms"] for row in rows]
    tokens = [row["tokens"] for row in rows]
    costs = [row["cost_usd"] for row in rows]
    capability_rows = [
        row
        for row in rows
        if (row.get("capability_selection") or {}).get("expected_available")
    ]
    capability_rate = (
        round(
            sum(
                float((row.get("capability_selection") or {}).get("recall") or 0.0)
                for row in capability_rows
            )
            / len(capability_rows),
            4,
        )
        if capability_rows
        else None
    )
    step_rows = [row for row in rows if row.get("step_type_coverage") is not None]
    step_rate = (
        round(
            sum(float(row.get("step_type_coverage") or 0.0) for row in step_rows)
            / len(step_rows),
            4,
        )
        if step_rows
        else None
    )
    by_domain: dict[str, dict[str, Any]] = {}
    for row in rows:
        domain = str(row.get("domain") or "unknown")
        bucket = by_domain.setdefault(
            domain,
            {"cases": 0, "errors": 0, "graph_valid": 0, "intent_valid": 0},
        )
        bucket["cases"] += 1
        bucket["errors"] += 1 if row.get("error") else 0
        bucket["graph_valid"] += 1 if row.get("graph_valid") else 0
        bucket["intent_valid"] += 1 if row.get("intent_valid") else 0
    for bucket in by_domain.values():
        total = max(1, int(bucket["cases"]))
        bucket["graph_valid_rate"] = round(bucket["graph_valid"] / total, 4)
        bucket["intent_valid_rate"] = round(bucket["intent_valid"] / total, 4)
    states: dict[str, int] = {}
    errors_by_reason: dict[str, int] = {}
    for row in rows:
        state = str(row.get("state") or "none")
        states[state] = states.get(state, 0) + 1
        error = row.get("error")
        if error:
            key = str(error).split(":", 1)[0]
            errors_by_reason[key] = errors_by_reason.get(key, 0) + 1
    return {
        "cases": len(rows),
        "errors": sum(1 for row in rows if row.get("error")),
        "intent_valid_rate": rate("intent_valid"),
        "graph_valid_rate": rate("graph_valid"),
        "graph_valid_rate_resolved": round(
            sum(
                1
                for row in rows
                if row.get("graph_valid") and not row.get("error")
            )
            / max(1, sum(1 for row in rows if not row.get("error"))),
            4,
        ),
        "capability_recall_rate": capability_rate,
        "capability_cases": len(capability_rows),
        "step_type_coverage_rate": step_rate,
        "safety_rate": rate("safety_ok"),
        "contract_clean_rate": round(
            sum(1 for row in rows if not row.get("contract_errors")) / len(rows), 4
        )
        if rows
        else 0.0,
        "simulation_executed_rate": rate("simulation_executed"),
        "durable_match_rate": round(
            sum(
                1
                for row in rows
                if row.get("durable_expected") == row.get("durable_observed")
            )
            / len(rows),
            4,
        )
        if rows
        else 0.0,
        "approval_match_rate": round(
            sum(
                1
                for row in rows
                if row.get("approval_expected") == row.get("approval_observed")
            )
            / len(rows),
            4,
        )
        if rows
        else 0.0,
        "exception_coverage_rate": rate("exception_coverage"),
        "mean_latency_ms": round(statistics.mean(latencies), 2) if latencies else 0.0,
        "p50_latency_ms": _pct(latencies, 0.50),
        "p95_latency_ms": _pct(latencies, 0.95),
        "p99_latency_ms": _pct(latencies, 0.99),
        "total_tokens": sum(tokens),
        "mean_tokens": round(statistics.mean(tokens), 2) if tokens else 0.0,
        "total_cost_usd": round(sum(costs), 6),
        "states": states,
        "errors_by_reason": errors_by_reason,
        "by_domain": by_domain,
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--per-domain", type=int, default=0)
    parser.add_argument("--domains", default="")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--model", default="")
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--out", default="artifacts/certification/ai/universal-eval.json")
    parser.add_argument("--max-llm-calls", type=int, default=6)
    parser.add_argument("--max-tool-calls", type=int, default=4)
    parser.add_argument("--max-tokens", type=int, default=40_000)
    parser.add_argument("--max-seconds", type=float, default=120.0)
    parser.add_argument("--repairs", type=int, default=0)
    parser.add_argument("--max-cost", type=float, default=0.50)
    parser.add_argument("--fail-under-intent", type=float, default=None)
    parser.add_argument("--fail-under-graph", type=float, default=None)
    parser.add_argument("--fail-under-capability", type=float, default=None)
    args = parser.parse_args()

    if os.environ.get("RAG_CERT_REAL_LLM") != "1":
        raise SystemExit("set RAG_CERT_REAL_LLM=1 with authorized real credentials")

    all_cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    domains = [item.strip() for item in str(args.domains).split(",") if item.strip()]
    if domains:
        all_cases = [case for case in all_cases if case.get("domain") in domains]
    rng = random.Random(args.seed)  # noqa: S311 — muestreo reproducible, no criptográfico
    rng.shuffle(all_cases)
    if args.per_domain:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for case in all_cases:
            grouped.setdefault(str(case.get("domain")), []).append(case)
        selected: list[dict[str, Any]] = []
        for domain in sorted(grouped):
            selected.extend(grouped[domain][: args.per_domain])
        all_cases = selected
    cases = all_cases[: args.limit]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        client = attach_auto_idempotency(client)
        org = await ready_tenant(
            client,
            "Universal Eval Real",
            with_payments=True,
            with_agent=True,
        )
        organization_id = UUID(org["organization_id"])
        session = await get_async_session()
        try:
            workspace_row = (
                await session.execute(
                    text(
                        "SELECT id FROM workspaces WHERE organization_id = :oid "
                        "ORDER BY created_at LIMIT 1"
                    ),
                    {"oid": str(organization_id)},
                )
            ).fetchone()
        finally:
            await session.close()
        workspace_id = UUID(str(workspace_row.id)) if workspace_row else None
        await _seed_resources(str(organization_id), str(workspace_id) if workspace_id else None)
        snapshot = await build_capability_snapshot(
            organization_id,
            workspace_id,
            permissions=frozenset({"admin:*"}),
            force_refresh=True,
        )
        capabilities = capabilities_from_snapshot(snapshot)

    budget = PlannerBudget(
        max_llm_calls=args.max_llm_calls,
        max_tool_calls=args.max_tool_calls,
        max_tokens=args.max_tokens,
        max_cost_usd=args.max_cost,
        max_duration_seconds=args.max_seconds,
        max_repair_attempts=args.repairs,
        max_candidates=5,
        max_steps=12,
    )
    semaphore = asyncio.Semaphore(args.concurrency)
    rows = await asyncio.gather(
        *(
            _run_case(
                case,
                organization_id=organization_id,
                workspace_id=workspace_id,
                snapshot=snapshot,
                capabilities=capabilities,
                budget=budget,
                semaphore=semaphore,
            )
            for case in cases
        )
    )
    dataset_bytes = CASES_PATH.read_bytes()
    try:
        git_bin = shutil.which("git") or "git"
        git_sha = subprocess.check_output(  # noqa: S603 — binario local resuelto
            [git_bin, "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except Exception:  # noqa: BLE001
        git_sha = ""
    planner_model = (
        args.model
        or os.environ.get("RAG_WORKFLOW_PLANNER_MODEL")
        or os.environ.get("RAG_LITELLM_DEFAULT_MODEL", "")
    )
    summary = _summary(rows)
    output = {
        "schema": "zent.universal.eval/v1",
        "provider": planner_model,
        "planner_model": planner_model,
        "git_sha": git_sha,
        "dataset_sha256": hashlib.sha256(dataset_bytes).hexdigest(),
        "seed": args.seed,
        "run_at": datetime.now(timezone.utc).isoformat(),
        "cases_path": str(CASES_PATH.relative_to(ROOT)),
        "limit": len(cases),
        "budget": budget.model_dump(mode="json"),
        "thresholds": {
            "intent": args.fail_under_intent,
            "graph": args.fail_under_graph,
            "capability": args.fail_under_capability,
        },
        "summary": summary,
        "rows": rows,
    }
    out_path = ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("wrote", out_path)

    failures: list[str] = []
    if args.fail_under_intent is not None and summary["intent_valid_rate"] < args.fail_under_intent:
        failures.append("intent")
    if args.fail_under_graph is not None and summary["graph_valid_rate_resolved"] < args.fail_under_graph:
        failures.append("graph")
    if (
        args.fail_under_capability is not None
        and summary.get("capability_recall_rate") is not None
        and summary["capability_recall_rate"] < args.fail_under_capability
    ):
        failures.append("capability")
    if failures:
        raise SystemExit(f"threshold gate failed: {', '.join(failures)}")


if __name__ == "__main__":
    asyncio.run(main())
