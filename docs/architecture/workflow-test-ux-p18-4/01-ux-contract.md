# P18.4-01 — Contrato de interacción y arquitectura de información

- Fecha: 2026-10-29
- Baseline: `bd142c480219eac56df020ca5a8642d513977fd2`
- Rama: `p18.4-workflow-test-ux`

## 1. Decisiones aprobadas

| Decisión | Valor |
|---|---|
| Modo inicial | `Simular` conserva el baseline; la explicación advierte lecturas reales |
| JSON | Se conserva el objeto completo para `/run`; en `/test` el escenario recibe el texto tal cual |
| Montaje | Un solo panel activo: aside en desktop, drawer en móvil |
| Alcance | Fase A primero; luego B, C y D por gates |

## 2. Vistas

Un dock, dos vistas semánticas:

- **Probar**: modo, escenario opcional, mensaje, previsión, preparación y CTA.
- **Resultado**: estado humano, respuesta, recorrido, verificación y detalles técnicos.

La vista Resultado se abre al completar una prueba. Se puede volver a Probar sin perder el borrador. Si no hay resultado, muestra un estado vacío útil. No se duplican chat y formulario al mismo tiempo.

## 3. Secuencia de Probar

1. Modo.
2. Explicación contextual del modo.
3. Escenario opcional, cerrado por defecto.
4. Mensaje de prueba.
5. Datos avanzados y JSON, cerrados.
6. Preparación para probar, cerrada salvo que haya avisos.
7. Previsión del flujo, cerrada.
8. Un CTA principal persistente.

## 4. Modos

| UI | IDs internos | Acción | Qué no garantiza |
|---|---|---|---|
| Vista previa | `preview` | `/test` con `requested_level=preview` | No ejecuta ni certifica |
| Simular | `simulation` | `/test` con `requested_level=simulation` | Puede leer datos; no certifica proveedor |
| Real, sandbox | `sandbox` | `/test` con `requested_level=sandbox` | Si no hay adaptador, el servidor capa y lo informa |
| Real, proveedor | `provider` | `/test` con `requested_level=provider` | Si no hay proveedor, `UNVERIFIED`; no publica |

“Real” no es alias de `/run`. Ejecutar con efectos vive en **Más acciones**, con `ConfirmDialog` y texto `EJECUTAR`.

## 5. Reglas de CTA

- Un solo CTA dominante por contexto.
- `Vista previa`: “Ver vista previa”.
- `Simular`: “Ejecutar simulación”.
- `Sandbox`: “Probar en sandbox”.
- `Proveedor`: “Solicitar certificación con proveedor”.
- `Real` sin carril: CTA deshabilitado con explicación.
- `Ejecutar workflow con efectos reales`: acción secundaria de riesgo, separada del CTA.
- Enter ejecuta solo preview/simulation y con input. En Real no ejecuta.

## 6. Escenarios y ejemplos

- Seis ejemplos dentro de “Escenario (opcional)”, cerrado por defecto.
- Copia: “Rellena el mensaje. No cambia tu agente, tus herramientas ni el workflow”.
- “Generar ejemplo” usa tipos de nodos del grafo; no inventa campos obligatorios.
- “Usar último” lee `/sample-outputs`; conserva el payload original; no cambia el modo.
- “Restaurar borrador” recupera la entrada anterior.

## 7. Resultado

Pestañas:

1. **Respuesta**: texto del agente, error humanizado, eco, ausencia de respuesta, nodo responsable.
2. **Recorrido**: `WorkflowRunInspector` reutilizado; pasos reales, efectos, selección de nodo.
3. **Verificación**: solicitado/ejecutado, resultado, `provider_verified`, `capped_reason`, efectos, readiness.

Detalles técnicos en disclosure: IDs, hashes, timeline, estado crudo. Nunca secretos.

## 8. Estados

| Estado | Copy |
|---|---|
| Sin input | “Escribe un mensaje o usa un ejemplo” |
| Preparando | “Preparando la prueba…” con tiempo real, sin porcentaje |
| Preview | “Vista previa completada” |
| PASSED simulación | “Simulación completada” |
| PASSED sandbox | “Prueba sandbox completada” solo si `effective=sandbox` |
| PASSED provider | “Verificación con proveedor completada” solo si `provider_verified=true` |
| UNVERIFIED | “Sin verificación de proveedor” |
| Capped | “Nivel ajustado por el servidor”; solicitado y ejecutado visibles |
| FAILED | “La prueba falló” |
| BLOCKED | “No se pudo probar” |
| WAITING | “Esperando mensaje” |
| Pending approval | “Esperando aprobación” |
| Save fail | “No pude guardar el grafo, así que no ejecuto” |
| Histórico | “Resultado histórico. No es el estado actual del grafo.” |
| Sin resultado | “Sin resultado todavía” |

## 9. Accesibilidad

- Contenedor de vistas con `tablist`, `tab`, `tabpanel`.
- Modos con `radiogroup` y `radio`; flechas izquierda/derecha.
- Resultado con `aria-live="polite"`.
- `Field` conecta label, hint y error.
- Foco visible, Escape cierra drawer/modal (Radix).
- Loading con `aria-busy`, no solo spinner.
- Colores de estado acompañados de icono y texto.
- `prefers-reduced-motion` respetado por las primitivas.
- Drawer conserva contenido montado al cerrar para no perder foco/estado.

## 10. Responsive

- Desktop: aside 320/352 px, un scroll de contenido, footer persistente.
- Móvil 390 px: drawer inferior, CTA sticky, `env(safe-area-inset-bottom)`.
- Tablet 820 px: drawer o dock según `min-width: 1024px`.
- Sin overflow horizontal; textos críticos a 12–14 px; metadatos a 10.5–11 px.

## 11. Garantías

- Nunca se fabrica `PROVIDER_VERIFIED`.
- Nunca se presenta sandbox capeado como sandbox aprobado.
- `/test` y `/run` conservan frontera.
- Guardar antes de probar bloquea la ejecución si falla.
- `onRun` y `onSelectNode` siguen siendo los puentes con el lienzo.
- Una prueba no publica el workflow.
