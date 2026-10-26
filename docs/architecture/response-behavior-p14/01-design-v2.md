# P14 — Response Behavior Engine V2

## 1. Autoridad única

`src/intelligence/response/profile.py` es la autoridad de presets. El portal
consume `GET /api/v1/agents/response-profile/catalog` y ya no define deltas de
perfil. El catálogo devuelve `schema`, `presets` (perfil completo resuelto),
`blueprints` y `defaults`.

`ResponseProfile` mantiene compatibilidad y añade:

- `profile_id`, `profile_version`
- `communication_strategy`
- `detail_budget`
- `structure_policy`
- `example_policy`
- `analysis_depth`
- `terminology_policy`
- `source_presentation_policy`
- `audience_assumptions`
- `override_origin`

`ResponseContract` lleva los campos efectivos, `effective_profile_hash`,
`turn_overrides`, `style_degraded` y `style_degradation_reason`.

## 2. Estrategias por perfil

| Perfil | Estrategia | Estructura | Ejemplos | Análisis |
|---|---|---|---|---|
| Equilibrado | `adaptive` | adaptativa | cuando aportan | proporcional |
| Preciso | `definition_scope` | definición/condiciones/alcance | nunca | exacto y superficial |
| Claro y didáctico | `progressive` | simple → porqué → ejemplo | mínimo sustentado | progresivo |
| Experto técnico | `implementation_first` | contrato → flujo → límites | mínimo | implementación |
| Ejecutivo | `decision_first` | decisión → impacto → riesgo → acción | nunca | impacto |
| Conciso | `answer_only` | respuesta directa | nunca | respuesta |
| Analítico | `decompose_compare` | problema → alternativas → criterios → conclusión | cuando aportan | hipótesis y trade-offs |
| Con evidencia | `claim_evidence` | afirmación → evidencia → inferencia → faltante | cuando aportan | evidencia primero |

Las citas obligatorias del blueprint o del pack **no se apagan** con ningún
perfil. El perfil decide presentación inline/on-request, no la existencia de la
cita.

## 3. Precedencia

1. Políticas de seguridad y evidencia (no negociables).
2. Petición explícita del turno (`respóndeme corto`, `nivel experto`, etc.).
3. Perfil guardado del agente (o perfil temporal del preview).
4. Defaults del sistema.

El turno se registra en `turn_overrides` y `override_origin=turn_override`; no
se persiste. El preview recibe un `profile` temporal y no escribe en el agente.

## 4. Rutas cubiertas

- Agent Runtime ReAct y finalizer: `prompt_block` recibe el perfil del
  `ResponsePlan`.
- RAG Orchestrator: usa el config completo de la organización y antepone el
  perfil al prompt.
- Fast path determinista: `personality_for_agent` aplica perfil + overrides y
  publica `personality` en la telemetría del compositor.
- Preview: perfil temporal explícito, evidencia simulada y `tools_executed=false`.
- Comparador A/B: mismo modelo, pregunta y evidencia; no ejecuta herramientas y
  no persiste.

## 5. Observabilidad

La traza publica:

- `flow.response.profile` (perfil solicitado/resuelto)
- `flow.response_contract` (perfil aplicado, estrategia, hash, overrides)
- `style_degraded` + motivo cuando el contrato no se aplicó
- `flow.fast_path.response_composer.personality` en fast path

La UI muestra **Perfil solicitado → aplicado → validación** en el preview y una
línea compacta en el Playground (`agent-profile-trace`).
