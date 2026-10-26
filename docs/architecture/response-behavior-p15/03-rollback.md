# P15 — Rollback

## Código

P15 no agrega migraciones ni tablas. Rollback de aplicación:

1. Revertir al SHA anterior (`c87fa71`, cierre P14).
2. Rebuild/redeploy de `api`, `ingestion-worker` y `portal`.
3. Los campos nuevos de contrato (`request_intent`, `identity_*`,
   `response_quality`) son aditivos; clientes anteriores los ignoran.
4. No se modifican agentes, fuentes, conocimiento ni versiones publicadas.

## Comportamiento

- `RAG_RESPONSE_INTELLIGENCE_MODE=off` sigue apagando el contrato y declara
  `style_degraded=response_intelligence_off`; no finge estilo aplicado.
- Si el juez semántico no corre, `semantic_evaluated=false` y la UI muestra
  `No evaluado` o `Chequeos deterministas`, nunca `Validado`.
- La valoración interpretativa sólo se conserva con evidencia sobre el objeto;
  sin evidencia, el gate mantiene la abstención.
- `ZENT_GOLD_RELEASE_ENABLED` permanece `false`.

## Datos

No hay datos que revertir. Los campos nuevos viven en `config_json` y en el
flujo de ejecución; el rollback de código simplemente deja de leerlos.
