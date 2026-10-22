# ADR — RoleProfiles, Solutions and runtime narrowing

- **Estado:** aceptado e implementado
- **Fecha:** 2026-10-21
- **Contexto:** Universal Agent & Workflow Studio, Prompt 00
- **Migración:** `163_role_profiles_and_solutions.py`
- **Contratos:** `zent.role/v1`, `zent.solution/v1`, `zent.session.ref/v1`

## Contexto

El sistema ya tenía Agents, Workflows, versiones de Agent, templates de
workflow, packages portables, design sessions y workflow instances. Faltaba una
identidad funcional reutilizable (rol) y una composición portable (solución).
El riesgo era resolverlo creando un segundo registro de agentes, un “Assistant”
nuevo o condicionales de profesión dentro del motor.

## Decisión 1 — RoleProfile es una entidad de identidad, no un Agent

`role_profiles` guarda misión, audiencia, competencias, límites, autonomía,
handoff, conocimiento declarativo, métricas y safety. `agents.role_profile_id`
es una FK nullable. Un rol no contiene prompt operativo, modelo, tools físicas ni
credenciales.

**Consecuencias.** Un mismo rol puede vincularse a varios agentes; un agente
puede cambiar de rol sin duplicar su runtime. `Assistants` sigue siendo una
proyección, no una entidad.

**Alternativas descartadas.** Reemplazar `agents` por roles; añadir reglas
`if role == "mentor"` al motor; crear una tabla `assistant`.

## Decisión 2 — Solution es un artefacto de diseño e instalación

`studio_solutions` guarda un `SolutionV1` en JSONB con refs lógicas a roles,
agentes, workflows, capacidades, conocimiento, canales, requisitos e
instrucciones de instalación. No ejecuta ni copia entidades.

**Consecuencias.** Exportar/importar una solución no filtra UUIDs de tenant ni
secretos. La instalación resuelve refs contra el catálogo real del tenant. Los
agentes y workflows vivos se crean con las APIs existentes y conservan sus
propias versiones.

**Alternativas descartadas.** Guardar la solución como `workflows.metadata`
(mezcla diseño con ejecución); ejecutar el blueprint directamente (motor
paralelo).

## Decisión 3 — El rol solo restringe; la autoridad es una intersección

`capability_decision` combina permisos del actor, identidad de servicio,
política de tenant, capacidades instaladas y restricciones del rol. Un rol no
puede añadir una capacidad ni un permiso.

En ejecución, `_exec_llm` carga el rol activo del agente y aplica
`filter_agent_tools` antes de construir `AgentRunRequest`. La autonomía
`answer_only`/`propose_actions` reduce las tools a lectura; las acciones
importantes de roles `high`/`regulated` requieren aprobación.

**Consecuencias.** El mismo workflow y el mismo `AgentRuntime` siguen siendo el
camino de ejecución. La seguridad no depende solo del prompt.

**Alternativas descartadas.** Convertir roles en scopes RBAC; confiar en el
system prompt; crear un runtime “seguro” separado.

## Decisión 4 — Las plantillas son borradores determinísticos

`src/platform/studio/templates.py` define seis plantillas mínimas. La propuesta
es determinística, marcada `source=template`, `requires_review=true` y
`publishable=false`. El usuario edita la hoja de misión y guarda un draft.

**Consecuencias.** No hay proveedores, precios ni esquemas de DB hardcodeados.
El LLM no publica roles por sí solo. Un usuario nuevo puede empezar sin conocer
el motor.

**Alternativas descartadas.** Generar y publicar automáticamente con un LLM;
incluir integraciones concretas en la plantilla.

## Decisión 5 — Tres sesiones, tres ciclos de vida

No se crea una tabla `sessions`. `zent.session.ref/v1` y
`/api/v1/studio/sessions/resolve` distinguen:

- `conversation`: chat del usuario final (`chat_events`/`conversation_id`);
- `design`: `workflow_design_sessions`;
- `workflow_instance`: `workflow_instances`, con `conversation_id` como enlace
  suave.

**Consecuencias.** Una sesión de diseño no se confunde con una instancia durable
ni con una conversación. Los IDs siguen siendo locales al tenant y no entran en
paquetes portables.

## Decisión 6 — Reglas de seguridad para funciones reguladas

El contrato rechaza secretos y IDs no portables. Wellness exige no diagnóstico,
no pretensión de psicoterapia, escalado de crisis y derivación. Los roles
`regulated` exigen triggers de handoff y no pueden desactivar la protección de
acciones irreversibles.

**Consecuencias.** El comportamiento seguro es parte del contrato y de la
validación, no una condición especial del motor. La derivación y la aprobación
humana son explícitas y auditables.

## Consecuencias de migración

- `163` es aditiva: crea `role_profiles`, `role_profile_versions`,
  `studio_solutions`, `studio_solution_versions` y añade
  `agents.role_profile_id`.
- No renombra ni elimina columnas existentes.
- `ensure_role_tables()` y `ensure_solution_tables()` permiten paridad en tests;
  la migración es la ruta canónica de producción.
- El rollback elimina solo las tablas/columna nuevas.

## Evidencia

Ver [`README.md`](README.md) §9 y `tests/test_role_profiles.py`,
`tests/test_studio_migrations.py`, `portal/src/pages/RoleStudio.test.tsx`.
