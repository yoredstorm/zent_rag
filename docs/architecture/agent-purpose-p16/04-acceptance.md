# P16 — Matriz de aceptación

| Caso | Intención preservada | Propósito específico | Instrucciones separadas | Audiencia correcta | Sin herramientas internas | Calidad |
|---|---|---|---|---|---|---|
| Narrador infantil | PASS | PASS | PASS | PASS, infantil | PASS | 10/10 |
| Vender productos | PASS | PASS | PASS | PASS | PASS | 10/10 |
| Mentor de programación | PASS | PASS | PASS | PASS | PASS | 10/10 |
| Analizar contratos | PASS | PASS | PASS | PASS | PASS | 10/10 |
| Manuales técnicos | PASS | PASS | PASS | PASS | PASS | 10/10 |
| Consultar pedidos | PASS | PASS | PASS | PASS | PASS | 10/10 |
| Profesor de matemática | PASS | PASS | PASS | PASS | PASS | 10/10 |
| Auditoría | PASS | PASS | PASS | PASS | PASS | 10/10 |
| Organizar citas | PASS | PASS | PASS | PASS | PASS | 10/10 |
| Políticas de RRHH | PASS | PASS | PASS | PASS | PASS | 10/10 |

## Caso Principito

- Mantiene narrador infantil: PASS.
- No impone audiencia técnica: PASS.
- No enumera herramientas internas: PASS.
- Incluye criterios de respuesta e interpretación: PASS.
- Distingue propósito de instrucciones: PASS.
- No inventa contenido del PDF: PASS, declara límites.
- Conserva identidad al cambiar de perfil: PASS, integración P14/P15.
- Borrador editable y reversible: PASS, no auto-aplica.
- Usa cambios sin guardar: PASS, test de UI y endpoint.

## Gates

- Revisión humana del contenido de los 10 propósitos: `NOT_VERIFIED`.
- E2E con LLM real desde el portal: `NOT_VERIFIED` en CI; preview/endpoint se
  probaron contra Docker local.
- Retrieval real de las fuentes en la generación de propósito: `NOT_VERIFIED`;
  la matriz usó contexto sintético.
- Coste en dólares: no medido; se registran tokens y latencia.
- `PROVIDER_VERIFIED`: no emitido.
- `ZENT_GOLD_RELEASE_ENABLED=false`.

## Decisión

GO para staging del constructor de propósito, con 10/10 de calidad determinista
sobre LLM real. No se declara certificación semántica humana ni de producción.
