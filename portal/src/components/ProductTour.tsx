import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { Session } from "../api";
import {
  PRODUCT_TOUR_START_EVENT,
  filterTourSteps,
  markCompleted,
  markSkipped,
  shouldAutoStart,
  visibleTourSteps,
  visibleTourTarget,
  type TourStep,
} from "../lib/productTour";

const PAD = 6;
const GAP = 12;
const EDGE = 12;
const DESKTOP_W = 340;
const EST_H = 280;
/** Coincide con el breakpoint `lg` de Tailwind: debajo, el menú vive en el drawer. */
const DRAWER_MAX_W = 1024;

type ProductTourProps = {
  steps: TourStep[];
  open: boolean;
  onSkip: () => void;
  onComplete: () => void;
  remeasureKey?: string | number | boolean;
};

type TooltipBox = {
  top?: number;
  bottom?: number | string;
  left: number;
  width: number;
  maxHeight: number;
};

/**
 * Posición de la tarjeta. En móvil el menú vive en el drawer (izquierda) y la
 * tarjeta se ancla abajo: el item señalado queda visible por encima de ella.
 */
function tooltipBox(rect: DOMRect | null, contentH: number): TooltipBox {
  const vw = Math.max(280, window.innerWidth);
  const vh = Math.max(280, window.innerHeight);
  const maxHeight = Math.max(180, vh - EDGE * 2);

  if (vw < DRAWER_MAX_W) {
    const width = Math.min(420, vw - EDGE * 2);
    return {
      bottom: `calc(${EDGE}px + env(safe-area-inset-bottom, 0px))`,
      left: Math.round((vw - width) / 2),
      width,
      maxHeight,
    };
  }

  const width = Math.min(DESKTOP_W, vw - EDGE * 2);
  const height = Math.min(contentH || EST_H, maxHeight);
  let left = rect ? rect.right + GAP : (vw - width) / 2;
  if (rect && left + width > vw - EDGE) left = rect.left - width - GAP;
  left = Math.round(Math.min(Math.max(left, EDGE), Math.max(EDGE, vw - width - EDGE)));
  const anchor = rect ? rect.top : vh / 2 - EST_H / 2;
  const top = Math.round(
    Math.min(Math.max(anchor, EDGE), Math.max(EDGE, vh - height - EDGE))
  );
  return { top, left, width, maxHeight };
}

export function ProductTour({ steps, open, onSkip, onComplete, remeasureKey }: ProductTourProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const nextRef = useRef<HTMLButtonElement>(null);
  const [index, setIndex] = useState(0);
  const [contentH, setContentH] = useState(0);
  const [tick, setTick] = useState(0);
  const activeSteps = visibleTourSteps(steps);
  const safeIndex = Math.min(index, Math.max(0, activeSteps.length - 1));
  const step = activeSteps[safeIndex];
  const isLast = safeIndex >= activeSteps.length - 1;
  const target = step ? visibleTourTarget(step.target) : null;
  const rect = target?.getBoundingClientRect() ?? null;
  const box = tooltipBox(rect, contentH);

  useEffect(() => {
    if (open) setIndex(0);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    setTick((n) => n + 1);
  }, [open, remeasureKey]);

  // Alto real de la tarjeta: sin eso el clamp contra el borde inferior la deja
  // recortada en pantallas bajas (o en horizontal).
  useLayoutEffect(() => {
    if (!open || !step) return;
    const node = dialogRef.current;
    if (!node) return;
    const read = () => setContentH(node.offsetHeight);
    read();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(read);
    observer.observe(node);
    return () => observer.disconnect();
  }, [open, step, tick, remeasureKey]);

  useEffect(() => {
    if (!open) return;
    function bump() {
      setTick((n) => n + 1);
    }
    window.addEventListener("resize", bump);
    window.addEventListener("scroll", bump, true);
    return () => {
      window.removeEventListener("resize", bump);
      window.removeEventListener("scroll", bump, true);
    };
  }, [open]);

  useEffect(() => {
    if (!open || !step) return;
    const el = visibleTourTarget(step.target);
    if (el?.getAttribute("aria-expanded") === "false") {
      el.click();
    }
    // En móvil la tarjeta se ancla abajo: centrar el objetivo lo deja a la vista.
    el?.scrollIntoView({
      block: window.innerWidth < DRAWER_MAX_W ? "center" : "nearest",
      inline: "nearest",
    });
  }, [open, step]);

  useEffect(() => {
    if (!open) return;
    nextRef.current?.focus();
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onSkip();
        return;
      }
      // La paleta (Ctrl/Cmd+K) vive debajo del tutorial: no la abras encima.
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        event.stopImmediatePropagation();
      }
    }
    // En captura: la paleta escucha en el documento y este atajo debe ganarle.
    document.addEventListener("keydown", onKey, true);
    return () => document.removeEventListener("keydown", onKey, true);
  }, [open, onSkip, safeIndex]);

  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement as HTMLElement | null;
    function onKey(event: KeyboardEvent) {
      if (event.key !== "Tab") return;
      const focusables = dialogRef.current?.querySelectorAll<HTMLElement>(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
      );
      if (!focusables || focusables.length === 0) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      prev?.focus?.();
    };
  }, [open]);

  if (!open || !step) return null;

  const hole = rect
    ? {
        top: rect.top - PAD,
        left: rect.left - PAD,
        width: rect.width + PAD * 2,
        height: rect.height + PAD * 2,
      }
    : null;

  return (
    <div
      className="pointer-events-auto fixed inset-0 z-[var(--z-tour)] overflow-hidden"
      data-testid="product-tour"
    >
      {hole ? (
        <div
          aria-hidden
          className="pointer-events-none absolute rounded-md ring-2 ring-accent"
          style={{
            top: hole.top,
            left: hole.left,
            width: hole.width,
            height: hole.height,
            boxShadow: "0 0 0 9999px rgb(0 0 0 / 0.55)",
          }}
        />
      ) : (
        <div className="absolute inset-0 bg-scrim" aria-hidden />
      )}
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="product-tour-title"
        aria-describedby="product-tour-body"
        className="absolute overflow-y-auto rounded-lg border border-border bg-overlay p-4 shadow-pop"
        style={{
          top: box.top,
          bottom: box.bottom,
          left: box.left,
          width: box.width,
          maxHeight: box.maxHeight,
        }}
      >
        <p className="mb-1 text-[11px] font-medium tracking-wide text-faint uppercase">
          Tutorial {safeIndex + 1} / {activeSteps.length}
        </p>
        <h2 id="product-tour-title" className="text-base font-semibold text-text">
          {step.title}
        </h2>
        <p id="product-tour-body" className="mt-2 text-sm leading-relaxed text-muted">
          {step.body}
        </p>
        <div className="mt-4 flex flex-wrap items-center justify-between gap-2">
          <button type="button" className="btn btn-ghost min-h-9 px-2 text-xs" onClick={onSkip}>
            Saltar
          </button>
          <div className="flex gap-2">
            <button
              type="button"
              className="btn btn-secondary min-h-9 px-3 text-xs"
              disabled={safeIndex === 0}
              onClick={() => setIndex((i) => Math.max(0, i - 1))}
            >
              Atrás
            </button>
            {isLast ? (
              <button
                ref={nextRef}
                type="button"
                className="btn btn-primary min-h-9 px-3 text-xs"
                onClick={onComplete}
              >
                Listo
              </button>
            ) : (
              <button
                ref={nextRef}
                type="button"
                className="btn btn-primary min-h-9 px-3 text-xs"
                onClick={() => setIndex((i) => i + 1)}
              >
                Siguiente
              </button>
            )}
          </div>
        </div>
        <span className="sr-only">{safeIndex + 1} / {activeSteps.length}</span>
      </div>
    </div>
  );
}

type ProductTourRootProps = {
  session: Session | null;
  entitlements?: Record<string, boolean | number | null>;
  blocked?: boolean;
  layoutKey?: string | number | boolean;
  onTourActive?: (active: boolean) => void;
};

export function ProductTourRoot({
  session,
  entitlements = {},
  blocked = false,
  layoutKey,
  onTourActive,
}: ProductTourRootProps) {
  const [open, setOpen] = useState(false);
  const steps = useMemo(
    () => filterTourSteps(session, entitlements),
    [session, entitlements]
  );

  useEffect(() => {
    if (!session || blocked) return;
    if (shouldAutoStart()) setOpen(true);
  }, [session, blocked]);

  useEffect(() => {
    function onStart() {
      if (blocked) return;
      setOpen(true);
    }
    window.addEventListener(PRODUCT_TOUR_START_EVENT, onStart);
    return () => window.removeEventListener(PRODUCT_TOUR_START_EVENT, onStart);
  }, [blocked]);

  useEffect(() => {
    onTourActive?.(open);
  }, [open, onTourActive]);

  return (
    <ProductTour
      steps={steps}
      open={open}
      remeasureKey={layoutKey}
      onSkip={() => {
        markSkipped();
        setOpen(false);
      }}
      onComplete={() => {
        markCompleted();
        setOpen(false);
      }}
    />
  );
}
