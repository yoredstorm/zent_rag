# P14 — Auditoría de comportamiento de respuesta

Fecha: `2026-10-26`. Base: HEAD de `yoredstorm/zent_rag` antes de P14.

## 1. Hallazgos reproducibles

1. **El perfil RAG se leía del lugar equivocado.** `orchestrator.py` pasaba
   `(organization.config_json or {}).get("response_profile")` a
   `compose_for_request`; esa función espera el config completo. El doble `get`
   convertía cualquier perfil en `ResponseProfile()` (Equilibrado). Además el
   perfil del agente nunca entraba por esa ruta.
2. **El bloque de perfil no llegaba al prompt normal.** `prompt_block` sólo
   anteponía `profile_prompt_block` si recibía `profile=`, y los tres llamadores
   (`orchestrator`, `AgentRuntime`, preview) lo omitían. El estilo sólo existía
   en el compositor del fast path.
3. **Campos del perfil inertes:** `use_examples`, `show_uncertainty` y
   `show_practical_implications` no se traducían a instrucciones en el contrato.
4. **Presets clonados entre Python y TypeScript**, con divergencia real
   (`technical_detailed.audience` era `expert` en TS y `technical` en Python).
   El endpoint `/response-profile/catalog` existía pero el portal no lo usaba.
5. **Cambiar de preset heredaba campos del anterior** en
   `AgentResponseProfileSection` (`{...profile, ...preset.profile}`). Analítico →
   Conciso conservaba, por ejemplo, `use_examples=true`.
6. **El preview usaba el perfil guardado**, no el temporal; no había forma de
   previsualizar cambios sin guardar.
7. **`contract_from_public` era lossy**: perdía estrategia, hash, overrides,
   presentación y límites. No se podía reconstruir el contrato desde la traza.
8. **Las citas obligatorias se apagaban** con `cite_sources=false` del perfil
   (Ejecutivo/Conciso), violando la regla de no suprimir evidencia obligatoria.
9. **No había comparador A/B** ni traza "solicitado → aplicado → validación".
10. **IDs DOM duplicados** `response-preset-*` entre el panel de Diseño y el
    avanzado.

## 2. Recorrido auditado

```
UI Agent Studio
  -> /api/v1/agents (config.response_profile)
  -> agent.config_json
  -> profile_from_config
  -> compose_for_request -> compose_contract
  -> prompt_block + profile_prompt_block
  -> AgentRuntime / RAGOrchestrator / preview / fast path
  -> flow.response + flow.response_contract
```

## 3. Fuera de alcance de esta fase

- No se creó un segundo motor, planner, catálogo ni esquema por profesión.
- No se cambiaron hechos, reglas de dominio ni políticas de seguridad.
- La evaluación con proveedor real y usabilidad quedan como gates externos
  (`NOT_VERIFIED`), no como PASS.
