import { useEffect, useRef } from "react";
import { cn } from "../ui/cn";
import {
  activePulses,
  brainContours,
  brainSulci,
  burst,
  createNeuralField,
  excite,
  stepNeuralField,
  type NeuralField,
} from "../../lib/neuralField";

export type NeuralStats = {
  /** Neuronas de la corteza simulada. */
  neurons: number;
  /** Sinapsis que las conectan. */
  synapses: number;
  /** Llegadas de señal por segundo (medido, ventana de 1 s). */
  rate: number;
  /** Sinapsis conduciendo en este instante. */
  active: number;
};

const SIGNAL = [52, 211, 166] as const;
const DEEP = [86, 148, 255] as const;

function rgba(color: readonly [number, number, number], alpha: number): string {
  return `rgba(${color[0]}, ${color[1]}, ${color[2]}, ${Math.max(0, Math.min(1, alpha))})`;
}

/** Sprite de resplandor pre-renderizado: glow barato sin shadowBlur por frame. */
function createGlowSprite(): HTMLCanvasElement {
  const size = 128;
  const sprite = document.createElement("canvas");
  sprite.width = size;
  sprite.height = size;
  const ctx = sprite.getContext("2d");
  if (ctx) {
    const gradient = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
    gradient.addColorStop(0, rgba(SIGNAL, 0.95));
    gradient.addColorStop(0.25, rgba(SIGNAL, 0.32));
    gradient.addColorStop(0.55, rgba(SIGNAL, 0.08));
    gradient.addColorStop(1, rgba(SIGNAL, 0));
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, size, size);
  }
  return sprite;
}

function quadraticAt(
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
 * Cerebro neuronal sobre canvas.
 *
 * La actividad es una simulación real (ver `lib/neuralField.ts`): los pulsos
 * viajan por las sinapsis, excitan la neurona de destino y se propagan. El
 * puntero excita la zona que toca, así que la red responde a la persona.
 *
 * - Sólo anima `transform`/dibujo por frame con `globalCompositeOperation`
 *   aditivo: sin filtros ni layout.
 * - Se detiene cuando la pestaña no está visible y se congela en un único frame
 *   con `prefers-reduced-motion`.
 * - Decorativo: `aria-hidden`, fuera del árbol accesible.
 */
export function NeuralBrain({
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

    let field: NeuralField = createNeuralField({
      seed: 20260926,
      count: window.innerWidth < 768 ? 96 : 168,
    });
    const contours = brainContours();
    const sulci = brainSulci();
    const glow = createGlowSprite();
    // Arranque con actividad: el cerebro no aparece apagado los primeros segundos.
    for (let i = 0; i < 150; i += 1) stepNeuralField(field, 1 / 60);
    let width = 0;
    let height = 0;
    let raf = 0;
    let last = 0;
    let lastStats = 0;
    let pointerX = 0.5;
    let pointerY = 0.5;
    let pointerActive = false;
    let driftX = 0;
    let driftY = 0;
    let lastExcite = 0;
    let tilt = 0;
    let nextBurstAt = 5000;

    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      width = Math.max(1, rect.width);
      height = Math.max(1, rect.height);
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      if (rect.width < 640 && field.neurons.length > 120) {
        field = createNeuralField({ seed: 20260926, count: 96 });
        for (let i = 0; i < 150; i += 1) stepNeuralField(field, 1 / 60);
      }
    };

    const draw = (now: number) => {
      ctx.clearRect(0, 0, width, height);
      const small = width < 768;
      // El cerebro se corre hacia el centro-derecha: queda entre la declaración
      // y la tarjeta, con el lóbulo occipital, el cerebelo y el tronco a la vista.
      const originX = width * (small ? 0.5 : 0.57) + driftX;
      const originY = height * (small ? 0.6 : 0.5) + driftY;
      const scale = small
        ? Math.min(width * 1.05, height * 0.52)
        : Math.min(height * 0.94, width * 0.44);
      // Deriva lenta: el cerebro respira en lugar de quedarse clavado.
      tilt = Math.sin(now / 9000) * 0.02;
      const cos = Math.cos(tilt);
      const sin = Math.sin(tilt);
      const toScreen = (x: number, y: number, depth: number) => {
        const px = (x - 0.47) * scale;
        const py = (y - 0.52) * scale;
        return {
          x: originX + px * cos - py * sin + driftX * (1 - depth) * 0.5,
          y: originY + px * sin + py * cos + driftY * (1 - depth) * 0.5,
        };
      };

      ctx.save();
      ctx.globalCompositeOperation = "lighter";

      // 0. Contorno: la silueta del cerebro, tenue pero legible.
      for (const loop of contours) {
        ctx.beginPath();
        loop.forEach((point, index) => {
          const screen = toScreen(point.x, point.y, 0.5);
          if (index === 0) ctx.moveTo(screen.x, screen.y);
          else ctx.lineTo(screen.x, screen.y);
        });
        ctx.strokeStyle = rgba(SIGNAL, 0.6);
        ctx.lineWidth = 1.3;
        ctx.stroke();
        ctx.strokeStyle = rgba(SIGNAL, 0.07);
        ctx.lineWidth = 11;
        ctx.stroke();
      }

      // 0b. Surcos: la fisura lateral y la cisura central, apenas insinuadas.
      for (const segment of sulci) {
        ctx.beginPath();
        segment.forEach((point, index) => {
          const screen = toScreen(point.x, point.y, 0.5);
          if (index === 0) ctx.moveTo(screen.x, screen.y);
          else ctx.lineTo(screen.x, screen.y);
        });
        ctx.strokeStyle = rgba(SIGNAL, 0.17);
        ctx.lineWidth = 1;
        ctx.stroke();
      }

      // 1. Látice de sinapsis: casi invisible hasta que algo la recorre.
      for (const synapse of field.synapses) {
        const from = field.neurons[synapse.a];
        const to = field.neurons[synapse.b];
        const depth = (from.depth + to.depth) / 2;
        const a = toScreen(from.x, from.y, depth);
        const c = toScreen(synapse.cx, synapse.cy, depth);
        const b = toScreen(to.x, to.y, depth);
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.quadraticCurveTo(c.x, c.y, b.x, b.y);
        ctx.strokeStyle = rgba(
          depth > 0.62 ? DEEP : SIGNAL,
          0.07 + (1 - depth) * 0.1 + synapse.weight * 0.05
        );
        ctx.lineWidth = 0.7 + synapse.weight * 0.6;
        ctx.stroke();
      }

      // 2. Pulsos: estela corta sobre el bezier + cabeza luminosa.
      for (const pulse of field.pulses) {
        const synapse = field.synapses[pulse.synapse];
        const from = field.neurons[synapse.a];
        const to = field.neurons[synapse.b];
        const depth = (from.depth + to.depth) / 2;
        const a = toScreen(from.x, from.y, depth);
        const c = toScreen(synapse.cx, synapse.cy, depth);
        const b = toScreen(to.x, to.y, depth);
        const head = pulse.dir === 1 ? pulse.t : 1 - pulse.t;
        const tailT = pulse.dir === 1 ? Math.max(0, head - 0.22) : Math.min(1, head + 0.22);
        const p0 = quadraticAt(a.x, a.y, c.x, c.y, b.x, b.y, tailT);
        const p1 = quadraticAt(a.x, a.y, c.x, c.y, b.x, b.y, head);
        const midT = (head + tailT) / 2;
        const mid = quadraticAt(a.x, a.y, c.x, c.y, b.x, b.y, midT);
        const alpha = (0.5 + pulse.strength * 0.5) * (1 - depth * 0.45);
        const gradient = ctx.createLinearGradient(p0.x, p0.y, p1.x, p1.y);
        gradient.addColorStop(0, rgba(SIGNAL, 0));
        gradient.addColorStop(1, rgba(SIGNAL, alpha));
        ctx.beginPath();
        ctx.moveTo(p0.x, p0.y);
        ctx.quadraticCurveTo(mid.x, mid.y, p1.x, p1.y);
        ctx.strokeStyle = gradient;
        ctx.lineWidth = 1.1 + pulse.strength * 1.4;
        ctx.stroke();

        const glowSize = 30 + pulse.strength * 46;
        ctx.globalAlpha = 0.5 + pulse.strength * 0.4;
        ctx.drawImage(
          glow,
          p1.x - glowSize / 2,
          p1.y - glowSize / 2,
          glowSize,
          glowSize
        );
        ctx.globalAlpha = 1;
      }

      // 3. Neuronas: núcleo nítido + resplandor según energía.
      for (const neuron of field.neurons) {
        const point = toScreen(neuron.x, neuron.y, neuron.depth);
        const energy = Math.min(1, neuron.energy);
        const base = neuron.radius * (width < 768 ? 0.9 : 1.25);
        const glowSize = base * (7 + energy * 16);
        const tone = neuron.role === "deep" ? DEEP : SIGNAL;
        ctx.globalAlpha = 0.1 + energy * 0.5;
        ctx.drawImage(glow, point.x - glowSize / 2, point.y - glowSize / 2, glowSize, glowSize);
        ctx.globalAlpha = 1;
        ctx.beginPath();
        ctx.arc(point.x, point.y, base * (1 + energy * 0.7), 0, Math.PI * 2);
        ctx.fillStyle =
          neuron.role === "hub"
            ? rgba([230, 255, 250], 0.55 + energy * 0.4)
            : rgba(tone, 0.3 + energy * 0.7);
        ctx.fill();
      }

      ctx.restore();
    };

    const frame = (now: number) => {
      if (!last) last = now;
      const dt = (now - last) / 1000;
      last = now;

      // Parallax suave hacia el puntero (lerp: sin saltos, interrumpible).
      const targetX = pointerActive ? (pointerX - 0.5) * 30 : 0;
      const targetY = pointerActive ? (pointerY - 0.5) * 20 : 0;
      driftX += (targetX - driftX) * 0.045;
      driftY += (targetY - driftY) * 0.045;

      if (pointerActive && now - lastExcite > 45) {
        lastExcite = now;
        excite(field, pointerX, pointerY, 0.07);
      }

      // Descarga cada tanto: la escena tiene un evento, no sólo ruido de fondo.
      if (now > nextBurstAt) {
        nextBurstAt = now + 7000 + Math.random() * 6000;
        burst(field);
      }

      stepNeuralField(field, dt);
      draw(now);

      if (now - lastStats > 400) {
        lastStats = now;
        statsRef.current?.({
          neurons: field.neurons.length,
          synapses: field.synapses.length,
          rate: Math.round(field.rate),
          active: activePulses(field),
        });
      }
      raf = window.requestAnimationFrame(frame);
    };

    const onPointerMove = (event: PointerEvent) => {
      pointerX = event.clientX / Math.max(1, window.innerWidth);
      pointerY = event.clientY / Math.max(1, window.innerHeight);
      pointerActive = true;
    };
    const onPointerLeave = () => {
      pointerActive = false;
    };
    const onVisibility = () => {
      if (document.hidden) {
        window.cancelAnimationFrame(raf);
        raf = 0;
      } else if (!reduce && !raf) {
        last = 0;
        raf = window.requestAnimationFrame(frame);
      }
    };

    resize();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(resize);
    observer?.observe(canvas);

    if (reduce) {
      // Un único frame, ya con actividad: el cerebro queda iluminado y quieto.
      draw(0);
      statsRef.current?.({
        neurons: field.neurons.length,
        synapses: field.synapses.length,
        rate: Math.round(field.rate),
        active: activePulses(field),
      });
    } else {
      raf = window.requestAnimationFrame(frame);
      window.addEventListener("pointermove", onPointerMove, { passive: true });
      if (finePointer) window.addEventListener("pointerleave", onPointerLeave);
    }
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      if (raf) window.cancelAnimationFrame(raf);
      observer?.disconnect();
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerleave", onPointerLeave);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, []);

  return <canvas ref={canvasRef} className={cn("block h-full w-full", className)} aria-hidden />;
}
