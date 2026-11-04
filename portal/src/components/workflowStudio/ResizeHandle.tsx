import { useRef, type PointerEvent } from "react";

type Props = {
  /** `x`: cambia un ancho (panel a la derecha); `y`: cambia un alto (panel abajo). */
  axis: "x" | "y";
  value: number;
  min: number;
  max: number;
  onChange: (value: number) => void;
  /** Doble clic restablece este valor. */
  resetTo?: number;
  label: string;
  className?: string;
  testId?: string;
};

const STEP = 16;

/**
 * Separador redimensionable (role="separator"): arrastre con puntero y
 * flechas/Inicio/Fin con teclado. El panel crece hacia el lado opuesto al
 * lienzo, por eso el delta se invierte.
 */
export function ResizeHandle({ axis, value, min, max, onChange, resetTo, label, className = "", testId }: Props) {
  const start = useRef<{ pos: number; value: number } | null>(null);
  const clamp = (v: number) => Math.round(Math.min(max, Math.max(min, v)));

  function onPointerDown(ev: PointerEvent<HTMLDivElement>) {
    if (ev.button !== 0) return;
    ev.preventDefault();
    ev.currentTarget.setPointerCapture?.(ev.pointerId);
    start.current = { pos: axis === "x" ? ev.clientX : ev.clientY, value };
  }

  function onPointerMove(ev: PointerEvent<HTMLDivElement>) {
    if (!start.current) return;
    const pos = axis === "x" ? ev.clientX : ev.clientY;
    onChange(clamp(start.current.value - (pos - start.current.pos)));
  }

  return (
    <div
      role="separator"
      aria-orientation={axis === "x" ? "vertical" : "horizontal"}
      aria-label={label}
      aria-valuenow={Math.round(value)}
      aria-valuemin={min}
      aria-valuemax={Math.round(max)}
      tabIndex={0}
      data-testid={testId}
      className={`group/resize absolute z-10 touch-none outline-none ${
        axis === "x" ? "inset-y-0 -left-1 w-2 cursor-col-resize" : "inset-x-0 -top-1 h-2 cursor-row-resize"
      } ${className}`}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={() => {
        start.current = null;
      }}
      onPointerCancel={() => {
        start.current = null;
      }}
      onDoubleClick={() => resetTo != null && onChange(clamp(resetTo))}
      onKeyDown={(ev) => {
        const grow = axis === "x" ? "ArrowLeft" : "ArrowUp";
        const shrink = axis === "x" ? "ArrowRight" : "ArrowDown";
        let next: number | null = null;
        if (ev.key === grow) next = value + STEP;
        else if (ev.key === shrink) next = value - STEP;
        else if (ev.key === "Home") next = min;
        else if (ev.key === "End") next = max;
        if (next == null) return;
        ev.preventDefault();
        onChange(clamp(next));
      }}
    >
      <span
        aria-hidden
        className={`absolute bg-accent opacity-0 transition-opacity group-hover/resize:opacity-60 group-focus-visible/resize:opacity-100 ${
          axis === "x" ? "inset-y-0 left-[3px] w-0.5" : "inset-x-0 top-[3px] h-0.5"
        }`}
      />
    </div>
  );
}
