# Zent — Design System

Contrato visual del frontend (`portal/`). Fuente de verdad: `portal/src/index.css` (tokens + capa de componentes) y `portal/src/components/ui/` (primitivas React).

## Dirección

**Instrumento de precisión.** Zent se ve como el panel desde donde una empresa opera su inteligencia: grafito fresado, hairlines de 1px, y teal como señal de actividad, nunca como decoración.

- Personalidad: técnico, calmo, preciso, enterprise-ready. Futurista sin cyberpunk. Vivo sin hiperanimado.
- Referencias de criterio (no de copia): Linear, Raycast, Stripe Dashboard, Vercel.

## Depth strategy

**Bordes + escalones tonales, una sola fuente de luz.** Sin glassmorphism decorativo; blur solo en scrim de overlay.

| Paso | Dark | Light | Uso |
|---|---|---|---|
| canvas | `#0a0e13` | `#f5f7fa` | fondo de app (`bg-bg`) |
| s1 `surface` | `#0f141b` | `#ffffff` | paneles, tablas, topbar (`bg-surface`) |
| s2 `raised` | `#151c25` | `#eef2f7` | popovers, filas elevadas, inputs de segundo nivel (`bg-raised`) |
| s3 `soft` | `#1c2531` | `#e7ecf3` | hover, chips, selección suave (`bg-soft`) |
| overlay | `#212b39` | `#ffffff` | modales y drawers (`bg-overlay`) |
| control | `rgb(5 8 12 / .42)` | `#fbfcfe` | inputs (inset en dark, claro en light) |

Bordes: `--zent-border-soft` (separación), `--zent-border/--color-border` (estructura), `--zent-border-strong` (énfasis/focus de hover). Dark vive en `rgba(255,255,255,.045–.14)`, light en `#e4e8ef–#cdd6e1`.

Sombras tintadas al hue del canvas (`--shadow-panel`, `--shadow-pop`, `--shadow-glow`). Nunca negro puro.

## Espaciado y geometría

- Base 4px. Permitidos: 4 / 8 / 12 / 16 / 20 / 24 / 32 / 40 / 48 / 64. Nada arbitrario.
- Densidad de producto: paneles `p-4`, celdas de tabla `px-3 py-2.5`, controles `min-h-9`.
- Radios: control `8px` (`rounded-sm`), contenedor `10px` (`rounded-md`) y panel `12px` (`rounded-lg`), overlay `16px` (`rounded-xl`). Concéntricos: `outer = inner + padding`. Nunca pill si no es un tag.

## Jerarquía tipográfica

Geist / Geist Mono. Escala fija 11 / 14 / 16 / 18 / 24 / 30.

- `display` 30/600/-0.025em (solo auth y empty states)
- `text-h1` 24/600/-0.022em (PageHeader)
- `text-h2` 18/600/-0.015em (SectionHeader)
- `text-h3` 14/600
- body 14/400, `leading-relaxed`, `max-w-[68ch]`
- `eyebrow` / `text-caption` 11/600/0.07em uppercase — solo para labels de sección, status y micro-metadatos.

La jerarquía se construye con **peso + color + tamaño juntos**, no con tamaño solo. Cuatro niveles de texto: `text-text` / `text-muted` / `text-faint` / `text-ghost` (este último solo decorativo o deshabilitado).

Todo dato numérico dinámico: `tabular-nums` (ya aplicado a `.mono`, `.stat-value` y tablas).

## Motion

| Token | Valor | Uso |
|---|---|---|
| `--dur-1` | 120ms | press, hover de fila |
| `--dur-2` | 160ms | hover, focus, botones |
| `--dur-3` | 200ms | tabs, dropdowns, tooltips |
| `--dur-4` | 260ms | drawers, paneles |
| `--dur-5` | 340ms | charts, progreso |
| `--dur-6` | 420ms | entrada de página |

- Easing de entrada/interacción: `--ease-out cubic-bezier(.23,1,.32,1)`. Movimiento en pantalla: `--ease-in-out`.
- Springs (`motion`) solo cuando hay razón espacial: sidebar, indicador activo de nav, canvas de workflows, reorder de listas.
- Regla dura: **la animación nunca retrasa la interacción**. Acciones repetidas 100+/día (palette, atajos) sin animación decorativa.
- Solo `transform` y `opacity` (+ `background-color`/`color`/`border-color`). Nunca `transition: all`.
- Entradas desde `opacity 0` + `scale(0.97)` / `translateY(4–12px)`. Nunca desde `scale(0)`.
- Popovers escalan desde su trigger (`transform-origin`); modales centrados.
- `prefers-reduced-motion`: se conservan opacidad y color, se elimina movimiento.

## Z-scale

`sticky 20 · sidebar 30 · drawer 40 · modal 50 · palette 60 · tour 70 · toast 80` (`--z-*` en `index.css`).

## Shell

- Sidebar 248px expandido / 72px colapsado, conmutable y persistido (`zent_sidebar_collapsed`, atributo `data-sidebar` en `<html>`). El ancho es una custom property registrada (`@property --sidebar-w`) para animar el colapso sin tocar la lógica de layout; el contenido usa `.app-main` (padding-left animado).
- Sidebar comparte el canvas: `bg-surface` + borde hairline, sin blur. El estado activo se marca con rail de 2px en accent + `bg-soft/70` (no un bloque de color).
- El topbar es chrome: **nunca** renderiza `h1` (dos h1 por página rompe jerarquía semántica y semántica de tests). Muestra eyebrow de sección + título como `span`.
- Ancho de contenido: `max-w-[1360px]`; full-bleed solo para el canvas de workflows.
- Drawers/modales/popovers/menús: siempre sobre Radix (focus trap, scroll lock, escape, colisiones). Tooltip para texto breve, Popover para contenido, Drawer para inspección contextual, Modal solo para decisiones.

## F5 — patrones de página

- **Dashboard**: un foco ("Pulso del workspace": estado 30px + servicios + cuota + pendientes) y métricas demotadas con `Metric size="md"` (22px). Nunca 6 tarjetas idénticas de KPI. Sin tendencias inventadas: si no hay dato de variación, no se dibuja flecha.
- **Chat/Playground**: composer multilínea (Enter envía, Shift+Enter salto), estados operacionales con `.state-rail[data-state=running]` mientras corre, fuentes como evidencia (lista numerada + `Drawer` con fragmento completo y relevancia), SQL en `CodeBlock`, error con "Reintentar" que re-ejecuta sin duplicar el mensaje del usuario.
- **Knowledge**: `Overview` = foco + 3 métricas + atención; listas densas en panel único con `state-rail` por estado real; el resto con `DataTable` (sorting controlado, `table-sticky`, loading/vacío/error) y `Pagination`/`ResultCount`. `SourceDetail` usa back + estado en `meta` + tabs.
- Los estados del backend van SIEMPRE por `StatusBadge` (traduce + icono + tono). Si un estado no existe en `STATUS_META`, se agrega ahí en vez de improvisar por página.

## Proceso (lecciones)

- `Field` conecta `label`↔control por contexto (`useId`): los inputs usan `ctx.id ?? id`. Nunca mover la marca de requerido (`*`) dentro del `<label>`: contamina el nombre accesible y rompe coincidencias exactas por label.
- Animación de entrada de página: `controls.start()` sobre un `motion.div` que NO se remonta. Usar `key` en el wrapper de ruta deja la página anterior montada oculta durante la transición y provoca duplicados de DOM.
- QA visual: capturar pantallas con Playwright (login + rutas clave en dark/light, 1440/820/390) y revisar PNGs; verificar `console`/`pageerror` en 0. No hay browser tool en todas las sesiones.
- Verificación por fase: `npm run typecheck`, `lint`, `test`, `build`; e2e contra `vite preview` (build real) usando `E2E_EXTERNAL=1 E2E_BASE_URL=…`, no contra el dev server (HMR rompe corridas largas).
- Los specs e2e dependen de nombres accesibles (`Continuar`, `Entrar`, `Empezar trial`, `Cuenta`, `Ocultar/Ocultar menú`, labels `Email`/`Contraseña`, `data-testid` de banners y de start-mode). Cambiar copy implica actualizar el spec de forma deliberada.
- La latencia de embeddings de Ollama es variable (9–90 s por batch): los e2e que dependen de indexación pueden fallar por cola congestionada, no por UI.
- Los tests unitarios (57 files / 329 tests) se ejecutan con `isolate` por archivo: bajo contención pueden aparecer flakes de `waitFor`. Si un test falla, re-córrelo aislado antes de tocar código.
- La entrega se hace por bloques validados: `typecheck` + `lint` (0 errores) + `test` + `build` + e2e contra `vite preview`, y recién ahí commit a master + rebuild del contenedor (`docker compose build portal && docker compose up -d portal`).

## Signature

- **Activity rail** (`.state-rail[data-state=…]`): rail de 2px en filas/nodos/items cuyo estado es real (`queued · running · ready · warning · failed`). El color acompaña, nunca es el único indicador.
- **Evidence-first chat**: las citas son tarjetas de evidencia inspeccionables en drawer de contexto, no links al pie.
- **Learning orb** (`.kl-*`): órbitas de etapas reales del pipeline de conocimiento.

## Componentes (medidas)

- **Button** — `min-h-9 · px-4 · radius 8 · 14px/500`; variantes primary (accent), secondary (border + `bg-raised`), danger, ghost; press `scale(.978)`; `btn-sm` `min-h-8 · px-2.5 · 13px`; `btn-icon` `36×36`.
- **Field** — label 13/500 `text-text`; control `min-h-9 · radius 8 · bg-control · border 1px`; focus `border-accent` + ring 3px `accent-soft`; error `border-danger` + ring `danger-soft`; hint 12/muted; error 13/500/danger. Nunca placeholder como label.
- **Panel** — radius 12 · border 1px · `bg-surface` · `shadow-panel`; `panel-header` `px-4 py-3` con border-b; `panel-body` `p-4`.
- **Badge** — `radius 6 · px-1.5 py-0.5 · 11/500`; tonos `ok · warn · danger · info · accent · muted`; estado siempre con icono o texto, no solo color.
- **Stat** — label 11/500 tracked uppercase `text-faint`; valor 26/600/-0.02em tabular; hint 12/muted. Un solo focal por vista.
- **Table** — th 11/600/0.06em uppercase `text-faint`; td `px-3 py-2.5` 14px; hover `soft` al 55%; `data-selected="true"` con `accent-soft`; `table-sticky` para thead.
- **Tabs** — `min-h-10 · px-3 · 13.5/500`; activo = `border-accent` + `text-text`.
- **Overlays** — tooltip 200ms · popover/dropdown 200ms · modal 260ms (scrim + `bg-overlay` + `shadow-pop` + radius 16) · drawer lateral para inspección contextual.
- **Skeleton** — forma del layout final, no spinner de página. Spinner solo en operaciones puntuales inline.

## Reglas

1. Color dice algo: accent = acción/identidad/actividad; ok/warn/danger/info = estado. Nunca decoración.
2. Un accent. Sin gradientes decorativos, sin violeta IA, sin neón.
3. Estados obligatorios por superficie: default, hover, focus, pressed, selected, disabled, loading, empty, error, sin permiso, sin resultados.
4. Usar primitivas antes que HTML suelto: `Button` antes que `<button className="...">`, `Field` antes que input a mano.
5. Sidebar comparte el canvas (misma superficie + borde), no es "otro mundo".
6. Sin `transition: all`, sin `h-[100vh]` (usar `100dvh`), sin `text-transform: uppercase` fuera de eyebrows.
7. Microcopy directo y accionable: decir qué pasó y qué hacer. Sin "Oops!" ni marketing en pantallas operativas.
