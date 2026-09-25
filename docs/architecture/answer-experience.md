# Answer experience — cómo se lee la respuesta

Documento del cambio de **presentación**: ZENT podía tener la información
correcta y responderla como una pared de texto. Response Intelligence sigue
siendo el mismo subsistema (blueprint + contrato + gate); lo que cambia es el
**ritmo** con que la información entra al lector y qué evidencia merece aparecer.

> Correcto no significa legible.

## 1. Causa raíz: la contradicción del contrato

`prompt_block()` habilitaba `headings`, `bullets`, `tables` y `bold`, pero al
mismo tiempo pedía:

```
- escribí una sola explicación conectada: ese orden dice cómo entra la
  información, no son secciones rotuladas ni una lista de puntos
- si usás encabezados … y no más de dos o tres: la respuesta se lee de corrido,
  no como un formulario
```

El resultado era predecible: párrafos largos, valores encadenados en una sola
frase, conceptos mezclados y una sección de límites que aparecía siempre porque
`technical_explanation` la declaraba en sus secciones fijas.

## 2. Ritmo por capas (`src/intelligence/response/presentation.py`)

Nuevo módulo dentro de Response Intelligence (no una arquitectura paralela):
calcula la política de presentación del caso, determinista y observable.

```
capa 1  answer     respuesta inmediata, sin preámbulo
capa 2  concepts   conceptos principales (uno por encabezado si hay varios)
capa 3  detail     detalle técnico pedido (enumeraciones como lista o tabla)
capa 4  practical  implicación práctica o ejemplo, si la evidencia lo sostiene
capa 5  limits     límites, SOLO si son materialmente relevantes
```

`build_presentation_policy()` mide, sin LLM:

| Señal | De dónde sale |
|---|---|
| `concepts` / `multi_concept` | entidades de la pregunta («categoría 31», «byte 105») y pares «X y Y» |
| `needs_list` / `enumeration_count` | enumeraciones explícitas en la evidencia («Value 1», «Valor 2:», «Opción 3») |
| `content_selected` / `content_omitted` | fragmentos que entraron al contexto contra los recuperados del run |
| `secondary_count` / `secondary_labels` | material que la pregunta no pide (notas al pie, records auxiliares, permutaciones, apéndices) |
| `show_limitations` / `limitations_reason` | falta información, conflicto de fuentes o inferencia sin resolver |
| `headings_budget` | crece con la complejidad: 1 en un dato, 3-5 en una explicación multi-concepto |
| `followup_allowed` | hay material disponible que no se explicó (continuación natural) |

La capa 5 no se pide nunca por obligación: si la respuesta está respaldada y
completa, el bloque de límites **no** aparece en las secciones ni en el prompt.

## 3. Relevancia para la respuesta

> Toda evidencia recuperada puede ser verdadera, pero no toda evidencia
> verdadera merece aparecer en la respuesta.

La evidencia **no se elimina del run**: sigue en el `EvidenceRegistry`, en las
citas y en «Ver flujo». Lo que cambia es qué se explica. El prompt recibe:

```
- relevancia: de 8 fragmentos recuperados, para ESTA pregunta alcanzan 4;
  no expliques el material secundario (notas al pie, registros auxiliares,
  permutaciones, apéndices) salvo que el usuario lo pida
```

## 4. Contrato: ritmo en lugar de formulario

`ResponseContract` suma `layers`, `presentation` (la política publicada) y
`show_limitations`. El prompt deja de contradecirse:

- el orden de las secciones es un **ritmo**, no un formulario;
- una idea por párrafo, bloques cortos;
- 3+ valores u opciones se enumeran (viñeta o tabla), no se encadenan;
- los encabezados son títulos naturales del contenido, con presupuesto adaptativo;
- nada de listas finales de «Fuentes/Referencias»: se cita en la línea;
- nada de convertir una lista de valores en jerarquía, ranking u orden de prioridad.

`technical_explanation` ahora declara `key_values` y ya no declara `limitations`
fija; la sección de límites la agrega el contrato sólo cuando hay una señal
material. Todo blueprint hereda por defecto los formatos legibles (encabezados,
viñetas, negritas) y las reglas de evidencia (citas, conflictos, distinción
hecho/inferencia).

## 5. JEV sigue siendo el editor, no el escritor

El gate de presentación amplía su taxonomía de motivos de revisión:

`wall_of_text`, `poor_chunking`, `buried_answer`, `irrelevant_detail`,
`bad_enumeration_format`, `unnecessary_limitations`.

Una mala presentación **siempre** produce `REVISE`; nunca `ABSTAIN`. El motivo
viaja al flujo (`presentation_revision_reason`) y se traduce en una instrucción
concreta para el generador. JEV no redacta: decide qué corregir y el generador
reescribe.

## 6. Presentation nunca cambia hechos

Dos guardas deterministas (regex + contención de texto, sin LLM):

- **figuras** (ya existente): fechas y años que la evidencia no contiene;
- **jerarquías**: frases que afirman un orden de prioridad cuando la fuente sólo
  define valores (`ungrounded_hierarchy_claims`). Se corrige una vez y queda
  visible en el flujo (`hierarchy_unverified`).

## 7. Higiene del texto final

`normalize_answer_text()` (en `contract.py`) resuelve tres defectos que llegaban
al lector, conservando el contenido:

1. **escapes de markdown** que el modelo agrega (`\*\*negrita\*\*`) → `**negrita**`;
2. **bloque de fuentes con nombres pegados** (`Fuentes**Cat31_dapp_C.pdfRec2…**`)
   → lista, un título por línea, usando sólo nombres conocidos de la evidencia;
3. **rótulos internos** del contrato filtrados por el modelo (ya existente).

En el portal, las respuestas se renderizan como markdown (incluido el chat de
prueba del Agent Studio) y las fuentes se muestran como elementos separados.

## 8. Observabilidad («Ver flujo»)

- Step `response_presentation`: capas, conceptos, presupuesto de encabezados,
  enumeraciones, `content_selected` / `content_omitted`, material secundario,
  límites declarados.
- El contrato publicado (`flow.response.contract`) incluye `layers`,
  `presentation` y `show_limitations`.
- Step `answer_gate`: `presentation_verdict` y `presentation_revision_reason`.

Sin scores inventados: lo que se publica son medidas (fragmentos, conceptos,
enumeraciones) o decisiones explícitas.

## 9. Configuración

No hay flags nuevos: la experiencia por defecto ya es legible. Los presets de
Agent Studio siguen mandando cuando el usuario los elige (un perfil «conciso»
produce 1-2 frases y sin encabezados). `RAG_RESPONSE_PRESENTATION_GATE` sigue
gobernando si el gate suma las preguntas de presentación.

## 10. Tests

`tests/test_response_presentation.py`:

- la contradicción del prompt ya no existe y el ritmo por capas está presente;
- límites por obligación vs. límites materiales;
- multi-concepto («categoría 31» + «byte 105»), enumeraciones, material
  secundario y conteos;
- jerarquía inventada detectada / jerarquía respaldada no marcada;
- taxonomía del gate ampliada y `wall_of_text` → `revise` (nunca abstención);
- batería de escenarios A-I (dato simple, X+Y, campo con 5 valores, mucha
  evidencia secundaria, evidencia completa, evidencia parcial, wall-of-text,
  markdown, fuentes múltiples).

`portal/src/lib/markdown.test.ts` y
`portal/src/components/agentStudio/AgentTestChat.test.tsx`: la negrita se
renderiza como negrita, las listas y tablas se renderizan, y cada fuente aparece
por separado.
