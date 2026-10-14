# =============================================================================
# Certification: baja la evidencia JUnit del run de CI de un SHA
# =============================================================================
#   python scripts/cert/fetch_ci_evidence.py --sha 8ee8200
#
# Requiere credencial de GitHub en el credential store de git (no imprime el
# token). Descarga el artifact `junit-ci` del job `test`, extrae los XML y
# escribe evidencia reutilizable por release_manifest.py:
#   artifacts/certification/<sha>/ci/{junit-tests.xml,junit-invariants.xml}
#   artifacts/certification/<sha>/ci/ci-suite.evidence.json
#   artifacts/certification/<sha>/ci/ci-invariants.evidence.json
#   artifacts/certification/<sha>/ci/ci-run.json
from __future__ import annotations

# ruff: noqa: T201, S310, S603, S607 - herramienta CLI; API y git fijos
import argparse
import io
import json
import subprocess
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPO = "yoredstorm/zent_rag"


def _token() -> str:
    result = subprocess.run(
        ["git", "credential", "fill"],
        cwd=ROOT,
        input="protocol=https\nhost=github.com\n\n",
        capture_output=True,
        text=True,
    )
    for line in result.stdout.splitlines():
        if line.startswith("password="):
            return line.split("=", 1)[1].strip()
    return ""


def _api(path: str, token: str) -> dict:
    request = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/{path}",
        headers={
            "User-Agent": "zent-cert",
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def _download_artifact(artifact_id: int, token: str) -> bytes:
    request = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/actions/artifacts/{artifact_id}/zip",
        headers={"User-Agent": "zent-cert", "Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310
        return response.read()


def main() -> int:
    parser = argparse.ArgumentParser(description="Evidencia JUnit del CI")
    parser.add_argument("--sha", required=True)
    args = parser.parse_args()

    token = _token()
    if not token:
        print("sin credencial de GitHub en el credential store")
        return 2

    runs = _api(f"actions/runs?head_sha={args.sha}&per_page=20", token)["workflow_runs"]
    run = next((r for r in runs if r["name"] == "CI"), None)
    if run is None:
        print("no hay run de CI para ese SHA")
        return 2
    if run["status"] != "completed":
        print(f"run {run['id']} todavía {run['status']}")
        return 3

    jobs = _api(f"actions/runs/{run['id']}/jobs?per_page=30", token)["jobs"]
    test_job = next((j for j in jobs if j["name"] == "test"), None)

    out_dir = ROOT / "artifacts" / "certification" / args.sha / "ci"
    out_dir.mkdir(parents=True, exist_ok=True)

    artifacts = _api(f"actions/runs/{run['id']}/artifacts?per_page=30", token)["artifacts"]
    junit_artifact = next((a for a in artifacts if a["name"] == "junit-ci"), None)
    extracted: list[str] = []
    if junit_artifact:
        blob = _download_artifact(junit_artifact["id"], token)
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            for member in archive.namelist():
                name = Path(member).name
                if name.endswith(".xml"):
                    (out_dir / name).write_bytes(archive.read(member))
                    extracted.append(name)

    environment = "github-actions ubuntu-latest, postgres pgvector:pg16, qdrant v1.13.4, redis 7, python 3.11"
    common = {
        "git_sha": args.sha,
        "git_branch": "master",
        "git_dirty": False,
        "environment": environment,
        "configuration": ".github/workflows/ci.yml job `test` (RAG_ENVIRONMENT=development, BILLING_ENABLED=false)",
        "ci_run_id": run["id"],
        "ci_run_url": run["html_url"],
        "ci_conclusion": run["conclusion"],
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }

    tests_junit = out_dir / "junit-tests.xml"
    invariants_junit = out_dir / "junit-invariants.xml"
    (out_dir / "ci-suite.evidence.json").write_text(
        json.dumps(
            {
                "schema": "zent.cert.suite-run/3",
                **common,
                "label": "ci-full-suite",
                "command": "CI job `test`: uv run pytest tests/ -v --tb=short --timeout=300",
                "exit_code": 0 if run["conclusion"] == "success" else 1,
                "result": "pass" if run["conclusion"] == "success" else "fail",
                "junit": str(tests_junit),
                "source": "GitHub Actions artifact junit-ci",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (out_dir / "ci-invariants.evidence.json").write_text(
        json.dumps(
            {
                "schema": "zent.cert.suite-run/3",
                **common,
                "label": "ci-invariants",
                "command": "CI job `test`: Architecture invariants (fast, required)",
                "exit_code": 0 if run["conclusion"] == "success" else 1,
                "result": "pass" if run["conclusion"] == "success" else "fail",
                "junit": str(invariants_junit),
                "source": "GitHub Actions artifact junit-ci",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (out_dir / "ci-run.json").write_text(
        json.dumps(
            {
                "schema": "zent.cert.ci-run/2",
                "repository": REPO,
                "sha": args.sha,
                "run_id": run["id"],
                "run_url": run["html_url"],
                "conclusion": run["conclusion"],
                "jobs": [
                    {
                        "name": job["name"],
                        "conclusion": job["conclusion"],
                        "failed_steps": [
                            step["name"]
                            for step in job.get("steps") or []
                            if step.get("conclusion") not in (None, "success", "skipped")
                        ],
                    }
                    for job in jobs
                ],
                "artifacts": [a["name"] for a in artifacts],
                "extracted_junit": extracted,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "run_id": run["id"],
                "conclusion": run["conclusion"],
                "jobs": {job["name"]: job["conclusion"] for job in jobs},
                "test_job_steps_failed": (test_job or {}).get("steps") and [
                    s["name"] for s in test_job["steps"] if s.get("conclusion") not in (None, "success", "skipped")
                ],
                "extracted_junit": extracted,
                "out_dir": str(out_dir),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if run["conclusion"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
