# Hardening F1–F3 — Reporte de cierre

Estado: **F0–F3 completados**. Base: `3d24057` + los cambios de este pase.
Complementa `00-audit.md` (baseline) y `docs/architecture/finalization-policy.md`
(contrato actualizado).

Decisiones fijadas con el usuario:

- cache: **fail-closed total** (sin ventana legacy para providers sin
  conversación);
- `zent_cache_bypass_total`: **sin label tenant** (org en log);
- load/chaos (F10-F11): harness + nightly local, fuera de este alcance.

---

## 1. Cambios por fase

### F0 — Auditoría y baseline (solo lectura + scripts)

- `src/scripts/flags_inventory.py`: inventario de flags (default, propósito) con
  `--check-drift` contra `.env.example`. Drift actual: **106 flags de Settings
  ausentes del ejemplo** (deuda P2 documentada).
- `src/scripts/simplification_score.py`: conteo por subsistema
  (writers/transiciones/fallbacks/flags/except) + hotspots LOC. Baseline en
  `artifacts/simplification-before.md`.
- `src/scripts/finalization_audit.py`: divergencia de autoridad con el pipeline
  real (gate operativo de promoción por etapa).
- `docs/architecture/hardening/00-audit.md`: transiciones terminales
  clasificadas, flags, `except Exception` (178 en caminos críticos, 25 sin
  comentario), simplification score, deuda P0-P3.

### F1 — Cache fail-closed por conversación (HIGH)

- `orchestrator._response_cache_key` devuelve `None` cuando hay conversación y
  el proveedor no acepta el scope: **caché desactivada para el request**, nunca
  clave degradada. Sin conversación no hay aislamiento que preservar (firma
  legacy intacta).
- `zent_cache_bypass_total{reason, provider}` + log con `organization_id`.
- Callers: `use_cache` se apaga si la clave es `None` (lectura y escritura) y se
  registra `cache_disabled_conversation_unsupported` en `adaptive.fallbacks`.
- Tests: `tests/test_conversation_isolation.py` (fail-closed, ×100 adversarial
  A-escribe/B-lee con 0 hits cruzados, compat sin conversación).

### F2 — Finalization enforcement hardening (HIGH)

- `src/runtime/enforcement.py`: `parse_stages`, `enforcement_stages`
  (prioridad **agente > organización > environment > global**),
  `should_hold_trigger`. `finalization_policy` re-exporta
  `ENFORCE_STAGES`/`enforced_stages`/`should_hold_trigger` (compat).
- Etapa nueva `answer_gate`: si el gate aprueba el borrador y la política pide
  RETRIEVE_MORE con búsqueda disponible, el cierre espera (una vez) y sigue
  reuniendo evidencia.
- Métrica `zent_finalization_divergence_total{stage, policy_action,
  legacy_action, reason_code}`; `zent_finalization_shadow_divergence_total`
  queda como alias deprecado. `closure` ahora reporta `legacy_action` por fase.
- Camino RAG: resolución del cierre publicada en `state.decisions.finalization`
  + divergencia medida (antes cerraba fuera de la política).
- Config: `RUNTIME_FINALIZATION_ENFORCE_ORGS`,
  `RUNTIME_FINALIZATION_ENFORCE_BY_ENV` (+ `.env.example`).
- Corpus dorado: `tests/golden/finalization_cases.json` (24 casos de la matriz
  evidencia/autoridad/budget/draft/termination/tool/JEV),
  `tests/test_finalization_golden.py` (resolución exacta + catálogo + fases +
  estabilidad ×100) y `tests/test_finalization_enforcement_scopes.py`.

### F3 — Guards como autoridad real (MEDIUM)

- `run_guards.evaluate_transition` ahora tiene caller real: el loop consulta la
  tabla en cada decisión de tool/retrieval y registra
  `zent_guard_divergence_total{event, guard_reason, legacy_reason}` cuando la
  razón del guard no coincide con la que registra la ruta vigente.
- `RUNTIME_RUN_GUARDS_ENFORCE=on` (default `off`): un veredicto denegado
  bloquea la ejecución de la tool con `guard_reason` del guard.
- Helpers de módulo testeables (`guard_verdict_for`, `observe_guard_transition`,
  `emit_guard_divergence`, `guards_enforced`) + `tests/test_run_guards_shadow.py`.

---

## 2. Tests

| Suite | Qué cubre |
|---|---|
| `test_conversation_isolation.py` | fail-closed, ×100 adversarial, compat sin conversación |
| `test_finalization_enforcement_scopes.py` | prioridad de scopes, parse, holds, etapa nueva |
| `test_finalization_golden.py` | 24 casos exactos + contrato de reason codes + ×100 estable |
| `test_run_guards_shadow.py` | veredictos, divergencia medible, flag, terminal sin transición |
| `test_finalization_policy.py` (actualizado) | stages con `answer_gate` |
| `test_adaptive_projection.py` / `test_terminal_transitions_allowlist.py` | sin regresiones de writers/transiciones |

Estado de las corridas en este pase:

- suites focales (nuevas + afectadas): **verdes**;
- `ruff check src/ tests/ sdk/python`: **verde**;
- smoke real (`perf_traffic --limit 1` + `finalization_audit --limit 1`):
  pipeline completo OK; cierre RAG `phase=FINALIZED action=FINALIZE
  divergent=False` (`artifacts/finalization-audit/f0-before.json`).

---

## 3. Rollback

| Fase | Rollback |
|---|---|
| F1 | revert del commit (1 archivo + tests); no hay flag porque el fallback dejó de existir |
| F2 | `RUNTIME_FINALIZATION_ENFORCE=""` → solo shadow; el resto (métrica/corpus) es aditivo |
| F2 (scopes) | quitar orgs/environment de las variables de override |
| F3 | `RUNTIME_RUN_GUARDS_ENFORCE=off` (default) → solo shadow |

---

## 4. Deuda restante (actualiza `00-audit.md` §6)

- P2: retries del router al ledger (F5); taxonomía de fallos (F6); métricas
  run-level (F7); extracción `_try_finalize_answer` (F8); drift de
  `.env.example`; 25 `except Exception` sin certificar; narrative fast path sin
  enforcement de trigger (solo `closure` + strict).
- P3: claves locales sin `_hash_query` (seguras, incluyen conversación);
  `request_cost` sin tokens; early returns operativos por diseño.

---

## 5. Evidencia de no-regresión

- `artifacts/perf/f0-before.json`: 1 run de smoke (60.5 s, pipeline real).
- `artifacts/finalization-audit/f0-before.json`: `divergences = 0`,
  `without_resolution = 0`.
- `artifacts/simplification-before.md` y `artifacts/flags.md`: baseline
  reproducible para el antes/después del programa completo.
