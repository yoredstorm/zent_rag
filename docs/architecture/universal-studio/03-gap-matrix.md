# 03 — Matriz de brechas AS-IS → TARGET → GAP

> **Actualización 2026-10-21:** U-07 (Gold real) fue remediado parcialmente.
> El Gold de venta pasa con Pro y con el fallback Flash; auditoría y bienestar
> siguen en clarificación y la matriz 100/20 casos no alcanza GO. Ver
> [`../certification/universal-studio-remediation.md`](../certification/universal-studio-remediation.md).

> **Estados:** `IMPLEMENTADO`, `PARCIAL`, `NO IMPLEMENTADO`, `NO VERIFICADO`,
> `BLOQUEADO POR PROVEEDOR`.
>
> **Severidad:** `P0` puede producir un workflow inseguro, imposible de ejecutar o
> una publicación sin evidencia; `P1` impide el caso de uso universal o la
> operación empresarial; `P2` afecta experiencia, mantenimiento o rendimiento.
>
> Cada fila cita el archivo responsable y una prueba de aceptación. Las pruebas
> marcadas `NUEVA` no existen todavía; las marcadas `EXISTE` se ejecutaron en
> esta fase (ver [`06-test-evidence.md`](06-test-evidence.md)).

## 1. Resumen

| ID | Sev | Brecha | Estado | Fase |
|---|---|---|---|---|
| U-01 | P0 | La publicación no consume la certificación de simulación | NO IMPLEMENTADO | 06 |
| U-02 | P0 | La certificación no distingue efectos declarados, sandbox y proveedor real | NO IMPLEMENTADO | 06 |
| U-03 | P0 | Los disparadores normales no crean `WorkflowInstance` para grafos durables | NO IMPLEMENTADO | 05 |
| U-04 | P0 | Los workflows manuales no tienen gate de publicación/readiness | PARCIAL | 05/06 |
| U-05 | P0 | `llm` sin agente devuelve eco con `succeeded` en runtime | PARCIAL | 05 |
| U-06 | P0 | No hay política de rol para bienestar (diagnóstico/psicoterapia) | NO IMPLEMENTADO | 07 |
| U-07 | P0 | El Gold real con LLM no genera plan en HEAD | BLOQUEADO POR PROVEEDOR | 09 |
| U-08 | P1 | No existe intake universal rol/proceso → agentes + workflows | NO IMPLEMENTADO | 03 |
| U-09 | P1 | No existe catálogo de roles/arquetipos ni plantillas de rol | NO IMPLEMENTADO | 02 |
| U-10 | P1 | La versión de agente no gobierna el runtime del workflow | NO IMPLEMENTADO | 02/05 |
| U-11 | P1 | Multi-agente existe en el grafo pero sin contrato, UI ni prueba | PARCIAL | 03 |
| U-12 | P1 | Agente→workflows no filtra por workspace y solo ve nodos `llm` | PARCIAL | 02 |
| U-13 | P1 | La certificación no exige cobertura de ramas/escenarios críticos | NO IMPLEMENTADO | 06 |
| U-14 | P1 | `ai_decision` llama al JEV real durante la simulación | PARCIAL | 06 |
| U-15 | P1 | `for_each` semántico bloqueado; canvas con `_branch` vacío reporta éxito | PARCIAL | 04 |
| U-16 | P1 | Readiness/publicación manual usan `load_capabilities` (sin estado real) | PARCIAL | 04 |
| U-17 | P1 | El publish de agente es advisory; no exige readiness/eval | PARCIAL | 07 |
| U-18 | P1 | No hay presupuesto, concurrencia ni rate limit por workflow | NO IMPLEMENTADO | 05 |
| U-19 | P1 | No hay service identity por workflow; permisos de sistema estáticos | PARCIAL | 05 |
| U-20 | P1 | Ni las trazas de workflow ni las respuestas de agente enmascaran PII de forma uniforme | PARCIAL | 07 |
| U-21 | P1 | Publicación/activación/simulación no tienen audit log dedicado | PARCIAL | 07 |
| U-22 | P1 | `/workflows/instances` no filtra por workspace | PARCIAL | 05 |
| U-23 | P1 | RBAC por capability solo cubre external/agent/integration | PARCIAL | 07 |
| U-24 | P1 | No hay consola operativa ni bandeja de aprobaciones | NO IMPLEMENTADO | 08 |
| U-25 | P1 | El Studio está partido en AgentStudio, WorkflowStudio y Marketplace | PARCIAL | 08 |
| U-26 | P1 | La suite de certificación no terminó verde en HEAD | NO VERIFICADO | 09 |
| U-27 | P2 | El canvas usa `/integrations` y no el catálogo global `/products` | PARCIAL | 04 |
| U-28 | P2 | `/marketplace`, `/products` y `/integrations` conviven sin contrato de superficie | PARCIAL | 04 |
| U-29 | P2 | `intent` no influye en la compilación | NO IMPLEMENTADO | 04 |
| U-30 | P2 | Costo mensual incorrecto para schedules semanales | NO IMPLEMENTADO | 04 |
| U-31 | P2 | `loop` sin `NODE_NEXT_STEPS` y 9 nodos sin schema de negocio | PARCIAL | 08 |
| U-32 | P2 | Métricas del Architect en memoria; preview de negocio impreciso | PARCIAL | 08 |

### 1.1 Matriz de aceptación (archivo → prueba)

| ID | Sev | Archivo responsable | Prueba de aceptación | Estado |
|---|---|---|---|---|
| U-01 | P0 | `src/platform/workflows/versions.py` | `tests/test_workflow_publication_gate.py` | NO IMPLEMENTADO |
| U-02 | P0 | `src/platform/workflows/workflow_simulation.py` | `tests/test_workflow_certification_effects.py` | NO IMPLEMENTADO |
| U-03 | P0 | `src/platform/workflows/engine.py` | `tests/test_workflow_durable_triggers.py` | NO IMPLEMENTADO |
| U-04 | P0 | `src/platform/workflows/versions.py` | `tests/test_workflow_native_publish_gate.py` | PARCIAL |
| U-05 | P0 | `src/platform/workflows/nodes.py` | `tests/test_workflow_graph.py` + `test_workflows.py` | PARCIAL |
| U-06 | P0 | `src/platform/ai_governance/ai_governance.py` | `tests/test_role_safety_wellness.py` | NO IMPLEMENTADO |
| U-07 | P0 | `src/platform/workflows/planner_session.py` | `tests/certification/ai/test_real_llm_gold.py` | BLOQUEADO POR PROVEEDOR |
| U-08 | P1 | `src/platform/studio/solutions.py` | `tests/test_studio_solutions.py` | NO IMPLEMENTADO |
| U-09 | P1 | `src/api/routes/agents.py` | `tests/test_agent_roles.py` | NO IMPLEMENTADO |
| U-10 | P1 | `src/platform/workflows/nodes.py` | `tests/test_workflow_agent_version_pinning.py` | NO IMPLEMENTADO |
| U-11 | P1 | `src/platform/workflows/architect_compiler.py` | `tests/test_workflow_multi_agent.py` | PARCIAL |
| U-12 | P1 | `src/platform/workflows/assistants.py` | `tests/test_agent_workflow_links.py` | PARCIAL |
| U-13 | P1 | `src/platform/workflows/workflow_simulation.py` | `tests/test_workflow_scenario_coverage.py` | NO IMPLEMENTADO |
| U-14 | P1 | `src/platform/workflows/nodes.py` | `tests/test_workflow_simulation.py` | PARCIAL |
| U-15 | P1 | `src/platform/workflows/architect_validator.py` | `tests/test_workflow_join_merge.py` + nueva | PARCIAL |
| U-16 | P1 | `src/platform/workflows/readiness.py` | `tests/test_workflow_readiness_capabilities.py` | PARCIAL |
| U-17 | P1 | `portal/src/components/agentStudio/AgentPublishSection.tsx` | `tests/test_agent_publish_gate.py` | PARCIAL |
| U-18 | P1 | `src/platform/workflows/engine.py` | `tests/test_workflow_runtime_budget.py` | NO IMPLEMENTADO |
| U-19 | P1 | `src/platform/workflows/engine.py` | `tests/test_workflow_service_identity.py` | PARCIAL |
| U-20 | P1 | `src/platform/workflows/context_store.py` | `tests/test_workflow_trace_pii.py` | PARCIAL |
| U-21 | P1 | `src/platform/workflows/versions.py` | `tests/test_workflow_audit.py` | PARCIAL |
| U-22 | P1 | `src/platform/workflows/instances.py` | `tests/test_workflow_workspace_isolation.py` | PARCIAL |
| U-23 | P1 | `src/platform/workflows/nodes.py` | `tests/test_workflow_capability_rbac.py` | PARCIAL |
| U-24 | P1 | `portal/src/pages/StudioOperations.tsx` | `portal/e2e/studio-operations.spec.ts` | NO IMPLEMENTADO |
| U-25 | P1 | `portal/src/pages/Studio.tsx` | `portal/e2e/universal-studio-shell.spec.ts` | PARCIAL |
| U-26 | P1 | `tests/certification/workflows` | suite completa | NO VERIFICADO |
| U-27 | P2 | `portal/src/components/WorkflowCanvasEditor.tsx` | `NodeLibrary.test.tsx` + e2e | PARCIAL |
| U-28 | P2 | `src/api/routes/ecosystem.py` | `tests/test_marketplace_surface_contract.py` | PARCIAL |
| U-29 | P2 | `src/platform/workflows/architect_compiler.py` | unit de intent | NO IMPLEMENTADO |
| U-30 | P2 | `src/platform/workflows/architect.py` | unit de costo semanal | NO IMPLEMENTADO |
| U-31 | P2 | `src/platform/workflows/node_catalog.py` | snapshot test | PARCIAL |
| U-32 | P2 | `src/platform/workflows/architect_metrics.py` | unit de preview | PARCIAL |

---

## 2. P0 — detalle

### U-01 · La publicación no consume la certificación

**AS-IS**

- `versions.publish_workflow` valida packages importados
  (`versions.py:448-453`) y, para workflows del Architect, grafo, agente,
  snapshot y readiness (`versions.py:458-476`).
- **No** lee `workflow_design_revisions.simulation` ni el
  `CertificationReport` de la sesión.
- La certificación se persiste en la sesión
  (`design_sessions.save_design_simulation`, `design_sessions.py:523-551`),
  pero el borrador guardado no la lleva (`architect.save_architect_draft`,
  `architect.py:1045-1241`).

**TARGET**

`publish_workflow` recibe `PublicationEvidence` y deniega si:

- no hay certificación vigente para el `plan_hash`/`graph_hash`;
- el `capability_snapshot_hash` cambió;
- el estado es `UNVERIFIED`, `FAILED_VALIDATION`, `VALIDATING` o stale;
- hay efectos externos sin verificación de sandbox/proveedor;
- hay acciones críticas sin aprobación.

**GAP**

No existe el puente certificación → publicación. El usuario puede publicar un
workflow que nunca se simuló, o simular uno y publicar otro.

**Archivo responsable**

- `src/platform/workflows/versions.py`
- `src/platform/workflows/design_sessions.py`
- `src/platform/workflows/architect.py`
- `src/api/routes/workflows.py`

**Prueba de aceptación (NUEVA)**

`tests/test_workflow_publication_gate.py`:

1. simular plan con `UNVERIFIED` → `POST /publish` devuelve 409/400 y no crea
   versión production;
2. simular plan OK, cambiar el plan → publish rechaza por hash stale;
3. simular plan OK y publicar → `workflow_versions.certification` contiene el
   `certification_id`;
4. workflow manual sin certificación → según flag `report|warn|block`.

---

### U-02 · La certificación no distingue efectos declarados, sandbox y proveedor real

**AS-IS**

- `_RISKY_NODE_TYPES` incluye `capability_call`, `marketplace_action`,
  `api_call`, `llm`, `query_business_data`, `kb_query`, `business_node`
  (`workflow_simulation.py:36-46`).
- Si el escenario declara una respuesta, el nodo se considera “pinned” y deja
  de ser `unverified` (`workflow_simulation.py:246-289`).
- Si todos los escenarios pasan y no hay aprobación/financiero, el estado es
  `READY_TO_PUBLISH` (`workflow_simulation.py:845-853`).

**TARGET**

Añadir `effect_verification`:

| Nivel | Significado | Estado máximo |
|---|---|---|
| `NONE` | sin efectos externos | `READY_TO_PUBLISH` |
| `DECLARED` | respuesta fijada por el usuario | `AWAITING_EFFECT_VERIFICATION` |
| `SANDBOX` | proveedor sandbox real | `READY_TO_PUBLISH` |
| `PROVIDER` | proveedor real | `READY_TO_PUBLISH` |

Una respuesta declarada **no** es evidencia de proveedor. El reporte debe
declararlo explícitamente.

**GAP**

Hoy `READY_TO_PUBLISH` puede alcanzarse con respuestas inventadas por el
usuario. Eso viola la regla “nunca READY con efectos externos no verificados”.

**Avance parcial (2026-10-23).** El run de prueba ya devuelve
`effect_verification` con `NONE`, `SIMULATED`, `DECLARED` o `UNVERIFIED`:
distingue pinned, interno simulado y externo sin doble. Siguen abiertos
`SANDBOX`, `PROVIDER`, `AWAITING_EFFECT_VERIFICATION` y el puente certificación
a publicación.

**Archivo responsable**

- `src/platform/workflows/workflow_simulation.py`
- `src/platform/workflows/design_sessions.py`
- `portal/src/components/workflowStudio/ArchitectAskZent.tsx`

**Prueba de aceptación (NUEVA)**

`tests/test_workflow_certification_effects.py`:

1. `capability_call` con respuesta declarada → `AWAITING_EFFECT_VERIFICATION`,
   no `READY_TO_PUBLISH`;
2. mismo flujo con sandbox marcado → `READY_TO_PUBLISH`;
3. nodo financiero → `AWAITING_APPROVAL` hasta aprobación;
4. UI muestra el nivel y no usa la palabra “publicable” para `DECLARED`.

---

### U-03 · Los disparadores no crean instancia durable

**AS-IS**

- Scheduler: `engine.run_due_scheduled_workflows` llama `run_workflow` sin
  `instance_id` (`engine.py:1548-1557`).
- Hook: `run_workflow_from_hook` llama `run_workflow` sin `instance_id`
  (`engine.py:1625-1634`).
- Evento: `dispatch_event_to_workflows` llama `run_workflow` (`events.py:257`).
- Manual: `POST /{id}/run` llama `run_workflow` (`routes/workflows.py:1761`).
- `wait_event`, `loop` y `state_*` exigen instancia
  (`nodes.py:3263-3267`, `3366-3368`, `3455-3457`).
- El planner solo advierte (`planner_verify.py:395-408`); la UI solo muestra un
  aviso (`ArchitectAskZent.tsx:808-816`).

**TARGET**

`graph_requires_instance(graph)` + arranque durable transparente en los cuatro
disparadores. Sin scheduler nuevo.

**GAP**

Un workflow durable publicado falla en el primer schedule/webhook/evento/manual.

**Archivo responsable**

- `src/platform/workflows/engine.py`
- `src/platform/workflows/events.py`
- `src/platform/workflows/instances.py`
- `src/platform/workflows/ir.py`
- `src/api/routes/workflows.py`

**Prueba de aceptación (NUEVA)**

`tests/test_workflow_durable_triggers.py`:

1. schedule con `wait_event` → crea `WorkflowInstance`, estado `WAITING`;
2. hook con `wait_event` → misma instancia, no run suelto;
3. evento con `wait_event` → misma instancia;
4. `/run` con `wait_event` → devuelve `instance_id`;
5. workflow sin nodos durables → sigue creando solo `workflow_run`.

---

### U-04 · Los workflows manuales no tienen gate de publicación

**AS-IS**

`_architect_publication_problems` retorna `[]` si el grafo no tiene
`metadata.architect` (`versions.py:335-337`). `readiness_checks` existe, pero
no se consume en `publish_workflow` para workflows nativos
(`readiness.py:38-155`).

**TARGET**

Gate por fases `report|warn|block` para todo workflow nativo, con
`acknowledge_blockers` explícito. Los workflows legacy/importados conservan su
gate actual.

**GAP**

Un workflow creado en el canvas con `llm` sin agente, KB inexistente o
`marketplace_action` sin instalar se publica y activa.

**Archivo responsable**

- `src/platform/workflows/versions.py`
- `src/platform/workflows/readiness.py`
- `src/api/routes/workflows.py`
- `portal/src/components/workflowStudio/WorkflowVersionsPanel.tsx`

**Prueba de aceptación (NUEVA)**

`tests/test_workflow_native_publish_gate.py`:

1. workflow manual con `llm` sin agente → bloqueado en fase `block`;
2. workflow manual con KB inexistente → bloqueado;
3. workflow manual con `marketplace_action` sin instalación → bloqueado;
4. workflow existente con error puede pausarse pero no reactivarse;
5. fase `report` no bloquea y registra.

---

### U-05 · `llm` sin agente devuelve eco

**AS-IS**

`_exec_llm` hace `if agent_id is None: return await _echo()`; `_echo` devuelve
texto `"[model] prompt"` con `echo=True` y `warning`, sin error
(`nodes.py:2042-2057`). El run queda `succeeded`.

El publish del Architect sí bloquea el caso (`versions.py:349-354`), pero:

- workflows manuales/legacy no pasan por ese gate;
- el canvas solo lo marca como issue local (`workflowGraph.ts:777-785`);
- el runtime sigue devolviendo texto falso.

**TARGET**

En grafos v2, `llm` sin agente devuelve `NodeOutcome(error=...)`. En grafos
legacy v1 se conserva el eco marcado, y readiness lo reporta como error de
migración (ADR-6 del contrato anterior).

**GAP**

Un workflow existente puede seguir produciendo “análisis” inventado.

**Archivo responsable**

- `src/platform/workflows/nodes.py`
- `src/platform/workflows/readiness.py`
- `src/platform/workflows/ir.py` (versión del grafo)

**Prueba de aceptación (NUEVA/EXISTE)**

- `tests/test_workflow_graph.py`: grafo v2 con `llm` sin agente falla;
- `tests/test_workflows.py`: grafo v1 conserva eco marcado;
- `tests/test_workflow_readiness.py`: readiness reporta error.

---

### U-06 · No hay política de rol para bienestar

**AS-IS**

- `ai_governance.apply_guardrails` solo enmascara PII
  (`ai_governance.py:52-68`).
- `trustsafety` gestiona AUP, consentimiento e incidentes, no salidas clínicas.
- `agents` no tiene `role_key`, `role_profile` ni `safety_policy`.
- No hay pre/post guardrail de diagnóstico, prescripción, crisis o derivación.

**TARGET**

`zent.agent.role/v1` + `safety_policy` determinística:

- `wellness_companion`: no diagnóstico, no psicoterapia, no receta, no promesa
  de curación; derivación a humano/servicios de emergencia; disclaimer visible.
- `tutor_minors`: límites de edad, contenido, escalado a adulto.
- `financial_advisor`: no ejecuta pagos, no promete rendimientos.

**GAP**

Si se publica un “acompañante de bienestar” hoy, el LLM puede diagnosticar o
presentarse como terapia. Es un riesgo de seguridad y de producto.

**Archivo responsable**

- `src/platform/ai_governance/ai_governance.py`
- `src/platform/trustsafety/trust_safety.py`
- `src/agents/runtime/agent_runtime.py`
- `src/platform/workflows/architect_validator.py`
- `portal/src/components/agentStudio/AgentPurposeForm.tsx`

**Prueba de aceptación (NUEVA)**

`tests/test_role_safety_wellness.py`:

1. prompt “¿tengo depresión?” → no diagnostica, deriva, muestra disclaimer;
2. prompt de autolesión → `human_handoff`/emergencia, no respuesta clínica;
3. prompt “recétame” → rechazo;
4. publicar rol wellness sin `safety_policy` → bloqueado;
5. respuesta del LLM con diagnóstico → post-guardrail la reemplaza y registra
   `safety_incident`.

---

### U-07 · El Gold real con LLM no genera plan en HEAD

**AS-IS**

Ejecución real en este HEAD:

- `pytest tests/certification/ai/test_real_llm_gold.py` con
  `RAG_CERT_REAL_LLM=1` → **FAILED**.
- `state=BLOCKED`, `planner.invalid_llm_output`,
  `llm_calls=9`, `tool_calls=5`, `total_tokens=107807`, `steps=0`,
  `graph=false`.
- Log: `planner action output invalid`, `content_chars=0`
  (`artifacts/universal-studio-baseline-real-llm.log`).
- Artefacto del run en HEAD: `artifacts/certification/ai/gold-real-llm.c65dbdf.json`
  (el artefacto histórico `gold-real-llm.json` se conserva sin sobrescribir).

**TARGET**

El planner real debe producir un `SemanticPlan` válido para el Gold y para el
dataset de 100 requerimientos, con métricas por modelo/versión.

**GAP**

La creación desde cero con el modelo real sigue bloqueada. No se puede declarar
GO del constructor inteligente.

**Archivo responsable**

- `src/platform/workflows/planner_session.py`
- `src/platform/workflows/architect.py`
- `src/platform/workflows/planner_verify.py`
- `tests/certification/ai/test_real_llm_gold.py`

**Prueba de aceptación (BLOQUEADA POR PROVEEDOR)**

- Gold real en verde con `RAG_CERT_REAL_LLM=1`;
- dataset de 100 casos con ≥90% interpretación y ≥95% selección de capacidades;
- artefacto con modelo, versión, tokens y costo.

---

## 3. P1 — detalle

### U-08 · No existe intake universal

**AS-IS**

- `/agents/new` crea un agente (`AgentBuilder`).
- `/workflows/new/ask` crea un workflow (`AskZent`).
- No hay una entrada que describa “mentor de estudio” y proponga agente(s) +
  workflow(s) + capacidades.

**TARGET**

`SolutionBlueprint` + `studio_solutions` + un intake único. El backend propone
la composición; el usuario revisa; publicar materializa agentes y workflows.

**Archivo responsable**

- `portal/src/pages/WorkflowNew.tsx`
- `portal/src/components/workflowStudio/ArchitectAskZent.tsx`
- `portal/src/pages/AgentBuilder.tsx`
- `src/platform/workflows/design_sessions.py` (o `studio_solutions` nueva)

**Prueba de aceptación (NUEVA)**

`portal/e2e/universal-studio.spec.ts`: describir “mentor de estudio para
universitarios”, obtener blueprint con 1 agente + 1 workflow, editar, guardar
borrador; no publicar.

---

### U-09 · No existe catálogo de roles

**AS-IS**

No hay `role_key`, arquetipos ni plantillas de rol. El Marketplace tiene
`AGENT_TEMPLATE` y `COMPOSITE_PACK`, pero no un catálogo de roles.

**TARGET**

`role_key` + `role_profile` en `agents`; plantillas de rol en el Marketplace
como `COMPOSITE_PACK` (agente + workflow + políticas), sin un tipo de producto
nuevo.

**Archivo responsable**

- `src/infrastructure/db_init/versions/*` (nueva migración aditiva)
- `src/api/routes/agents.py`
- `src/platform/marketplace/factory.py`
- `portal/src/pages/AgentBuilder.tsx`

**Prueba de aceptación (NUEVA)**

`tests/test_agent_roles.py`: crear agente con `role_key=mentor`, persistir
`role_profile`, instalar pack de rol y verificar que crea agente + workflow
draft sin publicar.

---

### U-10 · La versión de agente no gobierna el runtime

**AS-IS**

`AgentVersion` promete que la ejecución resuelve `config_snapshot`
(`entities.py:296-297`), pero `_exec_llm` carga el agente vivo
(`nodes.py:1998-2015`) y `AgentRunRequest.version_id` solo se usa para
usage/deployment (`agent_runtime.py:427-440`, `1847`, `1891`).

**TARGET**

`llm.config.agent_version_id`; resolución de `config_snapshot` en
`AgentRuntime`; fallback a `default_version_id` o a la versión production;
snapshot de versiones en `workflow_versions.agent_versions`.

**Archivo responsable**

- `src/platform/workflows/nodes.py`
- `src/agents/runtime/agent_runtime.py`
- `src/core/domain/entities.py`
- `src/platform/workflows/versions.py`

**Prueba de aceptación (NUEVA)**

`tests/test_workflow_agent_version_pinning.py`: publicar workflow con versión
v1, cambiar prompt del agente a v2, ejecutar workflow → usa v1.

---

### U-11 · Multi-agente sin contrato ni UI

**AS-IS**

Varios nodos `llm` pueden coexistir; el validador advierte `cost.many_agents`
(`architect_validator.py:1039-1046`). No hay contrato de handoff, ni prueba de
dos agentes, ni visualización de qué agente ejecutó cada paso.

**TARGET**

Contrato de nodo `llm` con `agent_id`, `agent_version_id`, `input_contract`,
`output_contract`; edges explícitos; UI muestra agente y versión por nodo;
costo por agente.

**Archivo responsable**

- `src/platform/workflows/nodes.py`
- `src/platform/workflows/architect_compiler.py`
- `portal/src/components/NodeConfigPanel.tsx`
- `portal/src/components/WorkflowRunInspector.tsx`

**Prueba de aceptación (NUEVA)**

`tests/test_workflow_multi_agent.py`: workflow con “calificador” y “auditor”,
handoff por edge, dos agentes distintos, costo separado, sin motor alterno.

---

### U-12 · Agente→workflows sin workspace y solo `llm`

**AS-IS**

`assistants.workflows_for_agent` consulta workflows por organización, sin
`workspace_id`, y solo mira nodos `llm` (`assistants.py:73-108`). No ve
workflows legacy (`steps`) ni agentes invocados por otras vías.

**TARGET**

Consulta workspace-scoped, sobre grafo y legacy adaptado; índice GIN; sin tabla
de autoridad nueva.

**Archivo responsable**

- `src/platform/workflows/assistants.py`
- `src/api/routes/agents.py`
- `portal/src/pages/AssistantDetailPage.tsx`

**Prueba de aceptación (NUEVA)**

`tests/test_agent_workflow_links.py`: agente en 2 workflows de 2 workspaces;
el detalle solo muestra el workspace activo; workflow legacy también aparece.

---

### U-13 · Cobertura de escenarios no es gate

**AS-IS**

`simulate_semantic_plan` marca `partial` solo por `UNVERIFIED`/`BLOCKED`
(`workflow_simulation.py:802`). No exige una rama por outcome, ni error path,
ni escenario crítico.

**TARGET**

`coverage` con branches/outcomes/error_paths/critical_scenarios; si falta
cobertura crítica → `AWAITING_EFFECT_VERIFICATION` o `NEEDS_CONFIGURATION`.

**Archivo responsable**

- `src/platform/workflows/workflow_simulation.py`
- `src/platform/workflows/design_sessions.py`

**Prueba de aceptación (NUEVA)**

`tests/test_workflow_scenario_coverage.py`: workflow con 2 ramas y 1 escenario
→ no `READY_TO_PUBLISH`; con 2 ramas + error path → `READY` si el resto pasa.

---

### U-14 · `ai_decision` llama al JEV real en simulación

**AS-IS**

`_exec_ai_decision` ejecuta `get_decision_engine().judge(...)` incluso con
`rctx.simulate=True` (`nodes.py:2538-2557`). `ai_decision` no está en
`_RISKY_NODE_TYPES` (`workflow_simulation.py:36-46`).

**TARGET**

En simulación, `ai_decision` usa un `pinned` de JEV o un resultado
determinístico declarado; nunca llama al proveedor real.

**Archivo responsable**

- `src/platform/workflows/nodes.py`
- `src/platform/workflows/workflow_simulation.py`

**Prueba de aceptación (NUEVA)**

`tests/test_workflow_simulation.py::test_ai_decision_is_pinned`: monkeypatch que
falla si `judge` se llama; la simulación pasa con respuesta declarada.

---

### U-15 · `for_each` semántico bloqueado y canvas silencioso

**AS-IS**

- El validador rechaza `for_each` (`architect_validator.py:907-919`).
- El compilador lo emite sin `_branch` (`architect_compiler.py:483-492`).
- El handler lee `_branch`; si está vacío, `run_branch([])` devuelve `{}` y el
  nodo reporta `items_processed=len(items)` sin error
  (`nodes.py:2902-2974`).

**TARGET**

Representación de cuerpo en el plan (sub-pasos) o bloqueo explícito también en
canvas; nunca éxito falso.

**Archivo responsable**

- `src/platform/workflows/architect_models.py`
- `src/platform/workflows/architect_compiler.py`
- `src/platform/workflows/architect_validator.py`
- `src/platform/workflows/nodes.py`
- `portal/src/lib/workflowGraph.ts`

**Prueba de aceptación (NUEVA/EXISTE)**

- plan con cuerpo de 2 pasos compila y ejecuta 2 ítems;
- grafo manual con `_branch=[]` → issue/error, no `succeeded`;
- `tests/test_workflow_join_merge.py` sigue verde.

---

### U-16 · Readiness manual usa capacidades sin estado

**AS-IS**

`readiness.workflow_readiness` llama `load_capabilities`
(`readiness.py:179`), que lista acciones instaladas sin mirar
`enabled_actions`, `credential_ref` ni `purpose` (`plan_compiler.py:95-177`).
El runtime sí las exige (`marketplace/runtime.py:1253-1283`).

**TARGET**

Readiness y publish consumen `build_capability_snapshot` (una autoridad).

**Archivo responsable**

- `src/platform/workflows/readiness.py`
- `src/platform/workflows/plan_compiler.py`
- `src/platform/workflows/capability_registry.py`

**Prueba de aceptación (NUEVA)**

`tests/test_workflow_readiness_capabilities.py`: acción deshabilitada/sin
credenciales/purpose → readiness `error`; no se publica.

---

### U-17 · Publish de agente advisory

**AS-IS**

`AgentPublishSection` muestra readiness (`AgentPublishSection.tsx:128`) pero el
botón “Go Live” solo se deshabilita por `deployBusy` o `!id`
(`AgentPublishSection.tsx:256`). No exige score mínimo ni evaluación.

**TARGET**

Gate de producción: readiness mínimo, versión `ready`, evaluación aprobada,
sin tools prohibidas; `warning` exige confirmación.

**Archivo responsable**

- `portal/src/components/agentStudio/AgentPublishSection.tsx`
- `src/platform/agents/readiness.py`
- `src/api/routes/agents.py`

**Prueba de aceptación (NUEVA)**

`tests/test_agent_publish_gate.py`: agente sin prompt/modelo/eval → deploy
production bloqueado; con readiness completo → permitido.

---

### U-18 · Sin presupuesto/concurrencia/rate limit por workflow

**AS-IS**

- Presupuesto del planner (`config.py:196-208`) y del agente
  (`agent_runtime.py`), no del run de workflow.
- `for_each` limita 16 por nodo (`nodes.py:2918`), no runs concurrentes.
- Rate limit de API/deployment, no por workflow.

**TARGET**

`zent.workflow.runtime_budget/v1` aplicado en `run_workflow` y
`start_workflow_instance`; `BUDGET_EXCEEDED`/`RATE_LIMITED`; uso agregado en
`usage_events`.

**Archivo responsable**

- `src/platform/workflows/engine.py`
- `src/platform/workflows/instances.py`
- `src/platform/workflows/runtime.py`
- `src/platform/metering` / `usage_events`

**Prueba de aceptación (NUEVA)**

`tests/test_workflow_runtime_budget.py`: costo/tokens/tiempo excedido → falla
controlada; 6 runs con límite 5 → sexto `RATE_LIMITED`; no se duplica ledger.

---

### U-19 · Service identity estática

**AS-IS**

`SYSTEM_NODE_PERMS` es un conjunto fijo para scheduler/hook/evento/reanudación
(`engine.py:278-303`). No hay identidad de servicio por workflow ni permisos
efectivos por versión.

**TARGET**

Service identity por workflow (org, workspace, scopes, flags) resuelta al
publicar; el run registra `service_identity_id`; los permisos no se amplían por
un trigger.

**Archivo responsable**

- `src/platform/workflows/engine.py`
- `src/platform/workflows/versions.py`
- `src/platform/rbac`

**Prueba de aceptación (NUEVA)**

`tests/test_workflow_service_identity.py`: workflow publicado con scopes A no
puede ejecutar capability B; scheduler usa la identidad, no `SYSTEM_NODE_PERMS`.

---

### U-20 · PII en trazas y respuestas de agente

**AS-IS**

- `workflow_run_steps` persiste outputs; no hay `mask_pii` en
  `context_store`/`engine`/`runtime`.
- `ai_governance.apply_guardrails` y `modelhealth.protect_answer` solo se usan
  en `public_query.py:348-355`; `AgentRuntime` no los aplica a la respuesta de
  un workflow.

**TARGET**

Máscara determinística antes de persistir outputs/eventos y antes de devolver
la respuesta de un agente en un workflow; configurable por org; los secretos
nunca se persisten.

**Archivo responsable**

- `src/platform/workflows/context_store.py`
- `src/platform/workflows/engine.py`
- `src/agents/runtime/agent_runtime.py`
- `src/platform/ai_governance/ai_governance.py`

**Prueba de aceptación (NUEVA)**

`tests/test_workflow_trace_pii.py`: email/teléfono/documento en output → se
persiste `[EMAIL:***]`, etc.; el valor original no está en DB; la respuesta del
agente en workflow también sale enmascarada.

---

### U-21 · Auditoría de publicación

**AS-IS**

`engine._audit_run_access` audita accesos cross-tenant. No hay audit log
dedicado para `publish`, `activate`, `simulate` o `patch-apply`. Las revisiones
de diseño son trazables, pero no son un audit log de seguridad.

**TARGET**

`audit_logs` con `workflow.publish`, `workflow.activate`, `workflow.simulate`,
`agent.publish`, `studio.solution.publish`, evidencia y actor.

**Archivo responsable**

- `src/platform/workflows/versions.py`
- `src/api/routes/workflows.py`
- `src/platform/audit/service.py`

**Prueba de aceptación (NUEVA)**

`tests/test_workflow_audit.py`: publicar deja fila con actor, org, workflow,
versión, certification_id y decisión.

---

### U-22 · Instancias sin filtro de workspace

**AS-IS**

`instances.list_instances` filtra solo por `organization_id`
(`instances.py:300-341`). La ruta no pasa workspace
(`routes/workflows.py:1477-1499`).

**TARGET**

Filtro workspace-scoped, igual que `list_workflows`
(`engine.py:774-776`).

**Archivo responsable**

- `src/platform/workflows/instances.py`
- `src/api/routes/workflows.py`

**Prueba de aceptación (NUEVA)**

`tests/test_workflow_workspace_isolation.py`: instancia de workspace B no
aparece en listado de A; detalle/signal también 404.

---

### U-23 · RBAC por capability incompleto

**AS-IS**

`_CAPABILITY_PERMISSION` solo mapea `calls_external`, `calls_agent`,
`uses_integration` (`nodes.py:43-47`). `notify` (`sends_notification`),
`business_result` (`writes_db`), `kb_query`/`query_business_data` (`reads_db`)
no exigen permiso de nodo. `notifications:send`, `business_results:write`,
`data:read` no existen.

**TARGET**

Mapa por capability con permisos dedicados o decisión de producto documentada;
flag y auditoría para la transición.

**Archivo responsable**

- `src/platform/workflows/nodes.py`
- `src/infrastructure/db_init/26-platform-rbac.sql` / migración
- `src/platform/rbac/policy.py`

**Prueba de aceptación (NUEVA)**

`tests/test_workflow_capability_rbac.py`: usuario con `workflows:run` pero sin
`notifications:send` no puede ejecutar `notify`; admin sí.

---

### U-24 · Sin consola operativa ni inbox de aprobaciones

**AS-IS**

- `WorkflowRunInspector` muestra una aprobación por run
  (`WorkflowRunInspector.tsx:322-324`).
- No hay página que consuma `/workflows/instances` ni una bandeja global.

**TARGET**

`StudioOperations` read-only: runs, instancias, aprobaciones, costo, señales,
filtros por workspace/rol.

**Archivo responsable**

- `portal/src/pages` (nueva página)
- `src/api/routes/workflows.py`
- `src/platform/workflows/engine.py` / `instances.py`

**Prueba de aceptación (NUEVA)**

`portal/e2e/studio-operations.spec.ts`: ver instancia WAITING, enviar señal,
aprobar run, ver costo; sin mutar definiciones.

---

### U-25 · Studio partido en tres superficies

**AS-IS**

- `AgentStudio` (develop/test/publish).
- `WorkflowStudio` (canvas/test/versions/publish).
- `MarketplacePage` (productos).
- No hay un “empezar con un rol” que conecte las tres.

**TARGET**

Un shell universal con etapas `Diseñar → Probar → Certificar → Publicar →
Operar`, reutilizando los componentes existentes.

**Archivo responsable**

- `portal/src/pages/AgentStudio.tsx`
- `portal/src/pages/WorkflowStudio.tsx`
- `portal/src/pages/marketplace/MarketplacePage.tsx`
- `portal/src/lib/nav.ts`

**Prueba de aceptación (NUEVA)**

`portal/e2e/universal-studio-shell.spec.ts`: un solo flujo desde rol hasta
operación; sin duplicar canvas ni marketplace.

---

### U-26 · Suite de certificación no verde en HEAD

**AS-IS**

`pytest tests/certification/workflows` se ejecutó en este entorno y terminó en
**timeout ambiental** tras 7 tests. No se declara verde. `test_tenant_isolation.py`
se ejecutó aparte: **5 passed** en 527.95s. `test_signals.py` también agotó
timeout. Ver [`06-test-evidence.md`](06-test-evidence.md).

**TARGET**

Suite completa verde, con tiempos controlados y evidencia por escenario.

**Archivo responsable**

- `tests/certification/workflows`
- `tests/certification/restart`
- `tests/certification/ai`

**Prueba de aceptación (BLOQUEADA POR ENTORNO)**

Ejecutar la suite completa con presupuesto de tiempo y sin contención; guardar
JUnit + artefacto.

---

## 4. P2 — detalle

| ID | AS-IS | TARGET | Archivo | Prueba |
|---|---|---|---|---|
| U-27 | Canvas llama `/api/v1/integrations/installs` y `/workflows/marketplace/context` (`WorkflowCanvasEditor.tsx:119-133`) | Canvas consume `/api/v1/products` + assets de instalación | `WorkflowCanvasEditor.tsx`, `marketplace_factory.py` | `NodeLibrary.test.tsx` + e2e |
| U-28 | `/marketplace` (ecosystem), `/products` (storefront), `/integrations` (exec/admin) sin contrato de superficie | Documentar `/products` como único storefront; legacy read-only; integrations como ejecución | `ecosystem.py:14`, `marketplace_factory.py:19`, `marketplace.py:18` | test de rutas + doc |
| U-29 | `compile_semantic_plan(..., intent=...)` no usa `intent` (`architect_compiler.py:561`) | Usar intent para trigger/costos o retirarlo | `architect_compiler.py` | unit |
| U-30 | `_trigger_config_for_cost` convierte daily a `{daily: time}`; `cost_estimate` no entiende weekly (`architect.py:470-482`, `capabilities.py:391-399`) | Costo mensual correcto por schedule | `architect.py`, `capabilities.py` | unit |
| U-31 | `NODE_NEXT_STEPS` sin `loop`; 9 nodos sin schema | Completar catálogo | `node_catalog.py`, `parameters.py` | snapshot test |
| U-32 | Métricas del Architect en memoria; `wait` cae a preview `then` (state/stop ya están mapeados) | Métricas operables y preview preciso | `architect_metrics.py`, `architect.py:353-382` | unit |

## 5. Trazabilidad a fases

| Fase | Findings |
|---|---|
| 01 | baseline, flags, contratos, esta matriz |
| 02 | U-09, U-10, U-12 |
| 03 | U-08, U-11, U-25 |
| 04 | U-15, U-16, U-27, U-28, U-29, U-30 |
| 05 | U-03, U-05, U-18, U-19, U-22 |
| 06 | U-01, U-02, U-04, U-13, U-14 |
| 07 | U-06, U-17, U-20, U-21, U-23 |
| 08 | U-24, U-25, U-31, U-32 |
| 09 | U-07, U-26, certificación final |
