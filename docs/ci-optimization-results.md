# ZENT — Resultados de la optimización del CI

Fecha: 2026-11-01.
Rama: `perf/ci-optimization` (PR #15, draft).
Baseline: `docs/ci-performance-baseline.md`.
Última ejecución verde del pipeline: **#507** (SHA `78064b2`).
Este documento no autoriza merge ni despliegue.

## 1. Resumen ejecutivo

La optimización reduce el wall-clock del workflow de **15,10 min a 8,73–9,18 min**
en cuatro ejecuciones comparables (#501, #502, #503, #506) más la validación
final #507 (**−41,2 % en promedio**; mejor run #506: **−42,2 %**), sin perder
cobertura ni controles de seguridad. El consumo
de runner-minutes queda en **76–85** (baseline 83; promedio 81,5, **−1,8 %**),
por lo que la mejora de latencia no se paga con más cómputo.

La causa principal de la mejora no es “tests más rápidos”: el trabajo real de
tests se mantiene en ~2.300–2.500 s. La mejora viene de repartir ese trabajo
mejor, eliminar la ejecución duplicada de 407 invariantes, sacar `build` de la
ruta crítica y paralizar E2E en dos jobs con bases de datos aisladas.

Resultado: **GO condicional** para el cambio de CI. La única meta no cumplida
es el balance fino de shards (`max/min` 1,43; objetivo 1,10), explicado por
variabilidad de runners/DB y por el costo de setup por shard. No afecta
correctitud, cobertura ni release gate.

### 1.1 Estabilidad observada

| Run | SHA | Wall | Resultado | Nota |
|---|---|---:|---|---|
| #501 | `7f3c26e` | 9,18 min | success | Primera versión file-level LPT |
| #502 | `4d8afa5` | 8,86 min | success | Refresh de duraciones |
| #503 | `c2a8244` | 8,77 min | success | Segundo refresh |
| #505 | `3efc5ea` | — | failure | Flake preexistente: `window is not defined` en `AgentBuilder.test.tsx` (promesa de catálogo resolviendo tras unmount) |
| **#506** | **`00f4f73`** | **8,73 min** | **success** | Fix de cleanup + mejor run |
| #507 | `78064b2` | 8,75 min | success | Validación del commit de documentación |

#505 no fue una regresión del sharding: el test pasaba, pero Vitest marcaba
exit 1 por un `unhandled rejection` de React tras el desmontaje. Se corrigió
con un flag `active` en el efecto del catálogo (`useAgentStudio.ts`) y #506
quedó verde. No se cambió ningún retry para ocultarlo.

## 2. Comparativa antes / después

### 2.1 Workflow completo

| Métrica | Baseline #497 | #501 | #502 | #503 | #506 | Promedio optimizado | Δ |
|---|---:|---:|---:|---:|---:|---:|---:|
| Wall-clock | **15,10 min** | 9,18 | 8,86 | 8,77 | **8,73** | **8,89 min** | **−41,2 %** |
| Runner-minutes facturables | **83** | 81 | 85 | 76 | 84 | **81,5** | **−1,8 %** |
| Job más lento | **13,27 min** | 8,86 | 8,56 | 8,52 | **8,51** | **8,61 min** | **−35,1 %** |
| Paso `Run tests` más lento | **11,85 min** | 8,20 | 7,83 | 7,31 | **7,59** | **7,73 min** | **−34,7 %** |
| Suma de trabajo de tests | 2.508,6 s | 2.386 s | 2.495 s | 2.298 s | 2.480 s | 2.415 s | −3,7 % |
| Tests en `junit-tests.xml` | 6.016 | 6.026 | 6.026 | 6.026 | 6.026 | 6.026 | +10 tests nuevos |
| Duplicados en JUnit | 0 | 0 | 0 | 0 | 0 | 0 | = |
| Invariantes | 407 | 407 | 407 | 407 | 407 | 407 | = |
| Certificación | 41 | 41 | 41 | 41 | 41 | 41 | = |
| E2E passed / skipped | 25 / 11 | 25 / 11 | 25 / 11 | 25 / 11 | 25 / 11 | 25 / 11 | = |
| Fallos / errores | 0 | 0 | 0 | 0 | 0 | 0 | = |

Baseline #456 (monolítico, ~50 min) se usa solo como referencia histórica:
**53,02 min** de wall y **69** runner-minutes. El sharding previo (#497) ya había
bajado el wall a 15,10 min; esta fase baja otros 6,3 min.

### 2.2 Shards del run final #506

| Shard | Archivos | Tests | Paso `Run tests` | Job completo | Estimación planner |
|---:|---:|---:|---:|---:|---:|
| 1 | 82 | 1.364 | 438,9 s (7,31 min) | 8,51 min | 399,5 s |
| 2 | 84 | 790 | 442,8 s (7,38 min) | 8,09 min | 399,5 s |
| 3 | 84 | 872 | 418,3 s (6,97 min) | 7,59 min | 399,5 s |
| 4 | 84 | 783 | 406,5 s (6,77 min) | 7,36 min | 399,5 s |
| 5 | 83 | 980 | 455,5 s (7,59 min) | 8,25 min | 399,5 s |
| 6 | 84 | 830 | 317,9 s (5,30 min) | 5,96 min | 399,5 s |
| **Total** | **501** | **5.619** | **2.480 s (41,3 min)** | **45,76 min** | — |

Los 407 invariantes corren una sola vez en el shard 1 y se fusionan en
`junit-tests.xml`; 5.619 + 407 = **6.026**.

El desbalance real (`max/min` de job = 8,51 / 5,96 = **1,43**) no viene de una
mala asignación de archivos: #503 y #506 usaron **la misma asignación** (mismo
`.test_durations`), y aun así el shard 2 pasó de 289,8 s a 442,8 s y el shard 6
de 412,9 s a 317,9 s. El tiempo por archivo cambia con el runner y el estado
acumulado de PostgreSQL; el máximo de 6 shards se mantiene estable en ~8,5 min
aunque el shard lento rote. Ese es el límite práctico de esta configuración.

### 2.3 Comparación de configuraciones de shards

Con el `.test_durations` refresh y LPT por archivo:

| Shards | Test time estimado por shard | Job estimado (+setup ~1,2 min) | Runner-min de tests | Comentario |
|---:|---:|---:|---:|---|
| 4 | ~9,96 min | ~11,2 min | ~44–46 | Menos runners, más latencia |
| **6** | **~6,64 min** | **~7,8 min** | **~52–55** | **Elegido** |
| 8 | ~4,98 min | ~6,2 min | ~62–66 | Latencia primero, +10–12 runner-min |

El run real #506 confirma que el setup y la variabilidad agregan ~1–2 min al
test time; aun así, 6 shards cumple el objetivo de wall ≤10 min con costo
similar al baseline. 8 shards queda como perfil futuro para bajar el job más
lento por debajo de 7,5 min.

## 3. Optimizaciones aplicadas

1. **Planificador LPT por archivo** (`scripts/ci/shard_plan.py`).
   `pytest-split --splitting-algorithm least_duration` se evaluó y se descartó:
   balancea tests individuales y puede separar tests del mismo archivo. En el
   run #499 eso hizo fallar `test_governance_dashboard` porque el test que crea
   las políticas quedó en otro shard. El planner actual asigna **archivos
   completos** con LPT, preservando fixtures de módulo, orden interno y estado
   compartido, con el mismo balance de duración.
2. **6 shards** en lugar de 4, con `.test_durations` refrescado desde JUnit de
   CI (no desde una suite monolítica). El archivo pasó de 5.936 a 6.067
   entradas; la suma estimada quedó en 2.425,7 s.
3. **Invariantes sin duplicación.** Los 34 archivos de invariantes se excluyen
   de los shards y se ejecutan una sola vez en el shard 1. `junit-invariants.xml`
   se conserva y se fusiona en `junit-tests.xml`; 407 tests, 0 duplicados.
4. **Evidencia fail-closed.** `merge_junit_shards.py` exige los 6 shards, falla
   con XML inválido, shard vacío o test duplicado, y no publica `junit-ci` si la
   fusión no es completa. `verify_junit_coverage.py` compara los manifiestos de
   nodeids de cada shard contra el JUnit fusionado; #506 reportó
   `collected=6026 junit=6026 mapped=6026`.
5. **`build` en paralelo.** Se eliminó `needs: [lint, test, sdk-python,
   sdk-node, portal]`; la imagen se construye con `push: false` mientras corren
   los tests. El gate `test` exige `build` y SBOM en success antes del release.
6. **Gate integral `test`.** Conserva el nombre required y evalúa los 12
   controles con `if: !cancelled()`: shards, certification, evidence, lint,
   pip-audit, secrets-scan, sdk-python, sdk-node, portal, portal-e2e, kustomize,
   build. `skipped` y `cancelled` no cuentan como éxito.
7. **E2E en 2 jobs** (`portal-e2e (1/2)`, `portal-e2e (2/2)`) con PostgreSQL,
   Redis, Qdrant, API y portal propios por shard. Playwright sigue con
   `workers: 1` dentro de cada job. El agregador `portal-e2e` conserva el nombre
   histórico del check.
8. **Caché de browsers Playwright** (`~/.cache/ms-playwright`, key por
   `portal/package-lock.json`). `setup-node` ya cacheaba npm; la caché uv no
   aporta porque `uv sync` tarda 2–3 s.
9. **DB init con `docker exec psql`** en los jobs con PostgreSQL: elimina
   `apt-get update/install postgresql-client` (~0,15 min por job) y usa el
   cliente de la misma versión que el servidor.
10. **Test determinista de MTTR**: se reemplazó el `asyncio.sleep(1.1)` de
    `test_escalation_policy_fires_once` por un backdate de `detected_at`; el
    test sigue exigiendo `mttr_seconds >= 1.0`, sin espera real.
11. **Capacidad determinista**: `test_capability_api_search_inspect_and_metrics`
    ahora llama a `ensure_demo_integrations()` antes de medir el catálogo
    grande. Sin ese seed, el conteo dependía de qué otro test había instalado
    integraciones antes (56 vs 60+).
12. **Compatibilidad de evidencia**: `fetch_ci_evidence.py` consulta jobs con
    `filter=all&per_page=100` para incluir `test` y `test-evidence` en
    `ci-run.json`; verificado contra #501.

## 4. Beneficios medidos

- **Latencia**: −6,37 min de wall en el mejor run (#506: 8,73 vs 15,10).
- **Costo**: 76–85 runner-min vs 83; sin aumento neto. El +costo de 2 jobs E2E
  y 6 shards se compensa con menos duplicación y jobs más cortos.
- **Ruta crítica**: ya no incluye `build`; el camino es shard más lento →
  evidence (0,10 min) → gate (0,01 min). `build` termina en 0,42 min en paralelo.
- **Cobertura**: 6.026 tests en JUnit; 0 duplicados; 12 skipped (los mismos 12
  del baseline); 5.619 tests de shards + 407 invariantes.
- **Certificación**: 41/41, incluido el Gold Sales Funnel; 0 fallos.
- **E2E**: 25 passed / 11 skipped en cada run; 0 fallos, 0 flaky, sin cambiar
  retries.
- **Seguridad**: gitleaks, pip-audit, SBOM y build en success en las ejecuciones
  verdes #501–#503 y #506. `pip-audit` y E2E ahora bloquean el release vía `test`.
- **Integridad**: #506 `merged=6 suites=7 tests=6026 failures=0 errors=0
  skipped=12`; `junit-ci` contiene `junit-tests.xml` + `junit-invariants.xml`.

## 5. Pruebas negativas (release gate)

Se usó un PR descartable (#16, ya cerrado) con fallos deliberados. El run
**#504** terminó en failure y el gate `test` reportó:

```
test-shard=failure
certification=failure
test-evidence=failure
lint=failure
pip-audit=failure
secrets-scan=success
sdk-python=success
sdk-node=success
portal=success
portal-e2e=failure
kustomize=success
build=success
```

Artefactos del run negativo:

- **No** se publicó `junit-ci`.
- Sí se publicó `junit-ci-merge-failure` con los shards disponibles.
- `portal-e2e` agregado falló porque uno de sus shards falló.
- `test` falló con exit 1; no hubo ningún estado `skipped` contado como éxito.

Esto demuestra que un fallo de tests, certificación, E2E, lint o pip-audit
bloquea el release gate, aunque branch protection no marque esos jobs
individualmente como required.

## 6. Riesgos y mitigaciones

| Riesgo | Evidencia | Mitigación |
|---|---|---|
| `least_duration` separa archivos y rompe estado intra-archivo | Run #499: `test_governance_dashboard` 0 >= 1 | Planner LPT por archivo; test de partición en `tests/test_ci_evidence_merge.py` |
| Tests dependen de seeds que otro test instala | Run #500: capability registry 56 < 60 | `ensure_demo_integrations()` en el test; planner conserva archivos completos |
| Evidencia parcial aceptada como válida | Baseline: merge omitía XML inválidos | Merge estricto + manifiestos + gate; probado en #504 |
| Shard más lento por variabilidad de runner/DB | #501 8,86 / #502 8,56 / #503 8,52 / #506 8,51 | 6 shards; refresh de duraciones; perfil 8 shards futuro |
| E2E comparte tenant/entidades | Todos los specs usan demo org/usuario | `workers: 1`; paralelismo solo a nivel job con DB propia |
| `build` construye una imagen de un commit que luego falla tests | Build en paralelo | `push: false`; gate exige build + todos los controles; no hay deploy |
| Caché de browsers corrupta | Cache key por lock | `actions/cache` inmutable; si falla, `playwright install` reinstala |
| `junit-ci` cambia de 4 a 6 shards | Consumers históricos | Nombre `junit-ci`, `junit-tests.xml`, `junit-invariants.xml` y job `test` preservados; `fetch_ci_evidence` verificado |
| 11 E2E skipped | Flags `E2E_*` | No se cambiaron; flujos durables/pagos cubiertos por 41 tests de certificación |

## 7. Problemas pendientes

1. **Balance fino de shards**: `max/min` 1,43 y job máximo 8,51 min. El objetivo
   de 7,5 min no se cumple a nivel job (sí a nivel `Run tests`: 7,59 min). La
   causa es variabilidad de entorno y costo de setup, no pérdida de tests.
2. **Refresh manual de `.test_durations`**: se hizo dos veces durante esta fase.
   Debe automatizarse en master/nightly con una mediana móvil de 3 runs.
3. **Trabajo real de tests**: los 30 tests más lentos son integración real
   (Postgres/Qdrant/Redis); no se reemplazaron por mocks. La mejora es de
   scheduling, no de CPU. Cualquier reducción adicional exige refactor de
   fixtures/DB o snapshots de base.
4. **E2E**: 11 tests siguen skipped por diseño; no se habilitaron flags para no
   cambiar cobertura/tiempos sin autorización.
5. **Node 20 deprecation warnings** en actions: no afecta el resultado, pero
   conviene subir acciones cuando haya versiones estables.
6. **Runner-minutes**: la medición usa la suma de spans de logs con redondeo
   hacia arriba; GitHub puede reportar un valor ligeramente distinto.

## 8. Recomendación GO / NO-GO

**GO condicional** para integrar la optimización de CI, con estas condiciones:

- Mantener el gate `test` integral y no degradarlo a los 3 checks originales.
- No cambiar branch protection sin una migración explícita; los required checks
  actuales (`secrets-scan`, `lint`, `test`, `sdk-python`, `sdk-node`, `portal`,
  `kustomize`, `build`) se conservan.
- Aceptar que el balance de shards queda como deuda de seguimiento; el objetivo
  de latencia y costo sí se cumple.
- Validar el commit final de documentación con una ejecución verde adicional
  antes de mergear (el pipeline probado es #507, SHA `78064b2`).

No se declara GO para 8 shards ni para `workers: 2` en Playwright: no fueron
medidos en producción y no son necesarios para el objetivo actual.

## 9. Evolución futura

1. **Perfil de 8 shards** detrás de una variable de workflow; medir 3 runs y
   comparar runner-minutes. Candidato si el objetivo pasa a ser latencia <7 min.
2. **Refresh automático de duraciones** en master/nightly con mediana móvil de
   3 ejecuciones; evitar el sesgo de una sola corrida.
3. **Snapshot/template de PostgreSQL** por shard para bajar el setup (~1,2 min)
   y reducir la varianza de los tests de integración.
4. **Aislamiento Playwright por worker** (tenant/usuario/entidades únicas) para
   evaluar `workers: 2` sin carreras; hoy está bloqueado por el tenant demo
   compartido.
5. **Paralelizar typecheck/lint/test/build del portal** si el job `portal` vuelve
   a ser ruta crítica; hoy no lo es.
6. **Subir actions a versiones Node 24** cuando estén disponibles, para eliminar
   los warnings de deprecación.
