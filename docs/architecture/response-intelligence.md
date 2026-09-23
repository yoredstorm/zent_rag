# Response Intelligence — cómo Zent explica lo que sabe

> Evidence Reasoning determina **qué puede concluirse**.
> Response Intelligence determina **cómo explicarlo**.
> Nunca cambia hechos.

Esta capa no agrega un subsistema LLM: se integra al pipeline actual y su salida
es un objeto observable (`ResponseContract`) que el generador recibe como
**instrucción de forma** y la Execution Story muestra como **dato**.

```
Evidence → Reasoning → Verified Conclusion → Response Blueprint
        → Response Contract → Generator → Claim Verification
```

## 1. Principio: el código decide, el generador escribe

- La **forma** (blueprint) se elige por **reglas**; JEV sólo entra cuando dos
  formas quedan empatadas de verdad.
- El **nivel de detalle** lo pide el caso (`required_detail`), no el perfil por
  sí solo: un dato puntual no se convierte en artículo.
- El **contrato** compone secciones, formato y política de evidencia. No contiene
  hechos ni conclusiones.
- **Sin cadena de pensamiento**: el contrato y el prompt no exponen razonamiento
  privado. Sólo hechos, veredictos y métricas.

## 2. Response Blueprint (§3, §10-§16)

Catálogo **extensible** en `src/intelligence/response/blueprints.py`
(`register_blueprint` agrega formas sin tocar el selector ni el contrato).

| Blueprint | Para qué sirve | Secciones por defecto |
|---|---|---|
| `direct_fact` | Un dato puntual | respuesta directa |
| `definition_explanation` | Definir y ubicar un concepto | definición, para qué sirve, dónde interviene |
| `technical_explanation` | Qué significa un campo/valor y qué implica | respuesta directa, significado, implicación, ejemplo, límites |
| `scenario_analysis` | Concluir sobre una secuencia | respuesta directa, secuencia, por qué, alternativa descartada, qué verificar |
| `diagnostic` | Por qué ocurrió algo | causa, evidencia, secuencia, qué revisar, límites |
| `comparison` | Contrastar opciones | comparación (tabla), implicación, evidencia |
| `procedure` | Cómo hacer algo | pasos, qué revisar, límites |
| `data_interpretation` | Leer un conjunto de datos | respuesta directa, lectura, implicación |
| `executive_summary` | Lo esencial sin detalle | resumen, implicación, límites |
| `tutorial` | Enseñar desde los fundamentos | respuesta directa, significado, ejemplo, pasos, dónde aplica |

## 3. Selección (§4)

Determinista, por estructura de la pregunta, forma de razonamiento e intent:

| Pregunta | Forma |
|---|---|
| «¿Qué es X?» | `definition_explanation` |
| «¿Qué significa byte 105 con valor 2?» | `technical_explanation` |
| «¿Falta un registro?» | `scenario_analysis` |
| «¿Por qué falló?» | `diagnostic` |
| «X vs Y» | `comparison` |
| «¿Cómo hago X?» | `procedure` |
| «¿Cuál es el código de X?» | `direct_fact` |

Cuando dos lecturas son legítimas (p. ej. campo/valor con «qué significa»), la
selección queda marcada `ambiguous` y **el pack JEV decide** (si el modo lo
permite).

## 4. Pack de composición (§5): una sola llamada

`RESPONSE_COMPOSITION` mezcla Choice + Score + Noul sobre un estado compartido:

- **Choice** `response_blueprint` — las 10 formas, con criterios declarados.
- **Score** `required_detail` — brief / normal / detailed / deep.
- **Noul** `needs_example`, `needs_table`, `needs_step_by_step`, `needs_warning`,
  `needs_definition`, `needs_practical_implication`, `needs_source_explanation`,
  `needs_citations`.

JEV **no redacta**: responde cómo explicar. El contrato lo compone el código y el
generador escribe.

## 5. Response Contract (§6, §51, §53)

```json
{
  "blueprint": "technical_explanation",
  "detail": "detailed",
  "conclusion_first": true,
  "sections": ["direct_answer", "meaning", "practical_effect", "example"],
  "formatting": {"headings": true, "bold_key_concepts": true, "bullets": true, "table": true},
  "evidence": {"citations_required": true, "disclose_conflicts": true},
  "decided_by": "jev",
  "confidence": 0.88,
  "hedging_required": false
}
```

Reglas de composición:

- `unresolved` / `missing_information` → `hedging_required: true` + sección
  `limitations` + **prohibido el lenguaje definitivo** (no «probablemente» sin
  explicar por qué).
- Conflicto entre fuentes (`source_conflict`) → `disclose_conflicts` + sección
  `sources`: se nombran ambas, no se fusionan en silencio.
- Perfil del agente (`use_tables: false`) puede apagar una tabla, pero **no puede
  ignorar al caso que la pide** (JEV `needs_table`).
- Citas junto a la afirmación, no acumuladas al final.

## 6. Perfil de respuesta — Agent Studio (§27-§36)

Propósito («qué debe lograr») y perfil («cómo debe explicarlo») son cosas
distintas; el perfil es estructura, no un system prompt gigante. En el Studio:
**Identidad** (nombre + propósito, con generación asistida) →
**Instrucciones libres** (plegadas, texto libre para casos puntuales) →
**Cómo debe responder** (perfil) → **Fuentes**.

Campos: `language`, `tone`, `technical_level`, `default_detail`, `audience`,
`conclusion_first`, `use_headings`, `use_bold`, `use_tables`, `use_examples`,
`cite_sources`, `show_uncertainty`, `show_practical_implications`,
`preserve_domain_terms`, `preferred_blueprints`, `custom_instructions`.

- Presets (tarjetas seleccionables): Claro y didáctico · Técnico detallado ·
  Ejecutivo · Conciso · Analítico · Con evidencia.
- `POST /api/v1/agents/{id}/config/response-profile` — propone un perfil.
- `POST /api/v1/agents/{id}/config/purpose` — propone un propósito.
- `POST /api/v1/agents/{id}/config/preview` — preview con conocimiento
  **simulado**; nunca ejecuta tools reales.
- `GET /api/v1/agents/response-profile/catalog` — presets y blueprints.

**El generador nunca aporta hechos.** Sólo conoce nombre, descripción, propósito
actual, fuentes, herramientas y dominio; si el borrador menciona una capacidad no
configurada (SQL/API/email/...) esa frase se descarta y se devuelve un aviso.

### Overrides del turno (§36)

«respóndeme corto», «explícamelo como experto», «resumen ejecutivo» ajustan el
perfil **sólo para ese turno**; el perfil guardado no cambia.

## 7. Gate de presentación (§24, §25)

El pack `POST_GENERATION` (y el gate de respuesta del agente) suma, **en la misma
llamada**: `answer_explains_key_reason`, `answer_is_needlessly_verbose`,
`important_context_missing`, `structure`, `usefulness` y `revision_reason`
(Choice cerrado: `unclear`, `too_verbose`, `too_short`, `missing_explanation`,
`missing_example`, `missing_evidence`, `unsupported_claim`, `poor_structure`,
`does_not_answer_question`).

El veredicto (`approve` / `revise` / `abstain`) lo compone el código con los
umbrales de `JudgmentConfidencePolicy`. Cuando el veredicto es `revise`, el
**motivo** se traduce en instrucción para el generador (`revision_feedback`).
Nunca hay revisiones infinitas: el presupuesto de reintentos es el existente.

## 8. Observabilidad

- **Flujo**: `flow.response_contract` + `flow.response` (modo, fuente, selección,
  pack) y un step `response_planning` con `blueprint`, `detail_level`,
  `decided_by`, `needs_*`, `citations_required`, `hedging_required`.
- **Execution Story**: vista Historia muestra "Cómo lo explicó" y nombra la
  generación según la forma («Explicó la conclusión», «Respondió el dato»); la
  vista Técnico muestra el contrato, el pack de composición y el gate de
  presentación. Ver `docs/architecture/execution-story.md`.
- **Métricas JEV**: `zent_decision_preflight_*` incluye la fase
  `response_composition`.

## 9. Flags

| Flag | Default | Qué hace |
|---|---|---|
| `RAG_RESPONSE_INTELLIGENCE_MODE` | `rules` | `off` sin contrato · `rules` determinista · `on` + pack JEV con ambigüedad · `canary` por porcentaje |
| `RAG_RESPONSE_INTELLIGENCE_CANARY_PERCENTAGE` | `0` | porcentaje para `canary` |
| `RAG_RESPONSE_PRESENTATION_GATE` | `true` | suma el gate de presentación en la misma llamada |

`off` reproduce exactamente el comportamiento previo: el prompt queda igual y no
se emite step ni contrato.

## 10. Tests

`tests/test_response_intelligence.py` fija los casos dorados: campo técnico,
dato simple, escenario, comparación, desconocido (nada de certeza falsa),
conflicto de fuentes, generador de perfil sin capacidades inventadas, sin
chain-of-thought, Noul honesto (0.51 no es un sí), una sola llamada del pack, y
las trazas (`response_planning` en el flujo). En el portal:
`portal/src/pages/chat/responseStory.test.ts` y `story/ExecutionStoryView.test.tsx`.

## 11. Prioridad de calidad (§26)

1. corrección · 2. respaldo en evidencia · 3. respuesta directa ·
4. explicación · 5. estructura · 6. estilo.

Nunca se sacrifican 1-3 por 4-6. Una respuesta «bonita» sin respaldo no es una
mejor respuesta.
