# Reporte final — Fase de convergencia de autoridad de agentes

## Entregable: identificación

| Campo | Valor |
|---|---|
| Baseline (CI 10/10 verde) | `5cd3dec1812955c28dd6ce338f56322022a2079c` |
| HEAD de la fase | `582159e` + el commit de cierre de este reporte |
| Primer SHA con CI 10/10 verde | `c2981297cfc154a8c9c66edb07caa77db16d053d` |
| Commits | 9 (S0–S7, S9-lite, cierre) |
| CI sobre el HEAD | verde (ver "Evidencia CI") |
| Restricción respetada | cero motores/orchestrators/planners nuevos; cero dependencias nuevas; cero CQRS/event sourcing; UI intacta |

## Commits ejecutados

| Slice | Commit | Alcance |
|---|---|---|
| S0 | `55dfcdb` | Ratchets de autoridad (6 familias) + frontera de confianza por AST + registro de autoridad |
| S1 | `0faaf77` | Mapa BEFORE (28 componentes), registro de duplicaciones (P0/P1/P2), ADRs 001–006 |
| S2 | `49012c2` | Autoridad del cierre: reducer + invariantes + `RUNTIME_RUN_STATE_STRICT` real |
| S5 | `0909f9b` | Ledger como escritor único de totales; fin del doble conteo de tokens del juez |
| S4 | `f36f30f` | Vocabulario único de condición de evidencia + conflictos medidos |
| S7 | `746d9d0` | Permisos explícitos y fail-closed en el plano de acción |
| S9-lite | `582159e` | Coherencia de flags: combinaciones pinneadas + registro con retiro |
| fix | `dfb1f09` | Allowlist del reducer del cierre (fallo detectado por CI) |
| cierre | (este commit) | Mapa AFTER, reporte final y ratchet de autoridades de la fase |

## Métricas before / after

| Métrica | Before | After | Cómo se verifica |
|---|---|---|---|
| Fases terminales derivadas del texto | 1 (mapper `terminal_phase_for` decidía) | 0 (la autoridad decide; el mapper es oráculo) | `test_closure_authority.py::test_propiedad_finalized_requiere_autorizacion_de_cierre` (≥700 combinaciones) |
| Writers de totales de costo fuera del ledger | 7 (`record_judge_call`) | 0 | familia `result_totals` en `test_authority_ownership.py` |
| Doble conteo de tokens del juez en `usage_events` | sí (evento por fase + evento del run) | no (0 tokens + `judge_token` en routing) | `test_cost_authority.py::test_evento_del_juez_no_repite_tokens` |
| Vocabulario de condición de evidencia | inexistente (conflaciones invisibles) | 9 condiciones + 2 conflictos medidos | `test_evidence_semantics.py` (21 casos) |
| Callers de workflow con permisos implícitos de sistema | 4 (escalado silencioso) | 0 (contexto de sistema explícito; sin él, set vacío) | `test_action_plane_authority.py::test_callers_de_sistema_declaran_system_context` |
| Flags documentados que no existen | 1 (`RUNTIME_RUN_STATE_STRICT`) | 0 | `test_closure_authority.py::test_config_declara_el_flag_estricto_global` |
| Ratchets arquitectónicos en CI | 2 (terminal transitions, exception certification) | 8 (6 nuevos + 2 pin) | paso `Architecture invariants` |
| Estados críticos con autoridad declarada y símbolo verificado | 0 | 17 | `AUTHORITY_REGISTRY` + mapa |

## Tests creados

| Archivo | Casos | Contrato |
|---|---|---|
| `tests/test_authority_ownership.py` | 13 | writers por familia, frontera de confianza (AST), registro de autoridad, mapa |
| `tests/test_closure_authority.py` | 24 | reducer del cierre, propiedades, estabilidad ×100, strict global/canary |
| `tests/test_cost_authority.py` | 11 | ledger como autoridad, evento del juez sin duplicar, unknown vs zero |
| `tests/test_evidence_semantics.py` | 21 | 9 condiciones, 2 conflictos, pin del vocabulario de stops, determinismo ×100 |
| `tests/test_action_plane_authority.py` | 6 | handlers verifican permisos, workflow fail-closed, contexto de sistema |
| `tests/test_run_state.py` (actualizado) | 2 casos nuevos | invariantes previos como defensa en profundidad |

Total: 75 casos nuevos + 2 reformulados. Todos integrados en el paso obligatorio
`Architecture invariants (fast, required)` de `.github/workflows/ci.yml`.

## Compatibilidad

| Cambio | Tipo | Impacto |
|---|---|---|
| `finish(phase_override=, oracle_phase=)` | aditivo (kwargs) | ninguno |
| `RunBudgetLedger.for_totals`, `account_judge_usage` | aditivo | ninguno |
| `UsageEvent` de `jev_judge:*` con 0 tokens | cambio de datos | un consumidor que sumara tokens desde esos eventos ahora ve 0; los tokens viven en el evento del run y en `routing["judge_tokens"]`. El costo estimado del juez no cambia |
| `run_workflow(system_context=)` | aditivo + cambio de default | un caller externo (fuera del repo) que no pase `permissions` ni `system_context` pierde los permisos de sistema implícitos: **fail-closed deliberado**, documentado |
| `RUNTIME_RUN_STATE_STRICT` | campo real (default `off`) | un entorno que ya lo tuviera en `on` (documentado antes como autoridad) empieza a aplicar fail-closed. Nota operativa: verificar el valor antes de desplegar |
| `decisions.closure` en `to_public_dict()` | aditivo | ninguno |
| Invariantes 11/12 del run state | aditivos, críticos en modo estricto | sin strict, solo traza y métrica |

## Evidencia CI

- Baseline `5cd3dec`: 10/10 `success` (run `38421254086`).
- Slices S2, S5, S4 y S7 (`49012c2`, `0909f9b`, `f36f30f`, `746d9d0`): el job
  `test` falló por **un único** test, `test_terminal_transitions_allowlist`
  (los literales de fase del reducer del cierre). Mismo fallo en los cuatro
  SHAs, sin ningún otro test rojo (verificado en las anotaciones de cada run).
- Corregido en `dfb1f09`: allowlist por entrada con justificación (la resolución
  del reducer no es una transición del run; el aplicador único sigue siendo
  `finish(phase_override=...)`).
- **CI 10/10 verde**: `c2981297cfc154a8c9c66edb07caa77db16d053d`
  (secrets-scan, lint, pip-audit, test, sdk-python, sdk-node, portal,
  portal-e2e, kustomize, build).
- Verificación local del paso completo de invariantes: **321 passed**; suites
  enfocadas verdes: ≈1500 ejecuciones (cierre, evidencia, costo, workflows,
  RAG/agente, trace/Execution Story: 78).
- Los commits posteriores al verde solo agregan documentación y tests: el
  mismo conjunto de invariantes corre en su CI.

## Deuda restante

### P0 (ambigüedad de autoridad que queda)

Ninguna conocida. Los cinco P0 del recon están resueltos o medidos:

| ID | Estado |
|---|---|
| P0-1 cierre sin enforcement / flag muerto | RESUELTO (S2) |
| P0-2 fase terminal derivada del texto | RESUELTO (S2) |
| P0-3 10 deciders de answerability | PARCIAL: productores de señal + resolver único; los deciders siguen existiendo como gates especializados (por diseño) |
| P0-4 sufficiency duplicada | RESUELTO en vocabulario; la unificación de `EvidenceQuality` como proyección queda en S11 |
| P0-5 tres writers de costo | RESUELTO (S5) |

### P1

Los siete P1 del recon original quedaron cerrados en el hardening de autoridad
(H0–H9). El detalle before/after, la evidencia y la deuda remanente viven en
`08-hardening-report.md`; resumen:

| ID | Deuda original | Estado |
|---|---|---|
| P1-1 | `JEV_SHADOW_MODE` no impide actuar en modo `jev` | RESUELTO (shadow no actúa) |
| P1-2 | Preflight con bloqueo JEV-only sin segunda señal | RESUELTO (matriz determinista × JEV) |
| P1-3 | Overrides por agente pueden desarmar autoridad global | RESUELTO (piso monotónico + contrato `on|shadow|off`) |
| P1-4 | Formas delegadas del plano de acción | CERRADO por contrato con test (eventos: P2-H1 aceptado) |
| P1-5 | RunGuards advisory por default | RECLASIFICADO P3 con evidencia (`GUARD_CLASS`) |
| P1-6 | 10 combinaciones de flags contradictorias | RESUELTO (startup fail-closed) |
| P1-7 | `budget.last_cut_reason` sin writer | RESUELTO (representación eliminada) |

Nuevos invariantes del hardening: cierre fail-closed ante fallo del reducer,
terminales solo por el aplicador canónico, un juicio JEV nunca decide solo, el
piso de seguridad no se debilita desde config normal, y ninguna instancia
arranca en una postura contradictoria. Cada uno tiene ratchet estático **y**
test behavioral (ver `08-hardening-report.md`).

### P2

| ID | Deuda |
|---|---|
| P2-1 | El inventario de flags no cubre `RAG_LONG_CONTEXT_*`, `RAG_COGNITIVE_OS_ENABLED`, `RAG_JEV_PREFLIGHT_*` |
| P2-2 | Flags sin owner ni condición de retiro por flag |
| P2-3 | Campos sin writer (`plan.strategy`, `knowledge.entities/brief/narrative_package`, `answer.gate`, `decisions.jev`, `tools.failures`) |
| P2-4 | `is_organization_admin` / `is_platform_admin` sin callers |
| P2-5 | `_check_subqueries` no-op ante error de parse (SQL Expert) |
| P2-6 | `usage_logs` legacy convive con `usage_events` |
| P2-7 | `DecisionUsageRecorder.record` sin call sites |
| P2-8 | `COUNT(*)` sobre `usage_events` incluye eventos por fase (métrica de requests ≠ facturación) |
| P2-9 | `EvidenceQuality.recommended_action` sigue siendo una segunda representación en el camino RAG (proyección declarada, no eliminada) |

### P3 (higiene)

| ID | Deuda |
|---|---|
| P3-1 | `except Exception` sin comentario en caminos críticos (agent_runtime 4, orchestrator 11, provider 4, router 1) — ratchet F11 vigente |
| P3-2 | `answer_gate` guarda el usage del juez en su propio resultado (documentado en el ratchet; no es writer del run) |
| P3-3 | El vocabulario `PARTIAL_STOPS` no cubre stops futuros del motor (el pin rompe CI y obliga a decidir) |

## La pregunta final

> «Si mañana un ingeniero pregunta quién tiene autoridad para cambiar cualquier
> estado crítico de un AgentRun, ¿puedo señalar exactamente un componente o
> reducer?»

**Sí, para los estados críticos que la fase definió como tales**, con la tabla de
`05-ownership-map-after.md`:

- fase terminal → `finalization_policy.resolve_closure_phase` + `finish()`;
- costo/tokens → `RunBudgetLedger`;
- condición/medición de evidencia → `evidence.assess_sufficiency` +
  `evidence_semantics.classify_evidence_condition`;
- autorización → `tools.registry.tool_allowed` / handlers del dispatcher;
- ejecución → `tools.guards.execute_tool_guarded`;
- identidad y tenant → `TenantContext` (frozen, del token);
- permisos de workflow → `resolve_workflow_permissions`;
- decisión definitiva → `DecisionEnvelope`;
- clasificación de fallo → `failure_taxonomy`.

Cada una de esas afirmaciones tiene un ratchet que falla si aparece un writer o
un bypass nuevo. **No es un "sí" absoluto para todo el sistema**: los deciders
de answerability siguen siendo diez gates especializados que aportan señales (por
diseño, no por ambigüedad), y la deuda P1/P2/P3 de arriba documenta lo que falta
antes de poder afirmarlo para el resto de los estados.

## Recomendación de continuación

1. **Producción (Prompt 3)**: iniciar Production Readiness / Load / Chaos /
   Canary con `P0 known = 0` y `P1 de arquitectura/seguridad = 0` (hardening
   H0–H9, ver `08-hardening-report.md`).
2. **Adopción por canary** de lo ya construido: con `closure` y `strict` reales,
   medir `zent_evidence_condition_conflicts_total`,
   `zent_finalization_divergence_total` y `zent_run_state_violations_total`
   antes de encender el fail-closed global; revisar el acknowledgement
   `RUNTIME_CONFIG_ACK_DANGEROUS` en el entorno de despliegue (el `.env` local
   tiene combinaciones DANGEROUS de calibración que en producción exigen ack).
3. **Deuda P2** sin riesgo de autoridad: planos delegados de eventos (P2-H1,
   firma de eventos como decisión de producto), inventario de flags
   (`RAG_LONG_CONTEXT_*`, `RAG_COGNITIVE_OS_ENABLED`, `RAG_JEV_PREFLIGHT_*`),
   `EvidenceQuality` como proyección y representaciones muertas restantes.
