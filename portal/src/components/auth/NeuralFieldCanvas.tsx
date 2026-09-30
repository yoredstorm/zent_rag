import { useEffect, useRef } from "react";
import { cn } from "../ui/cn";
import {
  assignZones,
  composeStillFrame,
  createNeuralNet,
  excitePointer,
  netStats,
  setFocus,
  stepNeuralNet,
  triggerDive,
  triggerError,
  triggerSubmit,
  triggerSuccess,
  type NetEdge,
  type NetPlane,
  type NetPulse,
  type NetTone,
  type NeuralNet,
  type NetStats,
} from "../../lib/neuralNet";
import { DIVE_MS, DIVE_ZOOM } from "./entryTransit";
import { emitNeuralEvent, onNeuralEvent } from "./neuralSignal";

export type NeuralStats = NetStats;

const TAU = Math.PI * 2;

/** Paleta de la escena: teal señal, azul profundo, destello y alerta. */
const TONES: Record<NetTone, readonly [number, number, number]> = {
  signal: [82, 224, 182],
  deep: [96, 156, 226],
  flash: [214, 255, 244],
  alert: [238, 122, 132],
};

/** Capas de dibujo, de fondo a primer plano. */
const LAYERS: { plane: NetPlane; alpha: number; width: number; radius: number }[] = [
  { plane: 2, alpha: 0.4, width: 2.2, radius: 0.72 },
  { plane: 1, alpha: 0.78, width: 1.1, radius: 1 },
  { plane: 0, alpha: 1, width: 0.88, radius: 1.24 },
];

/** Parallax por plano (0 = cerca). */
const PARALLAX = [1, 0.55, 0.22] as const;

const AMPLITUDE_X = 26;
const AMPLITUDE_Y = 18;

/** Anticipación de la travesía: la cámara retrocede antes de entrar. */
const DIVE_ANTICIPATION = 0.18;

function smoothstep(t: number): number {
  return t * t * (3 - 2 * t);
}

function rgba(color: readonly [number, number, number], alpha: number): string {
  return `rgba(${color[0]}, ${color[1]}, ${color[2]}, ${Math.max(0, Math.min(1, alpha))})`;
}

/** Alfas cuantizados: durante la travesía no se crean strings de color por trazo. */
const STYLE_STEPS = 64;
const styleCache: Record<NetTone, string[]> = {
  signal: [],
  deep: [],
  flash: [],
  alert: [],
};

function toneColor(tone: NetTone, alpha: number): string {
  const clamped = alpha < 0 ? 0 : alpha > 1 ? 1 : alpha;
  const index = (clamped * (STYLE_STEPS - 1) + 0.5) | 0;
  const bucket = styleCache[tone];
  const cached = bucket[index];
  if (cached) return cached;
  const next = rgba(TONES[tone], index / (STYLE_STEPS - 1));
  bucket[index] = next;
  return next;
}

for (const tone of Object.keys(TONES) as NetTone[]) {
  for (let step = 0; step < STYLE_STEPS; step += 1) toneColor(tone, step / (STYLE_STEPS - 1));
}

type PlaneView = { minX: number; minY: number; maxX: number; maxY: number; zoom: number };

function boxHits(view: PlaneView, minX: number, maxX: number, minY: number, maxY: number): boolean {
  return maxX >= view.minX && minX <= view.maxX && maxY >= view.minY && minY <= view.maxY;
}

/** Sprite de resplandor pre-renderizado: glow barato, sin shadowBlur por frame. */
function createGlow(color: readonly [number, number, number]): HTMLCanvasElement {
  const size = 96;
  const sprite = document.createElement("canvas");
  sprite.width = size;
  sprite.height = size;
  const ctx = sprite.getContext("2d");
  if (ctx) {
    const gradient = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
    gradient.addColorStop(0, rgba(color, 0.92));
    gradient.addColorStop(0.28, rgba(color, 0.32));
    gradient.addColorStop(0.6, rgba(color, 0.07));
    gradient.addColorStop(1, rgba(color, 0));
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, size, size);
  }
  return sprite;
}

function quadPoint(
  ax: number,
  ay: number,
  cx: number,
  cy: number,
  bx: number,
  by: number,
  t: number
): { x: number; y: number } {
  const inv = 1 - t;
  return {
    x: inv * inv * ax + 2 * inv * t * cx + t * t * bx,
    y: inv * inv * ay + 2 * inv * t * cy + t * t * by,
  };
}

/**
 * Red cognitiva viva sobre canvas 2D.
 *
 * La actividad es una simulación real (ver `lib/neuralNet.ts`): los impulsos
 * viajan por los enlaces, excitán el nodo de llegada y se propagan; el puntero
 * empuja y enciende la zona que toca; el envío del formulario lanza una onda
 * que entra al sistema.
 *
 * - El plano lejano se dibuja en un lienzo aparte a media resolución: al
 *   subirlo, el suavizado bilineal produce profundidad de campo real sin
 *   filtros GPU.
 * - En la travesía la cámara recorta lo que ya no cabe en el cuadro, y el
 *   destello y el bloom son capas de opacidad (compositor), no un fill del
 *   viewport. Así el zoom sigue nítido sin repintar de más.
 * - Se detiene cuando la pestaña no está visible; con `prefers-reduced-motion`
 *   compone un único frame curado (actividad repartida, inmóvil).
 * - Decorativo: `aria-hidden`, fuera del árbol accesible.
 */
export function NeuralFieldCanvas({
  className,
  onStats,
}: {
  className?: string;
  onStats?: (stats: NeuralStats) => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const flashRef = useRef<HTMLDivElement>(null);
  const bloomRef = useRef<HTMLDivElement>(null);
  const statsRef = useRef(onStats);

  // El callback se guarda en un ref desde un efecto: el bucle de dibujo lee el
  // último valor sin reiniciar la simulación en cada render.
  useEffect(() => {
    statsRef.current = onStats;
  }, [onStats]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    const finePointer = window.matchMedia?.("(pointer: fine)").matches ?? false;

    const glow: Record<NetTone, HTMLCanvasElement> = {
      signal: createGlow(TONES.signal),
      deep: createGlow(TONES.deep),
      flash: createGlow(TONES.flash),
      alert: createGlow(TONES.alert),
    };

    // Lienzo del plano lejano (profundidad de campo por submuestreo).
    const far = document.createElement("canvas");
    const farCtx = far.getContext("2d");

    let width = 1;
    let height = 1;
    let raf = 0;
    let last = 0;
    let statsAt = 0;
    const parallax = { x: 0, y: 0 };
    const target = { x: 0.5, y: 0.5, active: false };
    let lastExcite = 0;

    // Cámara de la travesía: nace con el evento `dive` y ya no vuelve atrás.
    // `p` es el avance de la línea de tiempo; `q`, la parte de entrada, que es
    // la que mueve y amplía cada plano.
    const dive = {
      active: false,
      started: 0,
      p: 0,
      q: 0,
      k: 1,
      rot: 0,
      target: { x: 0, y: 0 },
    };

    const build = (): NeuralNet => {
      const compact = width < 1024;
      const density = width < 480 ? 0.6 : width < 768 ? 0.76 : width < 1024 ? 0.9 : 1;
      const net = createNeuralNet({ width, height, seed: 20260926, density });
      assignZones(net, { compact });
      // Arranque con actividad: la red no aparece apagada los primeros segundos.
      for (let i = 0; i < 240; i += 1) stepNeuralNet(net, 1 / 60);
      if (reduce) composeStillFrame(net);
      return net;
    };

    let net = (() => {
      const rect = canvas.getBoundingClientRect();
      width = Math.max(1, Math.round(rect.width));
      height = Math.max(1, Math.round(rect.height));
      return build();
    })();

    const applySize = () => {
      const area = width * height;
      const dpr = Math.min(window.devicePixelRatio || 1, area > 2_200_000 ? 1.5 : 2);
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      // El fondo pierde detalle a propósito: poco más de media resolución.
      const farScale = dpr * (width < 768 ? 0.62 : 0.5);
      far.width = Math.max(1, Math.round(width * farScale));
      far.height = Math.max(1, Math.round(height * farScale));
      farCtx?.setTransform(farScale, 0, 0, farScale, 0, 0);
    };
    applySize();

    /**
     * Cámara por plano: cada profundidad se amplía y converge a su ritmo, así
     * la travesía se lee como un avance real y no como un zoom plano. El plano
     * cercano se traga el cuadro; el lejano apenas se mueve y se desvanece.
     */
    const camera = (g: CanvasRenderingContext2D, plane: NetPlane) => {
      const factor = PARALLAX[plane];
      const zoom = 1 + (dive.k - 1) * factor;
      const pull = dive.q * factor;
      g.translate(width / 2, height / 2);
      g.rotate(dive.rot * factor);
      g.scale(zoom, zoom);
      g.translate(
        -(width / 2 + (dive.target.x - width / 2) * pull),
        -(height / 2 + (dive.target.y - height / 2) * pull)
      );
    };

    const focusWeight = (edge: NetEdge): number => {
      const zone = net.focusZone;
      if (!zone || net.focus[zone] <= 0.02) return 0;
      return net.nodes[edge.a].zone === zone && net.nodes[edge.b].zone === zone ? net.focus[zone] : 0;
    };

    const ink = (tone: NetTone, alpha: number) =>
      dive.active ? toneColor(tone, alpha) : rgba(TONES[tone], alpha);

    /**
     * Recorte de la cámara: al acercar, el cuadro visible en el mundo se
     * encoge. Pintar sólo eso mantiene el trazo nítido y acota el fill-rate.
     */
    const viewFor = (plane: NetPlane): PlaneView | null => {
      if (!dive.active) return null;
      const factor = PARALLAX[plane];
      const zoom = Math.max(1, 1 + (dive.k - 1) * factor);
      const pull = dive.q * factor;
      const cx = width / 2 + (dive.target.x - width / 2) * pull;
      const cy = height / 2 + (dive.target.y - height / 2) * pull;
      const pad = 128;
      const hx = width / (2 * zoom) + pad;
      const hy = height / (2 * zoom) + pad;
      return { minX: cx - hx, maxX: cx + hx, minY: cy - hy, maxY: cy + hy, zoom };
    };

    const paintEdge = (
      g: CanvasRenderingContext2D,
      edge: NetEdge,
      layer: (typeof LAYERS)[number],
      ox: number,
      oy: number,
      view: PlaneView | null
    ) => {
      const a = net.nodes[edge.a];
      const b = net.nodes[edge.b];
      const ax = a.x + a.vx + ox;
      const ay = a.y + a.vy + oy;
      const bx = b.x + b.vx + ox;
      const by = b.y + b.vy + oy;
      const cx = edge.cx + ox;
      const cy = edge.cy + oy;
      if (
        view &&
        !boxHits(view, Math.min(ax, bx, cx), Math.max(ax, bx, cx), Math.min(ay, by, cy), Math.max(ay, by, cy))
      ) {
        return;
      }
      const cycle =
        edge.cycle > 0
          ? 0.4 + 0.6 * (0.5 + 0.5 * Math.sin(((net.time * 1000) / edge.cycle) * TAU + edge.phase))
          : 1;
      const focus = focusWeight(edge);
      const alpha =
        (0.045 + edge.weight * 0.14) * layer.alpha * cycle * (1 - net.recoil * 0.45) +
        focus * 0.26 +
        net.success * 0.1 +
        net.dive * 0.05;
      if (alpha < 0.012) return;
      g.beginPath();
      g.moveTo(ax, ay);
      g.quadraticCurveTo(cx, cy, bx, by);
      g.strokeStyle = ink(edge.plane === 2 ? "deep" : "signal", alpha);
      g.lineWidth = (0.5 + edge.weight * 0.5) * layer.width;
      g.stroke();
    };

    const paintPulse = (
      g: CanvasRenderingContext2D,
      pulse: NetPulse,
      edge: NetEdge,
      layer: (typeof LAYERS)[number],
      ox: number,
      oy: number,
      view: PlaneView | null
    ) => {
      const a = net.nodes[edge.a];
      const b = net.nodes[edge.b];
      const ax = a.x + a.vx + ox;
      const ay = a.y + a.vy + oy;
      const bx = b.x + b.vx + ox;
      const by = b.y + b.vy + oy;
      const cx = edge.cx + ox;
      const cy = edge.cy + oy;
      if (
        view &&
        !boxHits(view, Math.min(ax, bx, cx), Math.max(ax, bx, cx), Math.min(ay, by, cy), Math.max(ay, by, cy))
      ) {
        return;
      }
      const base = (0.32 + pulse.strength * 0.46) * layer.alpha * (1 - net.recoil * 0.45);
      const head = pulse.t;
      const span = Math.min(0.36, 130 / Math.max(1, edge.length));
      const steps = view && view.zoom > 2.4 ? 2 : 4;
      let prev = quadPoint(ax, ay, cx, cy, bx, by, Math.max(0, head - span));
      for (let i = 1; i <= steps; i += 1) {
        const t = Math.max(0, head - span + (span * i) / steps);
        const point = quadPoint(ax, ay, cx, cy, bx, by, t);
        g.beginPath();
        g.moveTo(prev.x, prev.y);
        g.lineTo(point.x, point.y);
        g.strokeStyle = ink(pulse.tone, base * Math.pow(i / steps, 1.7));
        g.lineWidth = (0.9 + pulse.strength * 1.5) * layer.width;
        g.stroke();
        prev = point;
      }
      const headPoint = quadPoint(ax, ay, cx, cy, bx, by, head);
      const size = (18 + pulse.strength * 30) * layer.radius;
      g.globalAlpha = Math.min(1, base * 1.5);
      g.drawImage(glow[pulse.tone], headPoint.x - size / 2, headPoint.y - size / 2, size, size);
      g.globalAlpha = 1;
    };

    const paintPlane = (
      g: CanvasRenderingContext2D,
      layer: (typeof LAYERS)[number],
      ox: number,
      oy: number
    ) => {
      const view = viewFor(layer.plane);
      for (const edge of net.edges) {
        if (edge.plane !== layer.plane) continue;
        paintEdge(g, edge, layer, ox, oy, view);
      }

      for (const pulse of net.pulses) {
        const edge = net.edges[pulse.edge];
        if (!edge || edge.plane !== layer.plane) continue;
        paintPulse(g, pulse, edge, layer, ox, oy, view);
      }

      for (const node of net.nodes) {
        if (node.plane !== layer.plane) continue;
        const wobbleX = Math.sin(net.time * 0.55 + node.phase) * (1.5 + node.z * 3);
        const wobbleY = Math.cos(net.time * 0.45 + node.phase * 1.3) * (1.2 + node.z * 2.4);
        const x = node.x + node.vx + ox + wobbleX;
        const y = node.y + node.vy + oy + wobbleY;
        if (view && (x < view.minX || x > view.maxX || y < view.minY || y > view.maxY)) continue;
        const energy = Math.min(1, node.energy);
        const tone: NetTone = node.energy > 1.02 || net.success > 0.4 ? "flash" : "signal";
        const radius = node.radius * layer.radius * (1 + energy * 0.85);
        const size = radius * (7 + energy * 13);
        const halo = (0.055 + energy * 0.4) * layer.alpha * (1 - net.recoil * 0.5);
        if (!(view && view.zoom > 2.6 && energy < 0.08)) {
          g.globalAlpha = halo;
          g.drawImage(glow[tone], x - size / 2, y - size / 2, size, size);
          g.globalAlpha = 1;
        }
        g.beginPath();
        g.arc(x, y, Math.max(0.4, radius), 0, TAU);
        g.fillStyle = ink(tone, Math.min(1, 0.2 + energy * 0.72) * layer.alpha);
        g.fill();
        if (node.role === "hub" && !(view && view.zoom > 2.6)) {
          g.beginPath();
          g.arc(x, y, radius + 3.5, 0, TAU);
          g.strokeStyle = ink(tone, (0.07 + energy * 0.22) * layer.alpha);
          g.lineWidth = 0.8;
          g.stroke();
        }
      }
    };

    let flashOpacity = -1;
    let bloomOpacity = -1;
    const setLayerOpacity = (el: HTMLDivElement | null, opacity: number, previous: number): number => {
      if (!el) return previous;
      const next = opacity < 0.004 ? 0 : Math.round(opacity * 1000) / 1000;
      if (next === previous) return previous;
      el.style.opacity = String(next);
      return next;
    };

    const draw = () => {
      ctx.clearRect(0, 0, width, height);
      const [farLayer, ...frontLayers] = LAYERS;
      // Durante la travesía el fondo y luego los planos quedan atrás: cuando el
      // cuadro ya es luz, seguir pintándolos sería trabajo perdido.
      const farVisible = !dive.active || dive.q < 0.55;
      const planesVisible = !dive.active || dive.q < 0.9;

      // Plano lejano: lienzo aparte a media resolución. Al subirlo, el
      // suavizado bilineal da desenfoque real (profundidad de campo) barato.
      if (farCtx && farVisible) {
        farCtx.clearRect(0, 0, width, height);
        farCtx.save();
        farCtx.globalCompositeOperation = "lighter";
        farCtx.globalAlpha = dive.active ? 1 - 0.95 * smoothstep(dive.q) : 1;
        const factor = PARALLAX[farLayer.plane];
        if (dive.active) camera(farCtx, farLayer.plane);
        paintPlane(farCtx, farLayer, parallax.x * AMPLITUDE_X * factor, parallax.y * AMPLITUDE_Y * factor);
        farCtx.restore();
      }

      ctx.save();
      ctx.globalCompositeOperation = "lighter";
      ctx.globalAlpha = 1;
      if (farCtx && farVisible) ctx.drawImage(far, 0, 0, width, height);

      if (planesVisible) {
        for (const layer of frontLayers) {
          const factor = PARALLAX[layer.plane];
          ctx.save();
          if (dive.active) camera(ctx, layer.plane);
          paintPlane(ctx, layer, parallax.x * AMPLITUDE_X * factor, parallax.y * AMPLITUDE_Y * factor);
          ctx.restore();
        }
      }

      // Onda de envío: cruza la red y la enciende a su paso.
      if (net.wave && (!dive.active || dive.q < 0.9)) {
        const wave = net.wave;
        const near = viewFor(0);
        const ring =
          !near ||
          wave.r + 24 >=
            Math.hypot(
              Math.max(wave.x - near.maxX, near.minX - wave.x, 0),
              Math.max(wave.y - near.maxY, near.minY - wave.y, 0)
            );
        if (ring) {
          ctx.save();
          if (dive.active) camera(ctx, 0);
          // El grosor crece con la cámara hasta un tope: más allá el halo
          // tapaba el cuadro y el stroke de 14px escalado era puro fill-rate.
          const cover = Math.max(1, (near?.zoom ?? 1) / 2.2);
          ctx.beginPath();
          ctx.arc(wave.x, wave.y, wave.r, 0, TAU);
          ctx.strokeStyle = ink(wave.tone, wave.alpha * 0.35);
          ctx.lineWidth = 1.4 / cover;
          ctx.stroke();
          ctx.beginPath();
          ctx.arc(wave.x, wave.y, wave.r, 0, TAU);
          ctx.strokeStyle = ink(wave.tone, wave.alpha * 0.1);
          ctx.lineWidth = 14 / cover;
          ctx.stroke();
          ctx.restore();
        }
      }

      ctx.restore();

      // Destello y bloom viven en capas CSS: opacidad en el compositor, el mismo
      // gradiente que la cortina. El canvas ya no rellena el viewport cada frame.
      const flashAlpha = net.success > 0.02 ? net.success * 0.42 : 0;
      flashOpacity = setLayerOpacity(flashRef.current, flashAlpha, flashOpacity);
      const bloomAlpha =
        dive.active && dive.p > 0.8 ? Math.pow(Math.min(1, (dive.p - 0.8) / 0.2), 1.25) : 0;
      bloomOpacity = setLayerOpacity(bloomRef.current, bloomAlpha, bloomOpacity);
    };

    const publish = (at: number) => {
      if (dive.active || at - statsAt < 420) return;
      statsAt = at;
      const stats = netStats(net);
      statsRef.current?.(stats);
      emitNeuralEvent({ type: "stats", stats });
    };

    /**
     * Línea de tiempo de la travesía: anticipación, entrada con aceleración
     * exponencial y freno en el destino, que ya queda en el centro del cuadro.
     */
    const advanceDive = (now: number) => {
      if (!dive.active) return;
      if (!dive.started) dive.started = now;
      const p = Math.min(1, (now - dive.started) / DIVE_MS);
      dive.p = p;
      if (p < DIVE_ANTICIPATION) {
        const t = p / DIVE_ANTICIPATION;
        dive.q = 0;
        dive.k = 1 - 0.02 * (1 - Math.pow(1 - t, 3));
        dive.rot = 0;
        return;
      }
      const q = (p - DIVE_ANTICIPATION) / (1 - DIVE_ANTICIPATION);
      dive.q = q;
      dive.k = 0.98 + (DIVE_ZOOM - 0.98) * Math.pow(q, 2.35);
      dive.rot = 0.012 * q * q;
    };

    const frame = (now: number) => {
      if (!last) last = now;
      const dt = (now - last) / 1000;
      last = now;

      // Parallax en lerp: sin saltos, interrumpible.
      const tx = target.active ? (target.x - 0.5) * 2 : 0;
      const ty = target.active ? (target.y - 0.5) * 2 : 0;
      parallax.x += (tx - parallax.x) * 0.05;
      parallax.y += (ty - parallax.y) * 0.05;

      advanceDive(now);
      // Con la cámara dentro de la neurona la simulación ya no se ve: se frena.
      if (dive.q < 0.9) stepNeuralNet(net, dt);
      draw();
      publish(now);

      raf = window.requestAnimationFrame(frame);
    };

    const onPointerMove = (event: PointerEvent) => {
      // Durante la travesía la cámara manda: el puntero no empuja ni enciende.
      if (dive.active) return;
      target.x = event.clientX / Math.max(1, window.innerWidth);
      target.y = event.clientY / Math.max(1, window.innerHeight);
      target.active = true;
      if (event.timeStamp - lastExcite < 55) return;
      lastExcite = event.timeStamp;
      const rect = canvas.getBoundingClientRect();
      excitePointer(net, event.clientX - rect.left, event.clientY - rect.top, 1);
    };
    const onPointerLeave = () => {
      target.active = false;
    };
    const onPointerDown = (event: PointerEvent) => {
      if (dive.active) return;
      const rect = canvas.getBoundingClientRect();
      excitePointer(net, event.clientX - rect.left, event.clientY - rect.top, 1.6);
    };
    const onVisibility = () => {
      if (document.hidden) {
        if (raf) window.cancelAnimationFrame(raf);
        raf = 0;
      } else if (!reduce && !raf) {
        last = 0;
        raf = window.requestAnimationFrame(frame);
      }
    };

    let resizeTimer = 0;
    const onResize = () => {
      window.clearTimeout(resizeTimer);
      resizeTimer = window.setTimeout(() => {
        const rect = canvas.getBoundingClientRect();
        const nextWidth = Math.max(1, Math.round(rect.width));
        const nextHeight = Math.max(1, Math.round(rect.height));
        const changed = nextWidth !== width || nextHeight !== height;
        if (!changed) return;
        const rebuild =
          Math.abs(nextWidth - net.width) > 48 || Math.abs(nextHeight - net.height) > 140;
        const ratioX = nextWidth / Math.max(1, width);
        const ratioY = nextHeight / Math.max(1, height);
        width = nextWidth;
        height = nextHeight;
        // El destino de la travesía vive en píxeles: si el cuadro cambia de
        // tamaño, se reescala para no perder el centro.
        if (dive.active) {
          dive.target.x *= ratioX;
          dive.target.y *= ratioY;
        }
        applySize();
        if (rebuild) net = build();
        if (reduce) draw();
      }, 140);
    };

    const unsubscribe = onNeuralEvent((event) => {
      if (event.type === "focus") setFocus(net, event.zone);
      else if (event.type === "submit") triggerSubmit(net);
      else if (event.type === "error") triggerError(net);
      else if (event.type === "success") triggerSuccess(net);
      else if (event.type === "dive") {
        // Sin movimiento reducido no hay travesía: la escena se queda en su
        // frame curado y el relevo lo hace la cortina, que es sólo opacidad.
        if (reduce) {
          triggerSuccess(net);
          draw();
          return;
        }
        const destination = triggerDive(net);
        dive.target.x = destination.x;
        dive.target.y = destination.y;
        dive.p = 0;
        dive.q = 0;
        dive.k = 1;
        dive.rot = 0;
        dive.started = 0;
        dive.active = true;
        target.active = false;
        if (!raf && !document.hidden) {
          last = 0;
          raf = window.requestAnimationFrame(frame);
        }
        return;
      } else return;
      if (reduce) draw();
    });

    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(onResize);
    observer?.observe(canvas);
    window.addEventListener("resize", onResize);
    document.addEventListener("visibilitychange", onVisibility);

    if (reduce) {
      draw();
      // En el siguiente tick: así el lector de telemetría ya está suscripto.
      window.setTimeout(() => {
        const stats = netStats(net);
        statsRef.current?.(stats);
        emitNeuralEvent({ type: "stats", stats });
      }, 0);
    } else {
      raf = window.requestAnimationFrame(frame);
      window.addEventListener("pointermove", onPointerMove, { passive: true });
      window.addEventListener("pointerdown", onPointerDown, { passive: true });
      if (finePointer) window.addEventListener("pointerleave", onPointerLeave);
    }

    return () => {
      if (raf) window.cancelAnimationFrame(raf);
      window.clearTimeout(resizeTimer);
      observer?.disconnect();
      window.removeEventListener("resize", onResize);
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerdown", onPointerDown);
      window.removeEventListener("pointerleave", onPointerLeave);
      document.removeEventListener("visibilitychange", onVisibility);
      unsubscribe();
    };
  }, []);

  return (
    <>
      <canvas ref={canvasRef} className={cn("block h-full w-full", className)} aria-hidden />
      <div ref={flashRef} className="auth-dive-flash" aria-hidden />
      <div ref={bloomRef} className="auth-dive-bloom" aria-hidden />
    </>
  );
}
