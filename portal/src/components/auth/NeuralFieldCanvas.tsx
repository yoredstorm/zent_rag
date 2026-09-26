import { useEffect, useRef } from "react";
import { cn } from "../ui/cn";
import {
  assignZones,
  createNeuralNet,
  excitePointer,
  netStats,
  setFocus,
  stepNeuralNet,
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

function rgba(color: readonly [number, number, number], alpha: number): string {
  return `rgba(${color[0]}, ${color[1]}, ${color[2]}, ${Math.max(0, Math.min(1, alpha))})`;
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
 * - Sólo dibuja por frame con composición aditiva: sin filtros, sin layout.
 * - Se detiene cuando la pestaña no está visible y se congela en un único frame
 *   con `prefers-reduced-motion`.
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

    let width = 1;
    let height = 1;
    let flash: CanvasGradient | null = null;
    let raf = 0;
    let last = 0;
    let statsAt = 0;
    const parallax = { x: 0, y: 0 };
    const target = { x: 0.5, y: 0.5, active: false };
    let lastExcite = 0;

    const build = (): NeuralNet => {
      const compact = width < 1024;
      const density = width < 480 ? 0.6 : width < 768 ? 0.76 : width < 1024 ? 0.9 : 1;
      const net = createNeuralNet({ width, height, seed: 20260926, density });
      assignZones(net, { compact });
      // Arranque con actividad: la red no aparece apagada los primeros segundos.
      for (let i = 0; i < 240; i += 1) stepNeuralNet(net, 1 / 60);
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
      const gradient = ctx.createRadialGradient(
        width * 0.52,
        height * 0.42,
        0,
        width * 0.52,
        height * 0.42,
        Math.max(width, height) * 0.72
      );
      gradient.addColorStop(0, "rgba(198, 255, 238, 0.5)");
      gradient.addColorStop(0.42, "rgba(82, 224, 182, 0.14)");
      gradient.addColorStop(1, "rgba(82, 224, 182, 0)");
      flash = gradient;
    };
    applySize();

    const focusWeight = (edge: NetEdge): number => {
      const zone = net.focusZone;
      if (!zone || net.focus[zone] <= 0.02) return 0;
      return net.nodes[edge.a].zone === zone && net.nodes[edge.b].zone === zone ? net.focus[zone] : 0;
    };

    const drawEdge = (
      edge: NetEdge,
      layer: (typeof LAYERS)[number],
      ox: number,
      oy: number
    ) => {
      const a = net.nodes[edge.a];
      const b = net.nodes[edge.b];
      const cycle =
        edge.cycle > 0
          ? 0.4 + 0.6 * (0.5 + 0.5 * Math.sin((net.time * 1000) / edge.cycle * TAU + edge.phase))
          : 1;
      const focus = focusWeight(edge);
      const alpha =
        (0.045 + edge.weight * 0.14) * layer.alpha * cycle * (1 - net.recoil * 0.45) +
        focus * 0.26 +
        net.success * 0.1;
      if (alpha < 0.012) return;
      ctx.beginPath();
      ctx.moveTo(a.x + a.vx + ox, a.y + a.vy + oy);
      ctx.quadraticCurveTo(edge.cx + ox, edge.cy + oy, b.x + b.vx + ox, b.y + b.vy + oy);
      ctx.strokeStyle = rgba(edge.plane === 2 ? TONES.deep : TONES.signal, alpha);
      ctx.lineWidth = (0.5 + edge.weight * 0.5) * layer.width;
      ctx.stroke();
    };

    const drawPulse = (
      pulse: NetPulse,
      edge: NetEdge,
      layer: (typeof LAYERS)[number],
      ox: number,
      oy: number
    ) => {
      const a = net.nodes[edge.a];
      const b = net.nodes[edge.b];
      const ax = a.x + a.vx + ox;
      const ay = a.y + a.vy + oy;
      const bx = b.x + b.vx + ox;
      const by = b.y + b.vy + oy;
      const cx = edge.cx + ox;
      const cy = edge.cy + oy;
      const base = (0.32 + pulse.strength * 0.46) * layer.alpha * (1 - net.recoil * 0.45);
      const color = TONES[pulse.tone === "flash" ? "flash" : pulse.tone];
      const head = pulse.t;
      const span = Math.min(0.36, 130 / Math.max(1, edge.length));
      let prev = quadPoint(ax, ay, cx, cy, bx, by, Math.max(0, head - span));
      for (let i = 1; i <= 4; i += 1) {
        const t = Math.max(0, head - span + (span * i) / 4);
        const point = quadPoint(ax, ay, cx, cy, bx, by, t);
        ctx.beginPath();
        ctx.moveTo(prev.x, prev.y);
        ctx.lineTo(point.x, point.y);
        ctx.strokeStyle = rgba(color, base * Math.pow(i / 4, 1.7));
        ctx.lineWidth = (0.9 + pulse.strength * 1.5) * layer.width;
        ctx.stroke();
        prev = point;
      }
      const headPoint = quadPoint(ax, ay, cx, cy, bx, by, head);
      const size = (18 + pulse.strength * 30) * layer.radius;
      ctx.globalAlpha = Math.min(1, base * 1.5);
      ctx.drawImage(glow[pulse.tone], headPoint.x - size / 2, headPoint.y - size / 2, size, size);
      ctx.globalAlpha = 1;
    };

    const draw = () => {
      ctx.clearRect(0, 0, width, height);
      ctx.save();
      ctx.globalCompositeOperation = "lighter";

      for (const layer of LAYERS) {
        const factor = PARALLAX[layer.plane];
        const ox = parallax.x * AMPLITUDE_X * factor;
        const oy = parallax.y * AMPLITUDE_Y * factor;

        for (const edge of net.edges) {
          if (edge.plane !== layer.plane) continue;
          drawEdge(edge, layer, ox, oy);
        }

        for (const pulse of net.pulses) {
          const edge = net.edges[pulse.edge];
          if (!edge || edge.plane !== layer.plane) continue;
          drawPulse(pulse, edge, layer, ox, oy);
        }

        for (const node of net.nodes) {
          if (node.plane !== layer.plane) continue;
          const wobbleX = Math.sin(net.time * 0.55 + node.phase) * (1.5 + node.z * 3);
          const wobbleY = Math.cos(net.time * 0.45 + node.phase * 1.3) * (1.2 + node.z * 2.4);
          const x = node.x + node.vx + ox + wobbleX;
          const y = node.y + node.vy + oy + wobbleY;
          const energy = Math.min(1, node.energy);
          const lit = node.zone && net.focus[node.zone] > 0.04;
          const tone: NetTone = node.energy > 1.02 || net.success > 0.4 ? "flash" : lit ? "signal" : "signal";
          const radius = node.radius * layer.radius * (1 + energy * 0.85);
          const size = radius * (7 + energy * 13);
          ctx.globalAlpha = (0.055 + energy * 0.4) * layer.alpha * (1 - net.recoil * 0.5);
          ctx.drawImage(glow[tone], x - size / 2, y - size / 2, size, size);
          ctx.globalAlpha = 1;
          ctx.beginPath();
          ctx.arc(x, y, Math.max(0.4, radius), 0, TAU);
          ctx.fillStyle = rgba(TONES[tone], Math.min(1, 0.2 + energy * 0.72) * layer.alpha);
          ctx.fill();
          if (node.role === "hub") {
            ctx.beginPath();
            ctx.arc(x, y, radius + 3.5, 0, TAU);
            ctx.strokeStyle = rgba(TONES[tone], (0.07 + energy * 0.22) * layer.alpha);
            ctx.lineWidth = 0.8;
            ctx.stroke();
          }
        }
      }

      // Onda de envío: cruza la red y la enciende a su paso.
      if (net.wave) {
        const wave = net.wave;
        ctx.beginPath();
        ctx.arc(wave.x, wave.y, wave.r, 0, TAU);
        ctx.strokeStyle = rgba(TONES[wave.tone], wave.alpha * 0.35);
        ctx.lineWidth = 1.4;
        ctx.stroke();
        ctx.beginPath();
        ctx.arc(wave.x, wave.y, wave.r, 0, TAU);
        ctx.strokeStyle = rgba(TONES[wave.tone], wave.alpha * 0.1);
        ctx.lineWidth = 14;
        ctx.stroke();
      }

      // Destello de acceso concedido.
      if (flash && net.success > 0.02) {
        ctx.globalAlpha = net.success * 0.42;
        ctx.fillStyle = flash;
        ctx.fillRect(0, 0, width, height);
        ctx.globalAlpha = 1;
      }

      ctx.restore();
    };

    const publish = (at: number) => {
      if (at - statsAt < 420) return;
      statsAt = at;
      const stats = netStats(net);
      statsRef.current?.(stats);
      emitNeuralEvent({ type: "stats", stats });
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

      stepNeuralNet(net, dt);
      draw();
      publish(now);

      raf = window.requestAnimationFrame(frame);
    };

    const onPointerMove = (event: PointerEvent) => {
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
        width = nextWidth;
        height = nextHeight;
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
      else return;
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

  return <canvas ref={canvasRef} className={cn("block h-full w-full", className)} aria-hidden />;
}
