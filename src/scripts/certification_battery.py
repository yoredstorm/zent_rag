# =============================================================================
# Certification battery — evidencia reproducible de seguridad, chaos,
# determinismo, aislamiento y contabilidad.
# =============================================================================
# Corre subconjuntos de pytest y mapea cada ESCENARIO del checklist de canary a
# los tests que lo prueban. Un escenario sin tests que lo matcheen cuenta como
# NO DEMOSTRADO (no como verde).
#
# Uso:
#   python -m src.scripts.certification_battery --suite security
#   python -m src.scripts.certification_battery --suite all --out-dir artifacts/certification/<sha>
#
# Salida: <out-dir>/battery/<suite>.json + <out-dir>/battery/<suite>.md
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Scenario:
    id: str
    title: str
    match: tuple[str, ...]  # substrings que deben aparecer en el nodeid del test


@dataclass(frozen=True)
class Suite:
    name: str
    files: tuple[str, ...]
    scenarios: tuple[Scenario, ...]
    purpose: str = ""


def _s(id: str, title: str, match: str) -> Scenario:
    """match: tokens separados por '|' (deben aparecer en el nodeid del test)."""
    return Scenario(
        id=id, title=title, match=tuple(t.strip() for t in match.split("|") if t.strip())
    )


# -----------------------------------------------------------------------------
# Seguridad / adversarial (Parte G del checklist)
# -----------------------------------------------------------------------------
SECURITY = Suite(
    name="security",
    purpose="Batería adversarial: el modelo nunca es autoridad de seguridad.",
    files=(
        "tests/test_certification_security.py",
        "tests/test_agent_security.py",
        "tests/test_prompt_assembly.py",
        "tests/test_prompt_block_headers.py",
        "tests/test_knowledge_adversarial.py",
        "tests/test_adaptive_passages_claims.py",
        "tests/test_evidence_assembly.py",
        "tests/test_tenant_isolation.py",
        "tests/test_conversation_isolation.py",
        "tests/test_certification_tenant_stress.py",
        "tests/test_identity_hardening.py",
        "tests/test_organization_filter_injection.py",
        "tests/test_sql_security.py",
        "tests/test_security_hardening.py",
        "tests/test_admin_sql.py",
        "tests/test_connector_security.py",
        "tests/test_connector_api.py",
        "tests/test_openapi_connector.py",
        "tests/test_authorized_scope.py",
        "tests/test_knowledge_scope.py",
        "tests/test_agent_source_ids.py",
        "tests/test_rbac_matrix.py",
        "tests/test_action_plane_authority.py",
        "tests/test_workflow_node_catalog.py",
        "tests/test_data_onboarding.py",
    ),
    scenarios=(
        _s("G01", "prompt injection del usuario", "injection_in_user_message|inyeccion_en_datos|user_turn"),
        _s(
            "G02", "prompt injection en documento recuperado",
            "injection_no_se_convierte|injection_en_golden|sanitizan|neutralizes_injection",
        ),
        _s("G03", "prompt injection en tool observation", "observation_instructions|tool_output_untrusted"),
        _s(
            "G04", "fake system instruction dentro de knowledge",
            "untrusted_source|injected_instruction|la_politica_no_absorbe",
        ),
        _s(
            "G05", "cross-tenant retrieval attempt",
            "tenant_isolation|scoped_to_organization|rejects_missing_organization",
        ),
        _s("G06", "cross-tenant cache key attempt", "cache_key_isolates|incluye_tenant|cruza_conversaciones"),
        _s(
            "G07", "model-proposed organization_id",
            "run_tenant_not_model_args|organization_literal|organization_filter",
        ),
        _s("G08", "model-proposed user_id", "run_user_not_model_args"),
        _s(
            "G09", "tool no autorizada",
            "unlisted_tool|unknown_tool|permission_gate|resolve_allowed_tools|tool_denegado",
        ),
        _s(
            "G10", "SQL no autorizado",
            "platform_table_blocked|prompt_injection_table_blocked|other_org_schema_blocked",
        ),
        _s(
            "G11", "SQL mutación con read-only",
            "destructive_statements|multi_statement|cte_with_delete|for_update|select_into|non_select",
        ),
        _s(
            "G12", "SSRF a endpoints internos",
            "private_ip_blocked|allowlist_enforced|no_allowlist|rejects_internal|private_host_blocked",
        ),
        _s("G13", "redirect-based SSRF", "redirect"),
        _s("G14", "exfiltración de credenciales/headers", "redaction|never_returns_them|headers|smuggled"),
        _s("G15", "path traversal en connectors/files", "traversal|upload_filename"),
        _s("G16", "payload sobredimensionado", "body_size|too_large|oversized"),
        _s("G17", "tool argument smuggling", "boolean_is_not|smuggled_boolean|extra_keys_dropped|wrong_type_rejected"),
        _s("G18", "metadata OpenAPI maliciosa", "OpenApiMetadata"),
        _s("G19", "knowledge_scope escape", "scope|source_ids|authorized_scope"),
        _s("G20", "conversation isolation", "conversation_isolation|dos_conversaciones|cross_conversation"),
        _s("G21", "RBAC downgrade", "elevate|spoofing|viewer|role_cannot"),
        _s("G22", "workflow privilege escalation", "workflow|permissions|system_context"),
    ),
)

# -----------------------------------------------------------------------------
# Chaos hermético (Parte F del checklist)
# -----------------------------------------------------------------------------
CHAOS = Suite(
    name="chaos",
    purpose="Política observada ante fallos de dependencias (hermético).",
    files=(
        "tests/test_chaos_resilience.py",
        "tests/test_provider_attempts.py",
        "tests/test_llm_stream_fallback.py",
        "tests/test_llm_embed_fallback.py",
        "tests/test_llm_embed_retry.py",
        "tests/test_model_health.py",
        "tests/test_budget_stop_reasons.py",
        "tests/test_db_lifecycle.py",
        "tests/test_answer_state_texts.py",
        "tests/test_evidence_semantics.py",
        "tests/test_certification_accounting_chain.py",
        "tests/test_certification_security.py",
    ),
    scenarios=(
        _s("F01", "primary LLM hard failure", "provider_down_no_propaga|todos_los_candidatos_fallan"),
        _s("F02", "primary LLM 429", "429_no_multiplica|429_antes_del_primer_token|rate_limited"),
        _s("F03", "primary LLM timeout", "timeout_antes_del_primer_token|timeout_no_se_reintenta"),
        _s("F04", "fallback LLM failure", "todos_los_candidatos_fallan|fallback"),
        _s("F05", "embedding provider unavailable", "embed_retry|embed_fallback"),
        _s("F06", "reranker unavailable", "reranker_caido"),
        _s("F07", "JEV unavailable", "jev_roto"),
        _s("F08", "Redis unavailable", "redis_caido"),
        _s(
            "F09", "Qdrant unavailable / retrieval failure",
            "retrieval_unavailable|retrieval_failed|retrieval_failure",
        ),
        _s("F10", "PostgreSQL transient disconnect", "transient_db_disconnect|engine_se_recrea"),
        _s("F11", "tool timeout", "timeout_no_se_reintenta"),
        _s("F12", "tool hard failure (5xx/permanente)", "fallo_permanente_no_se_reintenta"),
        _s("F13", "malformed tool output", "malformed_output"),
        _s("F14", "circuit breaker abierto", "circuit_open_antes_del_primer_token|circuit"),
        _s("F15", "partial streaming failure", "stream_cortado_tras_emitir"),
        _s(
            "F16", "dependency recovery (circuito se cierra)",
            "circuit_breaker_and_runtime_guard|circuito_aislado_por_tenant|reset_circuit",
        ),
        _s("F17", "retry amplification acotada", "retry_acotado_por_candidato|factor_de_amplificacion"),
    ),
)

# -----------------------------------------------------------------------------
# Determinismo ×100 (Parte O del checklist)
# -----------------------------------------------------------------------------
DETERMINISM = Suite(
    name="determinism",
    purpose="Autoridad determinista independiente de la creatividad del modelo.",
    files=(
        "tests/test_certification_determinism.py",
        "tests/test_finalization_golden.py",
        "tests/test_adversarial_matrix.py",
        "tests/test_conversation_isolation.py",
    ),
    scenarios=(
        _s("O01", "tool authorization ×100", "tool_authorization_is_deterministic"),
        _s("O02", "tenant authorization ×100", "tenant_authorization_is_deterministic"),
        _s("O03", "cache isolation ×100", "cache_isolation_key_is_deterministic|cross_conversation_hits_cero"),
        _s("O04", "budget blocking ×100", "budget_blocking_is_deterministic|budget_without_overrun"),
        _s("O05", "finalization canónica ×100", "finalization_authority_is_deterministic|estabilidad_cien_runs"),
        _s("O06", "security guards ×100", "injection_guard_is_deterministic|resolucion_estable_100_runs"),
    ),
)

# -----------------------------------------------------------------------------
# Contabilidad / FinOps (Parte I del checklist)
# -----------------------------------------------------------------------------
ACCOUNTING = Suite(
    name="accounting",
    purpose="ledger == usage == billing input == observability; unknown != 0.",
    files=(
        "tests/test_certification_accounting_chain.py",
        "tests/test_run_accounting.py",
        "tests/test_run_accounting_rag.py",
        "tests/test_cost_authority.py",
        "tests/test_run_budget.py",
        "tests/test_budget_stop_reasons.py",
        "tests/test_run_metrics.py",
        "tests/test_finops.py",
        "tests/test_billing_limits_api.py",
    ),
    scenarios=(
        _s("I01", "una llamada: cadena completa cuadra", "ledger_usage_billing_observability_chain"),
        _s("I02", "retry/fallback visibles sin doble conteo", "retry_and_fallback_are_visible|attempts"),
        _s("I03", "unknown != 0", "unknown_cost_is_not_zero|unknown"),
        _s("I04", "budget blocking", "budget|budget_overrun"),
        _s("I05", "suma de líneas == total", "ledger_totales_igualan_el_evento|lineas"),
        _s("I06", "reconciliación billing", "reconcile|billing"),
    ),
)

# -----------------------------------------------------------------------------
# Aislamiento multi-tenant con contenido idéntico (Parte H del checklist)
# -----------------------------------------------------------------------------
TENANT = Suite(
    name="tenant",
    purpose="Aislamiento con datos deliberadamente parecidos entre organizaciones.",
    files=(
        "tests/test_certification_tenant_stress.py",
        "tests/test_tenant_isolation.py",
        "tests/test_conversation_isolation.py",
        "tests/test_knowledge_scope.py",
        "tests/test_authorized_scope.py",
        "tests/test_workspace_isolation.py",
    ),
    scenarios=(
        _s("H01", "retrieval con mismo texto/filename", "identical_documents"),
        _s("H02", "cache con misma query/conversación", "identical_query"),
        _s("H03", "usage/billing por tenant", "tenant_scoped"),
        _s("H04", "knowledge scope disjunto", "never_widens"),
        _s("H05", "aislamiento de vectores por KB", "scoped_to_organization"),
        _s("H06", "aislamiento de conversaciones", "conversacion|conversation"),
    ),
)

SUITES: dict[str, Suite] = {
    suite.name: suite for suite in (SECURITY, CHAOS, DETERMINISM, ACCOUNTING, TENANT)
}


def _parse_junit(path: Path) -> list[dict]:
    cases: list[dict] = []
    # El XML lo genera el propio pytest en este proceso (no es input externo).
    tree = ET.parse(path)  # noqa: S314 - junit escrito por nuestro pytest
    for case in tree.iter("testcase"):
        status = "pass"
        detail = ""
        if case.find("failure") is not None:
            status = "fail"
            detail = (case.find("failure").get("message") or "")[:300]
        elif case.find("error") is not None:
            status = "error"
            detail = (case.find("error").get("message") or "")[:300]
        elif case.find("skipped") is not None:
            status = "skipped"
            detail = (case.find("skipped").get("message") or "")[:200]
        cases.append(
            {
                "classname": case.get("classname") or "",
                "name": case.get("name") or "",
                "nodeid": f"{case.get('classname') or ''}::{case.get('name') or ''}",
                "status": status,
                "detail": detail,
            }
        )
    return cases


def _scenario_result(scenario: Scenario, cases: list[dict]) -> dict:
    matched = [
        case
        for case in cases
        if all(token.lower() in case["nodeid"].lower() for token in scenario.match)
    ]
    if not matched:
        # sin match exacto: probar con cualquier token (escenario amplio)
        matched = [
            case
            for case in cases
            if any(token.lower() in case["nodeid"].lower() for token in scenario.match)
        ]
    failures = [c for c in matched if c["status"] in {"fail", "error"}]
    if not matched:
        status = "not_demonstrated"
    elif failures:
        status = "fail"
    else:
        status = "pass"
    return {
        "id": scenario.id,
        "title": scenario.title,
        "match": list(scenario.match),
        "status": status,
        "tests": [c["nodeid"] for c in matched],
        "failures": [{"test": c["nodeid"], "detail": c["detail"]} for c in failures],
    }


def _git_head() -> str:
    """HEAD del repo. Comando fijo, sin input externo (git del PATH)."""
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],  # noqa: S607 - git del PATH, args fijos
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def run_suite(suite: Suite, out_dir: Path, *, extra_args: list[str]) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    junit = out_dir / f"junit-{suite.name}.xml"
    command = [
        sys.executable,
        "-m",
        "pytest",
        *suite.files,
        "-q",
        "--tb=short",
        "--timeout=300",
        f"--junitxml={junit}",
        *extra_args,
    ]
    started = datetime.now(timezone.utc)
    # Comando fijo (python -m pytest + archivos del repo): no hay input externo.
    completed = subprocess.run(  # noqa: S603 - lista de args fija
        command, cwd=ROOT, capture_output=True, text=True
    )
    finished = datetime.now(timezone.utc)
    log_path = out_dir / f"pytest-{suite.name}.log"
    log_path.write_text(completed.stdout + completed.stderr, encoding="utf-8")

    cases = _parse_junit(junit) if junit.exists() else []
    scenarios = [_scenario_result(scenario, cases) for scenario in suite.scenarios]
    payload = {
        "schema": "zent.cert.battery/1",
        "suite": suite.name,
        "purpose": suite.purpose,
        "generated_at": finished.isoformat(),
        "duration_seconds": round((finished - started).total_seconds(), 1),
        "git_sha": _git_head(),
        "command": " ".join(command),
        "pytest_exit_code": completed.returncode,
        "totals": {
            "tests": len(cases),
            "pass": sum(1 for c in cases if c["status"] == "pass"),
            "fail": sum(1 for c in cases if c["status"] == "fail"),
            "error": sum(1 for c in cases if c["status"] == "error"),
            "skipped": sum(1 for c in cases if c["status"] == "skipped"),
        },
        "scenarios": scenarios,
        "summary": {
            "pass": sum(1 for s in scenarios if s["status"] == "pass"),
            "fail": sum(1 for s in scenarios if s["status"] == "fail"),
            "not_demonstrated": sum(
                1 for s in scenarios if s["status"] == "not_demonstrated"
            ),
        },
        "junit": str(junit),
        "log": str(log_path),
    }
    (out_dir / f"{suite.name}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        f"# Battery — {suite.name}",
        "",
        f"- SHA: `{payload['git_sha']}`",
        f"- Fecha: {payload['generated_at']}",
        f"- Comando: `{payload['command']}`",
        f"- Tests: {payload['totals']['tests']} "
        f"(pass {payload['totals']['pass']} / fail {payload['totals']['fail']} / "
        f"error {payload['totals']['error']} / skip {payload['totals']['skipped']})",
        f"- Escenarios: pass {payload['summary']['pass']} / fail {payload['summary']['fail']} "
        f"/ no demostrados {payload['summary']['not_demonstrated']}",
        "",
        "| ID | Escenario | Estado | Tests |",
        "|---|---|---|---|",
    ]
    for scenario in scenarios:
        icon = {"pass": "PASS", "fail": "FAIL", "not_demonstrated": "NO DEMOSTRADO"}[
            scenario["status"]
        ]
        lines.append(
            f"| {scenario['id']} | {scenario['title']} | {icon} | "
            f"{len(scenario['tests'])} |"
        )
    (out_dir / f"{suite.name}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Batería de certificación")
    parser.add_argument("--suite", default="all", choices=[*SUITES, "all"])
    parser.add_argument("--out-dir", default="")
    parser.add_argument("--extra", nargs="*", default=[])
    args = parser.parse_args()

    out_dir = Path(args.out_dir) if args.out_dir else ROOT / "artifacts" / "certification" / "battery"
    names = list(SUITES) if args.suite == "all" else [args.suite]

    failed: list[str] = []
    for name in names:
        payload = run_suite(SUITES[name], out_dir, extra_args=args.extra)
        print(
            f"[{name}] scenarios pass={payload['summary']['pass']} "
            f"fail={payload['summary']['fail']} "
            f"not_demonstrated={payload['summary']['not_demonstrated']} "
            f"tests_fail={payload['totals']['fail'] + payload['totals']['error']}"
        )
        if (
            payload["summary"]["fail"]
            or payload["summary"]["not_demonstrated"]
            or payload["totals"]["fail"]
            or payload["totals"]["error"]
        ):
            failed.append(name)
    if failed:
        print(f"baterías con problemas: {failed}")
        return 1
    print("baterías OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
