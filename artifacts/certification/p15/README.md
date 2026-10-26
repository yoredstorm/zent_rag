# P15 — Certificación de evidencia

- `real-matrix.json`: 48 llamadas reales (6 dominios × 8 perfiles), 0 errores.
- `real-matrix-judged.json`: 8 respuestas de literatura evaluadas por juez LLM
  real; 8/8 en intención, persona, estilo, evidencia, respuesta directa y
  ausencia de rechazos/metadatos.
- Los 40 resultados no literarios conservan chequeos deterministas; no se
  presentan como evaluación semántica.
- No se incluyen logs del proveedor ni credenciales.
- El proveedor primario devolvió 403 por saldo; las llamadas completaron por el
  fallback configurado.
