# P13 — 08 P04: composer universal

## 1. Contratos

`src/platform/studio/mission_contracts.py`:

- `MissionSpec` (`zent.mission/v1`)
- `CapabilityPlan` (`zent.capability_plan/v1`)
- `SolutionBlueprint` = alias explícito de `SolutionV1` (`zent.solution/v1`)
- `ValidatedWorkflowGraph` (`zent.validated_workflow_graph/v1`)
- `MaterializationPlan` (`zent.materialization_plan/v1`)

No se creó un segundo blueprint, planner ni catálogo.

## 2. Modos

`compile_solution(mode=...)` y `POST /studio/solutions/{compile,materialize}`:

| Modo | Comportamiento |
|---|---|
| `auto` | Plantilla si hay match de función; si no, composición |
| `template` | Fuerza plantilla; error si no existe |
| `compose` | Fuerza Architect + composición |
| `hybrid` | Plantilla si cubre; si no, composición |

La composición llama `architect.plan_workflow` con descubrimiento real de
capacidades y validación server-side. Si no hay proveedor LLM, usa el fallback
heurístico del Architect. Si ese fallback cae en un brief de ventas sin datos,
se aplica una composición determinista mínima solo cuando la misión no pide
ERP/pago/DB/CRM. Nunca inventa conectores: si pide una integración ausente,
devuelve `NEEDS_CONFIGURATION`.

El grafo compuesto se persiste en `compilation.graph`; `materialize_solution`
lo usa en vez de `_build_graph` y vincula el agente real a cada nodo `llm`.

## 3. UX

`SolutionBuilder.tsx` agrega selector Automático / Híbrido / Composición nueva /
Solo plantilla y muestra si el resultado es plantilla o composición.

## 4. Pruebas

```powershell
uv run --frozen --no-sync pytest tests/test_solution_composer.py -q
```

Resultado: **4 passed**.

- misión sin palabra de plantilla → `template_id=composed`, grafo con `llm`;
- materialización real → workflow draft con `agent_id` en todos los `llm`;
- misión con ERP/pago ausente → no inventa; `graph=null` y bloqueos;
- modo `template` sigue devolviendo la plantilla Mentor.

Regresión: `tests/test_solution_compiler.py` 9 passed.

## 5. Límites

- La calidad con LLM real y dataset ≥100/dominio queda `NOT_VERIFIED`.
- La composición determinista es deliberadamente conservadora: trigger, LLM,
  aprobación y notificación. No sustituye la evaluación semántica con proveedor.
- No se materializan bindings/KB automáticamente.
