# =============================================================================
# Certification: evidencia de deploy local (rebuild + verificación)
# =============================================================================
# Toma los datos observados de los contenedores/compose y escribe
# artifacts/certification/<sha>/local-deploy.json
#
#   python scripts/cert/local_deploy_evidence.py
from __future__ import annotations

# ruff: noqa: T201, S603, S607, S310 - herramienta CLI; URLs http fijas a localhost
import json
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def _run(args: list[str]) -> str:
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True).stdout.strip()


def _get(url: str, headers: dict[str, str] | None = None) -> tuple[int, str]:
    try:
        request = urllib.request.Request(url, headers=headers or {})
        with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310 - solo localhost
            return response.status, response.read().decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001 - evidencia, no rompe
        return 0, f"{type(exc).__name__}: {exc}"


def _metrics_token() -> str:
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("METRICS_TOKEN="):
                return line.split("=", 1)[1].strip()
    return ""


def main() -> int:
    sha = _run(["git", "rev-parse", "HEAD"])
    out = ROOT / "artifacts" / "certification" / sha / "local-deploy.json"
    evidence: dict = {
        "schema": "zent.cert.local-deploy/1",
        "git_sha": sha,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "checks": {},
    }

    status, body = _get("http://127.0.0.1:8000/health")
    evidence["checks"]["api_health"] = {"http": status, "body": body[:300]}

    evidence["checks"]["image_sha_in_container"] = {
        "RAG_GIT_SHA": _run(["docker", "exec", "rag-api", "printenv", "RAG_GIT_SHA"]),
        "RAG_RUNTIME_BUILD_TIMESTAMP": _run(
            ["docker", "exec", "rag-api", "printenv", "RAG_RUNTIME_BUILD_TIMESTAMP"]
        ),
    }

    status, body = _get("http://127.0.0.1:9090/api/v1/rules")
    rules = json.loads(body)["data"]["groups"] if status == 200 else []
    evidence["checks"]["prometheus_rules"] = {
        "groups": [group["name"] for group in rules],
        "total": sum(len(group["rules"]) for group in rules),
        "with_error": [
            rule["name"]
            for group in rules
            for rule in group["rules"]
            if rule.get("lastError") or rule.get("health") not in (None, "ok")
        ],
    }
    status, body = _get("http://127.0.0.1:9090/api/v1/targets")
    targets = json.loads(body)["data"]["activeTargets"] if status == 200 else []
    evidence["checks"]["prometheus_targets"] = {
        "up": [t["labels"]["job"] for t in targets if t["health"] == "up"],
        "down": [t["labels"]["job"] for t in targets if t["health"] != "up"],
    }

    grafana_user = ""
    grafana_pass = ""
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("GRAFANA_ADMIN_USER="):
                grafana_user = line.split("=", 1)[1].strip()
            if line.startswith("GRAFANA_ADMIN_PASSWORD="):
                grafana_pass = line.split("=", 1)[1].strip()
    import base64

    auth = base64.b64encode(f"{grafana_user}:{grafana_pass}".encode()).decode()
    status, body = _get(
        "http://127.0.0.1:3000/api/dashboards/uid/zent-production",
        {"Authorization": f"Basic {auth}"},
    )
    evidence["checks"]["grafana_dashboard"] = {
        "http": status,
        "title": (json.loads(body).get("dashboard", {}).get("title") if status == 200 else body[:200]),
        "panels": (len(json.loads(body).get("dashboard", {}).get("panels", [])) if status == 200 else 0),
    }

    status, body = _get(
        "http://127.0.0.1:8000/metrics", {"Authorization": f"Bearer {_metrics_token()}"}
    )
    run_metrics = [
        line.split(" ")[0]
        for line in body.splitlines()
        if line.startswith(("zent_runs_total", "zent_run_latency_seconds_count"))
    ]
    evidence["checks"]["metrics_run_level"] = {"http": status, "series": sorted(set(run_metrics))}

    ssrf = _run(["docker", "exec", "rag-api", "python", "/tmp/ssrf_e2e.py"])  # noqa: S108 - ruta dentro del contenedor
    evidence["checks"]["ssrf_e2e_in_container"] = {
        "passed": "PASS" in ssrf,
        "output": ssrf[-400:],
    }

    status, body = _get("http://127.0.0.1:9090/api/v1/alertmanagers")
    alertmanagers = json.loads(body)["data"] if status == 200 else {"activeAlertmanagers": []}
    status, body = _get("http://127.0.0.1:9093/api/v2/alerts")
    active_alerts = json.loads(body) if status == 200 else []
    status, body = _get("http://127.0.0.1:9093/api/v2/status")
    am_status = json.loads(body) if status == 200 else {}
    evidence["checks"]["alertmanager"] = {
        "prometheus_active_targets": [a["url"] for a in alertmanagers["activeAlertmanagers"]],
        "prometheus_dropped": len(alertmanagers.get("droppedAlertmanagers") or []),
        "alertmanager_cluster": (am_status.get("cluster") or {}).get("status"),
        "active_alerts": len(active_alerts),
        "alert_names": [alert["labels"].get("alertname") for alert in active_alerts],
    }

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
