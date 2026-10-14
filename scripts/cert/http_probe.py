# ruff: noqa: T201 - herramienta CLI: print es la salida
# =============================================================================
# Certification probe: cache on/off y TTFT sobre el deployment HTTP real
# =============================================================================
# Los harness in-process (perf_traffic/load_test) corren con use_cache=False.
# La evidencia de cache y de TTFT solo se puede tomar por HTTP, contra el API
# real (mismo deployment, mismas dependencias).
#
#   python scripts/cert/http_probe.py --out artifacts/certification/<sha>/perf/http-probe.json
#
# Mide:
#   - query 1 (miss) y query 1 repetida (hit) end-to-end
#   - TTFT del endpoint SSE /api/v1/rag/query/stream
#   - delta de rag_cache_hits_total / rag_cache_misses_total en /metrics
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def _metrics_snapshot(base_url: str, token: str) -> dict[str, float]:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with httpx.Client(timeout=10) as client:
        text = client.get(f"{base_url}/metrics", headers=headers).text
    values: dict[str, float] = {}
    for line in text.splitlines():
        if line.startswith("#") or " " not in line:
            continue
        name, _, value = line.rpartition(" ")
        if name.startswith(("rag_cache_", "zent_cache_bypass")):
            try:
                values[name] = float(value)
            except ValueError:
                continue
    return values


def _metrics_token(explicit: str) -> str:
    """Token de /metrics: argumento, env var o .env local (nunca se imprime)."""
    if explicit:
        return explicit
    env_token = os.environ.get("METRICS_TOKEN", "")
    if env_token:
        return env_token
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("METRICS_TOKEN="):
                return line.split("=", 1)[1].strip()
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe HTTP: cache y TTFT")
    parser.add_argument("--base-url", default=os.environ.get("ZENT_API_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--token", default=os.environ.get("ZENT_DEV_TOKEN", "rag_test_dev_token_for_local_testing_123"))
    parser.add_argument("--metrics-token", default=os.environ.get("METRICS_TOKEN", ""))
    parser.add_argument("--org-id", default="00000000-0000-0000-0000-000000000001")
    parser.add_argument("--query", default="¿Cuál es la política de vacaciones?")
    parser.add_argument("--out", default="artifacts/certification/http-probe.json")
    args = parser.parse_args()
    args.metrics_token = _metrics_token(args.metrics_token)

    headers = {
        "Authorization": f"Bearer {args.token}",
        "X-Organization-Id": args.org_id,
        "Content-Type": "application/json",
    }
    result: dict = {
        "schema": "zent.cert.http-probe/1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_url": args.base_url,
        "organization_id": args.org_id,
        "query": args.query,
    }
    with httpx.Client(timeout=300) as client:
        before = _metrics_snapshot(args.base_url, args.metrics_token)
        t0 = time.perf_counter()
        miss = client.post(
            f"{args.base_url}/api/v1/rag/query",
            headers=headers,
            json={"query": args.query, "top_k": 5},
        )
        result["miss_latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        result["miss_status"] = miss.status_code
        if miss.status_code == 200:
            body = miss.json()
            result["miss_answer_state"] = body.get("answer_state") or body.get("status")
            result["miss_cost"] = body.get("cost")
            result["miss_tokens"] = body.get("total_tokens")

        t0 = time.perf_counter()
        hit = client.post(
            f"{args.base_url}/api/v1/rag/query",
            headers=headers,
            json={"query": args.query, "top_k": 5},
        )
        result["hit_latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        result["hit_status"] = hit.status_code
        after = _metrics_snapshot(args.base_url, args.metrics_token)
        result["metrics_delta"] = {
            name: round(after.get(name, 0.0) - before.get(name, 0.0), 3)
            for name in sorted(set(after) | set(before))
        }

        # TTFT por SSE (query nueva para forzar generación).
        stream_query = f"{args.query} (variante streaming {int(time.time())})"
        t0 = time.perf_counter()
        ttft_ms = None
        first_event_ms = None
        events = 0
        with client.stream(
            "POST",
            f"{args.base_url}/api/v1/rag/query/stream",
            headers=headers,
            json={"query": stream_query, "top_k": 5},
        ) as response:
            result["stream_status"] = response.status_code
            for line in response.iter_lines():
                if not line:
                    continue
                events += 1
                if first_event_ms is None:
                    first_event_ms = round((time.perf_counter() - t0) * 1000, 1)
                if ttft_ms is None and line.startswith("data:"):
                    payload = line[len("data:"):].strip()
                    # El primer evento puede ser de arranque; TTFT = primer
                    # payload con contenido (texto/delta/answer).
                    if payload and any(
                        key in payload
                        for key in ('"delta"', '"text"', '"answer"', '"token"')
                    ):
                        ttft_ms = round((time.perf_counter() - t0) * 1000, 1)
        result["first_event_ms"] = first_event_ms
        result["ttft_ms"] = ttft_ms
        result["stream_total_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        result["stream_events"] = events

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
