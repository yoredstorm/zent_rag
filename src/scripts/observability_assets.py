# =============================================================================
# Observability assets — dashboard de producción (dashboards-as-code)
# =============================================================================
# Genera `config/grafana/dashboards/zent-production.json` desde un spec corto y
# revisable. Reglas:
#   - Solo métricas del registry real (src/infrastructure/observability/metrics.py).
#   - Labels acotados: nada de query text, user_id, conversation_id, run_id,
#     document_id ni trace_id en queries de panel.
#   - Cada panel responde una pregunta operativa del checklist de canary
#     (docs/architecture/certification/observability.md).
#
# Uso:
#   python -m src.scripts.observability_assets            # escribe el JSON
#   python -m src.scripts.observability_assets --check    # falla si difiere
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "config" / "grafana" / "dashboards" / "zent-production.json"
DS = {"type": "prometheus", "uid": "prometheus"}


def _target(expr: str, legend: str, *, instant: bool = False) -> dict:
    return {
        "datasource": DS,
        "expr": expr,
        "legendFormat": legend,
        "refId": "A",
        "instant": instant,
    }


def _timeseries(
    title: str,
    expr: str,
    legend: str,
    *,
    unit: str = "short",
    description: str = "",
    x: int = 0,
    y: int = 0,
    w: int = 12,
    h: int = 8,
) -> dict:
    return {
        "type": "timeseries",
        "title": title,
        "description": description,
        "datasource": DS,
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "fieldConfig": {"defaults": {"unit": unit}, "overrides": []},
        "targets": [_target(expr, legend)],
    }


def _stat(
    title: str,
    expr: str,
    *,
    unit: str = "short",
    description: str = "",
    x: int = 0,
    y: int = 0,
    w: int = 6,
    h: int = 5,
    thresholds: list[dict] | None = None,
) -> dict:
    return {
        "type": "stat",
        "title": title,
        "description": description,
        "datasource": DS,
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "thresholds": {"mode": "absolute", "steps": thresholds or [{"color": "green", "value": None}]},
            },
            "overrides": [],
        },
        "targets": [_target(expr, title, instant=True)],
    }


def _row(title: str, y: int) -> dict:
    return {
        "type": "row",
        "title": title,
        "collapsed": False,
        "gridPos": {"h": 1, "w": 24, "x": 0, "y": y},
        "panels": [],
    }


def build_dashboard() -> dict:
    panels: list[dict] = []
    y = 0

    # ---- ¿Está sano ZENT? --------------------------------------------------
    panels.append(_row("1. ¿Está sano ZENT?", y))
    y += 1
    panels += [
        _stat("API scrapeable", 'up{job="rag-api"}', x=0, y=y,
              description="1 = Prometheus puede leer /metrics del API."),
        _stat("Runs por minuto", 'sum(rate(zent_runs_total[5m])) * 60', unit="rpm", x=6, y=y,
              description="Volumen de runs cerrados (agent+rag)."),
        _stat(
            "Error rate runs FAILED",
            'sum(increase(zent_runs_total{phase="FAILED"}[15m]))'
            ' / clamp_min(sum(increase(zent_runs_total[15m])), 1)',
            unit="percentunit",
            x=12,
            y=y,
            thresholds=[{"color": "green", "value": None}, {"color": "red", "value": 0.01}],
            description="SLO: <1% de runs FAILED (ABSTAIN no cuenta como error).",
        ),
        _stat(
            "5xx HTTP",
            'sum(rate(http_requests_total{status=~"5.."}[5m]))'
            ' / clamp_min(sum(rate(http_requests_total[5m])), 0.001)',
            unit="percentunit",
            x=18,
            y=y,
            thresholds=[{"color": "green", "value": None}, {"color": "red", "value": 0.05}],
        ),
    ]
    y += 5
    panels.append(
        _timeseries(
            "Runs por fase terminal",
            'sum by (phase) (increase(zent_runs_total{phase!=""}[15m]))',
            "{{phase}}",
            x=0, y=y,
            description="Distribución de outcomes: FINALIZED/ABSTAINED/BLOCKED/FAILED/UNDETERMINED.",
        )
    )
    panels.append(
        _timeseries(
            "Error budget burn (availability 99.9%)",
            'sum(rate(rag_errors_total[1h])) / clamp_min(sum(rate(rag_queries_total[1h])), 0.001)',
            "burn 1h",
            unit="percentunit", x=12, y=y,
            description="Fast burn > 2% del presupuesto mensual en 1h ⇒ page.",
        )
    )
    y += 8

    # ---- ¿Qué dependencia falla? ------------------------------------------
    panels.append(_row("2. ¿Qué dependencia está fallando?", y))
    y += 1
    panels += [
        _timeseries(
            "Intentos de provider por status",
            'sum by (status) (increase(zent_provider_attempts_total[15m]))',
            "{{status}}", x=0, y=y,
            description="rate_limited / timeout / provider_error / circuit_open / success.",
        ),
        _timeseries(
            "Circuit breaker: aperturas",
            'sum by (model, scope) (increase(zent_model_circuit_openings_total[15m]))',
            "{{model}} {{scope}}", x=12, y=y,
        ),
    ]
    y += 8
    panels += [
        _timeseries(
            "Retrieval no disponible",
            'sum(increase(rag_agent_retrieval_unavailable_total[15m]))',
            "unavailable", x=0, y=y,
            description="RETRIEVAL_UNAVAILABLE ≠ 'no hay información'.",
        ),
        _timeseries(
            "Suficiencia de evidencia al cierre",
            'sum by (status) (increase(zent_run_evidence_total[15m]))',
            "{{status}}", x=12, y=y,
        ),
    ]
    y += 8

    # ---- Latencia ----------------------------------------------------------
    panels.append(_row("3. ¿Está aumentando la latencia?", y))
    y += 1
    panels += [
        _timeseries(
            "Latencia de run (p50/p95/p99)",
            'histogram_quantile(0.50, sum by (le, path) (rate(zent_run_latency_seconds_bucket[15m])))',
            "p50 {{path}}", unit="s", x=0, y=y,
        ),
        _timeseries(
            "Latencia de run p95/p99",
            'histogram_quantile(0.95, sum by (le, path) (rate(zent_run_latency_seconds_bucket[15m])))',
            "p95 {{path}}", unit="s", x=12, y=y,
        ),
    ]
    y += 8
    panels += [
        _timeseries(
            "Latencia por etapa (retrieval/rerank/LLM)",
            'histogram_quantile(0.95, sum by (le) (rate(rag_vector_search_latency_seconds_bucket[15m])))',
            "vector search p95", unit="s", x=0, y=y,
        ),
        _timeseries(
            "LLM p95",
            'histogram_quantile(0.95, sum by (le) (rate(rag_llm_latency_seconds_bucket[15m])))',
            "llm p95", unit="s", x=12, y=y,
        ),
    ]
    y += 8

    # ---- Retries y backpressure -------------------------------------------
    panels.append(_row("4. ¿Hay retry amplification o backpressure?", y))
    y += 1
    panels += [
        _timeseries(
            "Amplificación de intentos (intentos/run)",
            'sum(increase(zent_provider_attempts_total[5m])) / clamp_min(sum(increase(zent_runs_total[5m])), 1)',
            "intentos por run", x=0, y=y,
            description="Diseño: ≤4 con 2 candidatos. >3 sostenido ⇒ runbook §11.",
        ),
        _timeseries(
            "429 del provider (rate_limited)",
            'sum(increase(zent_provider_attempts_total{status="rate_limited"}[5m]))',
            "rate_limited 5m", x=12, y=y,
        ),
    ]
    y += 8

    # ---- Calidad de respuesta ---------------------------------------------
    panels.append(_row("5. ¿Aumentó la abstención? ¿Anomalías de evidencia/autoridad?", y))
    y += 1
    panels += [
        _timeseries(
            "Ratio de abstención / undetermined",
            'sum(increase(zent_runs_total{phase="ABSTAINED"}[1h])) / clamp_min(sum(increase(zent_runs_total[1h])), 1)',
            "abstained 1h", unit="percentunit", x=0, y=y,
        ),
        _timeseries(
            "Acciones de finalización",
            'sum by (action) (increase(zent_finalization_actions_total[1h]))',
            "{{action}}", x=12, y=y,
        ),
    ]
    y += 8
    panels += [
        _stat("Divergencia de autoridad", 'sum(increase(zent_finalization_divergence_total[1h]))', x=0, y=y,
              thresholds=[{"color": "green", "value": None}, {"color": "red", "value": 1}],
              description="Invariante dura: debe ser 0."),
        _stat("Violaciones de aislamiento", 'sum(increase(zent_run_state_violations_total[1h]))', x=6, y=y,
              thresholds=[{"color": "green", "value": None}, {"color": "red", "value": 1}],
              description="Invariante dura: cross-tenant = 0."),
        _stat("Cache bypass (fail-closed)", 'sum(increase(zent_cache_bypass_total[1h]))', x=12, y=y,
              description="Guard de conversación activo: bypass correcto, cuesta latencia."),
        _stat("Tool calls", 'sum(increase(zent_run_tool_calls_total[1h]))', x=18, y=y),
    ]
    y += 5

    # ---- Costo -------------------------------------------------------------
    panels.append(_row("6. ¿El costo por run cambió abruptamente? ¿Unknown cost?", y))
    y += 1
    panels += [
        _timeseries(
            "Costo por run (USD)",
            'sum(increase(zent_run_cost_usd_total[1h])) / clamp_min(sum(increase(zent_runs_total[1h])), 1)',
            "usd/run 1h", unit="currencyUSD", x=0, y=y,
        ),
        _timeseries(
            "Ratio de costo desconocido",
            'sum(increase(zent_run_cost_unknown_total[1h])) / clamp_min(sum(increase(zent_runs_total[1h])), 1)',
            "unknown/run 1h", unit="percentunit", x=12, y=y,
            description="unknown != 0: si sube, la facturación queda incompleta (runbook §14).",
        ),
    ]
    y += 8
    panels += [
        _timeseries(
            "Tokens por run (prompt/completion)",
            'sum by (kind) (increase(zent_llm_tokens_total[1h])) / clamp_min(sum(increase(zent_runs_total[1h])), 1)',
            "{{kind}} tokens/run", x=0, y=y,
        ),
        _timeseries(
            "Llamadas LLM por run",
            'sum(increase(zent_llm_calls_total[1h])) / clamp_min(sum(increase(zent_runs_total[1h])), 1)',
            "llm calls/run", x=12, y=y,
        ),
    ]
    y += 8

    # ---- Tenants -----------------------------------------------------------
    panels.append(_row("7. ¿Algún tenant está saturando recursos?", y))
    y += 1
    panels += [
        _timeseries(
            "Top 5 tenants por queries",
            'topk(5, sum by (organization_id) (increase(rag_queries_total[1h])))',
            "{{organization_id}}", x=0, y=y,
            description="organization_id es el único label por-tenant (acotado por diseño).",
        ),
        _timeseries(
            "Cache hit/miss",
            'sum(increase(rag_cache_hits_total[1h]))',
            "hits 1h", x=12, y=y,
        ),
    ]
    y += 8

    return {
        "uid": "zent-production",
        "title": "ZENT — Producción (canary)",
        "tags": ["zent", "production", "canary"],
        "timezone": "utc",
        "schemaVersion": 39,
        "version": 1,
        "refresh": "30s",
        "time": {"from": "now-6h", "to": "now"},
        "templating": {"list": []},
        "annotations": {"list": []},
        "panels": panels,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Genera el dashboard de producción")
    parser.add_argument("--check", action="store_true", help="no escribe; falla si difiere")
    args = parser.parse_args()

    rendered = json.dumps(build_dashboard(), indent=2, ensure_ascii=False) + "\n"
    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != rendered:
            print(f"dashboard desactualizado: {OUT}")
            return 1
        print("dashboard OK")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(rendered, encoding="utf-8")
    print(f"escrito: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
