# Guía de anotación P18.3 — v1

## Estado

El dataset `goldset_v1.jsonl` está en `draft_not_approved`. Fue preparado por
el agente a partir de fixtures sintéticos y **no** sustituye la revisión de dos
personas. No se puede declarar «gold set humano certificado» hasta completar
este procedimiento.

## Procedimiento

1. Congelar el manifiesto de fixtures (`manifest.json`) y el hash del gold set.
2. Asignar dos anotadores independientes a cada caso crítico (P0: normativo,
   tabular, contradicción y abstención).
3. Cada anotador verifica:
   - que la pregunta sea respondible o correctamente abstencionista;
   - que `gold_answer` y `accepted_variants` no admitan dos respuestas
     contradictorias;
   - que `supporting_evidence.verbatim_excerpt` exista literalmente en la
     fuente y en la localización declarada;
   - que `expected_claim_type` no convierta una interpretación en hecho;
   - que `must_not_claim` cubra la alucinación más probable.
4. Registrar acuerdos y desacuerdos en `review_disagreements.csv`.
5. Un tercer anotador arbitra los desacuerdos. Sin árbitro, el caso queda
   `in_review`, no `approved`.
6. Solo entonces cambiar `annotation_status` a `approved`, agregar al menos dos
   `reviewer_ids` pseudonimizados y volver a ejecutar:
   `python -m src.scripts.validate_goldset_v1 --strict-human`.

## Reglas de evidencia

- Una respuesta puede citar varios pasajes; cada afirmación verificable debe
  tener al menos un pasaje que la sostenga.
- La cita debe apuntar a la página, sección o fila correcta, no solo a un
  documento que contiene el término.
- Para narrativa, una valoración razonada puede ser `literary_interpretation`;
  no se exige una frase literal «este libro es excelente».
- Para contratos y políticas, `deberá`, `podrá`, `no`, `excepto` y las fechas
  son parte del claim. No se normalizan a una recomendación.
- Para tablas, el extracto debe incluir la fila y columna usadas. Si no existe
  la columna necesaria, la respuesta correcta es abstenerse.

## Holdout

Los casos con `split=holdout` no se usan para ajustar retrieval, prompts,
umbrales ni reglas. Se ejecutan una vez contra la configuración congelada y se
reportan por separado.
