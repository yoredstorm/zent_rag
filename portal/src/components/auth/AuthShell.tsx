import { GitBranch, Quotes, ShieldCheck, Stack, type Icon } from "@phosphor-icons/react";
import { motion } from "motion/react";
import { useState, type ReactNode } from "react";
import { Brand } from "../Brand";
import { NeuralBrain, type NeuralStats } from "./NeuralBrain";
import { useReveal } from "./reveal";

const CAPABILITIES: { icon: Icon; title: string; body: string }[] = [
  {
    icon: Quotes,
    title: "Respuestas con evidencia",
    body: "Cada respuesta cita los documentos que la sostienen.",
  },
  {
    icon: GitBranch,
    title: "Agentes versionados",
    body: "Configurá, probá y publicá por entorno sin romper producción.",
  },
  {
    icon: ShieldCheck,
    title: "Gobierno desde el día uno",
    body: "Roles, auditoría de acciones sensibles y verificación step-up.",
  },
  {
    icon: Stack,
    title: "Multi-workspace",
    body: "Demo, staging y negocio dentro de la misma organización.",
  },
];

/**
 * Shell de acceso: escena de cerebro neuronal + tarjeta de vidrio.
 *
 * - Fondo vivo: campo neuronal simulado (canvas) con mesh radial, viñeta y
 *   grano fijo. Es decorativo y no intercepta el puntero.
 * - Composición asimétrica: declaración grande a la izquierda, tarjeta flotante
 *   a la derecha construida con doble bisel (cáscara + núcleo) para que se lea
 *   como una pieza apoyada, no como un formulario pegado al fondo.
 * - `prefers-reduced-motion` congela el fondo en un frame y desactiva el
 *   parallax; el resto de la escena queda igual.
 */
export function AuthShell({
  eyebrow = "Intelligence workspace",
  title,
  subtitle,
  children,
  footer,
  variant = "tenant",
}: {
  eyebrow?: string;
  title: string;
  subtitle?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  variant?: "tenant" | "platform";
}) {
  const [stats, setStats] = useState<NeuralStats | null>(null);
  const reveal = useReveal();
  const platform = variant === "platform";

  return (
    <div className="auth-scene relative min-h-[100dvh] overflow-hidden">
      <div className="auth-mesh" aria-hidden />
      <div className="auth-brain" aria-hidden>
        <NeuralBrain onStats={setStats} />
      </div>
      <div className="auth-vignette" aria-hidden />
      <div className="auth-grain" aria-hidden />

      <header className="relative z-10 mx-auto flex w-full max-w-[1240px] items-center justify-between gap-4 px-5 pt-6 sm:px-8">
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
          className="auth-pill auth-pill--label hidden sm:inline-flex"
        >
          <span className="auth-dot" aria-hidden />
          {platform ? "Control Center" : "Red neuronal activa"}
        </motion.span>
      </header>

      <div className="relative z-10 mx-auto grid w-full max-w-[1240px] grid-cols-1 items-center gap-10 px-5 py-8 sm:px-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,440px)] lg:gap-16 lg:py-14">
        <section className="order-2 max-w-[56ch] lg:order-1">
          <motion.p {...reveal(0)} className="auth-eyebrow">
            {platform ? "Plataforma" : "Intelligence workspace"}
          </motion.p>
          <motion.h1 {...reveal(1)} className="auth-display">
            {title}
          </motion.h1>
          {subtitle && (
            <motion.p {...reveal(2)} className="auth-lead">
              {subtitle}
            </motion.p>
          )}

          <motion.ul {...reveal(3)} className="auth-facts">
            {CAPABILITIES.map((cap) => (
              <li key={cap.title}>
                <span className="auth-facts__icon" aria-hidden>
                  <cap.icon size={15} weight="light" />
                </span>
                <span className="min-w-0">
                  <span className="auth-facts__title">{cap.title}</span>
                  <span className="auth-facts__body">{cap.body}</span>
                </span>
              </li>
            ))}
          </motion.ul>

          {/* Lectura real de la simulación: cuántas señales cruzan por segundo. */}
          <motion.div {...reveal(4)} className="auth-readout" aria-hidden>
            <span className="auth-dot auth-dot--live" />
            <span className="auth-readout__value">{stats ? stats.rate : "—"}</span>
            <span className="auth-readout__unit">señales/s</span>
            <span className="auth-readout__meta">
              {stats
                ? `${stats.neurons} neuronas · ${stats.synapses} sinapsis · ${stats.active} conduciendo`
                : "midiendo actividad…"}
            </span>
          </motion.div>
        </section>

        <section className="order-1 lg:order-2 lg:justify-self-end">
          <motion.div
            initial={{ opacity: 0, y: 28 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ type: "spring", bounce: 0, duration: 0.95 }}
            className="auth-card-shell"
          >
            {/* Capa fantasma: da profundidad física bajo la tarjeta. */}
            <span className="auth-card-ghost" aria-hidden />
            <div className="auth-card-core">
              <h2 className="auth-card-eyebrow">{eyebrow}</h2>
              <div className="mt-6">{children}</div>
              {footer && <div className="auth-card-footer mt-6 pt-5">{footer}</div>}
            </div>
          </motion.div>
        </section>
      </div>
    </div>
  );
}
