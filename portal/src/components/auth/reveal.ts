import { useReducedMotion } from "motion/react";

/**
 * Entrada escalonada para las pantallas de acceso.
 *
 * Masa, no coreografía: springs críticamente amortiguados (sin rebote) y un
 * desplazamiento corto. Con `prefers-reduced-motion` sólo cambia la opacidad.
 */
export function useReveal({ step = 0.07, base = 0.05 }: { step?: number; base?: number } = {}) {
  const reduce = useReducedMotion();
  return (index: number) => ({
    initial: reduce ? { opacity: 0 } : { opacity: 0, y: 20 },
    whileInView: { opacity: 1, y: 0 },
    viewport: { once: true, amount: 0.15 },
    transition: {
      type: "spring" as const,
      bounce: 0,
      duration: 0.85,
      delay: reduce ? 0 : base + index * step,
    },
  });
}
