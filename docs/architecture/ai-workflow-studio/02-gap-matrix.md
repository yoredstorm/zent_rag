# 02 — Matriz de brechas

> Clasificación: **P0** genera workflows incorrectos, inseguros o imposibles de ejecutar; **P1** impide automatizaciones empresariales comunes; **P2** afecta experiencia, mantenimiento o rendimiento.
> Cada hallazgo cita archivo, función y comportamiento observado. La columna "Fix" apunta al plan por archivos de `08-findings-plan-risks.md`.

## Resumen

| ID | Sev | Brecha | Dominio |
|---|---|---|---|
| F-01 | P0 | El portal usa el Copilot legacy; el Architect no tiene interfaz | Planificación |
| F-02 | P0 | El nodo `llm` sin agente devuelve un **eco silencioso** con estado `succeeded` | Ejecución / Confianza |
| F-03 | P0 | La publicación no tiene gate para workflows nativos (readiness no bloquea) | Autorización |
| F-04 | P0 | Nodos durables (`wait_event`, `loop`) publican y activan, pero fallan en el primer run de schedule/webhook/manual | Ejecución |
| F-05 | P0 | `for_each` compilado sin `_branch`: itera sin ejecutar cuerpo y reporta éxito | Compilación |
| F-06 | P0 | El fallback heurístico descarta ramas y acciones anidadas sin error | Fallback |
| F-07 | P1 | Disponibilidad de acciones desalineada: `load_capabilities` ignora habilitación/credenciales/purpose | Discovery |
| F-08 | P1 | El planner no puede expresar capacidades de negocio (`capability_call`) ni bindings → no puede generar flujos commerce/conversación | Cobertura |
| F-09 | P1 | El planner no puede expresar `loop`, `ai_decision`, `api_call`, `set_variable`, `business_node` | Cobertura |
| F-10 | P1 | El digest del Architect comunica menos que el Copilot legacy (sin contratos, sin nombres de KB, sin `when_to_use`) | Prompt |
| F-11 | P1 | El validador no verifica precondiciones de runtime (instancia durable, `_branch`, binding, allowlist API, destinatarios, output schema) | Validación |
| F-12 | P1 | El planner no ve `requires_approval`/`risk_level`/`read_only` de acciones → no puede planificar aprobación humana para acciones sensibles | Seguridad funcional |
| F-13 | P1 | El puerto `timeout` de `wait_event` se compila pero nunca se conecta | Expresividad |
| F-14 | P1 | Edición conversacional partida: no se pueden agregar/quitar pasos de un workflow existente; el patch de plan no se persiste | UX / Edición |
| F-15 | P1 | Sin trazas persistidas de intent/plan: sin auditoría, sin base para patch, sin dataset real | Observabilidad |
| F-16 | P1 | `ArchitectIntent` no influye en la compilación (parámetro `intent` no usado) | Coherencia |
| F-17 | P2 | Costo mensual mal estimado para schedules `daily`/`weekly` | Costos |
| F-18 | P2 | 9 de 29 nodos sin schema de negocio (durables y `capability_call`) | UX |
| F-19 | P2 | `NODE_NEXT_STEPS` sin entrada para `loop` | UX |
| F-20 | P2 | Métricas del Architect solo en proceso | Operación |
| F-24 | P0 | El Architect puede devolver un grafo que `validate_graph` rechaza (no valida el resultado de compilar) | Compilación |
| F-25 | P1 | El gate de permisos del runtime solo cubre `external_actions:execute` y `agents:execute`: `notify`, `business_result`, `kb_query` y `query_business_data` no exigen permiso de nodo | Seguridad funcional |

---

## P0 — detalles

### F-01 · El portal usa el Copilot legacy; el Architect no tiene interfaz

**Evidencia**
- `portal/src/components/workflowStudio/AskZent.tsx:85` → `POST /api/v1/workflows/copilot/intent`; `:101` → `POST /api/v1/workflows/copilot/compile`; `:132` → `POST /api/v1/workflows` con `graph` del plan legacy.
- `src/api/routes/workflows.py:180-219` expone `/architect/plan` y `/architect/patch`. `grep -rn "architect" portal/src` → 0 coincidencias.
- `docs/architecture/workflow-architect.md:172-174` declara las fases 1–10 implementadas; la interfaz no las usa.

**Comportamiento observado:** el usuario final recibe el plan del Copilot legacy (plano, sin ramas, sin `wait/state`, sin capacidades de negocio) mientras la maquinaria semántica (discovery + validator + compiler semántico) queda sin ejecución real.

**Impacto:** todo el valor del Architect (validación pre-grafo, clarificaciones, requisitos, simulación de negocio) es invisible.

**Fix:** M2 (UI) + M1 (persistencia de trazas, F-15).

---

### F-02 · Nodo `llm` sin agente devuelve eco silencioso

**Evidencia**
- `nodes.py:2056-2057`: `if agent_id is None: return await _echo()`.
- `_echo()` (`nodes.py:2042-2051`) devuelve `{"text": f"[{model}] {prompt[:300]}", "echo": True, "warning": "El nodo no tiene agente asignado: esto es un eco…"}` **sin error**; el run queda `succeeded`.
- El validator solo emite **warning**: `architect_validator.py:208-218` (`plan.agent_needs_selection`).
- Readiness también solo warning: `readiness.py:109-123`.
- El gate de publicación solo aplica a workflows importados: `versions.py:303-311` + `packages.py:618-619` (`if row is None or not row.package: return []`).

**Comportamiento observado:** un flujo con "analiza con IA" sin agente asignado publica, se activa y produce texto falso con apariencia de análisis, sin alerta en el resultado del run.

**Impacto:** violación directa de "no fallbacks silenciosos que cambien la intención original"; riesgo de negocio (decisiones sobre texto inventado).

**Fix:** M1 (validator bloquea), M3 (gate de publicación + UI), M4 (contrato de runtime: `error` en vez de eco para agent_id ausente en grafo v2).

---

### F-03 · Publicación sin gate para workflows nativos

**Evidencia**
- `versions.publish_workflow` (`versions.py:291-326`) llama `publication_blockers`; esa función returns `[]` para todo workflow `package IS NULL` (`packages.py:618-619`).
- `readiness_checks` produce `error` para trigger ausente, KB inexistente, condiciones rotas, salidas incompletas (`readiness.py:48-155`) pero **nadie lo consume en activate/publish**: `routes:748-770, 1058-1077` no consultan readiness.

**Comportamiento observado:** se puede activar un flujo con `error` de readiness; el usuario lo descubre cuando falla en producción.

**Fix:** M3.

---

### F-04 · Nodos durables publicables pero no ejecutables desde schedule/webhook/manual

**Evidencia**
- `nodes.py:2941-2944`: `wait_event` → error `"wait_event requiere una instancia durable (inicia el flujo como proceso)"` si `rctx.instance is None`.
- `nodes.py:3018-3019`: `loop` → mismo error.
- `engine.py:1548-1557` (scheduler) y `engine.py:1598+` (hook) llaman `run_workflow` **sin** `instance_id`; `routes:772-797` (`/run`) tampoco lo admite; solo `POST /{workflow_id}/instances` (`routes:800-838` → `instances.start_workflow_instance`) crea instancias.
- El Architect puede emitir pasos `wait` (→ `wait_event`, `architect_compiler.py:172-186`) y el plan legacy puede emitir acciones `wait` (`plan_compiler.py:467-483`).
- Readiness/validator no mencionan la precondición.

**Impacto:** automatizaciones empresariales (esperar respuesta del cliente, esperar pago, reintentar pedido) se rompen en el primer disparo real; el fallo aparece lejos del momento de creación.

**Fix:** M1 (validator: `requires_instance` + issue de negocio), M4 (arranque durable transparente en los disparadores), M3 (gate de publicación).

---

### F-05 · `for_each` compilado sin subgrafo (`_branch`)

**Evidencia**
- El handler lee el cuerpo de `config._branch` o `metadata._branch` (`nodes.py:2628-2632`); con lista vacía llama `rctx.run_branch([], item)` (`nodes.py:2656-2668`), que retorna `{}` sin error, y devuelve `items_processed = len(items)` con `results = {}`.
- El portal sí escribe `_branch`: `portal/src/lib/workflowGraph.ts:609` (`n.config = { ...n.config, _branch: branchNodes }`).
- El compiler del Architect **nunca** lo escribe: `architect_compiler.py:245-254`.
- `plan_compiler` tampoco: no hay `_branch` en `plan_compiler.py`.

**Impacto:** un plan con "haz esto por cada…" produce un nodo que aparenta procesar N ítems y no procesa ninguno.

**Fix:** M1 (representación de cuerpo en el plan + `_branch` en el compiler + validator que exija ≥1 nodo en la rama).

---

### F-06 · El fallback heurístico descarta ramas y acciones anidadas

**Evidencia**
- `_legacy_step_to_plan` (`architect.py:162-223`) reconoce 7 tipos legacy y **no** recorre `then`/`else`.
- `heuristic_semantic_plan` (`architect.py:269-277`) itera solo `draft.steps` de primer nivel y encadena `depends_on` lineal.
- El draft legacy sí tiene ramas: `copilot.py:101-141` (bloque `condition` con `then`/`else` y una acción de marketplace con `{{_pack.demo_echo_install}}`).

**Comportamiento observado:** ante fallo del LLM, el usuario recibe un plan que **omite pasos** del escenario y no lo advierte con error (solo `notes: "armé un plan con reglas"`).

**Fix:** M5 (fallback: mapear ramas o negarse a compilar indicando el paso perdido).

---

### F-24 · El Architect puede devolver un grafo inválido

**Evidencia**
- `plan_workflow` (`architect.py:607-611`) hace `compiled = compile_semantic_plan(...)`, toma `graph` y suma los `issues` **del compiler**, pero **nunca** llama a `validate_graph` sobre el resultado.
- `architect_compiler` emite edges con `from_port = "then"/"else"` para cualquier `when` (`architect_compiler.py:387-388`), incluso cuando el paso referenciado es un `wait_event`, cuyos puertos son `out`/`timeout` (`architect_compiler.py:186`).
- Observado ejecutando el compiler con un plan `wait` + rama de timeout sobre el árbol actual:

```
compiler  → edges: [('t','out','w'), ('w','else','exp'), ('t','out','fe')]
validate_graph → WorkflowGraphError: edge e2: w no tiene puerto de salida else
```

- Consecuencia: `/architect/plan` responde con `graph != null` y `issues` vacíos, pero `POST /workflows` (que sí valida, `engine.py:837-840`) lo rechaza con "grafo inválido". El usuario ve un flujo "listo" que no puede crear.

**Impacto:** P0 porque rompe el contrato "el grafo devuelto es ejecutable" y la suite del dataset no lo detecta (ningún caso usa `wait`).

**Fix:** M1 (el compiler usa el puerto correcto para `wait`; `plan_workflow` valida el grafo compilado y degrada a `issue` de negocio en vez de devolver un grafo inválido).

---

## P1 — detalles

### F-07 · Disponibilidad de acciones desalineada

**Evidencia**
- `plan_compiler.load_capabilities` (`plan_compiler.py:125-141`) lista acciones cuyo install está en `('active','installed','connected')` **sin** mirar `enabled_actions`, `credential_ref` ni `purpose`.
- El runtime rechaza: `runtime.py:1253-1259` `ACTION_NOT_ENABLED`; `:1353` `CREDENTIALS_MISSING`; `:1267-1283` `PURPOSE_REQUIRED` / `LEGAL_BASIS_REQUIRED`.
- La lectura correcta ya existe en `capabilities._installed_status` (`capabilities.py:112-169`), que el Architect no usa.

**Impacto:** se valida y publica un flujo con acciones que fallarán en ejecución.

**Fix:** M1 (discovery + validator) y M2 (recomendaciones del canvas con el mismo contrato).

### F-08 · El planner no puede expresar capacidades de negocio

**Evidencia**
- `capability_call` existe y ejecuta (`nodes.py:3116-3155`, `bindings.execute_binding`), con contratos tipados (`commerce/contracts.py:252-388`) y certificación (gold sales funnel).
- `PLAN_STEP_TYPES` (`architect_models.py:15-34`) no lo incluye; el compiler no lo produce; `discover_capabilities` no expone bindings ni capacidades.
- El gold workflow (`tests/certification/workflows/test_gold_sales_funnel.py`, 4 tests en verde) es un grafo manual con 18 nodos `capability_call` (`commerce/sales_funnel.py:164-509`).

**Impacto:** la IA no puede generar la clase de flujo más valiosa del producto (ventas, stock, pagos, mensajería).

**Fix:** M1 (paso `capability_call` + discovery de bindings/proveedores).

### F-09 · Capacidades ejecutables sin paso semántico

**Evidencia:** `loop` (`nodes.py:2992-3055`), `ai_decision` (`2270-2350`), `api_call` (`1404-1505`), `set_variable` (`2891-2898`), `business_node` (`3399-3524`) y `end` (`3325-3327`) no están en `PLAN_STEP_TYPES` (`architect_models.py:15-34`) ni se producen en `_step_config`; con `capability_call` (F-08) son **7 de 29** nodos inalcanzables para el planner (verificado por script, `08` §4.1). **Impacto:** procesos iterativos, decisiones de IA por ruta nombrada, llamadas HTTP gobernadas y operaciones compuestas solo se construyen a mano. **Fix:** M1/M5.

### F-25 · Gate de permisos parcial

**Evidencia**
- `_CAPABILITY_PERMISSION` (`nodes.py:43-47`) mapea solo `calls_external → external_actions:execute`, `calls_agent → agents:execute` y `uses_integration → integrations:use`.
- Nodos con otras capabilities (`notify` = `sends_notification`, `business_result` = `writes_db`, `kb_query`/`query_business_data` = `reads_db`, `human_approval` = `needs_approval`) **no exigen permiso de nodo**: el único control es `workflows:run` a nivel endpoint (`routes:777`) y `workflow_approvals:approve` para decidir la aprobación (`routes:460`).
- Los permisos `notifications:send`, `business_results:write` y `data:read` **no existen** en el código (búsqueda en `src/` sin coincidencias).

**Impacto:** un usuario con `workflows:create`/`workflows:update` + `workflows:run` puede publicar y ejecutar avisos por correo a destinatarios arbitrarios y escrituras de resultados sin permiso dedicado. **Requiere decisión de producto** (puede ser intencional para no friccionar al tenant).

**Fix:** M3 (revisar el mapa de permisos por capability y registrar la decisión en un ADR; si se amplía, hacerlo con flag y auditoría).

### F-10 · El digest del Architect comunica menos que el legacy

**Evidencia:** `capability_digest` (`architect_discovery.py:202-240`) vs `planner_hints` (`node_catalog.py:742-777`). Faltan: `when_to_use`/`when_not_to_use`, `what_it_needs`, `what_it_produces`, nombres de KB, campos de evento, esquemas de acción, costos.

**Impacto:** el LLM elige nodos y parámetros a ciegas; la corrección la paga el validator (cuando la detecta).

**Fix:** M1 (digest desde el catálogo autorizado + capacidades con estado).

### F-11 · Validación sin precondiciones de runtime

**Evidencia:** `validate_semantic_plan` (`architect_validator.py:53-354`) no chequea: binding de `capability_call`, instancia durable, `_branch`, allowlist de `api_call`, destinatarios existentes, `output_schema` de agente, existencia y tipo de puerto `timeout`, `state.path` válido, presupuesto de costo.

**Fix:** M1.

### F-12 · El planner no ve riesgo ni aprobación de acciones

**Evidencia:** `capabilities._org_manifests` devuelve `requires_approval`, `risk_level`, `read_only`, `cost` (`capabilities.py:92-108`); `discover_capabilities` los descarta (`architect_discovery.py:126-133`). El runtime **no** bloquea por `requires_approval` para `source="workflow"` (`runtime.py:1260-1265` solo aplica a `agent|auto`).

**Impacto:** acciones sensibles (p. ej. `peru.identity.verify`, `requires_approval=true`) pueden quedar en un flujo automático sin aprobación humana y el planner no puede sugerirla.

**Fix:** M1 (exponer riesgo y exigir `human_approval` en el plan o en el validator).

### F-13 · Puerto `timeout` de `wait_event` inalcanzable

**Evidencia:** el compiler declara `outputs: ["out","timeout"]` (`architect_compiler.py:186`) pero el bucle de edges solo emite `out`/`then`/`else` (`architect_compiler.py:382-398`); mismo patrón en `plan_compiler.py:467-483`. El runtime **sí** soporta el puerto (`runtime.py:651-657`, `instances._targets_for_port`, `test_workflow_durable_instances.py:381`).

**Impacto:** `on_timeout: branch` no tiene a dónde ir; el flujo no puede derivar por timeout.

**Fix:** M1.

### F-14 · Edición conversacional partida

**Evidencia:** `patches._SUPPORTED_OPS` (`patches.py:89-98`) no incluye agregar/quitar nodos; `architect_patch.apply_semantic_patch` sí (`architect_patch.py:126-172`) pero el plan no se persiste y la UI no lo conserva (`AskZent.tsx:294-302` reinicia).

**Fix:** M2/M5.

### F-15 · Sin trazas de intent/plan

**Evidencia:** `plan_workflow` no persiste (`architect.py:569-660`); decisión D5 en `docs/architecture/workflow-architect.md:202` ("no persistir en first delivery"). El endpoint de patch recibe el plan del cliente (`routes:198-219`).

**Impacto:** sin auditoría de "qué propuso el LLM", sin base para patch confiable, sin dataset de evaluación real (`architect_metrics` es en proceso, `architect_metrics.py`).

**Fix:** M1/M2.

### F-16 · `ArchitectIntent` no influye en la compilación

**Evidencia:** `compile_semantic_plan(plan, capabilities, *, intent=None)` (`architect_compiler.py:305-310`); `intent` no se usa en el cuerpo. El trigger se toma del plan (`:361-364`), no de `intent.schedule`/`trigger_intent`.

**Fix:** M1 (usar intent para trigger/costos o eliminarlo del pipeline).

---

## P2 — detalles

| ID | Evidencia | Impacto |
|---|---|---|
| F-17 | `architect._trigger_config_for_cost` (`architect.py:348-358`) entrega `daily` como `{time:…}`; `capabilities.cost_estimate` solo entiende `frequency`/`every_minutes`/regex cron (`capabilities.py:391-398`) → mensual = 30 corridas para cualquier schedule diario/semanal | Estimaciones de costo engañosas |
| F-18 | `parameters.NODE_BUSINESS_SCHEMAS` cubre 20/29; faltan `capability_call`, `end`, `loop`, `state_*`, `wait_event` (`parameters.py:797`) | Sin formularios Simple/Guided para nodos durables |
| F-19 | `node_catalog.NODE_NEXT_STEPS` no tiene clave `loop` (`node_catalog.py:40-72`) | Sin "siguientes pasos" tras un loop |
| F-20 | `architect_metrics` en memoria del proceso (`architect_metrics.py`) | Sin métricas operables |
| F-21 | `semantic_preview` cae a `kind="then"` para tipos sin entrada en `_PREVIEW_KIND_BY_TYPE` (`architect.py:298-315`) — `wait`/`state`/`stop` no están | Preview de negocio impreciso |
| F-22 | `readiness_checks` no marca falta de agente/KB como `error` (`readiness.py:109-123`); `node_issues` solo propaga checks con `node_id` | Badges del canvas incompletos |
| F-23 | `AskZent` envía `steps: []` y `graph` (`AskZent.tsx:132-144`); `create_workflow` persiste ambos (`engine.py:837-848`) → workflows v2 con `steps` vacío | Herramientas que leen `steps` ven un flujo vacío |
