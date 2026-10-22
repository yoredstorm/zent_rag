# 02 — Arquitectura TARGET del Universal Agent & Workflow Studio

> Principio rector: **el rol describe; el agente razona; el workflow orquesta;
> el backend valida, autoriza, compila, simula y ejecuta.**
>
> No se crea un segundo motor, scheduler, bus, catálogo de integraciones ni
> tienda por módulo. Se extienden los contratos existentes.

## 1. Modelo universal

```
Rol / proceso (lenguaje natural)
        │
        ▼
SolutionBlueprint (artefacto de diseño, no runtime)
        │  compone 1..N
        ├──────────────► AgentProfile (rol + política + conocimiento + tools)
        │                        │
        │                        ▼
        │                 AgentVersion (snapshot inmutable)
        │                        │
        └──────────────► WorkflowGraph v2 (1..N workflows)
                                 │  usa 1..N agentes
                                 ▼
                    WorkflowInstance / run_workflow
                                 │
                                 ▼
                    Capability Registry + bindings + Marketplace
```

### 1.1 Entidades

| Entidad | Naturaleza | Autoridad | No es |
|---|---|---|---|
| `AgentProfile` | Extensión de `agents` | `agents` + `agent_versions` | Un runtime nuevo |
| `AgentVersion` | Snapshot inmutable | `agent_versions` | Una copia del workflow |
| `WorkflowGraph` v2 | IR ejecutable | `workflows.graph` | Un plan semántico |
| `WorkflowInstance` | Estado durable | `workflow_instances.definition_snapshot` | Una definición editable |
| `SolutionBlueprint` | Artefacto de diseño | `studio_solutions.blueprint` | Un workflow ejecutable |
| `CapabilityDescriptor` | Proyección de capacidades | `capability_registry` | Un catálogo paralelo |
| `Product` | Oferta del marketplace | `marketplace_products` | Una instalación |
| `PublicationEvidence` | Evidencia de gate | `workflow_versions` + `audit_logs` | Una promesa del LLM |

### 1.2 Regla de composición

- Un **agente puede participar en N workflows**: se referencia por `agent_id` +
  `agent_version_id` en cada nodo `llm`.
- Un **workflow puede usar N agentes**: varios nodos `llm` con contratos de
  entrada/salida y edges explícitos.
- Un **rol puede tener N agentes** (p. ej. vendedor senior y vendedor de
  soporte) y **N workflows** (calificación, cotización, seguimiento).
- El `SolutionBlueprint` no se ejecuta. Al publicar, el backend materializa
  agentes y workflows reales y guarda las referencias.

## 2. Límites de responsabilidad

| Etapa | Dueño | Entrada | Salida | Invariante |
|---|---|---|---|---|
| Intake universal | `studio_solutions` + `architect` | texto de rol/proceso | `SolutionBlueprint` propuesto | El texto es untrusted; no concede permisos |
| Descubrimiento | `capability_registry` + `business_resources` | org/workspace/actor | snapshot de capacidades y recursos | Una sola autoridad; sin secretos |
| Diseño de agente | `agents` + `agent_versions` | rol, propósito, tools, KB, política | `AgentProfile` + `AgentVersion` draft | Sin auto-deploy |
| Diseño de workflow | `architect` + `design_sessions` | blueprint + snapshot | `SemanticPlan` → `WorkflowGraph` | El LLM no escribe el grafo final |
| Validación | `architect_validator` + `readiness` | plan/grafo + snapshot | issues, requirements, blockers | `error` bloquea |
| Compilación | `architect_compiler` | plan válido | `WorkflowGraph` v2 | Siempre pasa `validate_graph` |
| Simulación | `workflow_simulation` | grafo + escenarios | `CertificationReport` | Cero efectos externos no declarados |
| Publicación | `versions.publish_workflow` | grafo + evidencia | versión production + audit | No publica sin evidencia vigente |
| Ejecución | `engine.run_workflow` / `instances` | grafo congelado | run/instancia | Un solo motor |
| Operación | `studio_operations` (read model) | runs, instancias, approvals, usage | vista operativa | Solo lectura; workspace-scoped |

## 3. Reutilización obligatoria

| Contrato existente | Uso en Universal Studio | No se toca |
|---|---|---|
| `WorkflowGraph` v2 / `validate_graph` | IR único | Semántica de nodos |
| `execute_graph` / `run_workflow` | Ejecución única | Firma y semántica |
| `WorkflowInstance` / señales / sweep | Durabilidad | Snapshot congelado |
| `capability_registry` | Autoridad de capacidades | Contrato `zent.capability/v1` |
| `bindings.execute_binding` | Ejecución de capacidades | Contratos de provider |
| `marketplace.runtime.execute_action` | Acciones externas | Gobierno de credenciales/purpose |
| `marketplace.factory.install_product` | Instalación de packs | Dependencias tipadas |
| `business_resources` | Resolución de recursos | Read-only |
| `workflow_simulation` | Certificación | Mismo `execute_graph` |
| `design_sessions` | Persistencia de diseño | Revisiones inmutables |
| `readiness` | Checklist de negocio | Se amplía, no se reemplaza |
| `rbac.policy` | Permisos efectivos | No se crea RBAC paralelo |
| `SecretStore` | Secretos | Nunca en graph/snapshot |
| `usage_events` | Costo/medición | No se duplica ledger |
| `audit_logs` | Auditoría | Se añaden acciones |

## 4. Extensiones aditivas propuestas

> Todas son aditivas. Ninguna migración destructiva. Ninguna muta
> `definition_snapshot` de instancias vivas.

### 4.1 `agents` (columnas nuevas, nullable)

| Columna | Tipo | Uso |
|---|---|---|
| `role_key` | `VARCHAR(80)` | `sales_advisor`, `mentor`, `tutor`, `business_advisor`, `analyst`, `auditor`, `support`, `wellness_companion` |
| `role_profile` | `JSONB` | alcance, tono, límites, handoff, idioma |
| `safety_policy` | `JSONB` | `no_diagnosis`, `no_psychotherapy`, `escalation`, `disclaimer`, `forbidden_claims` |
| `default_version_id` | `UUID` | versión que usa un workflow si no se fija otra |

`role_key` es una etiqueta de producto, **no** un permiso. Los permisos siguen
siendo RBAC + permisos delegados del agente.

### 4.2 `studio_solutions` (tabla nueva)

| Columna | Tipo | Uso |
|---|---|---|
| `id`, `organization_id`, `workspace_id` | UUID | Aislamiento |
| `title`, `original_prompt` | TEXT | Intake |
| `role_key` | VARCHAR(80) | Rol |
| `status` | VARCHAR(30) | `DRAFT`, `DESIGNING`, `READY_FOR_REVIEW`, `PUBLISHED`, `ARCHIVED` |
| `blueprint` | JSONB | Agentes, workflows, capacidades, supuestos, requisitos |
| `revision` | INT | Concurrencia optimista |
| `created_by`, `created_at`, `updated_at` | — | Auditoría |

`blueprint` guarda **referencias** (`agent_id`, `workflow_id`, `capability_ref`),
nunca copias de prompts, secretos ni bindings físicos.

### 4.3 `workflow_versions` (columnas nuevas, nullable)

| Columna | Tipo | Uso |
|---|---|---|
| `capability_snapshot_hash` | TEXT | Revalidar contratos |
| `agent_versions` | JSONB | `{node_id: {agent_id, version_id}}` |
| `certification` | JSONB | `CertificationReport` vigente |
| `effect_verification` | VARCHAR(30) | `NONE`, `DECLARED`, `SANDBOX`, `PROVIDER` |
| `published_by` | UUID | Auditoría |

### 4.4 Índices, no tablas

- GIN sobre `workflows.graph` para consultas de agentes por workflow.
- Índice `workflow_instances (organization_id, workspace_id, status, updated_at)`.
- Índice `workflow_runs (organization_id, workflow_id, started_at DESC)`.

No se crea una tabla `workflow_agent_links` como autoridad: el grafo es la
autoridad. Si se necesita rendimiento, se crea una **vista materializada**
derivada y reconstruible.

## 5. Contratos

### 5.1 `zent.studio.solution/v1`

```json
{
  "schema": "zent.studio.solution/v1",
  "role_key": "sales_advisor",
  "goal": "Calificar y cotizar pedidos",
  "agents": [
    {
      "ref": "qualifier",
      "name": "Calificador",
      "purpose": "...",
      "capability_refs": ["catalog.products.search"],
      "knowledge_scope": ["kb:..."],
      "safety_policy": "standard"
    }
  ],
  "workflows": [
    {
      "ref": "quote_flow",
      "goal": "...",
      "agent_refs": ["qualifier"],
      "capability_refs": ["catalog.products.search", "sales.cart.quote"],
      "trigger": {"type": "conversation"}
    }
  ],
  "assumptions": [],
  "requirements": [],
  "out_of_scope": []
}
```

El blueprint **no** contiene: `organization_id`, `install_id`, `credential_ref`,
`provider`, `permissions`, `system_prompt` completo ni secretos.

### 5.2 `zent.agent.role/v1`

```json
{
  "schema": "zent.agent.role/v1",
  "role_key": "wellness_companion",
  "scope": "acompañamiento general de bienestar",
  "not_a_substitute_for": ["psicoterapia", "diagnóstico clínico", "emergencia"],
  "allowed": ["escucha activa", "hábitos", "derivación"],
  "forbidden": ["diagnosticar", "recetar", "prometer curación"],
  "escalation": {
    "triggers": ["autolesión", "crisis", "violencia"],
    "action": "human_handoff",
    "message": "contacta servicios de emergencia locales"
  },
  "disclaimer": "No soy un profesional de salud mental."
}
```

La política se evalúa de forma **determinística** antes y después del LLM. El
prompt no es el único control.

### 5.3 `zent.workflow.certification/v1` (extensión)

Campos nuevos:

- `plan_hash`, `graph_hash`, `capability_snapshot_hash`;
- `agent_versions`;
- `effect_verification` (`NONE|DECLARED|SANDBOX|PROVIDER`);
- `coverage` (`branches`, `outcomes`, `error_paths`, `critical_scenarios`);
- `scenario_completeness` (`COMPLETE|PARTIAL|MISSING`);
- `stale` (boolean) y `stale_reasons`.

Regla de estado:

| Situación | Estado máximo |
|---|---|
| Sin escenarios | `VALIDATING` |
| Escenario falla | `FAILED_VALIDATION` |
| Escenario con nodo externo sin respuesta declarada | `SIMULATION_PASSED` (UNVERIFIED) |
| Nodo externo con respuesta declarada, sin sandbox/proveedor | `AWAITING_EFFECT_VERIFICATION` |
| Nodo externo verificado en sandbox | `READY_TO_PUBLISH` si el resto pasa |
| Nodo externo verificado con proveedor real | `READY_TO_PUBLISH` si el resto pasa |
| Acción financiera/crítica | `AWAITING_APPROVAL` hasta aprobación humana |
| Cobertura de ramas/errores incompleta | `AWAITING_EFFECT_VERIFICATION` o `NEEDS_CONFIGURATION` |

**`READY_TO_PUBLISH` nunca se usa para efectos externos solo declarados.**

### 5.4 `zent.workflow.publication/v1`

```json
{
  "schema": "zent.workflow.publication/v1",
  "workflow_id": "...",
  "version_id": "...",
  "decision": "ALLOW|DENY",
  "reasons": [],
  "evidence": {
    "certification_id": "...",
    "plan_hash": "...",
    "graph_hash": "...",
    "capability_snapshot_hash": "...",
    "effect_verification": "SANDBOX",
    "approvals": []
  }
}
```

Se escribe en `audit_logs` y se adjunta a `workflow_versions.certification`.

### 5.5 `zent.workflow.runtime_budget/v1`

```json
{
  "max_cost_usd": 0.50,
  "max_tokens": 50000,
  "max_duration_seconds": 300,
  "max_concurrent_runs": 5,
  "max_runs_per_hour": 60
}
```

Se evalúa en `run_workflow` y en `start_workflow_instance`. Si se excede, el run
falla con `BUDGET_EXCEEDED` o queda en `PAUSED` según política. No se inventa
un ledger: se agrega `usage_events` por `workflow_id`.

## 6. Disparadores durables

Función pura nueva en `ir.py` o `instances.py`:

```python
def graph_requires_instance(graph: dict) -> bool:
    return any(node["type"] in {"wait_event", "loop", "state_get",
                                "state_set", "state_merge", "state_append",
                                "state_remove"} for node in graph["nodes"])
```

Regla:

- `run_workflow` sigue siendo el motor.
- Si `graph_requires_instance(graph)` y el disparador es scheduler, hook, evento
  o `/run`, se llama `start_workflow_instance` con el mismo payload y actor.
- El resultado expone `instance_id` y `run_id`.
- Los workflows no durables conservan el camino actual.
- La decisión se audita en el run (`trigger_mode=durable_instance`).

No se crea scheduler ni worker nuevo.

## 7. Multi-agente sin orquestador paralelo

- El workflow sigue siendo un DAG de nodos.
- Cada nodo `llm` tiene `agent_id` y `agent_version_id`.
- La salida de un agente es un contrato (`text`, `structured`, `status`,
  `reason_codes`) y se referencia con `{{nodes.<id>.output.<field>}}`.
- El handoff es un edge explícito; no hay “agente que llama a otro agente” por
  fuera del grafo.
- El contexto se compone con `context_assembler` y selectores existentes.
- El costo por agente se agrega en `usage_events` y se muestra por workflow.

Esto permite “vendedor → especialista → auditor” sin crear un runtime de
multiagentes distinto.

## 8. Políticas de rol y bienestar

La política de rol se aplica en tres puntos:

1. **Publicación:** el validador exige `safety_policy` para roles sensibles
   (`wellness_companion`, `tutor_minors`, `financial_advisor`).
2. **Pre-LLM:** detecta intención prohibida (diagnóstico, prescripción,
   promesa de curación) y responde con derivación, sin llamar al modelo.
3. **Post-LLM:** verifica que la respuesta no contenga diagnóstico, dosis,
   promesa de curación ni omisión del disclaimer; si falla, reemplaza por
   mensaje seguro y registra un `safety_incident`.

Los flujos de bienestar:

- no se presentan como psicoterapia;
- no diagnostican;
- no recetan;
- no sustituyen emergencias;
- derivan a un humano o a servicios de emergencia;
- muestran el límite de alcance.

## 9. Operación

Vista read-only `studio_operations`:

- runs recientes por workflow;
- instancias WAITING/RUNNING/FAILED;
- aprobaciones pendientes;
- costo y tokens por workflow/agente;
- señales y timestamps;
- filtros por workspace y rol.

No crea estado: lee `workflow_runs`, `workflow_instances`, `workflow_run_steps`,
`workflow_approvals`, `usage_events`, `audit_logs`.

## 10. Feature flags y rollback

| Flag | Default | Rollback |
|---|---|---|
| `UNIVERSAL_STUDIO_ENABLED` | off | vuelve al portal actual |
| `STUDIO_SOLUTIONS_ENABLED` | off | oculta composición rol→agente→workflow |
| `AGENT_ROLE_POLICIES_ENABLED` | off | desactiva pre/post guardrails |
| `WORKFLOW_CERTIFICATION_GATE` | `report` | `report` → `warn` → `block` |
| `WORKFLOW_DURABLE_TRIGGERS_ENABLED` | off | vuelve a `run_workflow` |
| `WORKFLOW_RUN_BUDGETS_ENABLED` | off | no aplica límites |
| `MARKETPLACE_UNIFIED_CANVAS` | off | canvas usa `/integrations` |
| `STUDIO_OPERATIONS_ENABLED` | off | oculta consola |

Cada flag se resuelve con `feature_flags` (workspace → org → plan → platform) y
con env para rollback de despliegue. No hay `if tenant === ...`.

## 11. Dependencias permitidas

```
studio_solutions ──► agents / agent_versions
        │                 │
        ├──► architect ───┼──► capability_registry
        │                 │
        ├──► workflow_simulation
        │                 │
        └──► workflows ───┴──► engine ──► instances ──► runtime
                                      │
                                      └──► bindings ──► marketplace
```

Reglas:

1. `runtime`/`nodes` no importan `architect_*` ni `studio_*`.
2. `studio_*` no ejecuta workflows; solo diseña y publica.
3. `capability_registry` no importa `runtime`.
4. `marketplace` no importa `workflows`.
5. `instances` no importa `studio_*`.

El diseño completo de decisiones está en
[`04-adr-universal.md`](04-adr-universal.md).
