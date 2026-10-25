# P13 — 05 P03: política efectiva y PEP universal

SHA base: `b31b01402a2e10008eb09b77c148e48120af6004`.
Migración: `172_workflow_effective_policy.py`.

## 1. Modelo

`EffectiveExecutionPolicy` es inmutable, versionado y serializable:

- organización, workspace, workflow, solución, actor y tipo de actor;
- RBAC efectivo;
- scope de capacidades del workflow/solución;
- bindings por agente con rol, versión, revisión, autonomía y risk class;
- hash de bindings instalados;
- autonomía máxima, aprobación requerida, privacidad y límites;
- safety profile;
- revocaciones activas;
- `definition_source`;
- `policy_hash`.

El backend la calcula desde entidades persistidas. No se acepta rol, scope,
autonomía ni `system_context` desde payload, metadata del LLM o body.

## 2. Intersección

`ALLOW` solo si se cumple:

```text
RBAC actor/servicio
∩ scope workflow/solución
∩ rol del agente aplicable
∩ bindings instalados
∩ política de la acción
∩ aprobaciones exigidas
```

Reglas:

- Nodo sin `agent_id`: usa el scope del workflow/solución. No toma el rol de un
  agente arbitrario.
- Nodo con `agent_id`: el agente debe existir/estar activo; su rol solo puede
  recortar el scope.
- Dos agentes: cada nodo usa su propio rol; no hay unión.
- Subworkflow: intersección con la política padre.
- Wellness: bloquea clínicas y escrituras autónomas incluso sin agente.
- `llm` sin agente: DENY en published/instance; draft manual conserva eco
  marcado para pruebas.
- Acción irreversible con `approval_required`: DENY sin aprobación.

## 3. PEP

`policy_enforcement.authorize_node` retorna:

```json
{
  "allowed": false,
  "code": "policy.scope_exceeded",
  "reasons": ["payments.checkout.create está fuera del scope"],
  "capability_ref": "payments.checkout.create",
  "effective_scope_hash": "sha256",
  "approval_required": false,
  "policy_version": "v1"
}
```

El PEP se aplica en `runtime.run_node` y en `_run_node_once` (ramas for_each).
Las instancias congelan la política en `definition_snapshot.policy_snapshot`;
al reanudar se usa el snapshot + revocaciones, no el rol vivo.

## 4. Migración 172

- `workflows.capability_scope`, `capability_scope_source`, `safety_profile`,
  `policy_version`, `solution_id`.
- `workflow_runs.effective_policy`, `effective_scope_hash`.
- `workflow_instances.policy_hash`.
- `workflow_policy_revocations`.
- Backfill de scope desde nodos existentes, marcado `legacy_baseline`; no
  amplía autoridad.
- El compilador de soluciones fija `capability_scope_source='solution'` y el
  scope del blueprint; publicar un workflow manual lo fija desde el grafo.

## 5. Aislamiento workspace

- `_workspace_id` valida el header contra `workspaces.organization_id`.
- Dependencia central `_validate_workflow_workspace` en todas las rutas con
  `workflow_id`: 404 si el workflow pertenece a otro workspace.
- Header de otra organización: 404 sin revelar existencia.
- Sin workspace resoluble para un workflow con workspace: 400
  `workspace_required`.
- Versiones y certificados filtran workspace; promote/restore usan
  `workflow_id + organization_id + workspace_id`.

## 6. Pruebas

```powershell
uv run --frozen --no-sync pytest tests/test_workflow_effective_policy.py -q
```

Resultado: **7 passed**.

- capability_call sin agente fuera de scope → DENY;
- wellness sin agente → DENY;
- capacidad revocada → DENY;
- dos agentes sin unión de privilegios;
- simulación aplica la misma política;
- solución real (vendedor) + capability de pago inyectada sin agente → DENY
  `policy.scope_exceeded`;
- lectura/edición por workflow_id desde otro workspace → 404.

Regresión: `test_workflow_graph.py`, `test_workflow_composition.py`,
`test_policy_enforcement.py`, `test_workflow_workspace_isolation.py`
**39 passed**; `test_solution_compiler.py`, `test_workflow_studio.py`,
`test_workflow_publication_gate.py`, `test_workflows.py`,
`test_workflow_test_studio.py` **47 passed**; durables **34 passed**.

## 7. Riesgos

- Agentes activos sin RoleProfile conservan RBAC + scope; no se inventa un rol.
  Una política futura puede exigir RoleProfile obligatorio.
- Instancias históricas sin `EffectiveExecutionPolicy` se re-resuelven y pueden
  DENY si falta un dato crítico.
- La UI de denegaciones muestra código/razones, pero el estudio de usabilidad
  queda `NOT_VERIFIED`.
