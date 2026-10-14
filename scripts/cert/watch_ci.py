# =============================================================================
# Certification: espera el run de CI de un SHA y resume jobs
# =============================================================================
#   python scripts/cert/watch_ci.py --sha 684d383 --timeout-minutes 75
#
# Lee la API pública de GitHub (sin token) y espera a que el run del SHA termine.
# Escribe artifacts/certification/<sha>/ci-run.json con el resumen por job.
from __future__ import annotations

# ruff: noqa: T201, S310 - herramienta CLI; URLs fijas de la API de GitHub
import argparse
import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPO = "yoredstorm/zent_rag"


def _api(path: str) -> dict:
    request = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/{path}",
        headers={"User-Agent": "zent-cert", "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Espera el CI de un SHA")
    parser.add_argument("--sha", required=True)
    parser.add_argument("--timeout-minutes", type=int, default=75)
    parser.add_argument("--poll-seconds", type=int, default=60)
    args = parser.parse_args()

    deadline = time.time() + args.timeout_minutes * 60
    run: dict | None = None
    while time.time() < deadline:
        data = _api(f"actions/runs?head_sha={args.sha}&per_page=20")
        runs = data.get("workflow_runs") or []
        candidate = next((r for r in runs if r["name"] == "CI"), None)
        if candidate and candidate["status"] == "completed":
            run = candidate
            break
        print(
            f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] "
            f"runs={len(runs)} status={candidate['status'] if candidate else 'pending'}"
        )
        time.sleep(args.poll_seconds)

    if run is None:
        print("timeout esperando el run de CI")
        return 2

    jobs = _api(f"actions/runs/{run['id']}/jobs?per_page=30").get("jobs") or []
    summary = {
        "schema": "zent.cert.ci-run/1",
        "repository": REPO,
        "sha": args.sha,
        "run_id": run["id"],
        "run_url": run["html_url"],
        "event": run["event"],
        "conclusion": run["conclusion"],
        "created_at": run["created_at"],
        "updated_at": run["updated_at"],
        "jobs": [
            {
                "name": job["name"],
                "conclusion": job["conclusion"],
                "started_at": job["started_at"],
                "completed_at": job["completed_at"],
                "failed_steps": [
                    step["name"]
                    for step in job.get("steps") or []
                    if step.get("conclusion") not in (None, "success", "skipped")
                ],
            }
            for job in jobs
        ],
    }
    out = ROOT / "artifacts" / "certification" / args.sha / "ci-run.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"-> {out}")
    return 0 if run["conclusion"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
