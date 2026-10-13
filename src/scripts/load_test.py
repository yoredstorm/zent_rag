# =============================================================================
# Load test — concurrencia, throughput y backpressure (F10).
# =============================================================================
# Corre el pipeline REAL (Postgres/Redis/Qdrant/LLM del .env) con N requests
# repartidos en cada nivel de concurrencia y emite JSON comparable:
#   throughput, p50/p95/p99, error rate, 429 del proveedor, intentos de
#   provider y latencia de las dependencias (Postgres/Redis) durante la carga.
#
# Uso:
#   python -m src.scripts.load_test --label local --concurrency 1,2,5 --requests 6
#   python -m src.scripts.load_test --label staging --concurrency 1,5,10,25,50
#
# Regla de backpressure: ante saturación del proveedor la respuesta esperada es
# cola/rate-limit/degradación, nunca colapso. El conteo de `rate_limited` y de
# errores por nivel lo hace visible.
# =============================================================================
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from src.scripts.perf_traffic import (
    DEFAULT_QUERIES,
    _first_org_and_user,
    _pct,
    load_queries,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT_DIR = ROOT / "artifacts" / "load"


async def _infra_probe() -> dict:
    """Latencia de una operación trivial en Postgres y Redis (una muestra)."""
    out: dict[str, float] = {}
    try:
        from sqlalchemy import text

        from src.infrastructure.postgres.session import get_async_session

        started = time.perf_counter()
        session = await get_async_session()
        try:
            await session.execute(text("SELECT 1"))
        finally:
            await session.close()
        out["postgres_ms"] = round((time.perf_counter() - started) * 1000, 2)
    except Exception as exc:  # noqa: BLE001 — el harness mide, no rompe
        out["postgres_ms"] = -1.0
        out["postgres_error"] = type(exc).__name__
    try:
        from src.infrastructure.redis.cache import _get_redis

        started = time.perf_counter()
        client = await _get_redis()
        await client.ping()
        out["redis_ms"] = round((time.perf_counter() - started) * 1000, 2)
    except Exception as exc:  # noqa: BLE001
        out["redis_ms"] = -1.0
        out["redis_error"] = type(exc).__name__
    return out


def _attempts_of(result: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    for step in getattr(result, "steps", None) or ():
        if isinstance(step, dict) and step.get("type") == "provider_attempt":
            status = str(step.get("status") or "unknown")
            counts[status] = counts.get(status, 0) + 1
    return counts


async def _one(
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
            "wall_ms": round((time.perf_counter() - started) * 1000, 2),
            "status": "error",
            "error": f"{type(exc).__name__}: {str(exc)[:200]}",
        }
    return {
        "wall_ms": round((time.perf_counter() - started) * 1000, 2),
        "status": str(getattr(result, "status", "") or ""),
        "latency_ms": round(float(getattr(result, "total_latency_ms", 0.0) or 0.0), 2),
        "tokens": int(getattr(result, "total_tokens", 0) or 0),
        "attempts": _attempts_of(result),
    }


def _summarize(level: dict, cases: list[dict], wall_seconds: float) -> dict:
    ok = [c for c in cases if c.get("status") != "error"]
    latencies = [float(c["wall_ms"]) for c in ok]
    rate_limited = sum(
        int((c.get("attempts") or {}).get("rate_limited", 0)) for c in cases
    )
    attempts_total = sum(
        sum((c.get("attempts") or {}).values()) for c in cases
    )
    return {
        "concurrency": level,
        "requests": len(cases),
        "errors": len(cases) - len(ok),
        "error_rate": round((len(cases) - len(ok)) / max(1, len(cases)), 4),
        "wall_seconds": round(wall_seconds, 2),
        "throughput_rps": round(len(cases) / wall_seconds, 3) if wall_seconds else 0.0,
        "latency_ms_p50": _pct(latencies, 50),
        "latency_ms_p95": _pct(latencies, 95),
        "latency_ms_p99": _pct(latencies, 99),
        "latency_ms_mean": round(statistics.fmean(latencies), 2) if latencies else 0.0,
        "provider_attempts": attempts_total,
        "provider_rate_limited": rate_limited,
        "retry_amplification": round(
            attempts_total / max(1, len(cases)), 3
        ),
    }


async def _run_level(
    orchestrator: object,
    queries: list[str],
    *,
    level: int,
    requests: int,
    organization_id: UUID,
    user_id: UUID,
    role: str,
    top_k: int,
) -> dict:
    semaphore = asyncio.Semaphore(level)
    before = await _infra_probe()

    async def _guarded(index: int) -> dict:
        async with semaphore:
            question = queries[index % len(queries)]
            case = await _one(
                orchestrator,
                question,
                organization_id=organization_id,
                user_id=user_id,
                role=role,
                top_k=top_k,
            )
            case["question"] = question[:160]
            return case

    started = time.perf_counter()
    cases = await asyncio.gather(*(_guarded(i) for i in range(requests)))
    wall_seconds = time.perf_counter() - started
    after = await _infra_probe()
    summary = _summarize(level, list(cases), wall_seconds)
    summary["infra_before"] = before
    summary["infra_after"] = after
    return {"summary": summary, "cases": list(cases)}


async def _main(args: argparse.Namespace) -> None:
    from src.api.deps import get_rag_orchestrator

    queries = load_queries(Path(args.queries))
    if not queries:
        raise SystemExit("no hay queries para correr")
    levels = [int(item) for item in str(args.concurrency).split(",") if item.strip()]
    if not levels:
        raise SystemExit("--concurrency vacío")

    if args.org_id:
        organization_id = UUID(str(args.org_id))
        user_id = UUID(str(args.user_id)) if args.user_id else uuid4()
    else:
        organization_id, user_id = await _first_org_and_user()

    orchestrator = get_rag_orchestrator()
    results: list[dict] = []
    for level in levels:
        requests = int(args.requests) if args.requests else level
        outcome = await _run_level(
            orchestrator,
            queries,
            level=level,
            requests=requests,
            organization_id=organization_id,
            user_id=user_id,
            role=args.role,
            top_k=int(args.top_k),
        )
        results.append(outcome)
        summary = outcome["summary"]
        print(
            "[nivel {c}] rps={r} p50={p50} p95={p95} p99={p99} err={e} 429={rl}".format(
                c=summary["concurrency"],
                r=summary["throughput_rps"],
                p50=summary["latency_ms_p50"],
                p95=summary["latency_ms_p95"],
                p99=summary["latency_ms_p99"],
                e=summary["error_rate"],
                rl=summary["provider_rate_limited"],
            ),
            flush=True,
        )

    payload = {
        "label": args.label,
        "target": "rag-load",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "organization_id": str(organization_id),
        "queries_file": str(Path(args.queries)),
        "levels": [item["summary"] for item in results],
        "details": results,
    }
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{args.label}.json"
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"out": str(out_path), "levels": payload["levels"]}, ensure_ascii=False, indent=2))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load test del pipeline RAG")
    parser.add_argument("--label", default="local")
    parser.add_argument("--queries", default=str(DEFAULT_QUERIES))
    parser.add_argument("--concurrency", default="1,5,10,25,50")
    parser.add_argument("--requests", type=int, default=0, help="0 = igual a la concurrencia")
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--role", default="admin")
    parser.add_argument("--org-id", default="")
    parser.add_argument("--user-id", default="")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(_main(_parse_args()))
