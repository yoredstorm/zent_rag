# Release Evidence Manifest

- SHA: `a815a1d4ae8ef2ca9d9547394fa7626703cd23f8` (master, dirty=True)
- Generado: 2026-10-15T00:57:06.613614+00:00 por `src/scripts/release_manifest.py`
- Build: `local-20261015T005706Z` (CI run: 38658924678 (HEAD a815a1d: success) / 38653834675 (8ee8200: success, suite 5476 tests))
- Runtime: Python 3.13.7 / uv 0.12.13 / Windows-11-10.0.26200-SP0
- Migración head: `151`
- **Decisión: READY_FOR_INTERNAL** (github-actions runner (CI) + workstation local (evidencia local declarada por artefacto))
- Motivo: CI verde en HEAD (run 38658924678, 10/10 jobs) y en el release candidate 8ee8200 (run 38653834675: suite completa 5476 tests 0 fallos, invariantes 406 tests 0 fallos); bateria 57/57 escenarios (tree edeeb61, codigo de producto identico); branch protection aplicada; Alertmanager conectado y probado end-to-end en local. CANARY bloqueado por 2 condiciones: baseline/load de staging con corpus cargado y observabilidad desplegada en staging con receptor externo de alertas.

## Tests

| Suite | Estado | Detalle |
|---|---|---|
| full_suite | pass | tests=5476 fail=0 err=0 skip=4 |
| invariants | pass | tests=406 fail=0 err=0 skip=0 |
| battery | pass | accounting:pass, chaos:pass, determinism:pass, security:pass, tenant:pass |

## Checks

| Check | Resultado |
|---|---|
| ruff | pass |
| uv lock --check | pass |
| dashboard --check | pass |
| sbom --check | pass (mismo content hash que edeeb61) |
| gitleaks | pass (CI) |
| pip-audit | pass (CI, informativo) |
| nightly | bateria+invariantes+artifacts (implementado) |
| alertmanager | e2e fired+resolved (local) |

## Evidencia externa

| Evidencia | Estado | Archivo |
|---|---|---|
| perf | measured | `artifacts\certification\edeeb61a9e37fff1e39f1a751f5e97470f9ce3d8\perf\matrix.json` |
| load | measured | `artifacts\certification\edeeb61a9e37fff1e39f1a751f5e97470f9ce3d8\perf\cert-load.json` |
| http-probe | measured | `artifacts\certification\edeeb61a9e37fff1e39f1a751f5e97470f9ce3d8\perf\http-probe.json` |
| http-probe-after-deploy | measured | `artifacts\certification\edeeb61a9e37fff1e39f1a751f5e97470f9ce3d8\perf\http-probe-after-deploy.json` |
| migrations | measured | `artifacts\certification\edeeb61a9e37fff1e39f1a751f5e97470f9ce3d8\migrations.json` |
| rollback | measured | `artifacts\certification\edeeb61a9e37fff1e39f1a751f5e97470f9ce3d8\rollback\rehearsal.json` |
| local-deploy | measured | `artifacts\certification\684d383c6afb62c41522a69c026599965a7ea9e4\local-deploy.json` |
| branch-protection | measured | `artifacts\certification\684d383c6afb62c41522a69c026599965a7ea9e4\branch-protection.json` |
| ci-run-rc | measured | `artifacts\certification\8ee820004c8acfffff4a20e5250319634a69bb27\ci\ci-run.json` |
| ci-run-head | measured | `artifacts\certification\a815a1d4ae8ef2ca9d9547394fa7626703cd23f8\ci-run.json` |

## Dependencias (fingerprints)

| Archivo | sha256 |
|---|---|
| uv.lock | `da55449bedabd6c1…` |
| pyproject.toml | `76d0416e482fdac2…` |
| .python-version | `49a506dd32096b01…` |
| portal/package-lock.json | `53b88b8ed8745061…` |
| portal/package.json | `9737a9a32b808607…` |
| sdk/node/package-lock.json | `e9b6257cae3b4464…` |
| Dockerfile.api | `2d379e7b3e9fdb6c…` |
| portal/Dockerfile | `a80b2eb5b9091720…` |
| docker-compose.prod.yml | `62a4fec2b8ae34d1…` |

## Warnings conocidos

- WARNINGS CONOCIDOS (al SHA certificado; si el código cambia, re-verificar)
- - El venv local corre Python 3.13.7 mientras CI/imagen usan 3.11: los tests locales no son evidencia de paridad de runtime.
- - El .env de desarrollo define RUNTIME_ANSWER_GATE=on con 'answer_gate' en RUNTIME_JEV_SKIP_PHASES: config.py emite "dangerous_gate_phase_skipped" al importar (config de dev, no de CI).
- - El .env de desarrollo usa el POSTGRES_PASSWORD y PORTAL_SESSION_KEY de desarrollo: config.py emite warnings SECURITY en cada import (esperado fuera de producción).
- - portal-e2e tiene un flake conocido registrado en el repo (commit 17acf3d, docs/architecture/ownership): no se promueve a required check de release hasta estabilizarlo.
- - Las revisiones de migración recientes usan CREATE INDEX sin CONCURRENTLY y la 151 hace DROP COLUMN (lock/destructivo): ver docs/architecture/certification/delivery.md §4.
- - El reporte de reconciliación redondea a centavos (round 2): runs de menos de un centavo aparecen con delta 0.00.

## Riesgos aceptados

- [P2] Umbrales de latencia/costo PROVISIONAL (sin baseline de staging) — owner: Platform — Corrida de staging con 30 iteraciones y concurrencia 25/50; fijar umbrales en alert-rules.yml
- [P2] Carga cercana a capacidad (25/50 concurrentes) no medida — owner: Platform — Corrida de load en staging con pool dimensionado
- [P2] Observabilidad (Prometheus/Grafana/Alertmanager) no desplegada en el entorno real — owner: Platform — Desplegar stack de observabilidad y scrape de /metrics con METRICS_TOKEN
- [P2] Branch protection: enforcement duro requiere PRs requeridos (hoy los checks aplican a merges de PR, no a push directo) — owner: Platform — Activar required_pull_request_reviews con 0 approvals si se quiere bloquear el push directo (decisión del owner)
- [P2] pip-audit no bloquea el merge (continue-on-error) — owner: Security — Estabilizar advisories y promoverlo a required check
- [P2] Precios por defecto hardcodeados pueden convertir unknown en conocido — owner: FinOps — Cargar tarifas reales; revisar el fallback antes de producción
- [P2] Fallback del loop de candidatos sin línea contable con costo — owner: AI Runtime — Extender la emisión de provider_attempt al loop de candidatos
- [P2] Sin métrica de divergencia contable (ledger vs usage vs billing) — owner: FinOps — Métrica + alerta; billing_reconcile.py diario
- [P2] Alertmanager sin receptor externo y sin scheduler de POST /platform/obs/check — owner: Platform — Conectar webhook/Slack/PagerDuty en config/alertmanager/alertmanager.yml y agregar CronJob/scheduler
- [P2] 20 except Exception sin certificar en caminos críticos (ratchet en CI) — owner: AI Runtime — Certificar al tocar cada bloque; el número no puede crecer
- [P2] Imágenes base y actions de CI pinneadas por tag, sin Dependabot — owner: Platform — Pin por digest + Dependabot/renovate
- [P3] Tests dependientes de estado sembrado fallan con drift del DB local — owner: Platform — Usar scripts/cert/scratch_db.py (paridad CI) o reseed del org demo

> Este manifest se genera desde evidencia real. Cualquier resultado `not_available` significa NO DEMOSTRADO, nunca verde. Si el código cambia, este archivo caduca: regenerar antes de promover.
