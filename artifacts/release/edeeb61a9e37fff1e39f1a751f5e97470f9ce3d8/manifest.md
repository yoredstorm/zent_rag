# Release Evidence Manifest

- SHA: `edeeb61a9e37fff1e39f1a751f5e97470f9ce3d8` (master, dirty=True)
- Generado: 2026-10-14T20:45:27.197670+00:00 por `src/scripts/release_manifest.py`
- Build: `local-20261014T204527Z` (CI run: 38596793506 (base 17acf3d: success, todos los jobs))
- Runtime: Python 3.13.7 / uv 0.12.13 / Windows-11-10.0.26200-SP0
- Migración head: `151`
- **Decisión: NO_GO** (local-workstation (Windows) + DBs scratch con paridad CI)
- Motivo: Faltan 4 condiciones para canary (CI del SHA certificado, full suite del SHA certificado, baseline/load de staging, observabilidad desplegada). Detalle en docs/architecture/certification/final-report.md

## Tests

| Suite | Estado | Detalle |
|---|---|---|
| full_suite | not_available | tests=n/a fail=n/a err=n/a skip=n/a |
| invariants | pass | tests=406 fail=0 err=0 skip=0 |
| battery | pass | accounting:pass, chaos:pass, determinism:pass, security:pass, tenant:pass |

## Checks

| Check | Resultado |
|---|---|
| sbom --check | pass |

## Evidencia externa

| Evidencia | Estado | Archivo |
|---|---|---|
| rollback | measured | `artifacts\certification\edeeb61a9e37fff1e39f1a751f5e97470f9ce3d8\rollback\rehearsal.json` |

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
| docker-compose.prod.yml | `f7d1e5c77688c3d8…` |

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
- [P2] Branch protection no verificada (API GitHub 401 sin token) — owner: Platform — Auditar y fijar required checks con gh api (delivery.md §1)
- [P2] pip-audit no bloquea el merge (continue-on-error) — owner: Security — Estabilizar advisories y promoverlo a required check
- [P2] Precios por defecto hardcodeados pueden convertir unknown en conocido — owner: FinOps — Cargar tarifas reales; revisar el fallback antes de producción
- [P2] Fallback del loop de candidatos sin línea contable con costo — owner: AI Runtime — Extender la emisión de provider_attempt al loop de candidatos
- [P2] Sin métrica de divergencia contable (ledger vs usage vs billing) — owner: FinOps — Métrica + alerta; billing_reconcile.py diario
- [P2] Sin evaluación periódica de alertas de tenant (solo endpoint manual) — owner: Platform — CronJob/scheduler que dispare POST /platform/obs/check
- [P2] 20 except Exception sin certificar en caminos críticos (ratchet en CI) — owner: AI Runtime — Certificar al tocar cada bloque; el número no puede crecer
- [P2] Imágenes base y actions de CI pinneadas por tag, sin Dependabot — owner: Platform — Pin por digest + Dependabot/renovate
- [P3] Tests dependientes de estado sembrado fallan con drift del DB local — owner: Platform — Usar scripts/cert/scratch_db.py (paridad CI) o reseed del org demo

> Este manifest se genera desde evidencia real. Cualquier resultado `not_available` significa NO DEMOSTRADO, nunca verde. Si el código cambia, este archivo caduca: regenerar antes de promover.
