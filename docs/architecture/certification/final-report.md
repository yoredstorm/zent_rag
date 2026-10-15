# Certificación ZENT — Reporte final y GO/NO-GO

## 0. SHA certificado y entorno

| Dato | Valor |
|---|---|
| **SHA de release candidate (evidencia CI)** | `8ee820004c8acfffff4a20e5250319634a69bb27` (`8ee8200`) |
| SHA del código de producto | `edeeb61a9e37fff1e39f1a751f5e97470f9ce3d8` (idéntico en `8ee8200`: `git diff edeeb61..8ee8200 -- src ':!src/scripts'` vacío) |
| SHA base sobre el que se trabajó | `17acf3ddb7f2fbddc516830a3abdf7227bf72c8a` (`17acf3d`) |
| Rama | `master` (pusheada a `origin`) |
| Fecha de certificación | 2026-10-14/15 (UTC 18:30–00:15) |
| Entorno | GitHub Actions (runner ubuntu-latest, CI) + workstation local (Windows 11, Docker Desktop 29.7.2) + Postgres 16/pgvector, Redis 7, Qdrant v1.13.4 + providers reales |
| DBs de evidencia | `rag_cert`, `rag_cert_battery`, `rag_cert_invariants`, `rag_cert_mig`, `rag_cert_rehearsal` — creadas desde cero replicando el job `test` de CI (`scripts/cert/scratch_db.py`) |
| Config | perfil `ci-parity` (valores default de `config.py`) o `.env` local declarado en cada documento |
| Python | CI/imagen 3.11 (uv-managed); venv local 3.13.7 (**no** es paridad de runtime, ver `manifest-and-build.md` §5) |

Cambios incluidos en `edeeb61` (no son features: fixes de seguridad, tests,
tooling de evidencia y assets de operación): ver el commit y
`security-report.md` §2, `observability.md` §2, `delivery.md`.

## 1. Release Evidence Manifest

- `artifacts/release/8ee820004c8acfffff4a20e5250319634a69bb27/manifest.json` (machine-readable)
- `artifacts/release/8ee820004c8acfffff4a20e5250319634a69bb27/manifest.md` (human-readable)
- Generado por `src/scripts/release_manifest.py` (no escrito a mano; sin secretos).
- Decisión registrada: **READY_FOR_INTERNAL** (canary bloqueado por 2 condiciones, §13).
- Contenido clave: SHA/branch/tag/dirty, fingerprints de `uv.lock` +
  `pyproject.toml` + locks de portal/SDK + Dockerfiles, SBOM (734 componentes,
  content hash `458532fa…` idéntico al generado en `edeeb61`), migración head
  `151` (150 revisiones, todas con `downgrade`), imagen local
  `zent_rag-api` (`sha256:86685166…`), CI run `38653834675`, checks
  (ruff/lock/gitleaks/pip-audit/dashboard/SBOM/nightly), resultados de tests
  (suite completa CI 5476, invariantes CI 406, batería 57 escenarios), 9
  evidencias externas con hash, warnings conocidos, riesgos aceptados y la
  decisión con su motivo.

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
| Suite completa en CI sobre el SHA del release candidate | **PASS**: 5476 tests, 0 fail, 0 error, 4 skip (job `test`, 37 min) | run `38653834675` (`8ee8200`), artifact `junit-ci` |
| Invariantes en CI | **PASS**: 406 tests, 0 fail (mismo job, paso *Architecture invariants*) | run `38653834675` |
| CI completo (10 jobs) | **success** en `8ee8200` y en `684d383` | GitHub Actions |
| CI del SHA base `17acf3d` | success (10/10 jobs) | run `38596793506` |
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
  `observability`, verificado por test); **Alertmanager conectado y probado en
  local** (regla `ZENTApiDown` disparó y se resolvió end-to-end). Falta
  desplegarlo en staging, conectar un receptor externo y el scheduler de
  `POST /platform/obs/check` (P2-3, P2-9).

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

### 13.1 Condiciones que faltan para canary (2 de 5)

1. ~~CI verde del SHA certificado~~ **HECHA**: run `38653834675` en `8ee8200`
   (10/10 jobs) y `684d383` (10/10). Evidencia: `artifacts/certification/8ee8200…/ci/ci-run.json`.
2. ~~Suite completa verde sobre el SHA certificado~~ **HECHA**: 5476 tests, 0
   fallos, 0 errores (artifact `junit-ci` bajado y registrado en el manifest).
3. **FALTA** — Baseline de performance y load en staging con corpus cargado (30
   iteraciones, concurrencia 25/50) → fijar los umbrales PROVISIONAL de latencia
   y costo en `alert-rules.yml` y `slo.md` (P2-1, P2-2).
4. **FALTA (parcial)** — Observabilidad en staging: desplegar
   `--profile observability` en el entorno real, confirmar scrape de `/metrics`,
   conectar receptor externo de alertas (hoy el receptor `default` no envía a
   ningún canal) y scheduler de `POST /platform/obs/check` (P2-3, P2-9). En local
   ya está conectado y probado end-to-end.
5. ~~Branch protection verificada~~ **HECHA**: aplicada y verificada
   (`artifacts/certification/684d383…/branch-protection.json`). Para enforcement
   duro en push directo hay que activar PRs requeridos (decisión del owner).

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
| correctness | 8 | suite completa verde en CI (5476 tests, 0 fallos) + invariantes CI (406) + batería 57/57 | sin corrida local completa (la de CI es la evidencia) |
| authority | 9 | determinismo ×100 (6 escenarios) + golden corpus + alerta de divergencia | sin corrida prolongada en staging |
| security | 8 | 22/22 + 2 P1 cerrados + mitigaciones estructurales | sin pentest externo/fuzzing |
| tenant isolation | 9 | A/B idéntico + contratos + invariantes + 49 tests | sin prueba cross-región/workspace en batería |
| reliability | 8 | chaos 17/17 + fallback real + rollback ensayado | chaos de infraestructura en staging |
| observability | 7 | dashboards/alertas como código + contratos + compose profile + Alertmanager conectado y probado (fired/resolved) | no desplegado en staging, sin receptor externo ni scheduler |
| performance | 5 | baseline real medido (2 perfiles) + TTFT + rutas degradadas | local, n=3, sin corpus cargado ni staging |
| cost/accounting | 7 | cadena con matemática + unknown≠0 + budget | precios default, loop sin línea, sin métrica de divergencia |
| maintainability | 7 | tooling de evidencia + ratchets + docs indexados | 20 `except` sin certificar, módulos grandes |
| test quality | 7 | escenario→test mapeado + no-demostrados explícitos | suite lenta/pesada; hermeticidad a corregir por caso |
| build reproducibility | 8 | locks frozen + SBOM determinista (mismo content hash en dos SHAs) + imagen construida + CI build verde | bases/actions por tag, sin Dependabot |
| operational readiness | 7 | 18 runbooks + rollback 16,9 s + alertas con owner + branch protection aplicada | staging sin ejercitar; enforcement duro requiere PRs |

**Promedio: 7,5/10** — consistente con la decisión: sistema sólido y verificable
internamente, todavía **no certificable para canary** por evidencia de entorno
(staging), no por falta de diseño.

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
| **Alertmanager** | target activo en Prometheus (`dropped=0`), cluster `ready`; **prueba E2E**: `ZENTApiDown` disparó al detener `rag-api` y se resolvió al levantarlo (0 alertas activas después) |
| **Branch protection** | aplicada y verificada por API: 8 required checks, force push y borrado bloqueados (`branch-protection.json`) |
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
