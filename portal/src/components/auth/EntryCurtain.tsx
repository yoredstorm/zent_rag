import { motion } from "motion/react";
import { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import {
  BLOOM_MS,
  DIVE_MS,
  DIVE_REDUCED_MS,
  ENTRY_EXPIRY_MS,
  ENTRY_REVEAL_MS,
  disarmEntry,
  subscribeEntry,
  type EntryTransit,
} from "./entryTransit";

type Phase = "idle" | "bloom" | "reveal";

/**
 * Cortina de relevo entre el acceso y el panel.
 *
 * El canvas desaparece al cambiar de ruta, así que la última luz tiene que
 * vivir en otra parte: esta capa está montada en la raíz de la app y por eso
 * sobrevive a la navegación. Arranca con el mismo gradiente que el bloom del
 * canvas (mismas paradas, mismo color) y se disuelve sobre el panel ya montado,
 * que entra empujado por el mismo movimiento.
 *
 * Decorativa: `aria-hidden`, sin eventos y fuera del árbol accesible.
 */
export function EntryCurtain() {
  const { pathname } = useLocation();
  const [phase, setPhase] = useState<Phase>("idle");
  const [transit, setTransit] = useState<EntryTransit | null>(null);
  const origin = useRef(pathname);

  // El tránsito lo arma la página de acceso en el mismo tick en que la
  // autenticación se resuelve.
  useEffect(
    () =>
      subscribeEntry((state) => {
        if (!state.armed) {
          setPhase("idle");
          setTransit(null);
          return;
        }
        origin.current = window.location.pathname;
        setTransit(state);
        setPhase("bloom");
      }),
    []
  );

  // Cambió la ruta y el canvas ya se apagó: la cortina cubre el relevo.
  useEffect(() => {
    if (phase !== "bloom" || pathname === origin.current) return;
    setPhase("reveal");
  }, [pathname, phase]);

  // Si el armado nunca llega a destino, la cortina se retira sola.
  useEffect(() => {
    if (phase !== "bloom") return;
    const timer = window.setTimeout(() => setPhase("reveal"), ENTRY_EXPIRY_MS);
    return () => window.clearTimeout(timer);
  }, [phase]);

  // Cierre: se retira la luz y el tránsito queda limpio.
  useEffect(() => {
    if (phase !== "reveal") return;
    const timer = window.setTimeout(
      () => {
        setPhase("idle");
        setTransit(null);
        disarmEntry();
      },
      (transit?.reduced ? DIVE_REDUCED_MS : ENTRY_REVEAL_MS) + 80
    );
    return () => window.clearTimeout(timer);
  }, [phase, transit?.reduced]);

  if (phase === "idle" || !transit) return null;
  const reduced = transit.reduced;

  return (
    <motion.div
      className="auth-entry-curtain"
      aria-hidden
      initial={{ opacity: 0 }}
      animate={
        phase === "bloom"
          ? { opacity: reduced ? 0.5 : 1 }
          : { opacity: reduced ? [0.5, 0] : [1, 0], scale: reduced ? 1 : 1.06 }
      }
      transition={
        phase === "bloom"
          ? {
              opacity: {
                delay:
                  (reduced ? DIVE_REDUCED_MS * 0.2 : Math.max(0, DIVE_MS - BLOOM_MS)) / 1000,
                duration: (reduced ? DIVE_REDUCED_MS * 0.45 : BLOOM_MS) / 1000,
                ease: [0.32, 0.72, 0, 1],
              },
            }
          : {
              opacity: {
                duration: (reduced ? DIVE_REDUCED_MS : ENTRY_REVEAL_MS) / 1000,
                // Curva con meseta al principio: la luz aguanta el cambio de
                // ruta y recién después levanta, sin cortar el panel de golpe.
                ease: reduced ? [0.16, 1, 0.3, 1] : [0.65, 0, 0.35, 1],
              },
              scale: {
                duration: (reduced ? 0 : ENTRY_REVEAL_MS) / 1000,
                ease: [0.32, 0.72, 0, 1],
              },
            }
      }
    />
  );
}
