# P15 — Diseño de intención, identidad y calidad

## 1. Separación semántica

| Componente | Autoridad | Qué decide |
|---|---|---|
| `UserIntent` | `intelligence/response/intent.py` | información, valoración, interpretación, recomendación, comparación, creación, enseñanza o ejecución |
| `AgentIdentity` | `intelligence/response/identity.py` | quién habla, voz, misión, audiencia, dominio y límites persistentes |
| `ResponseProfile` | `intelligence/response/profile.py` | longitud, estructura, detalle, ejemplos, análisis y terminología |
| `ResponseContract` | `intelligence/response/contract.py` | intención + identidad + perfil efectivos, evidencia y reglas de presentación |
| `ResponseQuality` | `intelligence/response/quality.py` | chequeos de la respuesta, separados de la validez del contrato |

No hay una segunda autoridad de perfiles ni un segundo motor.

## 2. Intención

`detect_user_intent` reconoce patrones genéricos y multitemáticos:

- valoración: “qué te parece”, “qué opinas”, “qué valor tiene”;
- interpretación: “tu interpretación”, “qué significa para vos”, “simbología”;
- recomendación: “recomendarías”, “cuál conviene”;
- comparación, creación, enseñanza y ejecución.

`rules_turn_intent` mapea valoración/interpretación/recomendación a
`valuation`, `interpretation` o `recommendation`, con `evaluative=True`,
`needs_external_evidence=True` y route `knowledge`.

No exige experiencia personal: el objeto se busca en la evidencia y la tesis se
formula como lectura propia.

## 3. Identidad persistente

`identity_from_agent_config` deriva la identidad del `purpose`, `system_prompt`
o un bloque `identity` explícito. Reconoce narrador, docente, asesor, analista,
comercial, auditor y soporte sin depender de un dominio concreto.

`identity_prompt_block` se inyecta antes del perfil y se repite como
recordatorio final. Reglas:

- la voz y la misión no se borran;
- el perfil ajusta longitud, estructura, detalle y formato;
- la identidad no es una restricción de conocimiento;
- una identidad narrativa conserva imágenes simples, ritmo oral y evita jerga
  académica o de consultoría;
- no se muestran criterios, perfiles ni metadatos internos en la respuesta.

`resolve_identity_profile` publica `identity_conflicts` cuando el perfil apaga
ejemplos o cambia la audiencia. Para una identidad narrativa con
`example_policy=never`, restituye `minimal_supported`; no borra la identidad ni
marca el estilo como exitoso si hubo conflicto.

## 4. Blueprint de valoración

`interpretive_valuation` usa:

- respuesta directa;
- significado;
- evidencia;
- porqué;
- límites sólo cuando son materiales.

No es `technical_explanation` ni una plantilla de resumen ejecutivo. No exige
citas si el blueprint no las requiere, pero separa hecho de lectura propia.

## 5. Gate y evidencia

- Las valoraciones explícitas (“me parece”, “mi lectura”, “considero”, “a mi
  juicio”, “recomiendo”) se clasifican como `interpretive` y no como hechos
  universales.
- Los claims documentales siguen pasando por `documented_fact`, `inference`,
  `unsupported`.
- `keep_evaluative_answer` evita convertir una tesis con borrador y evidencia en
  `INSUFFICIENT_ANSWER`. No autoriza respuestas sin evidencia.
- La respuesta conserva `answer_with_limits` cuando hay evidencia sobre el
  objeto pero falta un fundamento específico.

## 6. Calidad

`ResponseQuality` evalúa:

- `intent_fulfilled`
- `persona_preserved`
- `style_applied`
- `evidence_integrity`
- `direct_answer_present`
- `unnecessary_refusal`
- `irrelevant_internal_metadata`
- `verbosity_appropriate`

Estados:

- `not_evaluated`: no hay respuesta/contrato.
- `deterministic_checks`: se ejecutaron chequeos del código; no es validación
  semántica.
- `semantic_evaluated`: un juez real evaluó la respuesta.
- `needs_review`: hay rechazo, metadato interno o incumplimiento material.

La UI muestra la etiqueta exacta y nunca “Validado” si `semantic_evaluated` es
falso.

## 7. UX

`AgentTestChat` agrega una vista técnica plegable con intención, identidad,
perfil, evidencia y validación. El preview muestra solicitado, aplicado,
identidad, intención y estado de calidad. El comparador muestra identidad y
calidad por variante. Las tarjetas de estilo permiten wrapping y no superponen
la etiqueta recomendada.
