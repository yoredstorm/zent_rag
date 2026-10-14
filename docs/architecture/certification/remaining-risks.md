# Riesgos remanentes (P0–P3)

Base: `edeeb61` (SHA certificado) sobre `17acf3d`. Cada riesgo declara evidencia,
impacto, mitigación y owner. **P0/P1 abiertos: ninguno** (los hallazgos de esta
fase se corrigieron; ver `security-report.md`).

## P0 — ninguno

No se encontró ningún riesgo que impida operar ni que comprometa aislamiento,
autoridad o contabilidad sin control.

## P1 — ninguno abierto

Dos hallazgos de seguridad reales se corrigieron en esta fase (quedan como P1
**cerrados** con test de regresión):

| Hallazgo | Evidencia | Fix |
|---|---|---|
| SSRF por redirect en conectores de knowledge (`web_source.py`, `api_source.py` seguían redirects sin revalidar host) | `tests/test_certification_security.py::TestKnowledgeSourceSSRF` | `src/knowledge/connectors/http.py` (allowlist + revalidación por salto) |
| `bool` aceptado como `integer`/`number` en argumentos de tools (smuggling) | `tests/test_certification_security.py::TestToolArgumentSmuggling` | `src/agents/tools/guards.py` rechaza bool salvo tipo `boolean` |

## P2 — aceptados con plan (bloquean PRODUCCIÓN, no INTERNAL/CANARY)

| # | Riesgo | Evidencia | Mitigación | Owner |
|---|---|---|---|---|
| P2-1 | Sin baseline de performance de staging: los umbrales de latencia/costo de las alertas son PROVISIONAL | `perf-baseline.md` (§límites), `alert-rules.yml` | correr `run_perf_matrix.ps1` en staging con 30 iteraciones y concurrencia 25/50; fijar umbrales | Platform |
| P2-2 | Carga cercana a capacidad (25/50 concurrentes) no medida: solo 1/2/4 local | `load-backpressure.md` | corrida en staging con provider real y pool dimensionado | Platform |
| P2-3 | Observabilidad no conectada en el entorno real: Prometheus/Grafana/Alertmanager fuera de `docker-compose.prod.yml` y k8s | `observability.md` §5 | desplegar el stack de observabilidad y el scrape con `METRICS_TOKEN` | Platform |
| P2-4 | ~~Branch protection no verificada~~ **CERRADO 2026-10-14**: protección aplicada y verificada (8 required checks, force push y borrado bloqueados). Enforcement duro en push directo requiere activar PRs requeridos (decisión del owner) | `artifacts/certification/684d383…/branch-protection.json` | activar PRs requeridos si se quiere bloquear el push directo | Platform |
| P2-5 | `pip-audit` no bloquea (`continue-on-error: true`) | `.github/workflows/ci.yml` | estabilizar advisories y promoverlo a required | Security |
| P2-6 | Precios por defecto hardcodeados (`run_budget.usage_cost`, `pricing.estimate_cost`) pueden convertir "sin tarifa" en costo "conocido" aguas abajo | `accounting-validation.md` §unknown | cargar tarifas reales; revisar el fallback antes de producción | FinOps |
| P2-7 | Intento fallido del loop de candidatos (`router_fallback`) no deja línea contable con costo (solo el router emite `provider_attempt`) | `accounting-validation.md` §límites | extender la emisión al loop de candidatos (cambio de código, no de certificación) | AI Runtime |
| P2-8 | Sin métrica de divergencia contable (ledger vs usage vs billing): se valida con job diario + test | `observability.md` §2 | agregar métrica y alerta; correr `billing_reconcile.py` a diario | FinOps |
| P2-9 | Alertmanager conectado y probado en local, pero sin receptor externo ni scheduler que dispare `POST /platform/obs/check` | `observability.md` §3/§6 | conectar webhook/Slack/PagerDuty y CronJob/scheduler | Platform |
| P2-10 | 20 `except Exception` sin certificar en caminos críticos (ratchet en CI impide que crezca) | `tests/test_exception_certification.py` | certificar al tocar cada bloque | AI Runtime |
| P2-11 | Imágenes base por tag, no por digest; actions de CI por tag mayor (`@v4`), sin Dependabot | `manifest-and-build.md` §riesgos | pin por digest + Dependabot/renovate | Platform |

## P3 — deuda menor

| # | Riesgo | Evidencia | Nota |
|---|---|---|---|
| P3-1 | `delta_usage_vs_invoiced` redondea a centavos: runs de <$0.01 dan delta 0 | `tests/test_certification_accounting_chain.py` | documentado; los cargos reales son ≥ centavos |
| P3-2 | `knowledge_usage` (ingesta) y `usage_events` (runs) son tablas distintas | `accounting-validation.md` | no comparten unidad por request; revisar en facturación de ingesta |
| P3-3 | `gdrive` client usa `follow_redirects=True` sobre hosts fijos de Google | `src/knowledge/connectors/gdrive/client.py` | host fijo del proveedor; revisar si se agregan scopes |
| P3-4 | Batería de seguridad tarda ~22 min (corre como paso de nightly, no de PR) | `security-report.md` §ejecución | partirla por suite si molesta |
| P3-5 | Config de desarrollo local con `RUNTIME_ANSWER_GATE=on` + `answer_gate` en `RUNTIME_JEV_SKIP_PHASES` dispara warning de config "gate que nunca juzga" | warning al importar `src/core/config.py` | el .env de dev no es paridad CI; corregir el `.env` local |
| P3-6 | Tests que dependen de estado sembrado (`subscriptions` del org demo) fallan en DBs locales con drift | `manifest-and-build.md` §entorno | usar `scripts/cert/scratch_db.py` (paridad CI) o reseed |

## Riesgos aceptados explícitamente para canary

Ninguno. La promoción a canary no requiere aceptar riesgos nuevos: P2-1/P2-2
se resuelven con la corrida de staging (que es parte del gate), P2-3/P2-4 se
resuelven con configuración de entorno, y el resto no bloquea canary.

Para **producción**, además, hay que aceptar (o cerrar) P2-6/P2-7/P2-8/P2-11.
