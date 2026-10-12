# =============================================================================
# Perf Traffic — línea base de performance con tráfico real (V2 F1).
# =============================================================================
# Corre un corpus de preguntas contra el pipeline REAL (Postgres/Redis/Qdrant/
# LLM del .env local) y emite métricas comparables antes/después:
#   p50/p95 de latencia, tokens/run, costo/run, llamadas LLM/run, rondas de
#   retrieval/run y tasa de error.
#
# Uso:
#   python -m src.scripts.perf_traffic --label after --limit 5
#   python -m src.scripts.perf_traffic --label before --queries tests/golden/rag_retail.json
#
# Sin `--org-id` toma la primera organización de la DB; sin `--user-id`, el
# primer usuario de esa organización.
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_QUERIES = ROOT / "tests" / "golden" / "rag_retail.json"
DEFAULT_OUT_DIR = ROOT / "artifacts" / "perf"


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def load_queries(path: Path) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        out: list[str] = []
        for item in data:
            if isinstance(item, str):
                out.append(item)
            elif isinstance(item, dict):
                question = str(item.get("question") or "").strip()
                if question:
                    out.append(question)
        return out
    if isinstance(data, dict) and isinstance(data.get("questions"), list):
        return [str(q).strip() for q in data["questions"] if str(q).strip()]
    raise SystemExit(f"formato de queries no soportado: {path}")


async def _first_org_and_user() -> tuple[UUID, UUID]:
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        org_row = (
            await session.execute(
                text("SELECT id FROM organizations ORDER BY created_at LIMIT 1")
            )
        ).first()
        if org_row is None:
            raise SystemExit("no hay organizaciones en la DB local")
        org_id = UUID(str(org_row.id))
        user_row = (
            await session.execute(
                text(
                    "SELECT id FROM users WHERE organization_id = :org "
                    "ORDER BY created_at LIMIT 1"
                ),
                {"org": org_id},
            )
        ).first()
        user_id = (
            UUID(str(user_row.id)) if user_row is not None else uuid4()
        )
        return org_id, user_id
    finally:
        await session.close()


def _pct(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((pct / 100) * (len(ordered) - 1)))))
    return float(ordered[index])


def _run_metrics(result: object) -> dict:
    llm = getattr(result, "llm_response", None)
    steps = list(getattr(result, "steps", []) or ())
    tokens = int(getattr(result, "total_tokens", 0) or 0) or int(
        getattr(llm, "total_tokens", 0) or 0
    )
    llm_calls = int(getattr(result, "llm_calls", 0) or 0) or (
        1 if llm is not None else 0
    )
    tool_steps = [
        step
        for step in steps
        if isinstance(step, dict)
        and str(step.get("type") or "") in {"tool_call", "jev_retrieval"}
    ]
    return {
        "latency_ms": round(float(getattr(result, "total_latency_ms", 0.0) or 0.0), 2),
        "tokens": tokens,
        "prompt_tokens": int(getattr(result, "prompt_tokens", 0) or 0),
        "completion_tokens": int(getattr(result, "completion_tokens", 0) or 0),
        "cost": round(float(getattr(result, "cost", 0.0) or 0.0), 6),
        "llm_calls": llm_calls,
        "tool_calls": int(getattr(result, "tool_calls", 0) or 0) or len(tool_steps),
        "retrieval_rounds": len(tool_steps),
        "status": str(getattr(result, "status", "") or ""),
        "error": str(getattr(result, "error_message", "") or "")[:200],
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
    started = time.perf_counter()
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
    except Exception as exc:  # noqa: BLE001 — el harness mide, no rompe
        return {
            "question": question[:200],
            "wall_ms": round((time.perf_counter() - started) * 1000, 2),
            "error": f"{type(exc).__name__}: {str(exc)[:200]}",
            "latency_ms": 0.0,
            "tokens": 0,
            "cost": 0.0,
            "llm_calls": 0,
            "tool_calls": 0,
            "retrieval_rounds": 0,
            "status": "error",
        }
    metrics = _run_metrics(result)
    metrics["question"] = question[:200]
    metrics["wall_ms"] = round((time.perf_counter() - started) * 1000, 2)
    return metrics


def _summarize(cases: list[dict]) -> dict:
    ok = [c for c in cases if not c.get("error") and c.get("status") != "error"]
    latencies = [float(c["latency_ms"]) for c in ok if c["latency_ms"] > 0]
    return {
        "runs": len(cases),
        "errors": len(cases) - len(ok),
        "latency_ms_p50": _pct(latencies, 50),
        "latency_ms_p95": _pct(latencies, 95),
        "latency_ms_mean": round(statistics.fmean(latencies), 2) if latencies else 0.0,
        "tokens_per_run": round(
            statistics.fmean([c["tokens"] for c in ok]), 2
        ) if ok else 0.0,
        "cost_per_run": round(
            statistics.fmean([c["cost"] for c in ok]), 6
        ) if ok else 0.0,
        "llm_calls_per_run": round(
            statistics.fmean([c["llm_calls"] for c in ok]), 2
        ) if ok else 0.0,
        "tool_calls_per_run": round(
            statistics.fmean([c["tool_calls"] for c in ok]), 2
        ) if ok else 0.0,
        "retrieval_rounds_per_run": round(
            statistics.fmean([c["retrieval_rounds"] for c in ok]), 2
        ) if ok else 0.0,
        "tokens_total": sum(c["tokens"] for c in ok),
        "cost_total": round(sum(c["cost"] for c in ok), 6),
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
                f"[{done}/{total}] {case['latency_ms']}ms "
                f"tokens={case['tokens']} {case['status']}",
                flush=True,
            )

    payload = {
        "label": args.label,
        "target": "rag",
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
    _print_json({"out": str(out_path), **payload["summary"]})


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Perf baseline con tráfico real")
    parser.add_argument("--label", default="after")
    parser.add_argument("--queries", default=str(DEFAULT_QUERIES))
    parser.add_argument("--iterations", type=int, default=1)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--role", default="admin")
    parser.add_argument("--org-id", default="")
    parser.add_argument("--user-id", default="")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(_main(_parse_args()))
