import { memo, useRef, type PointerEvent } from "react";
import { NODE_H, NODE_W, type Rect } from "../../lib/canvasViewport";
import type { Positions } from "./geometry";

const W = 200;
const H = 132;
const PAD = 120;

type Props = {
  positions: Positions;
  selected: ReadonlySet<string>;
  failed: ReadonlySet<string>;
  visible: Rect;
  /** Centra la vista en el punto de mundo pulsado/arrastrado. */
  onNavigate: (wx: number, wy: number) => void;
};

/** Minimapa: vista general del grafo y del área visible; clic o arrastre para moverse. */
function CanvasMinimapView({ positions, selected, failed, visible, onNavigate }: Props) {
  const dragging = useRef(false);
  const points = [...positions.entries()];
  let minX = visible.x;
  let minY = visible.y;
  let maxX = visible.x + visible.w;
  let maxY = visible.y + visible.h;
  for (const [, p] of points) {
    minX = Math.min(minX, p.x);
    minY = Math.min(minY, p.y);
    maxX = Math.max(maxX, p.x + NODE_W);
    maxY = Math.max(maxY, p.y + NODE_H);
  }
  minX -= PAD;
  minY -= PAD;
  maxX += PAD;
  maxY += PAD;
  const scale = Math.min(W / (maxX - minX), H / (maxY - minY));
  const offX = (W - (maxX - minX) * scale) / 2;
  const offY = (H - (maxY - minY) * scale) / 2;
  const toMini = (x: number, y: number) => ({ x: offX + (x - minX) * scale, y: offY + (y - minY) * scale });

  function navigate(ev: PointerEvent<SVGSVGElement>) {
    const rect = ev.currentTarget.getBoundingClientRect();
    const mx = ((ev.clientX - rect.left) / rect.width) * W;
    const my = ((ev.clientY - rect.top) / rect.height) * H;
    onNavigate(minX + (mx - offX) / scale, minY + (my - offY) / scale);
  }

  const view = toMini(visible.x, visible.y);
  return (
    <svg
      width={W}
      height={H}
      viewBox={`0 0 ${W} ${H}`}
      className="block cursor-pointer touch-none"
      data-testid="wf-minimap"
      role="img"
      aria-label="Minimapa del flujo: clic para desplazarte"
      onPointerDown={(ev) => {
        ev.stopPropagation();
        ev.currentTarget.setPointerCapture?.(ev.pointerId);
        dragging.current = true;
        navigate(ev);
      }}
      onPointerMove={(ev) => {
        if (dragging.current) navigate(ev);
      }}
      onPointerUp={() => {
        dragging.current = false;
      }}
    >
      {points.map(([id, p]) => {
        const m = toMini(p.x, p.y);
        return (
          <rect
            key={id}
            x={m.x}
            y={m.y}
            width={Math.max(2, NODE_W * scale)}
            height={Math.max(2, NODE_H * scale)}
            rx={1.5}
            fill={
              failed.has(id)
                ? "var(--color-danger)"
                : selected.has(id)
                  ? "var(--color-accent)"
                  : "color-mix(in srgb, var(--color-muted) 45%, transparent)"
            }
          />
        );
      })}
      <rect
        x={view.x}
        y={view.y}
        width={visible.w * scale}
        height={visible.h * scale}
        fill="color-mix(in srgb, var(--color-accent) 10%, transparent)"
        stroke="var(--color-accent)"
        strokeWidth={1.5}
        rx={2}
        data-testid="wf-minimap-viewport"
      />
    </svg>
  );
}

export const CanvasMinimap = memo(CanvasMinimapView);
