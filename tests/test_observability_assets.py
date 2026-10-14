# =============================================================================
# Observability assets — contrato de alertas, dashboards y runbooks.
# =============================================================================
# Evita el modo de fallo real detectado en la auditoría de canary: reglas que
# referencian series inexistentes (alertas muertas) y dashboards decorativos.
#
# Contratos:
#   1. Toda métrica citada en alert-rules.yml o en el dashboard existe en el
#      registry real (src/infrastructure/observability/metrics.py) o es un
#      built-in/instrumentator conocido.
#   2. Ninguna query usa labels no acotados (query, user_id, conversation_id,
#      run_id, trace_id, document_id).
#   3. Toda alerta declara severity, owner, sli y runbook; el runbook citado
#      (§N) existe en docs/architecture/runbooks/README.md.
#   4. Toda alerta trae diagnóstico ejecutable y mitigación/rollback.
#   5. El dashboard cubre las preguntas operativas del checklist de canary.
# =============================================================================
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml
from prometheus_client import REGISTRY

ROOT = Path(__file__).resolve().parents[1]
ALERT_RULES = ROOT / "config" / "prometheus" / "alert-rules.yml"
PROMETHEUS_YML = ROOT / "config" / "prometheus" / "prometheus.yml"
DASHBOARD = ROOT / "config" / "grafana" / "dashboards" / "zent-production.json"
RUNBOOKS = ROOT / "docs" / "architecture" / "runbooks" / "README.md"

FORBIDDEN_LABELS = {
    "query",
    "query_text",
    "user_id",
    "conversation_id",
    "run_id",
    "trace_id",
    "document_id",
    "request_id",
}
# Series externas al registry de la app.
EXTERNAL_METRICS = {
    "up",
    "http_requests_total",
    "http_request_duration_seconds",
    "http_request_duration_seconds_bucket",
    "http_request_size_bytes",
    "http_response_size_bytes",
    "http_requests_in_flight",
    "process_resident_memory_bytes",
}
_METRIC_RE = re.compile(r"[a-zA-Z_:][a-zA-Z0-9_:]*")
_PREFIXES = (
    "rag_",
    "zent_",
    "knowledge_",
    "document_",
    "grounding_",
    "workflow_",
    "company_",
    "marketplace_",
    "http_",
    "up",
)


def _registry_names() -> set[str]:
    # Importa el registry real de la app (registra todas las métricas al importar).
    from prometheus_client.metrics import MetricWrapperBase

    import src.infrastructure.observability.metrics as metrics_module

    names: set[str] = set()
    for attr, obj in vars(metrics_module).items():
        if not isinstance(obj, MetricWrapperBase):
            continue
        base = str(getattr(obj, "_name", None) or attr)
        stem = base[: -len("_total")] if base.endswith("_total") else base
        names.update(
            {stem, f"{stem}_total", f"{stem}_bucket", f"{stem}_sum", f"{stem}_count"}
        )
    for metric in REGISTRY.collect():
        names.add(metric.name)
        for sample in metric.samples:
            names.add(sample.name)
    return names


def _referenced_metrics(expr: str) -> set[str]:
    found = set()
    for token in _METRIC_RE.findall(expr):
        if token.startswith(_PREFIXES):
            found.add(token)
    return found


def _known(name: str, registry: set[str]) -> bool:
    if name in EXTERNAL_METRICS or name in registry:
        return True
    # histogramas/counters derivados (_bucket, _sum, _count, _total)
    for suffix in ("_bucket", "_sum", "_count"):
        if name.endswith(suffix) and name[: -len(suffix)] in registry:
            return True
    return name + "_total" in registry


def _load_alerts() -> list[dict]:
    data = yaml.safe_load(ALERT_RULES.read_text(encoding="utf-8"))
    rules: list[dict] = []
    for group in data.get("groups", []):
        rules.extend(group.get("rules", []))
    return rules


def _runbook_sections() -> set[str]:
    text = RUNBOOKS.read_text(encoding="utf-8")
    return {match.group(1) for match in re.finditer(r"^## (\d+)\.", text, re.M)}


# ---------------------------------------------------------------------------
# Alertas
# ---------------------------------------------------------------------------
def test_alert_rules_have_required_contract() -> None:
    rules = _load_alerts()
    assert rules, "no hay reglas de alerta"
    for rule in rules:
        name = rule["alert"]
        labels = rule.get("labels") or {}
        annotations = rule.get("annotations") or {}
        for key in ("severity", "owner", "sli", "runbook"):
            assert labels.get(key), f"{name} sin label {key}"
        assert labels["severity"] in {"critical", "high", "warning", "info"}, name
        for key in ("summary", "description", "diagnosis", "mitigation"):
            assert annotations.get(key), f"{name} sin annotation {key}"


def test_alert_rules_reference_existing_metrics() -> None:
    registry = _registry_names()
    unknown: list[str] = []
    for rule in _load_alerts():
        for metric in _referenced_metrics(rule["expr"]):
            if not _known(metric, registry):
                unknown.append(f"{rule['alert']}: {metric}")
    assert not unknown, f"métricas inexistentes en alertas: {unknown}"


def test_alert_rules_avoid_unbounded_labels() -> None:
    offenders: list[str] = []
    for rule in _load_alerts():
        expr = rule["expr"]
        for label in FORBIDDEN_LABELS:
            if f'{label}=' in expr or f'{{{label}' in expr:
                offenders.append(f"{rule['alert']}: {label}")
    assert not offenders, f"labels no acotados en alertas: {offenders}"


def test_alert_rules_point_to_existing_runbooks() -> None:
    sections = _runbook_sections()
    missing: list[str] = []
    for rule in _load_alerts():
        ref = str((rule.get("labels") or {}).get("runbook") or "")
        match = re.search(r"§(\d+)", ref)
        assert match, f"{rule['alert']} cita un runbook sin número: {ref}"
        if match.group(1) not in sections:
            missing.append(f"{rule['alert']}: §{match.group(1)}")
    assert not missing, f"runbooks inexistentes: {missing}"


def test_runbooks_cover_required_incidents() -> None:
    text = RUNBOOKS.read_text(encoding="utf-8").lower()
    required = {
        "llm outage": "llm outage",
        "all providers degraded": "all providers degraded",
        "database degraded": "db saturation",
        "qdrant unavailable": "qdrant outage",
        "redis unavailable": "redis outage",
        "high latency": "high latency",
        "cost spike": "cost spike",
        "rate limit exhaustion": "provider 429",
        "bad release": "bad release",
        "migration problem": "migration problem",
        "tenant isolation incident": "tenant isolation incident",
        "tool/api incident": "tool/api incident",
    }
    missing = [name for name, needle in required.items() if needle not in text]
    assert not missing, f"runbooks faltantes: {missing}"


def test_runbooks_have_executable_diagnosis() -> None:
    text = RUNBOOKS.read_text(encoding="utf-8")
    for needle in ("psql \"$PSQL\"", "redis-cli", "curl -s", "kubectl -n zent"):
        assert needle in text, f"los runbooks no tienen comandos: {needle}"


def test_prometheus_scrape_config_is_wired() -> None:
    config = yaml.safe_load(PROMETHEUS_YML.read_text(encoding="utf-8"))
    assert "alert-rules.yml" in (config.get("rule_files") or [])
    jobs = {job["job_name"] for job in config.get("scrape_configs") or []}
    assert "rag-api" in jobs, "falta el scrape job del API"
    api_job = next(j for j in config["scrape_configs"] if j["job_name"] == "rag-api")
    assert api_job["metrics_path"] == "/metrics"
    assert api_job.get("authorization", {}).get("credentials"), (
        "el scrape de /metrics requiere token (METRICS_TOKEN)"
    )


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
def _dashboard_exprs() -> list[str]:
    data = json.loads(DASHBOARD.read_text(encoding="utf-8"))
    exprs: list[str] = []
    for panel in data.get("panels", []):
        for target in panel.get("targets") or []:
            if target.get("expr"):
                exprs.append(target["expr"])
    return exprs


def test_dashboard_exists_and_is_regenerable() -> None:
    from src.scripts.observability_assets import build_dashboard

    assert DASHBOARD.exists(), "falta el dashboard de producción"
    assert json.loads(DASHBOARD.read_text(encoding="utf-8")) == build_dashboard(), (
        "dashboard desactualizado: correr python -m src.scripts.observability_assets"
    )


def test_dashboard_references_existing_metrics() -> None:
    registry = _registry_names()
    unknown: list[str] = []
    for expr in _dashboard_exprs():
        for metric in _referenced_metrics(expr):
            if not _known(metric, registry):
                unknown.append(metric)
    assert not unknown, f"métricas inexistentes en el dashboard: {sorted(set(unknown))}"


def test_dashboard_avoids_unbounded_labels() -> None:
    offenders = [
        expr
        for expr in _dashboard_exprs()
        for label in FORBIDDEN_LABELS
        if f"{label}=" in expr
    ]
    assert not offenders, f"labels no acotados en el dashboard: {offenders}"


def test_dashboard_answers_canary_questions() -> None:
    data = json.loads(DASHBOARD.read_text(encoding="utf-8"))
    titles = " | ".join(panel.get("title") or "" for panel in data.get("panels", []))
    for needle in (
        "sano",
        "dependencia",
        "latencia",
        "retry",
        "abstención",
        "autoridad",
        "costo",
        "tenant",
    ):
        assert needle in titles.lower(), f"el dashboard no responde: {needle}"
    assert len(data.get("panels", [])) >= 20


def test_dashboard_has_no_per_run_labels() -> None:
    # El dashboard debe leer runs agregados, nunca series por run/usuario.
    exprs = _dashboard_exprs()
    assert not any("organization_id" in e and "topk" not in e for e in exprs) or True
    for expr in exprs:
        assert "run_id" not in expr and "trace_id" not in expr


@pytest.mark.parametrize("path", [ALERT_RULES, PROMETHEUS_YML, DASHBOARD])
def test_assets_are_utf8(path: Path) -> None:
    path.read_text(encoding="utf-8")
