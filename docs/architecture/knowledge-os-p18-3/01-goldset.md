# P18.3-01 — Gold set de comprensión

Estado: **DRAFT_NOT_APPROVED**. No es un gold set humano certificado.

## Entregables

- `tests/fixtures/p18_3/goldset_v1.jsonl` — 40 casos.
- `tests/fixtures/p18_3/manifest.json` — SHA-256 de las seis fuentes sintéticas.
- `tests/fixtures/p18_3/metamorphic_v1.json` — 12 comprobaciones, 3 por familia.
- `tests/fixtures/p18_3/rubric_v1.md` — métricas, denominadores y umbrales propuestos.
- `tests/fixtures/p18_3/annotation_guide.md` — doble anotación, árbitro y holdout.
- `tests/fixtures/p18_3/review_disagreements.csv` — cabecera lista, sin filas.
- `src/rag/evaluation/goldset_v1.py` y `src/scripts/validate_goldset_v1.py`.

## Composición

| Familia | Casos | Dev | Holdout |
|---|---:|---:|---:|
| narrative | 10 | 7 | 3 |
| technical | 10 | 7 | 3 |
| policy_contract | 10 | 7 | 3 |
| tabular | 10 | 8 | 2 |
| **Total** | **40** | **29** | **11** |

Cada caso incluye pregunta, intención, comportamiento esperado, respuesta gold,
variantes aceptadas, evidencia con extracto literal, `must_not_claim`, tipo de
claim, permisos, dificultad, split, estado de anotación y versión de rúbrica.

## Validación ejecutada

```text
python -m src.scripts.validate_goldset_v1
status: DRAFT_NOT_APPROVED
cases: 40
errors: []
metamorphic_checks: 12
goldset_sha256: f0cdb4cb8cacee35908964d542919774674930ab75762bb7f233a8a2273c4f99
```

```text
python -m src.scripts.validate_goldset_v1 --strict-human
status: BLOCKED_HUMAN_REVIEW
```

La prueba `test_goldset_has_40_grounded_cases_but_stays_draft` verifica que las
40 citas aparecen literalmente en su fixture y que la localización no es
inventada. `test_invented_excerpt_is_rejected` demuestra que una cita fabricada
falla la validación.

## Lo que falta para PASS de construcción

1. Dos revisores humanos independientes por caso crítico.
2. Árbitro para desacuerdos, registrado en `review_disagreements.csv`.
3. Cambiar `annotation_status` a `approved` y agregar `reviewer_ids`.
4. Ejecutar `--strict-human` y obtener `PASS_HUMAN_REVIEWED`.

Sin esos pasos, el dataset sirve para desarrollo y detección de defectos, no
para una afirmación de calidad humana.

