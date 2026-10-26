# P16 — Evidencia

Fecha: `2026-10-26`.

## 1. Pruebas deterministas

```powershell
uv run --frozen --no-sync pytest tests/test_p16_purpose_builder.py -q
```

Resultado: **11 passed**.

```powershell
uv run --frozen --no-sync pytest tests/test_p16_purpose_builder.py \
  tests/test_agent_api.py tests/test_response_intelligence.py -q
```

Resultado: **76 passed**.

Portal:

```powershell
cd portal
npm run typecheck
npx vitest run src/pages/AgentStudio.test.tsx -t "construye propósito"
```

Resultado: **1 passed** para el flujo de propósito; typecheck OK.

Casos cubiertos:

- modos auto/expandir/mejorar/crear;
- prompt con propósito e instrucciones sin guardar;
- contrato estructurado con propósito e instrucciones separadas;
- audiencia infantil no subordinada al perfil técnico;
- rechazo de listados de herramientas y frases genéricas;
- fallback que conserva la entrada;
- compatibilidad con respuesta legacy de texto;
- endpoint que usa campos sin guardar, no auto-aplica y devuelve calidad;
- fallo de proveedor que conserva la entrada, sin 503 destructivo.

## 2. Matriz real de 10 propósitos

Script: `scripts/p16_real_purpose_matrix.py`.
Artefacto: `artifacts/certification/p16/real-purpose-matrix.json`.

- 10 propósitos de aceptación.
- 10/10 superaron los diez criterios del validador.
- 0 errores de proveedor en el artefacto final.
- 0 listados de herramientas internas.
- 0 textos clasificados como genéricos.
- 0 reparaciones aplicadas (las propuestas iniciales ya cumplían).
- 18.071 tokens totales: 6.284 de prompt y 11.787 de completion (matriz de 10).
- Docker real: endpoint con propósito sin guardar, `source=model`,
  `quality.passed=true`, `persona.audience=infantil`, 979 caracteres de
  propósito y 2452 de instrucciones. Ver `05-docker.md`.
- Latencia media 102,45 s; máxima 182,19 s. El proveedor primario devolvió
  403 por saldo y las llamadas usaron el fallback configurado; la latencia
  incluye esos reintentos. No se calculó coste en dólares porque el precio del
  fallback no está medido en este artefacto.

## 3. Caso Principito

Entrada:

> Responde como un narrador de cuentos infantil.

Antes: descripción de recursos, audiencia técnica y lista de herramientas.

Después (propuesta real):

> Eres Principito, un narrador de cuentos infantiles. Tu misión es contar,
> recrear y conversar sobre la historia de El Principito con un lenguaje cálido,
> sencillo y lleno de imaginación... No inventes hechos sobre el libro, su autor
> o la realidad. ... Conserva tu voz cálida, sencilla y poética, adaptando solo
> el nivel de detalle y la longitud, no tu esencia.

Instrucciones adicionales (extracto):

> Actúa siempre como un narrador de cuentos infantiles llamado Principito...
> frases cortas, imágenes simples y un ritmo pausado y afectuoso... evita
> tecnicismos, abstracciones adultas y tono académico... no inventes hechos...

El validador marcó `intent_preservation`, `mission_specificity`,
`persona_consistency`, `behavioral_actionability`, `audience_consistency`,
`capability_grounding`, `instruction_coherence`, `unnecessary_tool_listing`,
`genericness` y `safety_compliance` en true.

## 4. Límites

- El evaluador es determinista, no un juez humano.
- La matriz usó contexto sintético de fuentes/herramientas; no ejecutó retrieval
  real ni modificó workflows.
- No se probó la generación real desde el portal en CI porque el proveedor no
  está disponible allí; la UI está cubierta con mock y el endpoint se verificó
  con Docker local.
- El proveedor primario no está certificado por saldo; se usó el fallback.
- `saved=false` siempre: la generación nunca persiste ni sobrescribe el
  `system_prompt` sin acción del usuario.
