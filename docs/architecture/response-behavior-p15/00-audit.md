# P15 — Auditoría de intención, persona y calidad

Fecha: `2026-10-26`. Base de código: `c87fa71` (P14).

## 1. Reproducción del caso

Propósito:

> Responde como un narrador de cuentos infantil.

Evidencia congelada: hechos de *El principito* (Saint-Exupéry, 1943; aviador
en el Sahara; asteroide B-612; zorro, rosa, final ambiguo).

Pregunta:

> ¿Qué te parece El principito?

Comportamiento observado antes de P15:

1. `rules_turn_intent` la clasificaba como `knowledge_question` por tener
   entidad y palabra interrogativa (`turn_intent.py`).
2. El selector caía en `technical_explanation` por defecto (`selector.py`).
3. El gate documental evaluaba una tesis interpretativa como afirmación factual
   no respaldada y podía terminar en abstención.
4. La identidad del propósito sólo se inyectaba en el prompt del loop ReAct.
   El finalizador, el composer, el preview y el comparador no recibían esa
   identidad.
5. Los perfiles Preciso, Conciso, Analítico y Experto técnico podían imponer un
   registro adulto/académico sin que el sistema lo declarara.
6. La UI llamaba “validado” a que existiera un contrato, no a una evaluación
   semántica de la respuesta.

## 2. Causas raíz

- No existía una intención funcional de valoración, interpretación o
  recomendación; el léxico de conocimiento ganaba siempre.
- No existía una identidad persistente separada del estilo.
- El contrato no distinguía hecho documentado, inferencia y lectura propia.
- El gate no sabía que una tesis interpretativa legítima no es un hecho
  universal.
- La validación de UI medía presencia de contrato, no calidad semántica.
- Los perfiles se aplicaban como bloque imperativo al final del prompt, sin un
  recordatorio de identidad posterior.

## 3. Decisiones de diseño

- Extender el pipeline existente; no crear un motor, planner ni catálogo
  paralelo.
- La identidad es comunicativa: define voz, misión y audiencia. No es una
  restricción de conocimiento.
- La valoración interpretativa se permite con fundamento; los hechos no
  respaldados siguen prohibidos.
- La UI distingue “contrato aplicado”, “chequeos deterministas” y “evaluación
  semántica”; nunca presenta las dos primeras como validación semántica.
- Si no hay juez semántico, el estado es `No evaluado` o `Chequeos
  deterministas`, nunca `Validado`.
