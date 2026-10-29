# P18.3-08 — Conocimiento → Agente con proveedor real

Estado: **CONDITIONAL_REAL_PROVIDER**.

## Ejecución

`src/scripts/certify_agent_knowledge.py` crea un tenant sintético, ingesta dos
fuentes reales (narrativa y técnica), construye dos agentes en Agent Studio y
ejecuta `/run` y `/run/stream`.

| Agente | Perfil | Fuente | Propósito |
|---|---|---|---|
| Narrador infantil | `concise` | relato | narrador de cuentos, sin inventar |
| Analista de documentos | `analytical` | manual ATPCO | precisión técnica y citas |

## Casos y resultado

| Caso | Resultado | Verificación |
|---|---|---|
| Valoración «¿Qué te parece esta historia?» | PASS | verified |
| Hecho literal «¿Qué debe cuidar el principito?» | CONDITIONAL | partial |
| Ausencia «política de gastos del asteroide» | PASS | verified |
| Hecho técnico «posición de Fare Basis» | PASS | verified |
| Ausencia «empleados de ATPCO» | PASS | verified |
| Streaming | PASS, 25 eventos | n/a |
| Sin fuga entre fuentes | PASS | n/a |
| Identidad preservada | PASS | n/a |
| Answer Gate observado | PASS | n/a |
| Citas válidas | PASS | n/a |

Métricas observadas:

- modelo efectivo: `openai/deepseek-ai/DeepSeek-V4.1-Flash` (fallback real);
- latencias totales: 12,6 s a 152,1 s según caso;
- tokens: 11.052 a 17.742 por run;
- coste estimado: USD 0,00117 a 0,00180 por run;
- cada respuesta trae 2 citas; el caso literal narrativo queda `partial` por
  claims no citados.

## Contrato de verificación

La corrección P18.3-03 evita que un gate skipped convierta una narrativa
verificada en `blocked`. Aun así, el gate puede quedar
`provider=skip` si JEV no está disponible. Eso se registra, no se declara
“juzgado”.

## Límite

No se probó una fuente `processing`, una fuente revocada ni un corpus ajeno en
la misma ejecución. Esas rutas tienen tests de scope, pero no forman parte de
este certificado real. El estado es CONDITIONAL, no PASS pleno.
