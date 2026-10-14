# Certificación ZENT — Reporte final y GO/NO-GO

## 0. SHA certificado y entorno

| Dato | Valor |
|---|---|
| **SHA certificado (código)** | `edeeb61a9e37fff1e39f1a751f5e97470f9ce3d8` (`edeeb61`) |
| SHA base sobre el que se trabajó | `17acf3ddb7f2fbddc516830a3abdf7227bf72c8a` (`17acf3d`) |
| Rama | `master` |
| Fecha de certificación | 2026-10-14 (UTC 18:30–21:00) |
| Entorno | workstation local (Windows 11, Docker Desktop 29.7.2) + Postgres 16/pgvector, Redis 7, Qdrant v1.13.4 locales + providers reales (Novita primario, DeepInfra fallback) |
| DBs de evidencia | `rag_cert`, `rag_cert_battery`, `rag_cert_invariants`, `rag_cert_mig`, `rag_cert_rehearsal` — creadas desde cero replicando el job `test` de CI (`scripts/cert/scratch_db.py`) |
| Config | perfil `ci-parity` (valores default de `config.py`) o `.env` local declarado en cada documento |
| Python | venv local 3.13.7; CI/imagen 3.11 (**no** es paridad de runtime, ver `manifest-and-build.md` §5) |

Cambios incluidos en `edeeb61` (no son features: fixes de seguridad, tests,
tooling de evidencia y assets de operación): ver el commit y
`security-report.md` §2, `observability.md` §2, `delivery.md`.

## 1. Release Evidence Manifest

- `artifacts/release/edeeb61a9e37fff1e39f1a751f5e97470f9ce3d8/manifest.json` (machine-readable)
- `artifacts/release/edeeb61a9e37fff1e39f1a751f5e97470f9ce3d8/manifest.md` (human-readable)
- Generado por `src/scripts/release_manifest.py` (no escrito a mano; sin secretos).
- Contenido clave: SHA/branch/tag/dirty, fingerprints de `uv.lock` +
  `pyproject.toml` + locks de portal/SDK + Dockerfiles, SBOM (734 componentes,
  hash de contenido), migración head `151` (150 revisiones, todas con
  `downgrade`), imagen `zent-api:cert-edeeb61`
  (`sha256:cb7fba67…`), checks (ruff/lock/gitleaks/dashboard/SBOM), resultados de
  invariantes y batería, evidencia de perf/load/chaos/migraciones/rollback,
  warnings conocidos, riesgos aceptados y la decisión con su motivo.
- `not_available` en `tests.full_suite` es deliberado: **no se corrió la suite
  completa sobre `edeeb61`** (ver §3 y §12).

## 2. Resumen de tests

| Evidencia | Resultado | Fuente |
|---|---|---|
| Invariantes de arquitectura (lista exacta de `ci.yml`, 33 archivos) | **PASS** (exit 0, 970 s) | `artifacts/certification/<sha>/invariants/invariants.evidence.json` |
| Batería de certificación (5 suites, 57 escenarios) | **PASS** (0 fail, 0 no-demostrados) | `artifacts/certification/<sha>/battery/*.json` |
| — seguridad/adversarial | 22/22 escenarios · 350 tests | `battery/security.json` |
| — chaos | 17/17 escenarios · 115 tests | `battery/chaos.json` |
| — determinismo ×100 | 6/6 escenarios · 222 tests | `battery/determinism.json` |
| — contabilidad/FinOps | 6/6 escenarios · 65 tests | `battery/accounting.json` |
| — aislamiento tenant | 6/6 escenarios · 49 tests | `battery/tenant.json` |
| Lint + lock | ruff `All checks passed`; `uv lock --check` OK | local + CI |
| Suite completa sobre el SHA certificado | **NO CORRIDA (parcial)**: run local abortada a ~3% (≈218 tests, **0 fail/error** observados) por tiempo de pared; CI no ejecutado (commit no pusheado) | observación local, 2026-10-14 |
| CI del SHA base `17acf3d` | **success**: 10/10 jobs (secrets-scan, lint, pip-audit, test, sdk-python, sdk-node, portal, portal-e2e, kustomize, build) | GitHub Actions run `38596793506` |
| Nightly | 14/10 success; 13/10 **failure** (paso "Full suite") | runs `38520279844` / `38357887002` |

Hallazgo de calidad de suite: `tests/test_run_metrics.py` usaba aserciones de
valor **absoluto** sobre counters globales; la batería nueva (que publica en los
mismos labels) la rompió. Se corrigió a deltas (evidencia: fallaba solo en
suite, pasa aislado) — es el tipo de no-hermeticidad que la certificación debe
encontrar.

## 3. Performance (Parte C)

Detalle y tablas: `perf-baseline.md`. Resumen del perfil `ci-parity`
(org demo sin documentos → camino retrieval + política + abstención, 18 runs,
**0 errores**):

| Workload | p50 | p95 | Fases | Answer states |
|---|---:|---:|---|---|
| simple cold/warm | 3,1 / 2,4 s | 6,1 / 7,6 s | FINALIZED ×3 | INSUFFICIENT_EVIDENCE |
| rag multi-doc | 2,2 s | 6,3 s | FINALIZED ×3 | UNDETERMINED_RULE |
| agentic | 17,9 s | 55,4 s | FINALIZED ×3 | UNDETERMINED_RULE / INSUFFICIENT_EVIDENCE |
| no-evidence | 7,4 s | 8,1 s | FINALIZED ×3 | INSUFFICIENT_EVIDENCE / EXECUTION_FAILED |
| primario roto → **fallback real** | 10,1 s | 15,2 s | FINALIZED ×3 | INSUFFICIENT_EVIDENCE |

HTTP real (`http-probe.json`): miss 7,0 s · repetición 6,4 s · **TTFT 7,46 s**
(primer evento SSE a 24 ms) · stream completo 7,46 s. **Caché de respuestas: 0
hits y 2 misses** en la misma query → caché efectivamente deshabilitada por la
política fail-closed (riesgo P2, ver §12).

Perfil `dev` (config local completa): p50 ≈ 50 s, p95 ≈ 433 s, con una corrida de
33.537 tokens y `llm_latency_ms=941` → **la latencia la domina la ingesta
perezosa/ensamblado, no el LLM**. No sirve como SLO.

## 4. Load y backpressure (Parte E)

`cert-load.json` (3 requests por nivel, perfil ci-parity): 0 errores, 0
`rate_limited`, amplificación 0, Postgres/Redis planos y bajos (1–5 ms Redis,
112–141 ms Postgres). p50 crece con la concurrencia (5,3 → 12,3 s a 4) por
contención local, no por dependencias. **25/50 concurrentes: no medido**
(condición de staging, P2-2).

## 5. Chaos (Parte F)

`chaos-report.md`: 17/17 escenarios herméticos PASS (provider down/429/timeout,
fallback, embeddings, reranker, JEV, Redis, retrieval, Postgres transitorio,
tools timeout/5xx/malformada, circuito, stream parcial, recuperación,
amplificación acotada ≤4). Ensayos reales: **fallback de provider end-to-end**
(§3) y **rollback ensayado** (§9). Pendiente: matar Redis/Qdrant en staging.

## 6. Seguridad / adversarial (Parte G)

`security-report.md`: 22/22 escenarios, 350 tests, 0 fallos. Dos P1
**encontrados y cerrados** con regresión: SSRF por redirect en conectores de
knowledge (H1) y `bool` como `integer` en argumentos de tools (H2). El modelo no
es autoridad de seguridad en ninguno de los caminos verificados.

## 7. Aislamiento tenant (Parte H)

`tenant-isolation.md`: A/B con mismo texto, mismo `filename`, misma query, mismo
rol, misma etiqueta de conversación y mismo fingerprint → la clave de caché y el
filtro de retrieval siguen aislados; usage/billing por org; scope disjunto no se
amplía. 6/6 escenarios, 49 tests.

## 8. Contabilidad / FinOps (Parte I)

`accounting-validation.md`: cadena `ledger == usage == billing input ==
observability` verificada con matemática conocida (0,002002 USD en los cuatro
eslabones), `unknown != 0` (línea sin costo + flag + razón + counter), budget
blocking determinista, suma de líneas == total, reconciliación. 6/6, 65 tests.
Gaps declarados: precio default hardcodeado (P2-6), intentos del loop de
candidatos sin línea (P2-7), sin métrica de divergencia (P2-8).

## 9. Migraciones y rollback (Partes Q y P)

| Paso | Resultado |
|---|---|
| `alembic upgrade head` desde cero (150 revisiones) | exit 0, 2,6 s |
| `downgrade -1` (151→150) + `upgrade head` | exit 0, 3,2 s / 3,1 s |
| Rollback de release ensayado (imagen real) | bad release detectado (`/health` degraded, `qdrant: error`) y rollback sano en **16,9 s** |
| Lock risk | últimas 10 revisiones con `CREATE INDEX` sin `CONCURRENTLY`; la 151 además `DROP COLUMN` → ventana de baja escritura / snapshot |

## 10. SLO/SLI y error budget (Parte D)

`slo.md`: disponibilidad ≥99,9% mensual (0,1% de presupuesto), invariantes duros
sin presupuesto (aislamiento, autoridad, conversación, seguridad = 0), y targets
de latencia **derivados del baseline medido** (p95 ≤20 s determinista, ≤120 s
agentic, ≤30 s con fallback, TTFT ≤15 s) marcados PROVISIONAL hasta staging.
Definición explícita de error: ABSTAIN legítimo **no** es fallo; 429 con
fallback es evento degradado; `RETRIEVAL_UNAVAILABLE` **sí** es fallo.

## 11. Observabilidad, alertas y runbooks (Partes J–L)

- Dashboard de producción como código (`config/grafana/dashboards/zent-production.json`,
  35 paneles, generado por `src/scripts/observability_assets.py`) + contract
  test en CI (métricas existentes, labels acotados, `--check` de frescura).
- 21 reglas de alerta (`config/prometheus/alert-rules.yml`) con severity, owner,
  SLI, runbook, diagnóstico ejecutable y mitigación. Se eliminaron 2 reglas
  muertas y se corrigió el bug de counter monotónico en la alerta multi-tenant.
- 18 runbooks con comandos reales (`docs/architecture/runbooks/README.md`).
- Stack de observabilidad declarado en `docker-compose.prod.yml` (profile
  `observability`, verificado por test); **falta desplegarlo** (P2-3) y conectar
  Alertmanager/scheduler (P2-9).

## 12. Riesgos P0–P3

`remaining-risks.md`. **P0: ninguno. P1: ninguno abierto** (2 cerrados con
regresión). P2 (11): baseline/load de staging, observabilidad sin desplegar,
branch protection sin verificar, pip-audit no bloqueante, precios default,
intentos del loop sin línea contable, sin métrica de divergencia contable,
scheduler de alertas, 20 `except` sin certificar (ratchet), pin por digest,
caché sin señal accionable de bypass. P3 (6): redondeo a centavos, `knowledge_usage`
separado, gdrive redirects, duración de la batería, config de dev con warning,
tests dependientes de seed.

## 13. GO / NO-GO

| Estado | Decisión | Base |
|---|---|---|
| **READY FOR INTERNAL** | **SÍ** | invariantes + batería + contabilidad + aislamiento + determinismo verdes; fixes de seguridad con regresión; rollback ensayado |
| **READY FOR CANARY** | **NO-GO** | faltan condiciones exactas (§13.1) |
| READY FOR PRODUCTION | NO-GO | requiere canary + cierre de P2 de producción |

### 13.1 Condiciones exactas que faltan para canary

1. **CI verde del SHA certificado**: pushear `edeeb61` (o el SHA final con la
   evidencia) y obtener `success` en los 10 jobs (hoy solo existe para `17acf3d`).
2. **Suite completa verde sobre el SHA certificado**: el job `test` de CI la
   corre (~30 min en runner); localmente no se completó (no hay evidencia).
3. **Baseline de performance y load en staging** con corpus cargado (30
   iteraciones, concurrencia 25/50) → fijar los umbrales PROVISIONAL de latencia
   y costo en `alert-rules.yml` y `slo.md` (P2-1, P2-2).
4. **Observabilidad desplegada y conectada**: `--profile observability` en el
   entorno real, scrape de `/metrics` confirmado y receptor de alertas
   (Alertmanager o equivalente) + scheduler de `POST /platform/obs/check` (P2-3, P2-9).
5. **Branch protection verificada y configurada** con los required checks de
   `delivery.md` §1 (P2-4).

Condiciones adicionales **para producción**: cerrar o aceptar formalmente
P2-5…P2-8 y P2-11 (pip-audit bloqueante, precios reales, visibilidad de intentos
del loop, métrica de divergencia contable, pin por digest) y correr el chaos de
infraestructura real (Redis/Qdrant) en staging.

## 14. Scorecard (por evidencia, 0–10)

Ninguna dimensión obtiene 10: **no hay evidencia reproducible del contrato
completo en el entorno objetivo** (staging/producción). Un 10 exigiría, por
ejemplo, baseline y chaos de staging para performance/reliability, y observabilidad
desplegada para observabilidad. Los puntajes reflejan lo demostrado hoy.

| Dimensión | Nota | Evidencia positiva | Qué impide el 10 |
|---|---:|---|---|
| architecture | 8 | 33 invariantes PASS + ownership docs + tests de contrato | sin re-verificación independiente de cada ADR |
| correctness | 7 | batería 57/57 + invariantes + tests focalizados + 218 tests de la suite sin fallos (parcial) | suite completa no completada en el SHA certificado |
| authority | 9 | determinismo ×100 (6 escenarios) + golden corpus + alerta de divergencia | sin corrida prolongada en staging |
| security | 8 | 22/22 + 2 P1 cerrados + mitigaciones estructurales | sin pentest externo/fuzzing |
| tenant isolation | 9 | A/B idéntico + contratos + invariantes + 49 tests | sin prueba cross-región/workspace en batería |
| reliability | 8 | chaos 17/17 + fallback real + rollback ensayado | chaos de infraestructura en staging |
| observability | 6 | dashboards/alertas como código + contratos + compose profile | no desplegado, sin Alertmanager/scheduler |
| performance | 5 | baseline real medido (2 perfiles) + TTFT + rutas degradadas | local, n=3, sin corpus cargado ni staging |
| cost/accounting | 7 | cadena con matemática + unknown≠0 + budget | precios default, loop sin línea, sin métrica de divergencia |
| maintainability | 7 | tooling de evidencia + ratchets + docs indexados | 20 `except` sin certificar, módulos grandes |
| test quality | 7 | escenario→test mapeado + no-demostrados explícitos | suite lenta/pesada; hermeticidad a corregir por caso |
| build reproducibility | 7 | locks frozen + SBOM determinista + imagen construida | bases/actions por tag, sin Dependabot |
| operational readiness | 6 | 18 runbooks + rollback 16,9 s + alertas con owner | branch protection sin verificar, staging sin ejercitar |

**Promedio: 7,2/10** — consistente con la decisión: sistema sólido y verificable
internamente, todavía **no certificable para canary** por evidencia de entorno,
no por falta de diseño.

## 15. Verificación de deploy local (rebuild + smoke)

Ejecutada después de reconstruir las imágenes locales con el código certificado.
Evidencia: `artifacts/certification/ff072e8…/local-deploy.json`
(`scripts/cert/local_deploy_evidence.py`) + `…/perf/http-probe-after-deploy.json`.

| Check | Resultado |
|---|---|
| Imagen local `zent_rag-api` reconstruida (target worker, SHA inyectado) | `RAG_GIT_SHA=ff072e88…` dentro del contenedor |
| `/health` del contenedor nuevo | `healthy` (postgres/qdrant/redis/decision_engine ok) |
| Prometheus local tras `restart` | 6 grupos, **24 reglas**, 0 reglas con error |
| Targets de scrape | `rag-api` y `prometheus` up, **0 down** (jobs muertos de exporters deshabilitados) |
| Grafana | dashboard `ZENT - Producción (canary)` provisionado, 35 paneles |
| Métricas run-level en `/metrics` | `zent_runs_total{path="rag",phase="FINALIZED"}`, `zent_run_latency_seconds_count{path="rag"}` |
| **E2E del fix SSRF en el contenedor** | PASS: server local allowlisted recibe 1 request; el 302 a `169.254.169.254` se bloquea y el hop interno nunca se pide (`scripts/cert/ssrf_e2e.py`) |
| Smoke de query por HTTP (contenedor nuevo) | 200; miss 15,2 s / repetición 7,7 s; TTFT 8,24 s; 0 hits de caché (mismo hallazgo P2 que el probe previo) |

Nota: el SHA del build local es `ff072e8` (HEAD con la evidencia); el código de
producto es idéntico a `edeeb61` (`git diff edeeb61..ff072e8 -- src ':!src/scripts'` vacío).

## 16. Cómo reproducir esta certificación

```bash
python scripts/cert/scratch_db.py create --name rag_cert && python scripts/cert/scratch_db.py init --name rag_cert
python scripts/cert/run_invariants.py --out-dir artifacts/certification/<sha>/invariants
python -m src.scripts.certification_battery --suite all --out-dir artifacts/certification/<sha>/battery
pwsh scripts/cert/run_perf_matrix.ps1 -Profile ci-parity
pwsh scripts/cert/rehearse_rollback.ps1 -Image zent-api:cert-<sha> -Database rag_cert_rehearsal
python -m src.scripts.sbom --out artifacts/release/<sha>/sbom.json
python -m src.scripts.release_manifest --sha <sha> --decision <DECISION> ...   # ver README
```

Cualquier resultado de este paquete **caduca** si el código cambia: regenerar
antes de promover.
