# 01 — Auditoría AS-IS verificada (HEAD `c65dbdf`)

> Evidencia obtenida por lectura directa del árbol, enumeración ejecutable del
> registry/catálogo y ejecución de suites. No se usó el informe anterior como
> sustituto de la lectura: cada afirmación se contrastó con el código actual.

## 1. Entorno y estado del repositorio

| Dato | Valor | Cómo se verificó |
|---|---|---|
| HEAD | `c65dbdf729327eaf54fd74a9326cf5ae328dc0be` | `git rev-parse HEAD` |
| Rama | `master` (sincronizada con `origin/master`) | `git status -b` |
| Árbol de trabajo | limpio al iniciar | `git status --porcelain` |
| Archivos versionados | 2728 | `git ls-files` |
| Archivos de test Python | 476 | `Get-ChildItem tests -Recurse -Filter test_*.py` |
| Python | 3.13.7 | `.venv/Scripts/python.exe --version` |
| Node / npm | 22.22.1 / 11.17.0 | `node --version`, `npm --version` |
| Servicios locales | Postgres, Redis, Qdrant, API, portal arriba | `docker ps` |
| Migración más reciente | `162_conversation_guard.py` | `src/infrastructure/db_init/versions` |

Commits posteriores al SHA auditado por el informe anterior (`a826d8c`):

```
c65dbdf feat(workflows): add durable conversation guard and explicit AI fallback
b06a489 fix(workflows): preserve AI decision output when stopping on low confidence
57c4415 fix(workflows): retry transient JEV and explain failed AI decisions
0055d7d fix(workflows): give AI decisions upstream context and live JEV in preview
fdc340c docs(certification): refresh evidence after planner and sandbox hardening
```

Consecuencia: el informe `workflow-ai-go-no-go.md` **no describe el HEAD**. Hay
que releer los bloqueos, no asumir que siguen igual.

## 2. Inventario de superficies

### 2.1 Motor, IR y durabilidad

| Superficie | Estado | Evidencia |
|---|---|---|
| `WorkflowGraph` v2 + `validate_graph` | Implementado | `src/platform/workflows/ir.py`; validación usada por `engine.create_workflow` y `architect._compile_validated` |
| `execute_graph` | Implementado | `src/platform/workflows/runtime.py:206` |
| `run_workflow` (full/partial/simulate/resume) | Implementado | `src/platform/workflows/engine.py:306-755` |
| `WorkflowInstance` + snapshot congelado | Implementado | `src/platform/workflows/instances.py:484-630` |
| WAIT / RESUME / señales / timeout | Implementado | `instances.py:1046-1171`, `1323-1401`, `1778-1900`; tests de certificación |
| LOOP durable | Implementado | `nodes.py:3366-3368`; requiere instancia |
| Estado durable (`state_*`) | Implementado | `nodes.py:3455-3457`; requiere instancia |
| Scheduler único | Implementado | `engine.py:1577-1595`; `src/api/main.py:165` |
| Bus de eventos | Implementado | `src/platform/workflows/events.py`; consumer en `src/api/main.py:166` |
| Watchers | Implementado | `src/platform/workflows/watchers.py`; loop propio en `main.py:167` |

### 2.2 Tipos de nodo, pasos semánticos y schemas

Enumeración ejecutada con el intérprete del proyecto:

| Superficie | Conteo | Evidencia |
|---|---|---|
| Tipos de nodo ejecutables | **30** | `registry.all()` → `nodes.py` |
| Tipos de paso del `SemanticPlan` | **22** | `architect_models.py:15-38` |
| Schemas de negocio | **21** | `parameters.NODE_BUSINESS_SCHEMAS` |
| Nodos sin schema de negocio | **9** | `capability_call`, `end`, `loop`, `state_*` (5), `wait_event` |
| `NODE_NEXT_STEPS` sin `loop` | 1 brecha | `node_catalog.NODE_NEXT_STEPS` no contiene `loop` |

Los 30 nodos:

```
ai_decision, llm, business_node, stop, human_approval, wait_event, end, loop,
query_business_data, kb_query, marketplace_action, capability_call, api_call,
state_append, state_get, state_merge, state_remove, state_set, filter,
set_variable, conversation_guard, for_each, merge, condition, join, notify,
business_result, trigger_schedule, trigger_webhook, trigger_event
```

Los 22 pasos semánticos:

```
trigger_conversation, trigger_event, trigger_schedule, trigger_manual,
business_query, knowledge_query, capability_call, agent_analysis, decision,
filter, for_each, join, merge, human_approval, wait, state, loop,
compensation, notify, integration_action, business_result, stop
```

**Lectura:** el runtime sigue siendo más capaz que el planner, pero la brecha
bajó de 7 nodos a **1 nodo bloqueado explícitamente** (`for_each`) y varios
nodos sin formulario de negocio. El compilador emite `for_each` sin `_branch`
(`architect_compiler.py:483-492`) y el validador lo rechaza
(`architect_validator.py:907-919`): es código alcanzable solo por planes
antiguos o por el canvas.

### 2.3 Agentes

| Superficie | Estado | Evidencia |
|---|---|---|
| CRUD de agentes | Implementado | `src/api/routes/agents.py` |
| Versiones inmutables de agente | Implementado en dominio y repositorio | `src/core/domain/entities.py:291-308`; `relational_db.py:2074-2170` |
| Deployments por entorno | Implementado | `src/platform/deployments/deployments.py`; rutas de agentes |
| Readiness de agente 0–100 | Implementado, **advisory** | `src/platform/agents/readiness.py`; UI `AgentPublishSection.tsx:128` |
| Permisos delegados del agente | Implementado | `src/api/routes/agents.py:308-341`; `agent_runtime.py:2000` |
| Agente como capacidad del planner | Implementado | `capability_registry.py:1575-1665` |
| Rol / arquetipo / política de rol | **No implementado** | No existe `role`, `archetype` ni `role_policy` en agentes |
| Catálogo de roles (vendedor, mentor, tutor, asesor, auditor, bienestar) | **No implementado** | Búsqueda en `src/` y `portal/src/` sin resultados |
| Versión de agente usada por el workflow | **No implementado** | `nodes.py:1998` carga el agente mutable; `AgentRunRequest.version_id` solo se propaga a usage, no resuelve `config_snapshot` |
| Agente en múltiples workflows | **Parcial** | `assistants.workflows_for_agent` escanea grafos (`assistants.py:73-108`), solo nodos `llm`, sin workspace |
| Workflow con múltiples agentes | **Parcial** | Es posible con varios nodos `llm`; no hay contrato de handoff ni prueba dedicada |

La promesa del dominio (`AgentVersion`: "la ejecución resuelve la configuración
desde aquí", `entities.py:296-297`) **no se cumple en el runtime de workflows**:
`_exec_llm` obtiene `get_agent_repo().get_agent(...)` y ejecuta el agente vivo
(`nodes.py:1998-2015`). Cambiar el prompt del agente cambia el comportamiento de
un workflow ya publicado.

### 2.4 Capacidades, bindings y recursos

| Superficie | Estado | Evidencia |
|---|---|---|
| Capability Registry `zent.capability/v1` | Implementado | `capability_registry.py:1-65` |
| Snapshot con hash y cache | Implementado | `capability_registry.py`; `build_capability_snapshot` |
| Bindings por tenant | Implementado | `bindings.py:28-42`, `194-369` |
| Business Resource Resolver | Implementado | `business_resources.py`; doc `ai-workflow-studio/13` |
| Contratos commerce/pagos/conversación | Implementado | `src/platform/commerce/contracts.py`; `conversation_capability.py` |
| Disponibilidad con estado real | Implementado en canvas/registry | `capabilities._installed_status`; `capability_registry` |
| Disponibilidad usada por readiness | **Parcial** | `readiness.py` usa `plan_compiler.load_capabilities`, que ignora enabled/credentials/purpose (`plan_compiler.py:95-177`) |
| Autoridad única para el planner | Implementada | `architect_discovery` consume el snapshot |
| Autoridad única para publish/readiness | **Parcial** | publish de Architect usa snapshot; workflows manuales usan `load_capabilities` |

### 2.5 Marketplace

| Superficie | Estado | Evidencia |
|---|---|---|
| Storefront canónico `/api/v1/products` | Implementado | `src/api/routes/marketplace_factory.py:19`; portal `MarketplacePage.tsx:70-72` |
| Productos unificados (integración, workflow, agente, packs) | Implementado | `src/platform/marketplace/products.py:1-30` |
| Instalación con dependencias tipadas | Implementado | `factory.install_product`; certificación `test_marketplace_dependency_resolution.py` |
| Agente desde `AGENT_TEMPLATE` | Implementado | `factory.py:596-642` |
| Workflow desde `WORKFLOW_TEMPLATE` | Implementado | `factory.py`; `capabilities.install_inline` |
| Marketplace de ecosistema `/api/v1/marketplace` | **Legacy expuesto** | `src/api/routes/ecosystem.py:14` |
| Integraciones `/api/v1/integrations` | **Superficie de ejecución/admin** | `src/api/routes/marketplace.py:18` |
| Canvas usa catálogo de integraciones, no `/products` | **Parcial** | `WorkflowCanvasEditor.tsx:119-133` llama `/api/v1/integrations/installs` y `/workflows/marketplace/context` |
| Tienda por módulo | No se detectó una tienda nueva; sí tres superficies con propósitos solapados | ver §3 |

### 2.6 Simulación, certificación y publicación

| Superficie | Estado | Evidencia |
|---|---|---|
| Simulación ejecutable aislada | Implementado | `workflow_simulation.py`; `execute_graph(simulate=True)` |
| Escenarios WAIT/LOOP/timeout/dup | Implementado | `tests/test_workflow_simulation.py` (16 tests) |
| Certificación `zent.workflow.certification/v1` | Implementado | `workflow_simulation.py:34`, `747-868` |
| Persistencia de certificación en sesión | Implementado | `design_sessions.save_design_simulation` |
| Gate de publicación que consume certificación | **No implementado** | `versions.publish_workflow` no lee `workflow_design_revisions` ni `certification` |
| Simulación de `ai_decision` sin LLM real | **No implementado** | `_exec_ai_decision` llama `get_decision_engine().judge(...)` aun con `simulate=True` (`nodes.py:2538-2557`) |
| Cobertura de ramas/escenarios críticos como gate | **No implementado** | `simulate_semantic_plan` no exige cobertura; solo marca `partial` por UNVERIFIED/BLOCKED (`workflow_simulation.py:802`) |
| Niveles de verificación de efectos (declarado/sandbox/proveedor) | **No implementado** | El reporte no distingue pins declarados de proveedor real |
| Publicación de workflows nativos | **Parcial** | Gate solo si `metadata.architect` (`versions.py:336-337`) |
| Publicación con `confirm_architect_draft` | Implementado en API | `routes/workflows.py:2040-2065`; la UI no envía ese campo (`WorkflowVersionsPanel.tsx:110-125`) |

### 2.7 Operación

| Superficie | Estado | Evidencia |
|---|---|---|
| Runs y detalle | Implementado | `engine.run_detail`; `WorkflowRunInspector` |
| Instancias durables (listado API) | Implementado | `routes/workflows.py:1477-1499`; `instances.list_instances` |
| Timeline de instancia | Implementado | `InstanceTimeline.tsx`; `routes:1515-1525` |
| Aprobaciones por run | Implementado | `WorkflowApprovalPanel`; `engine.list_approvals` |
| Bandeja global de aprobaciones | **No implementado** | No hay página/ruta de inbox |
| Consola global de instancias | **No implementado** | No hay página que consuma `/workflows/instances` |
| Costo por workflow/agente | **Parcial** | `usage_events` registra `workflow_run` con `cost_ms`; no hay agregado por workflow |
| Presupuesto por run de workflow | **No implementado** | Solo budgets del planner (`config.py:196-208`) y del agente (`agent_runtime.py`) |
| Límite de concurrencia por workflow | **No implementado** | `for_each` limita 16 por nodo; no hay cuota de runs |
| Rate limit por workflow | **No implementado** | Rate limit de API/deployment, no por workflow |
| Service identity por workflow | **Parcial** | `SYSTEM_NODE_PERMS` estático (`engine.py:278-286`); no hay identidad de servicio por workflow |

### 2.8 Seguridad y gobierno

| Superficie | Estado | Evidencia |
|---|---|---|
| RBAC por endpoint | Implementado | `require_permission` en rutas |
| RBAC por capability de nodo | **Parcial** | `_CAPABILITY_PERMISSION` solo cubre `external_actions:execute`, `agents:execute`, `integrations:use` (`nodes.py:43-47`) |
| Permisos `notifications:send`, `business_results:write`, `data:read` | **No existen** | Búsqueda en `src/` sin coincidencias |
| SecretStore | Implementado | `marketplace/runtime.py:492-580`; `bindings.py:637-656` |
| Auditoría de acceso cross-tenant | Implementado | `engine._audit_run_access` |
| Auditoría de publish/activate/simulate | **Parcial** | Revisiones de diseño persistidas; no hay audit log dedicado de publicación |
| PII masking en respuestas de agente | **Parcial** | `apply_guardrails`/`protect_answer` solo se usan en `public_query.py:348-355`; `AgentRuntime` no los aplica |
| PII masking en trazas de workflow | **No implementado** | `workflow_run_steps` guarda outputs sin máscara; búsqueda de `mask`, `redact` y `pii` en `src/platform/workflows` solo encuentra metadata de catálogo |
| Política de rol de bienestar | **No implementado** | No hay `role_policy`, `disallowed_claims`, `escalation` ni `disclaimer` por agente |
| Guardrails de diagnóstico automático | **No implementado** | `ai_governance` solo hace PII; `trustsafety` gestiona incidentes/AUP, no salidas clínicas |

## 3. Recorridos actuales (UI → runtime)

### 3.1 Crear un agente

```
portal /agents/new
  → AgentBuilder / useAgentStudio
  → POST /api/v1/agents
  → agents (status draft, is_active false)
  → AgentStudio: develop → test → publish
  → readiness score (advisory)
  → deploy_to_environment (versión ready)
```

El agente se crea desde un propósito libre. **No hay elección de rol,
arquetipo, política de seguridad ni plantilla de rol.** La única plantilla de
agente viene del Marketplace (`AGENT_TEMPLATE`), que crea un agente draft
(`factory.py:596-642`).

### 3.2 Crear un workflow con IA

```
portal /workflows/new/ask
  → AskZent
  → fetchArchitectConfig()
  → flag RAG_WORKFLOW_ARCHITECT_ENABLED
      true  → ArchitectAskZent
      false → AskZentLegacy (Copilot)
  → POST /api/v1/workflows/architect/sessions
  → planner agéntico / SemanticPlan
  → validate_semantic_plan
  → compile_semantic_plan + validate_graph
  → simulate_semantic_plan (opcional)
  → save_architect_draft (workflow draft)
  → WorkflowStudio (canvas)
  → WorkflowVersionsPanel → POST /{id}/publish
```

El camino canónico ya es el Architect (`AskZent.tsx:53-55`). El Copilot legacy
sigue disponible como rollback.

### 3.3 Publicar un workflow

```
WorkflowVersionsPanel
  → POST /api/v1/workflows/{id}/publish
  → require_permission("workflows:activate")
  → publication_blockers (solo packages importados)
  → si metadata.architect:
        _architect_publication_problems:
          validate_graph
          llm sin agente
          snapshot de capacidades
          readiness_checks
  → create_version(status=production)
  → set_workflow_status(active)
```

**No consulta** la certificación de simulación de la sesión de diseño, ni el
`plan_hash`, ni el `capability_snapshot_hash` de la revisión. Un workflow manual
sin metadata de Architect no pasa por ningún gate de readiness.

### 3.4 Ejecutar

| Disparador | Código | ¿Crea instancia durable? |
|---|---|---|
| Scheduler | `engine.run_due_scheduled_workflows` → `run_workflow` sin `instance_id` (`engine.py:1548-1557`) | **No** |
| Webhook | `run_workflow_from_hook` → `run_workflow` sin `instance_id` (`engine.py:1625-1634`) | **No** |
| Evento | `dispatch_event_to_workflows` → `run_workflow` (`events.py:257`) | **No** |
| Manual `/run` | `routes/workflows.py:1761` → `run_workflow` | **No** |
| Instancia | `POST /{workflow_id}/instances` → `start_workflow_instance` | **Sí** |

Un grafo con `wait_event`, `loop` o `state_*` publicado y activo falla en el
primer disparo normal con "requiere una instancia durable"
(`nodes.py:3263-3267`, `3366-3368`, `3455-3457`). El planner lo advierte
(`planner_verify.py:395-408`) y la UI lo muestra
(`ArchitectAskZent.tsx:808-816`), pero **no bloquea la publicación**.

### 3.5 Simular y certificar

```
ArchitectAskZent (modo Avanzado)
  → POST /api/v1/workflows/architect/sessions/{id}/simulate
  → simulate_semantic_plan(plan, capabilities, scenarios)
  → WorkflowSimulationRunner
  → execute_graph(simulate=True, pinned=...)
  → CertificationReport
  → save_design_simulation (revisión)
```

La certificación queda en la sesión. El borrador guardado **no** la lleva. El
gate de publicación **no** la busca.

## 4. Bifurcaciones y redundancias verificadas

| # | Bifurcación | Estado | Riesgo |
|---|---|---|---|
| B1 | Architect vs Copilot legacy | Coexisten; Architect es canónico por flag | Deuda de dos planners; el legacy sigue expuesto |
| B2 | `capability_registry` vs `plan_compiler.load_capabilities` | Coexisten | Readiness/publish manual usan la lectura pobre |
| B3 | `/products` vs `/marketplace` vs `/integrations` | Coexisten con propósitos solapados | Descubrimiento dividido; canvas no ve productos |
| B4 | Simulación de sesión vs dry-run del canvas | Coexisten | Una certifica, la otra solo prueba |
| B5 | Agente vivo vs `AgentVersion` | La versión no gobierna el runtime de workflow | Cambio silencioso de comportamiento publicado |
| B6 | Run normal vs `WorkflowInstance` | Desconectados para disparadores | Fallo durable en producción |
| B7 | Readiness de agente (advisory) vs publish de agente | No hay gate duro | Agente sin evaluación puede desplegarse |
| B8 | Auditoría de acceso vs auditoría de publicación | Solo la primera es explícita | Sin rastro formal de quién publicó qué y con qué evidencia |

## 5. Pruebas existentes relevantes

| Área | Archivos | Cobertura |
|---|---|---|
| Architect / semantic | `test_workflow_architect.py`, `test_workflow_semantic_v2.py`, `test_workflow_architect_capability_call.py` | plan, compile, validator, capability_call, WAIT/LOOP |
| Planner agéntico | `test_workflow_planner_agentic.py` | tools, presupuesto, MATCH/VERIFY/REPAIR |
| Simulación | `test_workflow_simulation.py` | 16 escenarios |
| Sesiones | `test_workflow_design_sessions.py` | persistencia, conflicto, patch, restore, simulate, draft |
| Durabilidad | `test_workflow_durable_instances.py`, `tests/certification/workflows` | WAIT/RESUME, señales, reinicio, tenant |
| Marketplace | `test_marketplace.py`, `test_unified_marketplace.py`, `test_marketplace_factory.py`, `test_marketplace_dependency_resolution.py` | catálogo, instalación, dependencias |
| Agentes | `test_agent_api.py`, `test_agent_versions.py`, `test_agent_readiness.py`, `test_agent_budget_closure.py` | CRUD, versiones, readiness, budget |
| Portal | `ArchitectAskZent.test.tsx`, `WorkflowVersionsPanel` (sin test propio), `WorkflowTestPanel.test.tsx`, `MarketplacePage.test.tsx` | UI de diseño, test, marketplace |

**Ausencias verificadas:**

- no hay test que publique un workflow con `wait_event` desde schedule/webhook;
- no hay test que demuestre que `publish_workflow` rechaza una certificación
  `UNVERIFIED` o stale;
- no hay test de dos agentes en un mismo workflow;
- no hay test de un agente en dos workflows con versiones distintas;
- no hay test de aislamiento por workspace en `/workflows/instances`;
- no hay test de política de rol de bienestar;
- no hay test de PII masking en `workflow_run_steps`;
- no hay test de presupuesto/concurrencia por workflow.

## 6. Conclusión AS-IS

El sistema tiene **piezas de calidad** para planificar, compilar, simular y
ejecutar workflows durables. La universalización no requiere un motor nuevo:
requiere **cerrar los contratos que hoy están desconectados**:

1. rol → agente → workflow;
2. certificación → publicación;
3. grafo durable → instancia;
4. versión de agente → ejecución;
5. capability registry → readiness/publish;
6. marketplace global → canvas;
7. políticas de rol → runtime;
8. operación → observabilidad y gobierno.

Los detalles de brecha y severidad están en
[`03-gap-matrix.md`](03-gap-matrix.md).
