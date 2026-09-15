import { GitBranch, Quotes, ShieldCheck, Stack } from "@phosphor-icons/react";
import { motion, useReducedMotion } from "motion/react";
import type { ReactNode } from "react";
import { Brand } from "../Brand";
import { cn } from "../ui/cn";

/* ------------------------------------------------------------------ */
/* Composición ambiental: campo de conocimiento                        */
/* ------------------------------------------------------------------ */

const NODES: { id: string; x: number; y: number; big?: boolean }[] = [
  { id: "n1", x: 64, y: 84 },
  { id: "n2", x: 196, y: 56 },
  { id: "n3", x: 336, y: 104 },
  { id: "n4", x: 96, y: 236, big: true },
  { id: "n5", x: 232, y: 196, big: true },
  { id: "n6", x: 348, y: 262 },
  { id: "n7", x: 140, y: 356 },
  { id: "n8", x: 272, y: 322 },
  { id: "n9", x: 206, y: 452 },
  { id: "n10", x: 330, y: 470 },
];

const LINKS: [string, string][] = [
  ["n1", "n2"],
  ["n2", "n3"],
  ["n1", "n4"],
  ["n2", "n5"],
  ["n3", "n5"],
  ["n4", "n5"],
  ["n5", "n6"],
  ["n4", "n7"],
  ["n5", "n8"],
  ["n6", "n8"],
  ["n7", "n8"],
  ["n8", "n9"],
  ["n6", "n10"],
  ["n9", "n10"],
  ["n7", "n9"],
];

/** Rutas por las que viaja un pulso: señalan actividad real del sistema. */
const PULSES: { points: string[]; duration: number; delay: number }[] = [
  { points: ["n1", "n4", "n7"], duration: 7.5, delay: 0 },
  { points: ["n3", "n5", "n1"], duration: 9, delay: 1.6 },
  { points: ["n9", "n8", "n3"], duration: 8.2, delay: 3.1 },
];

function nodeById(id: string) {
  return NODES.find((n) => n.id === id) ?? NODES[0];
}

/**
 * Campo abstracto de conocimiento: nodos y relaciones con pulsos de actividad.
 * Movimiento de baja frecuencia y bajo costo. Se apaga con prefers-reduced-motion.
 */
function KnowledgeField({ className }: { className?: string }) {
  const reduce = useReducedMotion();
  return (
    <svg
      viewBox="0 0 420 640"
      className={cn("h-full w-full", className)}
      fill="none"
      aria-hidden
      preserveAspectRatio="xMidYMid slice"
    >
      <defs>
        <radialGradient id="zent-field-glow" cx="50%" cy="45%" r="60%">
          <stop offset="0%" stopColor="var(--color-accent)" stopOpacity="0.16" />
          <stop offset="100%" stopColor="var(--color-accent)" stopOpacity="0" />
        </radialGradient>
      </defs>
      <rect width="420" height="640" fill="url(#zent-field-glow)" />

      {LINKS.map(([a, b], i) => {
        const from = nodeById(a);
        const to = nodeById(b);
        return (
          <motion.line
            key={`${a}-${b}`}
            x1={from.x}
            y1={from.y}
            x2={to.x}
            y2={to.y}
            stroke="var(--color-border-strong)"
            strokeWidth="1"
            initial={reduce ? { opacity: 0.5 } : { opacity: 0, pathLength: 0 }}
            animate={{ opacity: 0.5, pathLength: 1 }}
            transition={{ duration: 0.9, delay: reduce ? 0 : i * 0.06, ease: [0.16, 1, 0.3, 1] }}
          />
        );
      })}

      {NODES.map((node, i) => (
        <motion.circle
          key={node.id}
          cx={node.x}
          cy={node.y}
          r={node.big ? 4.5 : 3}
          fill={node.big ? "var(--color-accent)" : "var(--color-faint)"}
          initial={{ opacity: 0, scale: 0.6 }}
          animate={
            reduce
              ? { opacity: node.big ? 0.95 : 0.55, scale: 1 }
              : { opacity: [0.45, node.big ? 1 : 0.7, 0.45], scale: 1 }
          }
          transition={
            reduce
              ? { duration: 0 }
              : {
                  opacity: {
                    duration: 5.5 + (i % 4) * 0.9,
                    repeat: Infinity,
                    ease: "easeInOut",
                    delay: i * 0.25,
                  },
                  scale: { duration: 0.6, delay: i * 0.08, ease: [0.16, 1, 0.3, 1] },
                }
          }
        />
      ))}

      {!reduce &&
        PULSES.map((pulse, i) => {
          const points = pulse.points.map(nodeById);
          return (
            <motion.circle
              key={`pulse-${i}`}
              r="2.6"
              fill="var(--color-accent)"
              initial={{ cx: points[0].x, cy: points[0].y, opacity: 0 }}
              animate={{
                cx: points.map((p) => p.x),
                cy: points.map((p) => p.y),
                opacity: [0, 0.95, 0.95, 0],
              }}
              transition={{
                duration: pulse.duration,
                delay: pulse.delay,
                repeat: Infinity,
                repeatDelay: 1.5,
                ease: "easeInOut",
                times: [0, 0.15, 0.85, 1],
              }}
            />
          );
        })}
    </svg>
  );
}

/* ------------------------------------------------------------------ */
/* Shell de autenticación                                              */
/* ------------------------------------------------------------------ */

const CAPABILITIES = [
  {
    icon: Quotes,
    title: "Respuestas con evidencia",
    body: "Cada respuesta cita los documentos y fuentes que la sostienen.",
  },
  {
    icon: GitBranch,
    title: "Agentes versionados",
    body: "Configurá, probá y publicá versiones por entorno sin romper producción.",
  },
  {
    icon: ShieldCheck,
    title: "Gobierno desde el día uno",
    body: "Roles, auditoría de acciones sensibles y verificación step-up.",
  },
  {
    icon: Stack,
    title: "Multi-workspace",
    body: "Separá demo, staging y negocio dentro de la misma organización.",
  },
];

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
  return (
    <div className="relative grid min-h-[100dvh] grid-cols-1 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] xl:grid-cols-[minmax(0,600px)_minmax(0,1fr)]">
      {/* Composición ambiental en móvil: fondo tenue detrás del formulario */}
      <div className="pointer-events-none absolute inset-0 opacity-[0.14] lg:hidden">
        <KnowledgeField />
      </div>

      <main className="relative flex flex-col justify-center px-5 py-10 sm:px-8 lg:px-14">
        <div className="mx-auto w-full max-w-[400px]">
          <div className="mb-9">
            <Brand />
          </div>
          <p className="eyebrow mb-2">{eyebrow}</p>
          <h1 className="text-display">{title}</h1>
          {subtitle && (
            <p className="prose-measure mt-2.5 text-sm leading-relaxed text-muted">{subtitle}</p>
          )}
          <div className="mt-8">{children}</div>
          {footer && <div className="mt-6">{footer}</div>}
        </div>
      </main>

      <aside
        className="relative hidden overflow-hidden border-l border-border bg-surface lg:block"
        aria-hidden
      >
        <div className="absolute inset-0">
          <KnowledgeField />
        </div>
        <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-surface via-surface/90 to-transparent p-10 pt-32">
          <p className="eyebrow mb-4">
            {variant === "platform" ? "Control Center" : "Qué estás operando"}
          </p>
          <ul className="flex flex-col gap-4">
            {CAPABILITIES.map((cap) => (
              <li key={cap.title} className="flex items-start gap-3">
                <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-sm border border-border bg-raised text-accent">
                  <cap.icon size={14} aria-hidden />
                </span>
                <span className="min-w-0">
                  <span className="block text-[13px] font-medium text-text">{cap.title}</span>
                  <span className="mt-0.5 block max-w-[42ch] text-[12.5px] leading-relaxed text-muted">
                    {cap.body}
                  </span>
                </span>
              </li>
            ))}
          </ul>
        </div>
      </aside>
    </div>
  );
}
