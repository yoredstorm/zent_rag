# Ownership — Baseline de la fase de convergencia de autoridad

## Baseline registrado

| Campo | Valor |
|---|---|
| `BASELINE_SHA` | `5cd3dec1812955c28dd6ce338f56322022a2079c` |
| Fecha del commit | 2026-10-13 10:20:39 -0500 |
| Mensaje | `fix(test): hermeticidad de reglas genericas de enrichment` |
| CI sobre el baseline | 10/10 checks `success` (secrets-scan, lint, pip-audit, test, sdk-python, sdk-node, portal, portal-e2e, kustomize, build) |
| Run | `actions/runs/38421254086` |
| Verificación | API `repos/yoredstorm/zent_rag/commits/master/check-runs` (no hay `gh` CLI en el entorno) |
| Rama | `master` (única), sin worktrees activos al inicio |

Requisito de entrada de la fase cumplido: no se tocó código productivo hasta
verificar CI verde sobre ese SHA.

## Método del recon

Cinco barridos paralelos read-only con evidencia `file:line`, más verificación
puntual propia de los hallazgos que deciden prioridades:

1. Writers de `AgentRunState` y transiciones terminales.
2. Autoridad de costo/budget y persistencia.
3. Frontera de confianza (tenant/org/RBAC) y plano de acción.
4. Evidencia, answerability y JEV.
5. Flags, modos y enforcement.

Los números del ratchet de S0 (`tests/test_authority_ownership.py`) se midieron
sobre este baseline con el mismo método que el test.

## Ratchets introducidos en S0

`tests/test_authority_ownership.py` corre en el paso obligatorio
`Architecture invariants (fast, required)` de `.github/workflows/ci.yml`.

| Familia | Hits en baseline | Archivos | Autoridad declarada |
|---|---|---|---|
| `phase_writes` | 10 | 4 | `run_state.try_advance` / `finish` |
| `result_totals` | 16 | 3 | `RunBudgetLedger.account_*` |
| `answer_writes` | 6 | 2 | `finalize_state` (+ strict block declarado) |
| `decision_writes` | 2 | 2 | `finalize_state` + `resolve_closure` |
| `authority_flag_writes` | 2 | 1 | `observe_prep` (deuda: escritura directa en RAG) |
| `terminal_mapper` | 2 (def + 1 call) | 1 | `finish()` |
| `ToolContext` | 2 sitios | 2 | frontera de confianza (AST) |

## Estados críticos con más de un writer (baseline)

| Estado | Writers | Naturaleza de la duplicación |
|---|---|---|
| `phase` | `run_state`, `agent_runtime`, `orchestrator`, (`decision/preflight` en otro run) | transiciones terminales allowlisted; deuda S2 |
| `result.cost/total_tokens` | `run_budget` (canónico), `run_accounting` (juez), `answer_gate` (usage del juez) | bypass del ledger; deuda S5 |
| `answer.text/answer_state` | `finalize_state`, strict block de `agent_runtime` | strict block reemplaza al cierre; deuda S2/S3 |
| `decisions.requires_deterministic` | `run_state.observe_prep`, escritura directa en `orchestrator` (2 sitios) | deuda S2/S3 |
| `evidence.registry/selection/sufficiency` | `agent_runtime`, `orchestrator`, `run_state.observe()` | métodos del estado como reducer parcial |
| `trace.notes` | `run_state`, `agent_runtime`, `orchestrator` | observacional, sin impacto en autoridad |
| `answer.guard_overrides` | `agent_runtime`, `orchestrator` | contador observacional |
| `budget.stop_reason` | `agent_runtime` (8 sitios de corte) | un solo módulo, múltiples puntos de corte (S11) |

## Preguntas de la fase y su estado en el baseline

| Pregunta | Respuesta en baseline |
|---|---|
| ¿Quién posee el estado de un run? | `AgentRunState`, pero con 3 writers de fase |
| ¿Quién puede modificar cada estado? | Cada sub-estado tiene métodos (`observe*`), con excepciones directas |
| ¿Quién decide que existe evidencia suficiente? | Dos modelos rivales: `EvidenceSufficiency` y `EvidenceQuality` (adaptive) |
| ¿Quién autoriza una acción? | `registry.tool_allowed` (triple gate) en el loop; dispatcher/cognitive/workflow con formas delegadas |
| ¿Quién ejecuta una acción? | `execute_tool_guarded` (6 call sites declarados) |
| ¿Quién decide que el run termina? | **Nadie de forma única**: la fase se deriva del texto en `finish()` |
| ¿Quién posee el costo? | `RunBudgetLedger`, con bypasses en el juez |
| ¿Quién produce una decisión definitiva? | `FinalizationPolicy` + `DecisionEnvelope` cuando existe; en ejecutables sin autoridad, fail-closed |
| ¿Quién redacta la respuesta final? | Generador + `FINAL_AUTHORITY_LOCK` + composer, con veto del strict block |

Ver `01-ownership-map-before.md` para la matriz por componente y
`02-duplicated-authorities.md` para el registro de duplicaciones.
