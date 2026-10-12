# =============================================================================
# Finalization Audit — divergencia de autoridad del cierre con tráfico real.
# =============================================================================
# Corre un corpus contra el pipeline REAL (Postgres/Redis/Qdrant/LLM del .env)
# y reporta, por run, la resolución de la FinalizationPolicy vs la fase terminal
# del estado canónico (camino RAG y camino agente). Es el gate operativo de
# promoción por etapa: cero divergencias no justificadas antes de armar una
# etapa en enforcement.
#
# Uso:
#   python -m src.scripts.finalization_audit --label f2 --limit 20
#   python -m src.scripts.finalization_audit --label f2 --queries tests/golden/rag_retail.json
#
# Requiere el mismo entorno que `src.scripts.perf_traffic`.
# =============================================================================
from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from src.scripts.perf_traffic import (
    DEFAULT_QUERIES,
    _first_org_and_user,
    load_queries,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT_DIR = ROOT / "artifacts" / "finalization-audit"


def _case_observation(result: object) -> dict:
    """Resolución del cierre y fase terminal del estado canónico del run."""
    from src.runtime.finalization_policy import (
        FinalizationAction,
        expected_actions_for_phase,
        legacy_action_for_phase,
    )
    from src.runtime.run_state import RunPhase

    state = getattr(result, "run_state", None)
    if state is None:
        return {"phase": "", "action": "", "reason_code": "", "divergent": False}
    phase = state.phase
    policy = getattr(state.decisions, "finalization", None) or {}
    action = str(policy.get("action") or "")
    expected = expected_actions_for_phase(phase) if isinstance(phase, RunPhase) else frozenset()
    if not action:
        return {
            "phase": str(phase),
            "action": "",
            "reason_code": "",
            "divergent": False,
            "no_resolution": True,
        }
    try:
        resolved = FinalizationAction(action)
    except ValueError:
        return {
            "phase": str(phase),
            "action": action,
            "reason_code": str(policy.get("reason_code") or ""),
            "divergent": True,
            "unknown_action": True,
        }
    divergent = bool(expected) and resolved not in expected
    warn_steps = [
        step
        for step in (getattr(result, "steps", None) or ())
        if isinstance(step, dict)
        and step.get("type") == "finalization_policy"
        and step.get("status") == "warn"
    ]
    return {
        "phase": str(phase),
        "legacy_action": legacy_action_for_phase(phase) if isinstance(phase, RunPhase) else "",
        "action": action,
        "reason_code": str(policy.get("reason_code") or ""),
        "authority": str(policy.get("authority") or ""),
        "limited": bool(policy.get("limited")),
        "signals_ignored": list(policy.get("signals_ignored") or ()),
        "divergent": divergent,
        "warning_steps": len(warn_steps),
    }


async def _run_case(
    orchestrator: object,
    question: str,
    *,
    organization_id: UUID,
    user_id: UUID,
    role: str,
    top_k: int,
) -> dict:
    try:
        result = await orchestrator.execute(
            organization_id=organization_id,
            user_id=user_id,
            query=question,
            model=None,
            temperature=0.3,
            top_k=top_k,
            use_cache=False,
            role=role,
        )
    except Exception as exc:  # noqa: BLE001 — el auditor mide, no rompe
        return {
            "question": question[:200],
            "status": "error",
            "error": f"{type(exc).__name__}: {str(exc)[:200]}",
            "phase": "",
            "action": "",
            "reason_code": "",
            "divergent": False,
        }
    observation = _case_observation(result)
    observation["question"] = question[:200]
    observation["status"] = str(getattr(result, "status", "") or "")
    observation["latency_ms"] = round(
        float(getattr(result, "total_latency_ms", 0.0) or 0.0), 2
    )
    return observation


def _summarize(cases: list[dict]) -> dict:
    divergent = [case for case in cases if case.get("divergent")]
    by_stage = Counter(
        str(case.get("phase") or "")
        for case in divergent
    )
    by_reason = Counter(
        str(case.get("reason_code") or "") for case in divergent
    )
    phases = Counter(str(case.get("phase") or "") for case in cases)
    actions = Counter(str(case.get("action") or "") for case in cases)
    return {
        "runs": len(cases),
        "errors": sum(1 for case in cases if case.get("status") == "error"),
        "divergences": len(divergent),
        "divergences_by_phase": dict(sorted(by_stage.items())),
        "divergences_by_reason_code": dict(sorted(by_reason.items())),
        "phases": dict(sorted(phases.items())),
        "actions": dict(sorted(actions.items())),
        "without_resolution": sum(1 for case in cases if case.get("no_resolution")),
    }


async def _main(args: argparse.Namespace) -> None:
    from src.api.deps import get_rag_orchestrator

    queries = load_queries(Path(args.queries))
    if args.limit:
        queries = queries[: int(args.limit)]
    if not queries:
        raise SystemExit("no hay queries para correr")
    if args.org_id:
        organization_id = UUID(str(args.org_id))
        user_id = UUID(str(args.user_id)) if args.user_id else uuid4()
    else:
        organization_id, user_id = await _first_org_and_user()

    orchestrator = get_rag_orchestrator()
    cases: list[dict] = []
    total = len(queries) * max(1, int(args.iterations))
    done = 0
    for iteration in range(max(1, int(args.iterations))):
        for question in queries:
            case = await _run_case(
                orchestrator,
                question,
                organization_id=organization_id,
                user_id=user_id,
                role=args.role,
                top_k=int(args.top_k),
            )
            case["iteration"] = iteration
            cases.append(case)
            done += 1
            print(
                f"[{done}/{total}] phase={case.get('phase')} "
                f"action={case.get('action')} divergent={case.get('divergent')}",
                flush=True,
            )

    payload = {
        "label": args.label,
        "target": "finalization",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "organization_id": str(organization_id),
        "queries_file": str(Path(args.queries)),
        "iterations": int(args.iterations),
        "summary": _summarize(cases),
        "cases": cases,
    }
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{args.label}.json"
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"out": str(out_path), **payload["summary"]}, ensure_ascii=False, indent=2))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Auditoría de divergencia de la política de finalización"
    )
    parser.add_argument("--label", default="audit")
    parser.add_argument("--queries", default=str(DEFAULT_QUERIES))
    parser.add_argument("--iterations", type=int, default=1)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--role", default="admin")
    parser.add_argument("--org-id", default="")
    parser.add_argument("--user-id", default="")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(_main(_parse_args()))
