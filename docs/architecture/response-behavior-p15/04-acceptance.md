# P15 — Matriz de aceptación

## Caso El principito

| Criterio | Resultado |
|---|---|
| Los 8 perfiles responden directamente qué les parece la obra | PASS |
| Ninguno rechaza la valoración por falta de experiencia personal | PASS |
| Los 8 conservan la identidad de narrador infantil | PASS (juez LLM, 8/8) |
| Preciso y Conciso no se convierten en negativas | PASS (juez LLM) |
| Analítico entrega interpretación y razones | PASS (juez LLM) |
| Con evidencia formula una tesis interpretativa respaldada | PASS (juez LLM) |
| No aparecen métricas internas irrelevantes | PASS (juez LLM, 0/8) |
| Hechos y citas correctos | PASS (juez LLM, evidence_integrity 8/8) |
| Estilo y persona separados del contrato | PASS |
| UI no llama “Validado” sin juez semántico | PASS (test portal y código) |

## Otros dominios

Los 48 resultados de la matriz 6×8 tienen chequeos deterministas:

- intención cumplida: 48/48;
- identidad presente: 48/48;
- rechazo innecesario: 0;
- metadatos internos: 0;
- longitud dentro del perfil: 48/48 (según umbrales deterministas).

No se ejecutó juez semántico para los 40 resultados no literarios. Quedan
`deterministic_checks`, no `semantic_evaluated`.

## Gates no cerrados

- Revisión humana de las 8 respuestas de El principito: `NOT_VERIFIED`.
- Juez semántico de los otros 5 dominios: `NOT_VERIFIED`.
- Retrieval real del PDF y ejecución de herramientas: `NOT_VERIFIED`.
- Proveedor primario: `NOT_VERIFIED` por `403 NOT_ENOUGH_BALANCE`; se usó el
  fallback configurado.
- `PROVIDER_VERIFIED`: no emitido.
- `ZENT_GOLD_RELEASE_ENABLED`: permanece `false`.

## Decisión

P15 queda **GO para staging** en intención, identidad, gate y UX, con la
evidencia real del caso literario y los chequeos deterministas del resto.

No se declara GO de producción ni certificación semántica completa: faltan
revisión humana, juez de los demás dominios y retrieval real.
