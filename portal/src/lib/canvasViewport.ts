/**
 * Geometría del viewport del canvas de workflows: zoom anclado al cursor,
 * encuadres (todo / selección / nodo), nivel de detalle semántico y
 * persistencia por usuario y workflow. Funciones puras: el canvas solo aplica
 * el resultado como `translate(x, y) scale(s)`.
 */

export type Viewport = { x: number; y: number; s: number };
export type Rect = { x: number; y: number; w: number; h: number };
export type Size = { w: number; h: number };

export const NODE_W = 248;
export const NODE_H = 112;
export const MIN_ZOOM = 0.2;
export const MAX_ZOOM = 2;

export function clampZoom(s: number): number {
  if (!Number.isFinite(s)) return 1;
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, s));
}

/** Zoom manteniendo fijo el punto `(px, py)` de pantalla (cursor o centro). */
export function zoomAt(view: Viewport, px: number, py: number, nextScale: number): Viewport {
  const s = clampZoom(nextScale);
  if (s === view.s) return view;
  return {
    x: px - ((px - view.x) / view.s) * s,
    y: py - ((py - view.y) / view.s) * s,
    s,
  };
}

/** Caja que envuelve los nodos (posición de esquina superior izquierda + tamaño fijo). */
export function nodesBounds(nodes: { position: { x: number; y: number } }[]): Rect | null {
  if (nodes.length === 0) return null;
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const n of nodes) {
    const x = Number.isFinite(n.position?.x) ? n.position.x : 0;
    const y = Number.isFinite(n.position?.y) ? n.position.y : 0;
    minX = Math.min(minX, x);
    minY = Math.min(minY, y);
    maxX = Math.max(maxX, x + NODE_W);
    maxY = Math.max(maxY, y + NODE_H);
  }
  return { x: minX, y: minY, w: maxX - minX, h: maxY - minY };
}

/**
 * Encuadra `rect` dentro del área visible. `insets` descuenta lo que tapan los
 * overlays (rail, inspector flotante) para que el contenido no quede debajo.
 */
export function fitRect(
  rect: Rect,
  host: Size,
  options: { padding?: number; maxZoom?: number; insets?: { left?: number; right?: number; top?: number; bottom?: number } } = {},
): Viewport {
  const pad = options.padding ?? 48;
  const left = options.insets?.left ?? 0;
  const right = options.insets?.right ?? 0;
  const top = options.insets?.top ?? 0;
  const bottom = options.insets?.bottom ?? 0;
  const availW = Math.max(80, host.w - left - right - pad * 2);
  const availH = Math.max(80, host.h - top - bottom - pad * 2);
  const s = clampZoom(Math.min(options.maxZoom ?? 1, availW / Math.max(1, rect.w), availH / Math.max(1, rect.h)));
  const cx = left + pad + availW / 2;
  const cy = top + pad + availH / 2;
  return {
    x: cx - (rect.x + rect.w / 2) * s,
    y: cy - (rect.y + rect.h / 2) * s,
    s,
  };
}

/** Centra el punto de mundo `(wx, wy)` sin cambiar el zoom (o con `scale`). */
export function centerOn(view: Viewport, wx: number, wy: number, host: Size, scale?: number): Viewport {
  const s = clampZoom(scale ?? view.s);
  return { x: host.w / 2 - wx * s, y: host.h / 2 - wy * s, s };
}

/**
 * Desplaza lo mínimo para que `rect` (mundo) quede visible dentro de
 * `host` menos `rightInset`. Devuelve la misma referencia si ya es visible.
 */
export function revealRect(view: Viewport, rect: Rect, host: Size, rightInset = 0, margin = 16): Viewport {
  const left = view.x + rect.x * view.s;
  const top = view.y + rect.y * view.s;
  const right = left + rect.w * view.s;
  const bottom = top + rect.h * view.s;
  const usableW = host.w - rightInset;
  let x = view.x;
  let y = view.y;
  if (right > usableW - margin) x = view.x - (right - (usableW - margin));
  if (left + (x - view.x) < margin) x = view.x + (margin - left);
  if (bottom > host.h - margin) y = view.y - (bottom - (host.h - margin));
  if (top + (y - view.y) < margin) y = view.y + (margin - top);
  return x === view.x && y === view.y ? view : { ...view, x, y };
}

/** Rectángulo visible en coordenadas de mundo (para el minimapa). */
export function visibleWorldRect(view: Viewport, host: Size): Rect {
  return { x: -view.x / view.s, y: -view.y / view.s, w: host.w / view.s, h: host.h / view.s };
}

export function rectsIntersect(a: Rect, b: Rect): boolean {
  return a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;
}

/** Rectángulo normalizado desde dos esquinas cualesquiera. */
export function rectFromPoints(ax: number, ay: number, bx: number, by: number): Rect {
  return { x: Math.min(ax, bx), y: Math.min(ay, by), w: Math.abs(bx - ax), h: Math.abs(by - ay) };
}

/**
 * Zoom semántico: en alejado se pintan nodos simplificados con etiqueta
 * grande; en acercado, detalle técnico (id, puertos, duración).
 */
export type DetailLevel = "overview" | "normal" | "detail";

export function detailLevel(scale: number): DetailLevel {
  if (scale < 0.5) return "overview";
  if (scale >= 1.25) return "detail";
  return "normal";
}

/**
 * Rueda/trackpad con un mismo comportamiento:
 * - pinch del trackpad (el navegador manda `ctrlKey`) y Ctrl/⌘ + rueda: zoom fino.
 * - rueda de ratón (saltos discretos, sin eje X): zoom por pasos.
 * - desplazamiento de dos dedos en trackpad: pan.
 */
export type WheelIntent = { kind: "zoom"; factor: number } | { kind: "pan"; dx: number; dy: number };

export function wheelIntent(ev: {
  deltaX: number;
  deltaY: number;
  deltaMode: number;
  ctrlKey: boolean;
  metaKey: boolean;
  shiftKey: boolean;
}): WheelIntent {
  const lineScale = ev.deltaMode === 1 ? 16 : ev.deltaMode === 2 ? 400 : 1;
  const dx = ev.deltaX * lineScale;
  const dy = ev.deltaY * lineScale;
  if (ev.ctrlKey || ev.metaKey) {
    return { kind: "zoom", factor: Math.exp(-dy * 0.01) };
  }
  const mouseWheel = ev.deltaMode !== 0 || (dx === 0 && Math.abs(dy) >= 40 && Number.isInteger(dy));
  if (mouseWheel && !ev.shiftKey) {
    return { kind: "zoom", factor: dy < 0 ? 1.12 : 1 / 1.12 };
  }
  if (ev.shiftKey && dx === 0) return { kind: "pan", dx: -dy, dy: 0 };
  return { kind: "pan", dx: -dx, dy: -dy };
}

// ---------------------------------------------------------------------------
// Persistencia por usuario y workflow (localStorage, nunca en el grafo)
// ---------------------------------------------------------------------------

const VIEWPORT_PREFIX = "zent.wf.viewport.v1";

export function viewportStorageKey(userKey: string, workflowId: string): string {
  return `${VIEWPORT_PREFIX}:${userKey}:${workflowId}`;
}

export function loadViewport(key: string | null | undefined): Viewport | null {
  if (!key) return null;
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<Viewport>;
    if (![parsed.x, parsed.y, parsed.s].every((v) => typeof v === "number" && Number.isFinite(v))) return null;
    return { x: parsed.x!, y: parsed.y!, s: clampZoom(parsed.s!) };
  } catch {
    return null;
  }
}

export function saveViewport(key: string | null | undefined, view: Viewport): void {
  if (!key) return;
  try {
    window.localStorage.setItem(
      key,
      JSON.stringify({ x: Math.round(view.x), y: Math.round(view.y), s: Number(view.s.toFixed(3)) }),
    );
  } catch {
    // sin persistencia (modo privado / cuota)
  }
}
