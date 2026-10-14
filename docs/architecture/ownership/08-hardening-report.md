# Hardening de autoridad — reporte de cierre (H0–H9)

Segunda pasada sobre `docs/architecture/ownership/06-final-report.md`: cierra los
huecos de autoridad P1 que quedaban después de la convergencia, **sin features,
sin motores nuevos y sin abstracciones nuevas**. Regla que ahora es cierta y
está ratcheteada:

> UNTRUSTED / PROBABILISTIC COMPONENTS PRODUCE SIGNALS.
> POLICY PRODUCES AUTHORIZATION.
> CANONICAL REDUCERS PRODUCE CRITICAL STATE TRANSITIONS.
> RUNTIME EXECUTES.
> NO COMPONENT MAY SILENTLY FALL BACK TO A WEAKER AUTHORITY MODEL WHEN THE
> STRONGER AUTHORITY FAILS.

| Campo | Valor |
|---|---|
| Baseline | `6bfed8092232720ff21ccbf07ccfb1e9162a8145` (CI 10/10 verde) |
| Alcance | cierre de P1 de arquitectura/seguridad; cero features; UI intacta |
| Restricciones respetadas | cero orchestrators/planners/ledgers/event stores nuevos; cero dependencias nuevas; mapper legacy conservado como oráculo |

## P1 before / after

| ID | Before | After | Cómo se verifica |
|---|---|---|---|
| P1-A fallo de autoridad del cierre | `resolve_closure_phase` lanzaba → `phase_override=None` → mapper legacy → **FINALIZED por texto** | `closure_authority_failure` → FAILED + `closure_authority_failed` (crítico) + traza; `finish()` sin resolución tampoco cae al mapper (FAILED) | `test_closure_authority.py::TestAutoridadDeCierreFailClosed` (excepción monkeypatcheada, texto no vacío, barrido ≥40 combinaciones) |
| P1-B transiciones terminales | `try_advance(FINALIZED)` aceptado desde cualquier fase (CREATED→FINALIZED) | `try_advance` no acepta terminales; aplicador único `_apply_terminal` (privado) + `apply_closure_override` solo no-concluyentes | `test_run_state.py` (barrido por enum), `test_terminal_transitions_allowlist.py` (allowlist + asignaciones `.phase =`) |
| P1-C autoridad JEV | `JEV_SHADOW_MODE` no impedía actuar en modo `jev`; preflight podía BLOQUEAR con un juicio solo (≥2 insatisfechas, conf ≥0.70) | `acts()` no actúa con shadow; matriz explícita `resolve_authorization` (DENY gana; ALLOW no se invierte; UNKNOWN+JEV solo → advisory/retrieve/corroboración, nunca definitivo) | `test_authorization_matrix.py` (matriz + barrido + shadow + JEV no otorga capacidad) |
| P1-D piso de seguridad | org/agente podían desarmar strict y enforcement (`config_json` con prioridad absoluta) | piso monotónico: `global ∪ org ∪ agente`; el agente solo refuerza; downgrade prohibido (no hay break-glass porque el producto no lo necesita) | `test_safety_floor.py`, `test_finalization_enforcement_scopes.py::TestPisoMonotonico` |
| P1-E flags contradictorios | 10 combinaciones detectadas, solo pinneadas en tests | `config_rules.py` con severidades INVALID/DANGEROUS; INVALID = startup failure; DANGEROUS = warning en dev, error en prod sin `RUNTIME_CONFIG_ACK_DANGEROUS` | `test_config_rules.py` (cada INVALID + prod + ack) |
| P1-F autoridad durante el run | envelope/authority en variable local; SQL se publicaba ~1000 líneas después de resolverse | publicación en el event boundary (SQL al resolver el modo; envelope al construirse) | `test_decision_state_inflight.py` (run observado antes de finalization + ratchet de orden) |
| P1-G RunGuards | advisory por default sin clasificación (P1-5 artificial) | `GUARD_CLASS` + `GUARD_CANONICAL_ENFORCER`: SECURITY/CORRECTNESS duplican autoridades que corren siempre; RESOURCE respeta el ledger; QUALITY advisory | `test_run_guards_classification.py` (barrido de todos los veredictos + behavioral del cierre y del ledger) |
| P1-H plano de acción | dispatcher/embed/cognitive con authz "a nivel trigger" sin test runtime | contrato demostrado con tests: deny corta antes del handler; shadow no ejecuta; tool privilegiada no corre con permisos vacíos; DAG con tenant del run | `test_action_plane_authority.py` (3 tests behavioral + 1 ratchet de tenant) |
| P1-I accounting | ya estabilizado (S5) | **sin tocar**: invariantes verificados | `test_cost_authority.py` (ledger único writer, juez sin doble conteo, unknown≠0), `test_run_budget.py`, `test_run_accounting*`, `test_authority_ownership.py::result_totals` |
| P1-7 representación muerta | `budget.last_cut_reason` sin writer | campo eliminado; `stop_reason` es la única representación (writer único `_mark_budget_stop`) | grep de callers (0) + `agent-run-state.md` actualizado |

## Cambios por archivo

| Archivo | Cambio |
|---|---|
| `src/runtime/finalization_policy.py` | `CLOSURE_AUTHORITY_FAILED`/`_MISSING`; `ClosureResolution.reason_code`; `closure_authority_failure()` |
| `src/runtime/run_state.py` | terminales fuera de `_allowed_transitions`; `try_advance` rechaza terminales; `_apply_terminal`; `apply_closure_override`; `CLOSURE_OVERRIDE_PHASES`; `CRITICAL_INVARIANTS += closure_authority_failed`; `finalize_state` fail-closed y observabilidad separada; `strict_mode_enabled` monotónico; `last_cut_reason` eliminado |
| `src/runtime/enforcement.py` | scopes de enforcement como unión (piso monotónico) |
| `src/runtime/answer_gate.py` | `answer_gate_mode` honra `on/shadow/off` (contrato documentado) |
| `src/decision/settings.py` | `acts()` no actúa con `shadow_mode` |
| `src/decision/preflight.py` | matriz `resolve_authorization` + `_deterministic_state` + fallback determinista (JEV no elige la acción de un DENY) |
| `src/core/config_rules.py` (nuevo) | validación de combinaciones (severidades + reason codes estables) |
| `src/core/config.py` | `RUNTIME_CONFIG_ACK_DANGEROUS` + `assert_runtime_config` en el model validator (startup) |
| `src/runtime/run_guards.py` | `GuardClass`, `GUARD_CLASS`, `GUARD_CANONICAL_ENFORCER`, `requires_guard_enforcement` |
| `src/agents/runtime/orchestrator.py` | publicación de autoridad en el boundary (SQL y envelope); strict block por `apply_closure_override` |
| `src/agents/runtime/agent_runtime.py` | strict block por `apply_closure_override` (reason code `STRICT_BLOCK` del catálogo) |
| `src/runtime/reason_codes.py` / `failure_taxonomy.py` | `strict_block` en el catálogo + clasificación (`POLICY_BLOCK`, visible, no operativo) |
| `.github/workflows/ci.yml`, `.env.example`, `deploy/k8s/configmap.yaml`, `docker-compose.prod.yml` | ratchets nuevos en el paso obligatorio de invariantes; flag de acknowledgement documentado en las superficies de despliegue |
| `docs/architecture/jev-preflight.md`, `ownership/02`, `ownership/03`, `ownership/05`, `ownership/06`, `ownership/07`, `architecture/agent-run-state.md` | contrato actualizado (matriz JEV, piso, flags, mapa, este reporte) |

## Invariantes nuevos

1. `closure_authority_failed` es invariante crítico: en modo estricto bloquea la
   respuesta; la fase aplicada es FAILED aunque haya texto.
2. Ninguna fase terminal se alcanza por `try_advance` (ratchet behavioral por
   enum + ratchet estático de asignaciones `.phase =`).
3. Un override post cierre solo puede aplicar fases no-concluyentes (nunca
   fabricar FINALIZED).
4. Los scopes de seguridad (strict, enforcement) son unión: nunca resta.
5. Una señal JEV sola no produce acción definitiva (`abstain`/`ask_user`/
   `deterministic_answer`); el DENY determinista siempre gana.
6. `shadow_mode` nunca cambia la ejecución (observa y registra).
7. Cada veredicto de `run_guards` declara clase y autoridad canónica.
8. Toda combinación INVALID de flags impide el arranque.
9. Los campos de autoridad de `DecisionState` solo se escriben por métodos
   (`set_envelope`/`observe_*`).

## Deuda restante (P2/P3)

| ID | Deuda | Estado |
|---|---|---|
| P2-H1 | `dispatch_event_to_workflows` deriva el tenant del payload del evento (canal Redis = infraestructura confiable; cualquiera con acceso a Redis puede disparar triggers de otra org). Firma/token de eventos es una decisión de producto | INTENTIONALLY ACCEPTED — owner: plataforma; riesgo: cross-tenant trigger con acceso a Redis; mitigación actual: triggers por org + depth 4 + dedupe |
| P2-H2 | `sql_executor` del cognitive executor no cableado y `_handle_data_analyst` skipped: capacidad latente | ABIERTO (higiene) |
| P2-H3 | `embeddings`/`cognitive` sin RBAC por request (authz a nivel trigger): equivalente verificado (tools permissioned bloqueadas por permisos vacíos) | RECLASIFICADO P2 con evidencia |
| P2-1..P2-9 | deuda de higiene previa (inventario de flags, `EvidenceQuality`, `usage_logs`) | ABIERTO, sin riesgo de autoridad |
| P3-1..P3-3 | higiene previa; P3 nuevo: `RUNTIME_RUN_GUARDS_ENFORCE` con clase M | ABIERTO |

## La pregunta final

> «¿Puede un fallo de la autoridad más fuerte degradar en silencio a un modelo
> de autoridad más débil?»

**No.** Cierre: fallo del reducer del cierre → FAILED estructurado (no legacy).
JEV: sombra no actúa y un juicio solo no decide. Config normal: no debilita el
piso ni arranca en postura contradictoria. Terminal: solo el aplicador canónico.
Cada afirmación tiene un test behavioral además del estático.
