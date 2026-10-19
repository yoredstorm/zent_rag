# 09 — Prompt 01: unificación del AI Workflow Architect

> **Actualización Prompt 03:** el portal ya usa `POST /architect/agentic-plan`
> (planner con tool calling read-only, MATCH/VERIFY/REPAIR). `POST /architect/plan`
> queda como compatibilidad para el camino de una sola pasada y para tests
> existentes. Ver [`11-agentic-planner.md`](11-agentic-planner.md).

> Fecha: 2026-10-19. Base: `master` @ `70620a9` + cambios de esta entrega.
> Alcance: convertir el Architect semántico en el camino principal de creación
> con IA, sin romper el Copilot legacy ni los workflows existentes.

## 1. Auditoría del flujo frontend-backend (A)

| Camino | Entrada UI | Endpoint(s) | Motor | Persistencia | Estado |
|---|---|---|---|---|---|
| Crear con IA (canónico) | `/workflows/new/ask` → `AskZent` | `GET /architect/config` → `POST /architect/plan` → `POST /architect/patch` (opcional) → `POST /architect/draft` | `architect.py` (discovery → intent → plan → validator → compiler) | `POST /architect/draft` re-valida y crea `draft` | **Nuevo camino principal** |
| Crear con IA (legacy) | mismo componente | `POST /copilot/intent` → `POST /copilot/compile` → `POST /workflows` | `copilot_v2.py` + `plan_compiler.py` | `POST /workflows` con grafo del cliente | **Rollback / compatibilidad** |
| Lienzo manual | `/workflows/new/manual` → `WorkflowStudio.create()` | `POST /workflows` | sin IA | grafo del canvas | Sin cambios |
| Plantilla | `/workflows/new` / lista | `POST /templates/{slug}/install` | `engine.create_from_template` | `POST /workflows` interno | Sin cambios |
| Asistente → automatización | `AssistantAutomations` | navega a `/workflows/new/ask` con prompt | el mismo `AskZent` | igual que el camino elegido | Sin cambios |

Hallazgos de la auditoría:

1. `AskZent` consumía solo `/copilot/*` y trataba la respuesta como `WorkflowPlan`; nunca llamaba al Architect (ver `01-audit-as-is.md`, F-01).
2. El plan del Architect no se persiste: el patch requería que el cliente reenviara el plan completo sin garantía de vigencia.
3. El guardado se hacía con `POST /workflows` enviando el grafo compilado por el cliente: React podía alterarlo y el backend solo validaba la estructura del grafo, no capacidades ni permisos.
4. El fallback heurístico no se distinguía de un plan real en la UI.
5. `for_each` podía compilarse sin cuerpo y ejecutarse como no-op (F-05). En esta entrega el planificador semántico lo rechaza con un mensaje accionable.

## 2. Recorrido canónico (B)

```
prompt del usuario
  → GET  /workflows/architect/config              (feature flag + estados)
  → POST /workflows/architect/plan
        discover_capabilities()                    (tenant/workspace/permissions)
        extract_intent_with_architect()            (LLM 1, validado)
        extract_plan_with_architect()              (LLM 2, validado)
        validate_semantic_plan()                   (errores bloquean)
        compile_semantic_plan() + validate_graph() (nunca devuelve grafo inválido)
        readiness + simulation + costo             (vista de negocio)
  → UI: estado + preview + preguntas + dependencias (sin crear nada)
  → POST /workflows/architect/patch                (edición semántica opcional)
  → POST /workflows/architect/draft                (confirmación humana)
        re-descubre capacidades + re-valida + re-compila + re-valida el grafo
        persiste SOLO un borrador (status draft, nunca activo)
  → redirección al estudio con el workflow_id
```

El portal **no compila**: envía el plan y el backend decide. La capa de
presentación (`workflowArchitect.ts`) solo adapta el envelope del Architect a
tipos de UI; no reimplementa el motor de planificación.

### Contrato de `POST /architect/plan` (aditivo sobre el existente)

| Campo | Uso |
|---|---|
| `session_id` | id de sesión de diseño (`ds_…`), estable entre patch y guardado |
| `state` | estado canónico (ver §4) |
| `planner` | `{version, provider, model, source}`; `source` = `llm`/`heuristics` |
| `phases[]` | `{name, duration_ms}` de discovery/intent/planning/validation/compilation/readiness |
| `fallback` | `null` o `{used, reason_code, limitations, requires_review, publishable, preserved_requirement}` |
| `plan_hash` | SHA-256 canónico del plan; el patch lo exige para evitar editar planes viejos |
| `publishable` | `true` solo si `state=DRAFT_READY` y no hubo fallback |
| `blockers[]` | lista única de requisitos/problemas que impiden considerar el flujo listo |
| `preview`, `clarifications`, `requirements`, `readiness`, `simulation`, `cost` | vista de negocio (se conservan los campos anteriores) |
| `graph`, `steps_map` | grafo v2 ya validado (o `null` si el diseño está bloqueado) |

`POST /architect/patch` devuelve el mismo envelope + `patch`. Si el
`plan_hash` no coincide → `409`. El patch aplica operaciones sobre el plan
(`set_param`, `remove_step`, `add_step`, …) y conserva los pasos no afectados.

`POST /architect/draft` recibe `{plan, plan_hash?, session_id?, name?,
description?, editor_state?, source?}` y **nunca** el grafo. Re-ejecuta
discovery + validator + compiler + `validate_graph`, exige que exista un grafo
compilable y persiste con `create_workflow` (status `draft` por defecto). Si el
diseño está bloqueado responde `422` con `{saved:false, state, issues,
requirements, clarifications}`.

## 3. Compatibilidad (C)

| Elemento | Estado |
|---|---|
| `/copilot/intent` y `/copilot/compile` | Siguen operativos. Responden con `Deprecation: true`, `Sunset: Wed, 31 Dec 2026 23:59:59 GMT`, `Link: </api/v1/workflows/architect/plan>; rel="successor-version"` y `Warning` |
| `copilot_v2.py` | Marcado `LEGACY_COPILOT = True` en código y docstring; sin cambios de comportamiento |
| Tests legacy | Siguen verdes (`tests/test_workflow_architect_patch.py` cubre el patch legacy; `AskZent.test.tsx` cubre el flujo Copilot con el flag apagado) |
| Workflows persistidos v1/v2 | Sin cambios: el gate de publicación nuevo solo actúa si `graph.metadata.architect` existe |
| Planes anteriores | `plan_compiler` intacto; `/copilot/compile` sigue compilando `WorkflowPlan` |
| Rollback | `RAG_WORKFLOW_ARCHITECT_ENABLED=false` (o `GET /architect/config` → `enabled:false`) devuelve el portal al Copilot legacy sin desplegar código |

### Plan de retirada del Copilot legacy

| Etapa | Acción | Criterio para avanzar |
|---|---|---|
| R0 (esta entrega) | Architect detrás de flag, default **on**; legacy intacto y marcado | suite completa verde |
| R1 (próximo release) | Medir uso de `/copilot/*` por tenant y errores del camino canónico; corregir paridad | uso legacy < 5% de creaciones y 0 incidentes P0 |
| R2 | Ocultar el legacy en la UI; mantener endpoints | 2 releases con R1 estable |
| R3 | Anunciar retirada con `Sunset` (≥ 90 días) y migrar consumidores | confirmación de que ningún cliente lo usa |
| R4 | Eliminar endpoints/modelos legacy | — |

## 4. Estados del proceso creativo (D)

| Estado | Significado | ¿Grafo? | ¿Guardar borrador? | ¿Publicar? |
|---|---|---|---|---|
| `UNDERSTANDING` | interpretando el requerimiento | — | no | no |
| `DISCOVERING` | comprobando capacidades del tenant | — | no | no |
| `PLANNING` | diseñando el proceso | — | no | no |
| `NEEDS_CLARIFICATION` | faltan datos o supuestos de alto impacto | puede existir | sí (borrador) | requiere confirmación explícita |
| `NEEDS_CONFIGURATION` | faltan integraciones, agentes, KB, DB, permisos o binding | normalmente no | sí si hay grafo | bloqueado hasta resolver (`readiness` en error) |
| `VALIDATING` | verificando el diseño | — | no | no |
| `DRAFT_READY` | diseño revisable y ejecutable | sí | sí | sí (con gate del servidor) |
| `BLOCKED` | error de diseño o grafo no compilable | no | no | no |

Reglas de cálculo (`architect_observability.design_state`):

1. Sin grafo y solo faltan dependencias del tenant → `NEEDS_CONFIGURATION`.
2. Sin grafo con preguntas → `NEEDS_CLARIFICATION`; sin preguntas → `BLOCKED`.
3. Con grafo y preguntas/fallback → `NEEDS_CLARIFICATION` (nunca "listo").
4. Con grafo y requisitos/permisos/readiness en error → `NEEDS_CONFIGURATION`.
5. Resto → `DRAFT_READY`.

La UI muestra el estado, las fases con duración, los bloqueos y el preview de
negocio. No ofrece "Crear borrador" si el estado no es `DRAFT_READY`.

## 5. Resultados engañosos (E)

- El fallback solo se usa cuando el LLM falla o devuelve un formato inválido.
- Se informa en la UI: banner "El modelo no estuvo disponible", limitaciones y
  el pedido original conservado (`preserved_requirement`).
- El plan queda en `NEEDS_CLARIFICATION` (nunca `DRAFT_READY`) y
  `publishable=false`.
- Al guardarlo, `source=heuristics` queda en `graph.metadata.architect_source`.
  Publicarlo exige `confirm_architect_draft=true`; además se re-ejecuta
  readiness y se rechaza si hay errores o un paso de IA sin agente.
- No existe ningún camino que active un workflow por `confidence` del modelo.

## 6. Edición semántica (F)

- `AskZent` envía `plan + plan_hash + session_id + instruction` a
  `/architect/patch`; el backend aplica el patch sobre el plan, re-valida,
  recompila y devuelve el envelope completo.
- El plan y su hash se conservan en la sesión de diseño: un patch sobre un plan
  viejo responde `409` (no se pisa trabajo del usuario).
- Los pasos no afectados se conservan (el patch no regenera el plan).
- La edición manual (`WorkflowPatchPanel` + `/workflows/{id}/patch/*`) sigue
  disponible para el grafo persistido.

## 7. Observabilidad (G)

Eventos estructurados (`architect_observability.log_design`), sin prompt crudo:

| Evento | Campos |
|---|---|
| `architect.plan` | `session_id`, `organization_id`, `workspace_id`, `actor_id`, `planner{version,provider,model,source}`, `state`, `phases[{name,duration_ms}]`, `total_duration_ms`, `issue_codes`, `requirements`, `fallback_used`, `fallback_reason`, `graph_nodes`, `prompt_hash`, `prompt_chars` |
| `architect.patch` | idem + `instruction_chars`, `fallback_used` |
| `architect.draft.saved` | `workflow_id`, `state`, `source`, `plan_hash`, fases, requisitos, `graph_nodes` |
| `architect.draft.blocked` | `state`, `issue_codes`, `requirements` |

No se registran prompts, tokens, credenciales ni contenido de KB. El prompt se
representa por hash + longitud.

## 8. Seguridad

- **Re-validación en el guardado:** `/architect/draft` ignora cualquier grafo
  del cliente, vuelve a descubrir capacidades con `organization_id`,
  `workspace_id` y `permissions` del request, valida el plan, compila y ejecuta
  `validate_graph`. Si no hay grafo válido, no persiste.
- **Autorización:** los endpoints exigen `workflows:create` (plan/patch/draft) y
  `workflows:read` (config); el runtime sigue aplicando permisos por capability.
- **Sin auto-activación:** el borrador se crea con el status por defecto
  (`draft`); activar/publicar es una acción humana.
- **Gate de publicación:** para workflows del Architect se re-ejecuta
  `readiness_checks` con las capacidades actuales, se valida el grafo y se
  exige confirmación si el borrador viene de reglas o de un estado no listo.
- **Aislamiento:** el workspace se toma del request y se usa en discovery y en
  la persistencia; el workflow se crea con la organización del contexto.

## 9. Archivos de la entrega

**Backend**
- `src/platform/workflows/architect_observability.py` (nuevo): estados, sesión,
  hash, blockers, fallback informado, logging y feature flag.
- `src/platform/workflows/architect.py`: envelope canónico, validación del
  grafo compilado, `save_architect_draft`, patch con hash/sesión.
- `src/platform/workflows/architect_compiler.py`: puertos correctos por tipo
  (`condition`/`ai_decision` → then/else, `wait_event` → out/timeout,
  `for_each` → done) y warning de rama implícita.
- `src/platform/workflows/architect_validator.py`: `when` sobre `wait`; `for_each`
  bloqueado con mensaje accionable.
- `src/api/routes/workflows.py`: `/architect/config`, `/architect/draft`,
  headers de deprecación, modelos nuevos, `confirm_architect_draft`.
- `src/platform/workflows/versions.py`: gate de publicación del Architect.
- `src/core/config.py`: `WORKFLOW_ARCHITECT_ENABLED` (default `true`).
- `src/platform/workflows/copilot_v2.py`: marca legacy.

**Frontend**
- `portal/src/components/workflowStudio/workflowArchitect.ts` (nuevo): contrato
  tipado y cliente de `/architect/config|plan|patch|draft`.
- `portal/src/components/workflowStudio/ArchitectAskZent.tsx` (nuevo): UI
  canónica con estados, fases, clarificaciones, requisitos, fallback, patch y
  guardado.
- `portal/src/components/workflowStudio/AskZentLegacy.tsx`: UI anterior intacta
  para rollback.
- `portal/src/components/workflowStudio/AskZent.tsx`: selector por flag.

**Tests**
- `tests/test_workflow_architect_canonical.py` (13 casos).
- `portal/src/components/workflowStudio/ArchitectAskZent.test.tsx` (8 casos).
- `portal/src/components/workflowStudio/AskZent.test.tsx` (3 legacy, ajustados
  al estado de carga del selector).

## 10. Pruebas ejecutadas

| Verificación | Resultado |
|---|---|
| Backend canónico (`tests/test_workflow_architect_canonical.py`) | **14 passed** |
| Architect + eval 50 casos + patch + studio + readiness | **38 passed** |
| Workflows legacy (`tests/test_workflows.py`) | **10 passed** |
| Durabilidad (`tests/test_workflow_durable_instances.py`) | **27 passed** |
| Certificación gold sales funnel | **4 passed** |
| Frontend `AskZent` (legacy) + `ArchitectAskZent` | **11 passed** |
| Suite frontend completa | **758 passed, 1 flake** (`AgentStudio` streaming; pasa aislado, ver nota) |
| `npm run typecheck` | sin errores |
| `npm run build` | build OK (solo warnings preexistentes de tamaño de chunks) |
| `eslint` (archivos tocados) | sin errores |
| `ruff` (archivos tocados) | sin errores |

> Nota sobre el flake: `AgentStudio.test.tsx > pinta los deltas en vivo antes del done`
> falló en la corrida completa (758/759) por timeout de streaming bajo carga.
> Ejecutado aislado (`vitest run src/pages/AgentStudio.test.tsx -t "pinta los deltas…"`)
> pasa en 31s. No toca workflows ni fue modificado por esta entrega.

> Nota de ejecución: la corrida backend combinada de 8 archivos se reemplazó por
> corridas dirigidas (tabla superior) para evitar contención de la base local;
> cubren el mismo conjunto y se ejecutaron después de los últimos cambios.

Cobertura de los casos pedidos:

| Caso | Test |
|---|---|
| Workflow sencillo desde la UI nueva | `test_plan_returns_canonical_envelope_and_valid_graph`, `crea el borrador re-validado`, `muestra el estado…` |
| Varias ramas | `test_plan_compiles_both_decision_branches`, `muestra el flujo avanzado con las dos ramas` |
| Aclaraciones | `test_plan_with_high_impact_assumption_needs_clarification`, `pide aclaración y reinterpreta…` |
| Integración ausente | `test_missing_integration_needs_configuration_and_no_graph`, `muestra dependencias ausentes…` |
| Respuesta LLM inválida | `test_invalid_llm_response_returns_informed_fallback` |
| Fallback no publica | `test_publish_blocks_unreviewed_fallback_draft` + estado nunca `DRAFT_READY` |
| Rollback del flag | `test_architect_feature_flag_is_reversible` + `AskZent.test.tsx` con `enabled:false` |
| Compatibilidad legacy | `test_legacy_copilot_is_marked_deprecated` + suite legacy existente |
| Guardado re-validado | `test_draft_endpoint_revalidates_and_saves_only_draft`, `…rejects_plan_with_unresolved_dependency` |
| Hash de plan viejo | `test_patch_rejects_stale_plan_hash` |

## 11. Limitaciones conocidas (declaradas, no silenciosas)

1. **`for_each`**: el plan semántico no expresa cuerpos de iteración; el
   validator lo rechaza con `plan.for_each_unsupported` y sugiere el lienzo.
   Preferimos bloquear antes que ejecutar un no-op (F-05).
2. **Gate de publicación**: aplica a workflows con `metadata.architect`; los
   workflows manuales/legacy mantienen su comportamiento (el gate general de
   readiness queda para la fase siguiente del plan de migración).
3. **Costos**: la estimación mensual para schedules diarios/semanales sigue
   usando la lógica existente (F-17); no se tocó en esta entrega.
4. **Trazas**: la sesión de diseño viaja en la respuesta y en logs, pero aún no
   se persiste una tabla append-only (ADR-7); el `plan_hash` ya protege el patch.
5. **Publicación desde la UI**: el estudio no expone un botón de publicar; el
   gate se verifica por API. La creación con IA solo guarda borradores.

## 12. Rollback

1. `RAG_WORKFLOW_ARCHITECT_ENABLED=false` → el portal vuelve al Copilot legacy.
2. Si se requiere revertir código, el commit es independiente y no toca
   `runtime.py`, `ir.py`, `instances.py`, `context_store.py` ni
   `definition_snapshot`.
3. Los workflows creados por el Architect siguen siendo `WorkflowGraph` v2
   estándar: se abren y ejecutan en el canvas aunque el flag esté apagado.
