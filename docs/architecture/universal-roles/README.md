# Universal Roles & Solutions — implemented slice

> Estado: implementado sobre el runtime existente. No crea un segundo registro
> de agentes ni un motor de workflows alterno.
>
> Migración canónica: `163_role_profiles_and_solutions.py`.
> Contratos: `zent.role/v1`, `zent.solution/v1`, `zent.session.ref/v1`.

## 1. Qué se agregó y qué no

| Concepto | Dónde vive | Qué es | Qué no es |
|---|---|---|---|
| **RoleProfile** | `role_profiles` + `role_profile_versions` | Identidad funcional, misión, público, competencias, límites, autonomía, handoff y métricas. | No razona, no tiene tools, no ejecuta workflows. |
| **Agent** | `agents` (existente) | Instancia de razonamiento y herramientas. `role_profile_id` es nullable. | No se duplica: no hay tabla `assistant` ni `role_agent`. |
| **Workflow** | `workflows` / grafo existente | Proceso versionado con trigger, nodos, estado y acciones. | No contiene la identidad del rol. |
| **Solution / Blueprint** | `studio_solutions` + `studio_solution_versions` | Composición reusable de roles, agentes, workflows, capacidades, conocimiento y requisitos. | No ejecuta; es un artefacto de diseño e instalación. |
| **Session** | `conversation_id`, `workflow_design_sessions`, `workflow_instances` | Distingue chat de usuario, diseño y proceso durable. | No se creó una tabla `sessions` que mezcle ciclos de vida. |

`Assistants` sigue siendo una **proyección** de agentes + workflows
(`/api/v1/agents/assistants`), no una entidad nueva.

## 2. Flujo de creación

1. La persona escribe **“Describe la función”**.
2. `POST /api/v1/studio/roles/propose` propone un borrador determinístico desde
   una plantilla mínima: misión, público, límites, autonomía, handoff, métricas
   y un proceso sugerido.
3. La persona revisa la **hoja de misión**: qué hará, qué no hará, qué necesita
   y cuándo deriva.
4. `POST /api/v1/studio/roles` guarda un **draft** editable.
5. Un agente existente se vincula con
   `POST /api/v1/studio/agents/{agent_id}/role`.
6. Revisión y prueba ocurren en Agent Studio/Workflow Studio. El borrador no se
   publica automáticamente.
7. Desde la misma hoja se puede crear una **solución borrador** que agrupa el
   rol, el proceso sugerido y sus requisitos; no instala ni publica nada.

La pantalla vive en `/roles` (`portal/src/pages/RoleStudio.tsx`) y aparece en
**Construir → Roles**.

## 3. Autoridad efectiva

Un rol **nunca eleva** permisos. La autoridad efectiva es la intersección de:

```
permisos del actor
∩ identidad de servicio
∩ política del tenant
∩ capacidades instaladas
∩ restricciones del rol
```

`src/platform/studio/policy.py` implementa la intersección y la decisión por
capacidad. `src/platform/studio/roles.py` aplica el estrechamiento de
herramientas antes de ejecutar un agente. En `_exec_llm` el agente se reemplaza
con `dataclasses.replace` y solo recibe las tools que el rol permite; el
workflow y el `AgentRuntime` siguen siendo los mismos.

Niveles de autonomía:

- `answer_only`: responder; no ejecuta escrituras.
- `propose_actions`: propone; no ejecuta escrituras.
- `execute_reversible`: puede ejecutar acciones reversibles bajo política.
- `require_approval`: en el runtime de tools queda en lectura; toda consecuencia
  importante debe pasar por un nodo de aprobación explícito.

Una capacidad regulada de un rol `regulated` no obtiene autoridad automática:
siempre necesita handoff y aprobación cuando la acción no es de lectura.

## 4. Contrato y portabilidad

`RoleProfileV1` incluye IDs estables, `name`/`display_name`, misión, audiencia,
competencias, constraints, `allowed_capabilities`, `knowledge_scope`,
`memory_policy`, `autonomy_level`, `human_handoff`, `expected_outcomes`,
`evaluation_rubric`, `risk_class`, locales, compliance tags y versión.

`SolutionV1` incluye refs lógicas (no UUIDs de tenant) para roles, agentes,
workflows, capacidades, conocimiento, canales, requisitos e instalación.

Reglas de seguridad del contrato:

- rechaza claves como `password`, `api_key`, `token`, `organization_id`,
  `workspace_id`, `tenant_id`, `credential_ref`;
- rechaza connection strings (`postgres://`, `redis://`, etc.);
- rechaza IDs físicos y bindings en paquetes exportables;
- `record_id` es un puntero local de API/UI y se excluye de todo dump portable;
- wellness exige `no_medical_diagnosis`, `no_psychotherapy_claim`,
  `crisis_escalation` y un destino de derivación.

## 5. N:M y versiones

- Un agente puede aparecer en varios `workflow_refs`.
- Un workflow puede declarar varios `agent_refs` y varios `role_refs`.
- Una solución puede agrupar varios roles, agentes y workflows.
- Editar un rol crea una nueva revisión y snapshot; no reescribe las versiones
  anteriores ni las instancias de workflow ya ejecutadas o en curso.
- Los snapshots viven en `role_profile_versions` y
  `studio_solution_versions`.

## 6. Plantillas mínimas

`GET /api/v1/studio/templates` devuelve:

`sales_advisor`, `tutor`, `mentor`, `support_agent`, `auditor`,
`wellness_companion`.

No contienen proveedores, precios, esquemas de DB ni IDs de tenant. Son drafts
editables, no roles publicados. Sus `allowed_capabilities` son refs lógicas de
diseño; la instalación de una `Solution` las resuelve contra el catálogo real
del tenant y nunca las inventa.

## 7. API

Prefijo: `/api/v1/studio`.

| Método | Ruta | Permiso RBAC |
|---|---|---|
| GET | `/templates` | `agents:read` |
| POST | `/roles/propose` | `agents:read` |
| GET/POST | `/roles` | `agents:read` / `agents:write` |
| GET/PUT/DELETE | `/roles/{id}` | `agents:read` / `agents:write` |
| POST | `/roles/{id}/clone` | `agents:write` |
| GET | `/roles/{id}/versions` | `agents:read` |
| GET | `/roles/{id}/versions/{revision}` | `agents:read` |
| GET | `/roles/{id}/export` | `agents:read` |
| POST | `/roles/import` | `agents:write` |
| GET | `/roles/{id}/mission-sheet` | `agents:read` |
| GET/POST | `/agents/{id}/role` | `agents:read` / `agents:write` |
| GET/POST | `/solutions` | `workflows:read` / `workflows:create` |
| GET/PUT | `/solutions/{id}` | `workflows:read` / `workflows:create` |
| POST | `/solutions/{id}/clone` | `workflows:create` |
| GET | `/solutions/{id}/versions` | `workflows:read` |
| GET | `/solutions/{id}/versions/{revision}` | `workflows:read` |
| GET | `/solutions/{id}/export` | `workflows:read` |
| POST | `/solutions/import` | `workflows:create` |
| POST | `/solutions/validate` | `workflows:read` |
| GET | `/solutions/{id}/install-plan` | `workflows:read` |
| POST | `/sessions/resolve` | `rag:read` |

La autorización de endpoints usa permisos existentes. El rol de negocio no es
un scope RBAC.

## 8. Separación de funciones reguladas

- Bienestar general no se presenta como psicología licenciada ni psicoterapia.
- No diagnostica, no prescribe y no promete curación.
- Crisis/autolesión/violencia derivan a emergencia o persona de confianza.
- Auditoría, finanzas, legal y clínica son `high`/`regulated`: requieren
  políticas explícitas y aprobación humana para consecuencias.
- La autoridad no se deriva del nombre del rol.

Ver `ADR-role-profiles.md` y los ejemplos:

- [`examples/mentor-role.json`](examples/mentor-role.json)
- [`examples/auditor-role.json`](examples/auditor-role.json)
- [`examples/audit-solution.json`](examples/audit-solution.json)
- [`examples/wellness-role.json`](examples/wellness-role.json)

## 9. Pruebas y evidencia

Comandos ejecutados para esta slice:

```bash
.venv/Scripts/python.exe -m pytest tests/test_role_profiles.py tests/test_studio_migrations.py -q
cd portal && npm run typecheck && npx vitest run src/pages/RoleStudio.test.tsx
```

Cobertura de las pruebas:

- contrato JSON, secretos, IDs no portables y migración 163;
- create/edit/version/clone/export/import y cross-tenant;
- rol vinculado a un agente y tools estrechadas en una ejecución real del
  workflow (runtime falso, sin proveedor);
- N:M agente↔workflows y workflow↔agentes;
- snapshot de versión inmutable tras editar;
- propuesta UX para usuario nuevo y hoja de misión;
- sesiones de conversación/diseño/instancia resueltas por separado.

Resultados locales de esta slice (2026-10-21):

- backend: `22 passed` (`tests/test_role_profiles.py` + `tests/test_studio_migrations.py`);
- portal: `14 passed` en 2 archivos (`RoleStudio.test.tsx`, `nav.test.ts`);
- `tsc --noEmit`: sin errores;
- migración: `alembic downgrade 162` → `upgrade head` → `163 (head)` sin error;
- tablas verificadas: `role_profiles`, `role_profile_versions`,
  `studio_solutions`, `studio_solution_versions` y `agents.role_profile_id`.

La ejecución con proveedor real no es parte de esta evidencia; las pruebas de
runtime usan el `_FakeRuntime` existente.
