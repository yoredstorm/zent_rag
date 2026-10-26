# P14 — Evidencia de ejecución

Fecha: `2026-10-26`.

## 1. Backend

```powershell
uv run --frozen --no-sync pytest tests/test_response_profiles_v2.py \
  tests/test_response_intelligence.py tests/test_response_presentation.py \
  tests/test_response_composer.py tests/test_agent_api.py -q
```

Resultado: **143 passed** (regresión + 8 casos P14). Tras añadir la traza de
personalidad al compositor: **152 passed** en la misma matriz.

```powershell
uv run --frozen --no-sync pytest tests/test_narrative_fast_path.py \
  tests/test_deterministic_fast_path.py tests/test_response_composer_benchmark.py \
  tests/test_prompt_assembly.py tests/test_agent_flow_v2.py \
  tests/test_portal_ia.py -q
```

Resultado: **140 passed**.

Casos P14 (`tests/test_response_profiles_v2.py`):

- los 8 presets tienen estrategia operativa distinta;
- config completo y sub-dict producen el mismo perfil;
- el contrato lleva estrategia, hash, origen y roundtrip no lossy;
- el override de turno queda auditado sin cambiar el perfil guardado;
- `ResponsePlan` publica perfil solicitado y aplicado;
- preview con perfil temporal no persiste;
- guardado sólo del perfil reemplaza campos del preset anterior;
- comparador A/B usa misma evidencia, no ejecuta herramientas y rechaza
  perfiles desconocidos.

## 2. Portal

```powershell
cd portal
npm run typecheck
npm run build
npx vitest run src/components/agentStudio/agentModes.test.ts \
  src/components/agentStudio/types.test.ts src/pages/AgentStudio.test.tsx
```

Resultado: **71 passed**, typecheck OK, build OK. Lint: 0 errores
(1 warning preexistente de `AgentSourcePicker.tsx`).

Casos nuevos:

- `Analítico → Conciso` elimina `use_examples`, `use_tables` y
  `analysis_depth` del perfil anterior;
- preview envía el perfil temporal y muestra `Solicitado → Aplicado →
  validación`, con evidencia simulada y sin herramientas;
- comparador A/B muestra variantes y aplica una al borrador sin guardar;
- catálogo del backend con 8 presets en el Agent Studio.

## 3. E2E

Spec: `portal/e2e/agent-response-profiles.spec.ts`.

Flujo: crear agente por API → login → abrir `?panel=advanced&tab=response` →
verificar los 8 presets del catálogo → elegir Conciso → guardar → verificar por
API `profile_id=concise`, `structure_policy=answer_only` → recargar → verificar
que Conciso sigue seleccionado y no aparece “Personalizado”.

Resultado contra Docker local (`http://127.0.0.1:8080`): **1 passed**.
El agente se eliminó al final del test; no quedó data de prueba.

## 4. Limitaciones

- No se ejecutó un proveedor LLM real ni un dataset ≥100/dominio: las
  diferencias semánticas medidas con modelo real quedan `NOT_VERIFIED`.
- La comparación A/B usa la misma evidencia simulada y no mide coste/latencia
  de un proveedor real.
- La usabilidad con ≥5 personas queda `NOT_VERIFIED`.
- El fast path determinista conserva el estilo vía compositor, pero no se
  reescribe por presupuesto/validación; en ese caso la traza lo declara
  (`personality.applied`, `skip_reason`) en lugar de simular éxito.
