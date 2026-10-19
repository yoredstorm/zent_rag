# 03 — Arquitectura TARGET y contrato de responsabilidades

> Principio rector: **el LLM propone; el backend descubre, valida, autoriza, compila, simula y ejecuta.**
> Ninguna etapa nueva crea engine, scheduler, colas ni estado paralelo.

## 1. Límites de responsabilidad

```
User Intent → Capability Discovery → Planning → Validation → Compilation
     → Simulation → Approval → Execution → Observation
```

| Etapa | Dueño (módulo) | Entrada | Salida | Invariante | Etapa previa no puede… |
|---|---|---|---|---|---|
| **User Intent** | `architect.extract_intent_with_architect` (reuso) | prompt NL (≤2000 chars) + digest de capacidades | `ArchitectIntent` validado (`extra="forbid"`) | El texto es untrusted; no produce efectos | — |
| **Capability Discovery** | `architect_discovery.discover_capabilities` (**evoluciona**) | org/workspace/permissions | snapshot único: nodos+contratos, agentes, KBs, datos, eventos, acciones *con estado*, capacidades/bindings, canales, watchers, permisos, costos | Nunca inventa: todo viene de registry/DB/Marketplace | Inyectar secretos o credenciales |
| **Planning** | `architect.extract_plan_with_architect` (**evoluciona** vocabulario) | intent + snapshot | `SemanticPlan` v2 | Sin ids de nodo, sin mustache, sin permisos, sin costos inventados | Concederse permisos, ejecutar, instalar, publicar |
| **Validation** | `architect_validator.validate_semantic_plan` (**evoluciona**) | plan + snapshot + permisos del actor | `PlanIssue[]` (error bloquea) + `requirements[]` | Solo reporta; jamás eleva privilegios | Mutar el plan para "hacerlo pasar" |
| **Compilation** | `architect_compiler.compile_semantic_plan` (**evoluciona**) | plan válido + snapshot | `WorkflowGraph` v2 + `steps_map` + issues de compile | Determinístico; mismas estructuras que `execute_graph`; **el grafo devuelto siempre pasa `validate_graph`** (si no, se convierte en `issue` de negocio) | Emitir nodos sin contrato de ejecución |
| **Simulation** | `architect.simulation_plan` (**evoluciona**) + `run_workflow(simulate=True)` (reuso) | grafo + pinned data | preview de negocio + dry-run real sin efectos | Cero efectos externos | Aprobar por el usuario |
| **Approval** | `readiness.workflow_readiness` + `versions.publish_workflow` (**evoluciona** gate) | grafo persistido + capacidades | checklist + bloqueo de publicación/activación | `error` bloquea; `warning` exige confirmación explícita | Publicar sin decisión humana |
| **Execution** | `engine.run_workflow` + `runtime.execute_graph` + `instances.start_workflow_instance` (**reuso + decisión durable**) | grafo congelado, `ExecutionContext` | run/instancia, WAIT/RESUME, señales | Un solo motor; permisos fail-closed | Re-ejecutar efectos ya confirmados (idempotencia) |
| **Observation** | `context_store`, `instances.instance_timeline`, `engine.run_detail`, `architect_metrics` (**reuso + trazas**) | run/instancia | timeline, contexto, métricas | Sin secretos; tenant-scoped | Alterar el resultado del run |

### Frontera LLM/backend (explícita)

| El LLM PUEDE | El LLM NO PUEDE |
|---|---|
| proponer `ArchitectIntent` y `SemanticPlan` | elegir nodos inexistentes o inventar integraciones/agentes/KBs |
| referenciar capacidades **presentes en el snapshot** | crear bindings, instalar productos, conceder permisos |
| declarar supuestos e incertidumbres | publicar, activar, ejecutar o leer secretos |
| proponer patches sobre un plan/grafo existente | escribir el grafo final (lo compila el backend) |

---

## 2. Contratos a reutilizar (no se tocan)

| Contrato | Superficie | Por qué |
|---|---|---|
| `WorkflowGraph` v2 + `validate_graph` | `ir.py:107-287` | representación canónica |
| `execute_graph`, `ExecutionContext`, `NodeContext`, `registry` | `runtime.py`, `nodes.py` | único motor de nodos |
| `run_workflow` (full/partial/simulate/resume) | `engine.py:306-755` | único punto de ejecución |
| `WorkflowInstance` + señales + state ops + sweep | `instances.py` | durabilidad ya resuelta |
| `bindings.execute_binding` + `PROVIDER_KINDS` | `bindings.py:28-369` | ejecución de capacidades con contrato |
| `marketplace.runtime.execute_action` | `runtime.py:1240+` | gobierno de acciones (habilitación, credenciales, purpose, costo, evidencia) |
| `capabilities._installed_status` | `capabilities.py:112-169` | **única verdad** del estado de instalación |
| `marketplace.resolver.resolve_capability/resolve_dependency` | `resolver.py:105-244` | capability-first y reuso de instalaciones |
| `notifications.notification_targets` | `notifications.py:65-156` | canales/destinatarios reales |
| `context_store`, `contributions`, `values` | — | estado, merge validado y resolución de referencias |
| `node_catalog` + `parameters` | — | nombres/contratos de negocio |
| `event_registry` | — | eventos con campos |
| `packages.STATUSES` + `publication_blockers` | `packages.py:31-44, 597-629` | vocabulario de resolución y gate de importados |
| `commerce.contracts` | — | contratos de negocio independientes del proveedor |

## 3. Interfaces que deben evolucionar

| Interfaz | Cambio requerido | Compatibilidad |
|---|---|---|
| `architect_models.PLAN_STEP_TYPES` | sumar `capability_call`, `loop`, `ai_decision`, `api_call`, `set_variable`, `business_node`, `wait` con **rama de timeout**, `for_each` con **cuerpo**, `state` con path validado | Aditivo; planes antiguos siguen válidos |
| `architect_discovery.discover_capabilities` | nueva clave `capabilities[]` (bindings + providers + addons) y `actions[]` con estado; reutilizar `_installed_status` y `resolver` | Clave nueva; consumidores actuales no se rompen |
| `architect_discovery.capability_digest` | construir desde `build_node_catalog()` + snapshot (contratos, `when_to_use`, KBs con nombre, campos de evento, riesgo/approval/costo de acciones) | El prompt cambia; el shape de salida no |
| `architect_validator` | tabla de precondiciones por tipo de paso (ver §4) | Isssues nuevos pueden ser `error`; requiere versionar el gate (ver ADR-5) |
| `architect_compiler` | `_branch` para `for_each`, puerto `timeout` para `wait`, cfg de `capability_call` desde binding, políticas de retry/timeout desde el catálogo, nodo `end` opcional | Mismo `WorkflowGraph` v2 |
| `architect.plan_workflow` | persistir `intent`/`plan` + `source` + hash del grafo (traza) | Aditivo |
| `readiness.workflow_readiness` | checks de durabilidad, binding, destinatarios, riesgo | Checks nuevos; `status` existente se mantiene |
| `versions.publish_workflow` + `routes.activate` | gate de readiness para workflows **nativos** | Requiere flag y mensaje claro; ver ADR-5 |
| `engine` disparadores (scheduler/hook/event/manual) | si el grafo contiene nodos durables → `start_workflow_instance` en vez de `run_workflow` | Decisión determinística, sin cambiar el motor |
| `AskZent.tsx` (+ `AskZentPage`) | consumir `/architect/plan`, `/architect/patch`, `/architect/apply` con preview de negocio | Legacy `copilot/*` sigue disponible (ADR-4) |
| `parameters.NODE_BUSINESS_SCHEMAS` | schemas de negocio para `loop`, `wait_event`, `state_*`, `capability_call` | Aditivo |
| `node_catalog.NODE_NEXT_STEPS` | entrada `loop` | Aditivo |

## 4. Precondiciones de ejecución (contrato mínimo del validador)

| Tipo de paso | Precondición | Severidad si falta |
|---|---|---|
| `wait`, `loop`, `state` | el grafo se ejecutará como **proceso durable** (`WorkflowInstance`) | `error` (con acción "ejecutar como proceso") |
| `for_each` | cuerpo declarado con ≥1 paso y `collection` referenciable | `error` |
| `capability_call` | binding activo **o** provider publicado instalable | `error` (con `requirement`) |
| `integration_action` | acción instalada **y** habilitada **y** con credenciales **y** purpose si es dato personal | `error` |
| `integration_action` con `requires_approval` | `human_approval` previo o `risk_ack` explícito del usuario | `error` |
| `api_call` | URL en allowlist del tenant (SSRF check) | `error` |
| `notify` con `email` | ≥1 destinatario resoluble | `error` |
| `notify` con canal externo | integración conectada **y** canal soportado por el executor | `error` |
| `knowledge_query` | KB elegida o única KB disponible (nunca "la primera" implícita) | `warning` → `error` si hay >1 y no se eligió |
| `agent_analysis` (nodo `llm`) | agente elegido (nunca eco) | `error` |
| `ai_decision` | `decision_kind`, `question` y rutas nombradas; `on_low_confidence` válido | `error` |
| `loop` | `target` existe y pertenece al cuerpo re-entrante | `error` |

> Nota (F-25): hoy el runtime solo exige `external_actions:execute` y `agents:execute` a nivel nodo (`nodes.py:43-47`). Si el producto decide ampliar el gate (p. ej. permiso de notificación o de escritura de resultados), esas precondiciones entran en esta tabla antes de activar la fase M3.

## 5. Mapa de dependencias

```
                         ┌─────────────────────────────┐
                         │  API / Portal (AskZent,     │
                         │  canvas, paneles)           │
                         └──────────────┬──────────────┘
                                        │
              ┌─────────────────────────┼──────────────────────────┐
              ▼                         ▼                          ▼
   ┌────────────────────┐   ┌────────────────────┐   ┌────────────────────┐
   │ architect.py       │   │ engine.py          │   │ capabilities.py    │
   │ (intent→plan→      │   │ run_workflow       │   │ canvas/installs    │
   │  validate→compile) │   │  └─ instances.py   │   │ recommend/cost     │
   └─────┬──────────────┘   │      (durable)     │   └─────┬──────────────┘
         │                  └─────────┬──────────┘         │
         │                            │                    │
         ▼                            ▼                    ▼
 ┌────────────────────┐   ┌────────────────────┐   ┌────────────────────┐
 │ architect_*.py     │   │ runtime.py         │   │ marketplace/       │
 │ discovery/validator│   │ execute_graph      │   │ resolver+runtime   │
 │ compiler/models    │   │ nodes.py registry  │   │ factory/products   │
 └─────┬──────────────┘   └─────────┬──────────┘   └─────┬──────────────┘
       │                            │                    │
       ▼                            ▼                    ▼
 ┌──────────────────────────────────────────────────────────────────────┐
 │ ir.py (WorkflowGraph v2) · values.py · conditions.py · context_store │
 │ bindings.py · commerce/contracts.py · event_registry.py · packages.py│
 └──────────────────────────────────────────────────────────────────────┘
```

Reglas de dependencia:
1. `architect_*` **solo** depende de registry/catálogo/capabilities/DB de tenant; nunca importa `runtime`/`nodes` para ejecutar.
2. `runtime`/`nodes` **nunca** importan `architect_*` (evita ciclos y permite borrar el planner sin romper ejecución).
3. El estado de disponibilidad tiene **una sola fuente** (`capabilities._installed_status` + `resolver`), consumida tanto por canvas como por discovery y validator.
4. Todo lo relacionado con durabilidad pasa por `instances.py`; ningún módulo nuevo guarda estado por su cuenta.
