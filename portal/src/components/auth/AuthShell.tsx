import { motion } from "motion/react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Brand } from "../Brand";
import { NeuralFieldCanvas, type NeuralStats } from "./NeuralFieldCanvas";
import { onNeuralEvent } from "./neuralSignal";
import { useReveal } from "./reveal";

/**
 * Shell de acceso: red cognitiva viva + tarjeta que emerge de ella.
 *
 * - Fondo: simulación neuronal en canvas (tres planos de profundidad, impulsos,
 *   reconfiguración lenta de rutas) más mesh radial, viñeta y grano fijo.
 * - Composición: declaración editorial arriba en móvil; a partir de 1024 px la
 *   declaración queda a la izquierda y la tarjeta a la derecha, conectada a la
 *   red por el dock (tres canales: email, contraseña, envío).
 * - La tarjeta usa doble bisel (cáscara + núcleo) y un parallax de pocos píxeles
 *   que se apaga con `prefers-reduced-motion` o puntero grueso.
 * - El estado (foco / envío / error / éxito) llega por `neuralSignal`, fuera de
 *   React: el dock y el borde de la tarjeta reaccionan sin re-renders.
 */
export function AuthShell({
  eyebrow = "Entrar",
  kicker,
  title,
  subtitle,
  children,
  footer,
  variant = "tenant",
}: {
  /** Título de la tarjeta. */
  eyebrow?: ReactNode;
  /** Etiqueta de la columna editorial. */
  kicker?: string;
  title: ReactNode;
  subtitle?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  variant?: "tenant" | "platform";
}) {
  const reveal = useReveal();
  const platform = variant === "platform";
  const dockRef = useRef<HTMLDivElement>(null);
  const shellRef = useRef<HTMLDivElement>(null);
  const stateRef = useRef<HTMLSpanElement>(null);
  const parallaxRef = useRef<HTMLDivElement>(null);

  // Parallax de la tarjeta: pocos píxeles, lerp por rAF, sin renders.
  useEffect(() => {
    const el = parallaxRef.current;
    if (!el) return;
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    const fine = window.matchMedia?.("(pointer: fine)").matches ?? false;
    if (reduce || !fine) return;
    let raf = 0;
    let cx = 0;
    let cy = 0;
    let tx = 0;
    let ty = 0;
    const tick = () => {
      cx += (tx - cx) * 0.06;
      cy += (ty - cy) * 0.06;
      el.style.transform = `translate3d(${cx.toFixed(2)}px, ${cy.toFixed(2)}px, 0)`;
      raf =
        Math.abs(tx - cx) > 0.05 || Math.abs(ty - cy) > 0.05
          ? window.requestAnimationFrame(tick)
          : 0;
    };
    const onMove = (event: PointerEvent) => {
      tx = (event.clientX / Math.max(1, window.innerWidth) - 0.5) * 12;
      ty = (event.clientY / Math.max(1, window.innerHeight) - 0.5) * 9;
      if (!raf) raf = window.requestAnimationFrame(tick);
    };
    window.addEventListener("pointermove", onMove, { passive: true });
    return () => {
      window.removeEventListener("pointermove", onMove);
      if (raf) window.cancelAnimationFrame(raf);
      el.style.transform = "";
    };
  }, []);

  // Estado visual (dock + borde de la tarjeta) suscrito al bus neuronal.
  useEffect(() => {
    let resetTimer = 0;
    const unsubscribe = onNeuralEvent((event) => {
      const dock = dockRef.current;
      const shell = shellRef.current;
      const state = stateRef.current;
      if (event.type === "focus") {
        if (dock) {
          dock.dataset.route = event.zone ?? "";
          dock.dataset.state = "";
        }
        if (shell && shell.dataset.state !== "success") shell.dataset.state = "";
        if (state && state.dataset.state !== "success") state.dataset.state = "idle";
        window.clearTimeout(resetTimer);
      } else if (event.type === "submit") {
        if (dock) {
          dock.dataset.route = "";
          dock.dataset.state = "submit";
        }
        if (shell) shell.dataset.state = "submit";
        if (state) state.dataset.state = "submit";
        window.clearTimeout(resetTimer);
      } else if (event.type === "error") {
        if (dock) dock.dataset.state = "error";
        if (shell) shell.dataset.state = "error";
        if (state) state.dataset.state = "error";
        window.clearTimeout(resetTimer);
        resetTimer = window.setTimeout(() => {
          if (dock) dock.dataset.state = "";
          if (shell) shell.dataset.state = "";
          if (state) state.dataset.state = "idle";
        }, 2600);
      } else if (event.type === "success") {
        if (dock) dock.dataset.state = "success";
        if (shell) shell.dataset.state = "success";
        if (state) state.dataset.state = "success";
        window.clearTimeout(resetTimer);
      }
    });
    return () => {
      unsubscribe();
      window.clearTimeout(resetTimer);
    };
  }, []);

  return (
    <div className="auth-scene">
      <div className="auth-mesh" aria-hidden />
      <div className="auth-net" aria-hidden>
        <NeuralFieldCanvas />
      </div>
      <div className="auth-vignette" aria-hidden />
      <div className="auth-grain" aria-hidden />

      <div className="relative z-10 flex min-h-[100dvh] flex-col">
        <header className="auth-header">
          <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ type: "spring", bounce: 0, duration: 0.8 }}
            className="auth-pill auth-brand"
          >
            <Brand />
          </motion.div>
          <motion.span
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ type: "spring", bounce: 0, duration: 0.8, delay: 0.08 }}
            className="auth-pill auth-pill--label"
          >
            <span className="auth-dot auth-dot--live" aria-hidden />
            {platform ? "Control Center" : "Red activa"}
          </motion.span>
        </header>

        {/* Riel de señal: el pulso recorre la escena de punta a punta. */}
        <div className="auth-rail" aria-hidden>
          <span className="auth-rail__pulse" />
        </div>

        <main className="auth-stage">
          <section className="auth-intro">
            <motion.p {...reveal(0)} className="auth-eyebrow">
              {kicker ?? (platform ? "Control Center" : "Portal de clientes")}
            </motion.p>
            <motion.h1 {...reveal(1)} className="auth-display">
              {title}
            </motion.h1>
            {subtitle && (
              <motion.p {...reveal(2)} className="auth-lead">
                {subtitle}
              </motion.p>
            )}
            <motion.div {...reveal(3)}>
              <NeuralReadout />
            </motion.div>
          </section>

          <section className="auth-card-col">
            {/* Dock: canales entre la red y la tarjeta. Decorativo. */}
            <div className="auth-dock" ref={dockRef} aria-hidden>
              <span className="auth-dock__spine" />
              <span className="auth-dock__node" data-route="email" />
              <span className="auth-dock__node" data-route="password" />
              <span className="auth-dock__node" data-route="submit" />
            </div>

            <motion.div
              initial={{ opacity: 0, y: 26 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ type: "spring", bounce: 0, duration: 0.95, delay: 0.12 }}
            >
              <div className="auth-card-parallax" ref={parallaxRef}>
                <div className="auth-card-shell" ref={shellRef}>
                  <span className="auth-card-sheen" aria-hidden />
                  <div className="auth-card-core">
                    <div className="auth-card-meta">
                      <h2 className="auth-card-title">{eyebrow}</h2>
                      <span className="auth-card-state" ref={stateRef} aria-hidden>
                        <span className="auth-card-state__dot" />
                        <span className="auth-card-state__label" />
                      </span>
                    </div>
                    <div className="auth-card-body">{children}</div>
                    {footer && <div className="auth-card-footer">{footer}</div>}
                  </div>
                </div>
              </div>
            </motion.div>
          </section>
        </main>
      </div>
    </div>
  );
}

/** Lectura real de la simulación: cuántas señales cruzan por segundo. */
function NeuralReadout() {
  const [stats, setStats] = useState<NeuralStats | null>(null);
  useEffect(
    () =>
      onNeuralEvent((event) => {
        if (event.type === "stats") setStats(event.stats);
      }),
    []
  );
  return (
    <div className="auth-telemetry" aria-hidden>
      <span className="auth-telemetry__dot" />
      <span className="auth-telemetry__rate">{stats ? stats.rate : "—"}</span>
      <span className="auth-telemetry__unit">señales/s</span>
      <span className="auth-telemetry__sep" />
      <span className="auth-telemetry__meta">
        {stats
          ? `${stats.neurons} nodos · ${stats.synapses} enlaces · ${stats.active} en curso`
          : "calibrando la red…"}
      </span>
    </div>
  );
}
