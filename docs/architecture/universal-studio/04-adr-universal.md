# 04 — ADR del Universal Agent & Workflow Studio

> Estado: **propuestas**. Esta fase no implementa.
> Los ADR del contrato anterior (`ai-workflow-studio/04-adr.md`) siguen vigentes.
> Estos ADR resuelven lo específico de la universalización.

---

## ADR-U1 · El blueprint universal es un artefacto de diseño, no un runtime

**Contexto.** El usuario quiere describir un rol (“mentor”, “vendedor”,
“auditor”) y obtener agentes y workflows. Si el blueprint se ejecuta, se crea un
motor alterno y se duplica el estado.

**Decisión.** `SolutionBlueprint` vive en `studio_solutions` y contiene
referencias a agentes, workflows, capacidades y requisitos. No contiene
secretos, bindings físicos, permisos ni prompts completos. Al publicar, el
backend materializa `agents` + `agent_versions` + `workflows` y guarda las
referencias. La ejecución sigue siendo `run_workflow` / `execute_graph`.

**Consecuencias.** Un blueprint puede evolucionar sin tocar instancias vivas.
Se puede descartar sin efectos. El costo es una tabla de diseño adicional y un
materializador explícito.

**Alternativas descartadas.**
(a) Guardar el blueprint como `workflows.metadata` → mezcla diseño con
definición ejecutable;
(b) ejecutar el blueprint directamente → motor alterno.

---

## ADR-U2 · El rol es una etiqueta de producto, no un permiso

**Contexto.** “Vendedor”, “mentor”, “auditor” y “bienestar” son roles de
negocio. Si el rol concede permisos, el LLM podría escalar privilegios
cambiando una palabra.

**Decisión.** `agents.role_key` y `agents.role_profile` son metadata de
producto. Los permisos siguen siendo RBAC + permisos delegados del agente
(`agents/{id}/permissions`) + permisos efectivos del actor. El validador puede
exigir una política de rol, pero nunca derivar permisos de ella.

**Consecuencias.** Un rol “auditor” no puede leer más datos por llamarse así.
La política de rol solo restringe y guía.

**Alternativas descartadas.** Roles como scopes RBAC → escalada por prompt.

---

> Implementación 163: `agents.role_profile_id` referencia `role_profiles`.
> El rol sigue sin conceder permisos; el runtime solo estrecha tools.

## ADR-U3 · La política de rol se aplica de forma determinística, no solo por prompt

**Contexto.** Un prompt de “no diagnostiques” no impide que el modelo
diagnostique. Los flujos de bienestar tienen riesgo real.

**Decisión.** `safety_policy` se evalúa en tres puntos:

1. publicación: el validador exige política para roles sensibles;
2. pre-LLM: intención prohibida → respuesta segura/derivación sin llamar al
   modelo;
3. post-LLM: verificación de diagnóstico, prescripción, promesa de curación,
   disclaimer y escalado; si falla, se reemplaza la respuesta y se registra
   `safety_incident`.

La política es datos versionados (`zent.agent.role/v1`), no código por tenant.

**Consecuencias.** Más latencia mínima y una tabla de políticas. Se puede
auditar. Los falsos positivos se revisan como incidentes.

**Alternativas descartadas.**
(a) solo prompt → no verificable;
(b) clasificador LLM como único gate → probabilístico y costoso;
(c) prohibir el dominio → no cumple el objetivo de acompañamiento.

---

## ADR-U4 · La versión de agente gobierna la ejecución del workflow

**Contexto.** `AgentVersion` existe y promete un snapshot inmutable
(`entities.py:296-297`), pero el runtime de workflow usa el agente vivo
(`nodes.py:1998`). Un cambio de prompt altera workflows publicados.

**Decisión.** `llm.config.agent_version_id` es opcional. Al publicar, el backend
resuelve:

1. `agent_version_id` explícito;
2. `agents.default_version_id`;
3. versión `production`/`ready` más reciente;
4. si no hay versión, el agente vivo con `legacy_unpinned=true` y warning.

`AgentRuntime` resuelve `config_snapshot` de la versión y lo usa para prompt,
modelo, tools y config. El `workflow_versions.agent_versions` guarda el mapa.

**Consecuencias.** Reproducibilidad de workflows publicados. Los workflows
existentes siguen funcionando con fallback y quedan marcados para migración.

**Alternativas descartadas.**
(a) copiar el prompt en el grafo → duplica la fuente de verdad;
(b) no fijar versión → cambios silenciosos.

---

## ADR-U5 · Multi-agente se expresa con el DAG, no con un orquestador nuevo

**Contexto.** Se necesitan cadenas “vendedor → especialista → auditor” y varios
agentes en un workflow.

**Decisión.** Cada agente es un nodo `llm` con `agent_id` y
`agent_version_id`. El handoff es un edge explícito. El contrato de salida es
`text`, `structured`, `status`, `reason_codes`. El contexto se compone con
`context_assembler` y selectores. No hay llamadas directas entre agentes fuera
del grafo.

**Consecuencias.** Se reutiliza `execute_graph`, retries, timeouts, costos,
trazas y approvals. La UI puede mostrar qué agente ejecutó cada nodo.

**Alternativas descartadas.**
(a) `AgentOrchestrator` nuevo → motor paralelo;
(b) agentes que se llaman por tool → sin control de grafo ni costos.

---

## ADR-U6 · Arranque durable transparente en los disparadores existentes

**Contexto.** `wait_event`/`loop`/`state_*` exigen instancia, pero scheduler,
hook, evento y `/run` no la crean.

**Decisión.** Función pura `graph_requires_instance(graph)`. Si es verdadera,
los cuatro disparadores llaman `start_workflow_instance` con el mismo payload,
actor y correlation. Si es falsa, siguen con `run_workflow`. La decisión se
audita y se expone en el resultado.

**Consecuencias.** Los flujos durables funcionan desde cualquier disparador. No
se crea scheduler ni worker. Los flujos cortos no pagan instancia.

**Alternativas descartadas.**
(a) instancia para todos → costo innecesario;
(b) exigir `/instances` manual → fallo silencioso en producción.

---

## ADR-U7 · La certificación es evidencia, no un adorno

**Contexto.** La simulación existe y produce `READY_TO_PUBLISH`, pero el publish
no la consume. Además, una respuesta “pinned” declarada por el usuario no es
verificación de proveedor.

**Decisión.** `publish_workflow` exige `PublicationEvidence`:

- `certification_id`, `plan_hash`, `graph_hash`,
  `capability_snapshot_hash`;
- `effect_verification` (`NONE|DECLARED|SANDBOX|PROVIDER`);
- `coverage` y `scenario_completeness`;
- approvals.

Reglas:

- `DECLARED` con efectos externos → `AWAITING_EFFECT_VERIFICATION`, no
  `READY_TO_PUBLISH`;
- `SANDBOX`/`PROVIDER` → puede ser `READY_TO_PUBLISH`;
- hashes distintos → stale, denegado;
- sin certificación → según flag `report|warn|block`.

**Consecuencias.** El usuario ve exactamente qué se probó. Un workflow con
pagos no se publica solo porque el escenario inventó una respuesta.

**Alternativas descartadas.**
(a) confiar en el estado de la sesión → se puede publicar otro grafo;
(b) aceptar pins como verdad → falsa certificación.

---

## ADR-U8 · Un solo storefront: `/api/v1/products`

**Contexto.** Conviven `/api/v1/marketplace` (ecosistema), `/api/v1/products`
(catálogo unificado) y `/api/v1/integrations` (ejecución/admin). El canvas usa
integraciones, el marketplace usa productos.

**Decisión.** `/api/v1/products` es el **único storefront** (descubrimiento,
instalación, actualización, reviews). `/api/v1/integrations` queda como
superficie de ejecución/administración de instalaciones y credenciales, no como
catálogo de descubrimiento. `/api/v1/marketplace` queda legacy read-only y se
marca `Deprecation`/`Sunset`.

**Consecuencias.** Un solo lugar para descubrir; el canvas migra a productos.
No se borran rutas legacy antes de la ventana de compatibilidad.

**Alternativas descartadas.**
(a) mantener tres catálogos → duplicación;
(b) borrar legacy de golpe → rompe integraciones y admin.

---

## ADR-U9 · Operación workspace-scoped y sin estado nuevo

**Contexto.** Hay runs, instancias, aprobaciones y costos, pero no una consola
operativa. Las instancias no filtran workspace.

**Decisión.** `studio_operations` es una **vista read-only** sobre
`workflow_runs`, `workflow_instances`, `workflow_run_steps`,
`workflow_approvals`, `usage_events` y `audit_logs`. Filtra por organización y
workspace. No escribe estado. Las acciones (señal, cancelar, aprobar) llaman a
los endpoints existentes.

**Consecuencias.** No se duplica el estado. La consola puede borrarse sin
afectar ejecución.

**Alternativas descartadas.**
(a) tabla de operaciones → estado paralelo;
(b) solo inspector por run → no hay operación global.

---

## ADR-U10 · Rollout por fases con flags y rollback de datos

**Contexto.** Universalizar toca creación, publicación y ejecución. Un cambio
global puede romper workflows existentes.

**Decisión.** Flags por fase (`UNIVERSAL_STUDIO_ENABLED`,
`STUDIO_SOLUTIONS_ENABLED`, `AGENT_ROLE_POLICIES_ENABLED`,
`WORKFLOW_CERTIFICATION_GATE`, `WORKFLOW_DURABLE_TRIGGERS_ENABLED`,
`WORKFLOW_RUN_BUDGETS_ENABLED`, `MARKETPLACE_UNIFIED_CANVAS`,
`STUDIO_OPERATIONS_ENABLED`). Defaults conservadores. Rollback:

- código: flag off;
- datos: columnas aditivas nullable, sin borrar;
- workflows: versiones publicadas e instancias no se mutan;
- certificación: se conserva como evidencia histórica.

**Consecuencias.** Se puede adoptar por org/workspace. El costo es mantener
caminos duales durante la ventana.

**Alternativas descartadas.**
(a) big bang → riesgo de regresión;
(b) migraciones destructivas → rompe instancias vivas.

---

## ADR-U11 · El LLM no puede crear ni publicar roles, agentes o workflows por sí solo

**Contexto.** El intake universal recibe texto libre y podría intentar crear
agentes/workflows directamente.

**Decisión.** El LLM solo produce `SolutionBlueprint`/`SemanticPlan`. El backend:

- descubre capacidades y recursos;
- valida y compila;
- exige aprobación humana para materializar agentes/workflows;
- nunca instala, conecta credenciales, concede permisos ni publica desde el
  LLM.

**Consecuencias.** Un paso humano explícito entre “propuesta” y “publicado”.
La UI muestra el diff y los requisitos.

**Alternativas descartadas.** Auto-publicación → viola “LLM propone; backend
valida, autoriza”.

---

## ADR-U12 · El marketplace de roles usa `COMPOSITE_PACK`, no un tipo nuevo

**Contexto.** Se necesitan packs de rol (agente + workflow + políticas).

**Decisión.** Un pack de rol es un `COMPOSITE_PACK` con
`applies_to=["AGENTS","WORKFLOWS"]` y `included_assets` que referencian
`AGENT_TEMPLATE` + `WORKFLOW_TEMPLATE`. No se crea `ROLE_PACK` ni una tienda
nueva.

**Consecuencias.** Se reutilizan dependencias tipadas, publishing gate,
rollout y analytics. El `role_key` viaja en metadata del asset.

**Alternativas descartadas.** Tipo nuevo → duplica el factory y el gate.
