# Entrega y operación: branch protection, nightly, canary y migraciones

Partes M, N, P y Q del checklist de certificación.

## 1. Branch protection (Parte M)

**Estado: NO VERIFICADO desde este entorno.** La API de GitHub devuelve `401`
sin token (`GET /repos/yoredstorm/zent_rag/branches/master/protection`), así que
la protección de `master` no se puede auditar ni certificar sin credenciales.
Se declara como **condición de canary** (ver `final-report.md`).

Configuración objetivo (checks que ya existen como jobs reales en
`.github/workflows/ci.yml`):

| Job de CI | Rol | ¿Required en PR? | ¿Required en release? |
|---|---|---|---|
| `secrets-scan` (gitleaks) | seguridad | sí | sí |
| `lint` (uv lock --check + ruff) | higiene + lock reproducible | sí | sí |
| `test` → paso *Architecture invariants* | invariantes de contrato | sí | sí |
| `test` → suite completa | correctness | sí (con `-x`) | sí (sin `-x`) |
| `sdk-python`, `sdk-node` | contratos de SDK | sí | sí |
| `portal` (typecheck/lint/test/build) | frontend | sí | sí |
| `portal-e2e` | E2E + axe | sí (ver nota de flake) | sí |
| `kustomize` | manifests renderizan | sí | sí |
| `build` (docker build) | build reproducible | sí | sí |
| `pip-audit` | dependencias (HIGH+) | **no** (`continue-on-error: true`) | no |
| `nightly` (suite completa, adversarial, estabilidad ×100) | estabilidad | no | informativo |

Notas:
- `pip-audit` es informativo a propósito: convertirlo en blocker sin estabilizar
  el feed de advisories crearía falsos bloqueos. Sigue siendo visible en cada PR.
- `portal-e2e` tiene un flake conocido y registrado en el repo
  (`docs/architecture/ownership/…`, commit `17acf3d`). No se promueve a blocker
  de release hasta estabilizarlo.
- No existe Dependabot/renovate: las actualizaciones de dependencias son una
  operación deliberada (riesgo P3 en `remaining-risks.md`).

Comando para auditar (una vez con token disponible):

```bash
gh api repos/yoredstorm/zent_rag/branches/master/protection | jq '.required_status_checks.contexts'
```

## 2. Nightly (Parte N)

`.github/workflows/nightly.yml` (06:00 UTC + `workflow_dispatch`) ya corre con
propósito distinto al PR CI:

| Paso | Propósito |
|---|---|
| Suite completa sin `-x` | todos los fallos visibles sobre el mismo SHA |
| Matriz adversarial (`test_adversarial_matrix`, `test_adversarial_generalization`, `test_llm_stream_fallback`, `test_llm_embed_retry`) | generalización de reglas y fallback |
| Estabilidad ×100 (3 pasadas de `test_finalization_golden` + `test_adversarial_matrix`) | autoridad determinista |
| Upload de JUnit | reproducibilidad del fallo |

Pendiente en nightly (declarado, no implementado en esta fase): batería de
certificación completa (seguridad/tenant/contabilidad) como paso propio, y
retención de logs (`/tmp/*.log`) además de los JUnit. Ver
`remaining-risks.md` P2.

## 3. Canary (Parte P)

Esquema progresivo configurable (los porcentajes se ajustan al tráfico real;
no hay esquema rígido impuesto):

| Etapa | Audiencia | Puerta de promoción |
|---|---|---|
| 0. internal | operadores + orgs de prueba | evidencia de certificación completa (este paquete) |
| 1. canary mínimo | 1 org interna + 1 org voluntaria | 24 h sin señales de rollback |
| 2. canary ampliado | 5–10% del tráfico | 72 h con SLI dentro de objetivo y sin señales |
| 3. producción | 100% | aceptación explícita de riesgos remanentes |

Palancas ya existentes en el producto (no se inventan flags nuevas):
`RAG_RAG_LONG_CONTEXT_CANARY_PERCENTAGE`, `RAG_JEV_CANARY_PERCENTAGE`,
`RAG_ADAPTIVE_RAG_CANARY_PERCENTAGE`, `RAG_RUNTIME_AGENT_JEV_LOOP_CANARY_PERCENTAGE`,
`RAG_RAG_RESPONSE_INTELLIGENCE_CANARY_PERCENTAGE`,
`RAG_KNOWLEDGE_SEMANTIC_INGESTION_CANARY_PERCENTAGE`.

### Señales de rollback (cualquiera dispara)

| Señal | Fuente | Umbral |
|---|---|---|
| Regresión de error rate | `ZENTErrorBudgetFastBurn` / `ZENTHighErrorRate` | burn > 2%/1 h |
| Regresión de latencia | `ZENTRunP95Regression` | p95 > baseline (ver `slo.md`) |
| Regresión de costo/run | `ZENTCostPerRunSpike` | > baseline medido |
| Invariante de seguridad | `ZENTTenantIsolationViolation` | > 0 |
| Divergencia contable | `billing_reconcile` diario | delta ≠ 0 |
| Retry amplification | `ZENTProviderAttemptAmplification` | > 3 intentos/run |
| Saturación de DB | runbook §4 | `waiting > 0` sostenido |
| Inestabilidad de provider | `ZENTCircuitBreakerOpenGlobal` | apertura global |
| Distribución de estados inesperada | `ZENTAbstentionSpike` / `ZENTUndeterminedSpike` | > 30% / > 10% |

### Rollback (practicable y ensayado)

- **App**: `kubectl -n zent rollout undo deploy/zent-api` (o
  `docker compose -f docker-compose.prod.yml up -d --no-deps api` con el SHA
  previo). El procedimiento se ensaya en `scripts/cert/rehearse_rollback.ps1`
  (arranca la imagen certificada, inyecta una configuración rota, verifica
  `/health` degradado y ejecuta el rollback verificando `/health` sano; deja
  evidencia con timestamps).
- **Migraciones**: 150/150 revisiones tienen `downgrade()` y el ciclo
  `downgrade -1` → `upgrade head` está verificado (ver §4). Para migraciones
  destructivas (la 151 dropea una columna) el rollback de DB exige restaurar
  snapshot: el rollback de app no depende de la migration porque el schema es
  compatible hacia atrás en esa revisión.
- **Config**: las palancas de canary vuelven a su valor previo sin deploy.

## 4. Migraciones (Parte Q)

Evidencia: `artifacts/certification/<sha>/migrations.json`
(`scripts/cert/run_migrations.py` sobre una DB scratch creada desde cero).

| Paso | Resultado | Duración |
|---|---|---|
| `alembic upgrade head` (150 revisiones desde cero) | exit 0 | 2,6 s |
| `alembic current` | head `151` | 3,4 s |
| `alembic downgrade -1` (151 → 150) | exit 0 | 3,2 s |
| `alembic upgrade head` (150 → 151) | exit 0 | 3,1 s |
| Revisiones totales / con `downgrade()` | 150 / 150 | — |

Riesgos de lock (últimas 10 revisiones): todas usan `CREATE INDEX` **sin**
`CONCURRENTLY` y la 151 además hace `DROP COLUMN`. Implicaciones operativas:

- `CREATE INDEX` normal toma un lock de escritura en la tabla: en tablas
  grandes (usage_events, api_logs, traces) el deploy debe hacerse en ventana de
  baja escritura o con `CREATE INDEX CONCURRENTLY` manual previo.
- `DROP COLUMN` (151) es destructivo: su `downgrade()` recrea la columna vacía
  (se pierde el dato viejo). El rollback de DB no recupera datos; requiere
  snapshot si el dato importa.
- Compatibilidad app↔schema durante el deploy: el orden es
  `alembic upgrade head` → arranque de la app (igual que CI y
  `Dockerfile.api`). La app no lee columnas nuevas de la 151 hasta que el
  circuit breaker de tenant las usa, y tolera su ausencia (downgrade verificado).
- Backfills: no hay backfills en las últimas 10 revisiones; los backfills de
  conocimiento se hacen por scripts (`knowledge_backfill.py`) fuera del deploy.

Para producción: ejecutar `upgrade head` con `statement_timeout` controlado y
verificar `pg_locks` (comando en runbook §16).
