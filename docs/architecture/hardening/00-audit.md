# Hardening F0 — Auditoría y baseline

Estado: **F0 completado** (auditoría, solo lectura). Commit base: `3d24057`.
Método: lectura de código + tres scripts de medición read-only
(`src/scripts/flags_inventory.py`, `src/scripts/simplification_score.py`,
`src/scripts/finalization_audit.py`). No cambia comportamiento.

Objetivo del programa: menos ambigüedad, menos estados paralelos, menos fallos
silenciosos, mejores métricas. Orden: F0 auditoría → F1 cache fail-closed →
F2 enforcement hardening → F3 guards como autoridad real (hechos en este pase,
ver `01-report.md`).

---

## 1. Transiciones terminales — quién decide, por qué

Fuente: `tests/test_terminal_transitions_allowlist.py` (lista cerrada) + grep
propio. 15 sitios fuera de `FinalizationPolicy`, clasificados:

| Sitio | Clase | Quién decide | Reason code | Autoridad |
|---|---|---|---|---|
| `agent_runtime.py` `phase = RunPhase.UNDETERMINED` | POLICY DRIVEN | modo estricto aplica la resolución de la política | `AUTHORITY_MISSING_FOR_EXECUTABLE` / política | DETERMINISTIC |
| `agent_runtime.py` `phase=RunPhase.BLOCKED` (×2) | OPERATIONAL EARLY RETURN | budget excedido / circuito abierto antes del loop | `BUDGET_*` / circuit | RESOURCE |
| `run_guards.py` `phase=RunPhase.UNDETERMINED` | GUARD TABLE | tabla (ejecutable sin autoridad) | `AUTHORITY_MISSING_FOR_EXECUTABLE` | DETERMINISTIC |
| `run_guards.py` `phase=RunPhase.FINALIZED` (×2) | GUARD TABLE | tabla (evidencia / READY) | `BUDGET_EXHAUSTED_WITH_EVIDENCE` / `READY_TO_FINALIZE` | EVIDENCE / GENERATION |
| `orchestrator.py` `phase = RunPhase.UNDETERMINED` | LEGACY (cerrado en F2) | fallo determinista del camino RAG, sin política | `UNDETERMINED_RULE` | DETERMINISTIC |
| `run_state.py` `return RunPhase.*` (×7) | MAPPER | `terminal_phase_for()` mapea status/answer_state a fase | n/a (mapper único) | — |

Hallazgos:

1. **`run_guards.evaluate_transition` no tenía caller en `src/`**: la tabla era
   contrato + tests; el loop decidía inline. Dos autoridades en práctica.
   Cerrado en F3 (shadow medible + flag de enforcement).
2. **El camino RAG cerraba fuera de la política**: `orchestrator` nunca llamaba
   `evaluate_finalization`; la divergencia RAG era invisible. Cerrado en F2
   (resolución observada al cierre + `state.decisions.finalization`).
3. Las **salidas tempranas operativas** (circuito abierto, budget, fail-closed
   RAG) siguen fuera de la política a propósito: no hay run que finalizar.
4. **`terminal_phase_for` es el mapper único** status→fase; ninguna otra ruta
   escribe fases terminales por texto (verificado por la allowlist en CI).

---

## 2. Inventario de flags

`python -m src.scripts.flags_inventory --out artifacts/flags.md` (genera tabla
con default + propósito; `--check-drift` falla si hay drift).

- Flags de runtime inventariados (prefijos `RUNTIME_`, `ADAPTIVE_RAG_`,
  `DECISION_`, `JEV_`, `NARRATIVE_`, `GATEWAY_`, `EMBEDDING_`, `LLM_`, `CACHE_`).
- **Drift detectado: 106 flags de Settings ausentes de `.env.example`** (y 0
  claves de `.env.example` sin campo). Deuda P2: el ejemplo no alcanza como
  documento de configuración; la fuente real es `src/core/config.py`.
- Flags nuevos de este pase: `RUNTIME_FINALIZATION_ENFORCE_ORGS`,
  `RUNTIME_FINALIZATION_ENFORCE_BY_ENV`, `RUNTIME_RUN_GUARDS_ENFORCE`
  (documentados también en `.env.example`).

Criterio de retiro: cada flag transitorio (shadow/canary) debe declarar owner,
criterio de retiro y default. `flags_inventory` es la tabla viva.

---

## 3. `except Exception` en caminos críticos

Archivos: `agent_runtime`, `orchestrator`, `finalization_policy`,
`run_accounting`, `run_budget`, `redis/cache`, `enforcement`, `evidence`,
`finalizer`, `narrative_fast_path`.

| Clase | Cantidad |
|---|---:|
| Declarado fail-soft (comentario con causa) | 67 |
| Declarado con comentario breve (sin keyword) | 84 |
| Declarado fail-closed | 4 |
| Declarado compat/legacy | 1 |
| Declarado observability-only | 3 |
| **Sin comentario** | **25** |

Los 25 sin comentario: 17 en `redis/cache.py` (wrappers de logging: loguean y
devuelven `None`/`False` → observability-only, verificado leyendo el código),
y 8 en `agent_runtime`/`orchestrator` (hooks fail-soft hacia el camino legacy).
Deuda P2: certificar cada uno con un comentario de una línea
(`fail-soft` | `fail-closed` | `observability-only`) o eliminarlo.

Total en `src/`: 1.776 `except Exception` (el conteo global incluye
subsistemas no críticos: ingesta, parsers, portal API).

---

## 4. Simplification score (baseline)

`python -m src.scripts.simplification_score --out artifacts/simplification-before.md`:

| Subsistema | files | loc | adaptive_writers | terminal_transitions | fallbacks | settings_reads | authority_refs | except_exception |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| agent_runtime | 5 | 13.903 | 10 | 4 | 77 | 22 | 49 | 168 |
| runtime_core | 67 | 28.411 | 0 | 11 | 106 | 23 | 132 | 112 |
| decision | 35 | 10.290 | 0 | 0 | 132 | 9 | 2 | 46 |
| cache | 2 | 214 | 0 | 0 | 0 | 0 | 0 | 10 |
| accounting | 2 | 1.092 | 0 | 0 | 4 | 0 | 0 | 5 |
| metrics | 5 | 1.433 | 0 | 0 | 5 | 0 | 0 | 2 |
| retrieval | 100 | 29.471 | 0 | 0 | 144 | 0 | 18 | 112 |
| **total** | 217 | 91.941 | 20 | 16 | 525 | 55 | 228 | 543 |

Lectura: `adaptive_writers` = 20 ocurrencias, todas en `agent_runtime`
(`_adaptive_write`/`_adaptive_publish` son la única vía; el scan del test
`test_adaptive_projection` sigue en 0 offenders). `terminal_transitions` = 16
(15 allowlisted + 1 del cierre RAG nuevo). Hotspots LOC: `orchestrator.py`
7.127, `agent_runtime.py` ~5.750, `agent_flow.py` 1.633,
`deterministic_authority.py` 1.623, `narrative_fast_path.py` 1.342.

---

## 5. Baseline de performance y divergencia

Harness existente (V2 F1): `src/scripts/perf_traffic.py` (p50/p95, tokens,
costo, llamadas, errores). Baseline previo documentado en
`docs/architecture/perf-baseline.md` (commit `856392d`).

Comando de este pase (F0):

```bash
python -m src.scripts.perf_traffic --label f0-before --limit 1 --iterations 1
python -m src.scripts.finalization_audit --label f0-before --limit 1 --iterations 1
```

`artifacts/perf/f0-before.json` y `artifacts/finalization-audit/f0-before.json`
quedan con el summary por corrida. La corrida local tiene ruido conocido
(rerank cold-start, proveedor LLM local): sirve de smoke, no de comparación
final; la comparación exige el mismo entorno/corpus (`perf-baseline.md` §Cómo
medir producción).

---

## 6. Deuda detectada (clasificada)

**P0** — ninguna demostrada (leakage tenant/conversación, autoridad
determinista invertida, tool sin autorización: todos con test verde).

**P1** — cerradas en F1-F3 de este pase:
- fallback de cache sin aislamiento por conversación (F1);
- camino RAG fuera de la política de finalización (F2);
- tabla de guards sin caller (F3).

**P2** — pendiente con plan:
- `.env.example` con 106 flags ausentes (documentación de configuración);
- 25 `except Exception` sin certificar en caminos críticos;
- retries internos del router RAG no surfacean al ledger (F5, programado);
- tarifa del juez JEV sin pricing real (`cost_status=unknown`, nunca 0);
- `_try_finalize_answer` restante (~160 líneas) y bloque de cierre del
  orquestador (F8, programado);
- mensajes de `reason_code` fuera de `src/runtime/**` (decision engine) no
  cubiertos por el contrato `reason-codes-1` (F6, programado).

**P3** — conocida y aceptada:
- providers de cache viejos sin `_hash_query` calculan clave local (segura,
  incluye conversación);
- `request_cost` del camino RAG sin tokens reportados (documentado en
  `run-accounting.md`);
- transiciones terminales early-return operativas (por diseño).

---

## 7. Regla

Correctness, seguridad, simplificación, observabilidad, confiabilidad, costo —
antes que features nuevas. Cada fase cierra con suite verde y rollback
documentado.
