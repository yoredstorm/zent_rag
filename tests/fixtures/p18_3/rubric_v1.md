# Rúbrica de evaluación P18.3 — v1

Estado del dataset: **draft_not_approved**. Esta rúbrica define cómo se
evaluará, no certifica que las anotaciones ya sean humanas.

## Principios

1. Una respuesta correcta no compensa una cita falsa. La cita falsa es el
   defecto de mayor severidad.
2. Una abstención correcta es una respuesta de calidad, no un fallo.
3. La interpretación literaria se evalúa como interpretación sustentada; no se
   exige que el texto diga literalmente la conclusión.
4. Una obligación normativa no se evalúa como opinión. Las negaciones,
   excepciones y fechas deben conservarse.
5. Las operaciones tabulares se evalúan contra la tabla, no contra una suma
   generada por el modelo.
6. El holdout no se usa para ajustar prompts, retrieval ni umbrales.

## Dimensiones por caso

| Dimensión | Peso | Criterio |
|---|---:|---|
| Corrección de la respuesta | 0.35 | Coincide con `gold_answer` o una variante aceptada. |
| Grounding | 0.30 | Cada afirmación verificable está sustentada por la evidencia citada. |
| Cita y localizador | 0.20 | Documento, página/sección/fila y extracto corresponden a la afirmación. |
| Comportamiento esperado | 0.10 | `answer`, `abstain` o `contradiction` según el caso. |
| Tipo de claim | 0.05 | No se presenta una interpretación como hecho ni una recomendación como obligación. |

Una cita fabricada, una fuente fuera de permisos o una operación no autorizada
invalida el caso completo (P0), sin importar el resto de la puntuación.

## Métricas agregadas

- `retrieval_recall_at_k`: evidencia anotada recuperada / evidencia anotada.
- `citation_precision`: citas que apuntan a la localización correcta / citas emitidas.
- `citation_coverage`: afirmaciones verificables con cita válida / afirmaciones verificables.
- `grounded_claim_precision`: claims sustentados / claims verificables emitidos.
- `abstention_correctness`: abstenciones correctas / casos que exigen abstención.
- `contradiction_handling`: contradicciones detectadas y explicadas / contradicciones anotadas.
- `exact_match_normalized`: solo para tabulares y respuestas literales, con
  normalización de acentos, mayúsculas y espacios.
- `unsupported_claim_rate`: claims sin evidencia / claims emitidos.

Se reportan por familia y por dificultad, con denominador explícito. Los 40
casos son una señal de calidad, no una estimación estadística universal.

## Umbrales propuestos (congelar antes de la corrida final)

- P0: 0 citas fabricadas, 0 cruces de tenant/corpus, 0 efectos no autorizados.
- Respuestas literales/tabulares: ≥ 90 % de corrección normalizada.
- Abstención: ≥ 95 % cuando el caso la exige.
- Grounding de claims críticos: ≥ 95 %.
- Regresión frente a baseline: ≤ 2 puntos porcentuales en categorías cubiertas.

Estos umbrales son criterios internos del proyecto; no son estándares
universales ni sustituyen una revisión humana.
