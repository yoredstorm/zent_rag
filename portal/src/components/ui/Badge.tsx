import {
  CheckCircle,
  CircleNotch,
  Clock,
  Info,
  Question,
  WarningCircle,
  XCircle,
  type Icon,
} from "@phosphor-icons/react";import type { ReactNode } from "react";
import { cn } from "./cn";

export type Tone = "neutral" | "accent" | "ok" | "warn" | "danger" | "info";

const TONE_CLASS: Record<Tone, string> = {
  neutral: "badge-muted",
  accent: "badge-accent",
  ok: "badge-ok",
  warn: "badge-pending",
  danger: "badge-danger",
  info: "badge-info",
};

export type BadgeProps = {
  tone?: Tone;
  icon?: Icon;
  /** Punto de estado a la izquierda del texto. */
  dot?: boolean;
  className?: string;
  children: ReactNode;
  title?: string;
};

/** Etiqueta compacta. Color + texto (+ icono opcional) — nunca color solo. */
export function Badge({ tone = "neutral", icon: IconEl, dot, className, children, title }: BadgeProps) {
  return (
    <span className={cn("badge", TONE_CLASS[tone], className)} title={title}>
      {dot && <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-current" aria-hidden />}
      {IconEl && <IconEl size={12} weight="fill" aria-hidden />}
      {children}
    </span>
  );
}

/** Un punto de estado nunca comunica solo: siempre acompañado de texto. */
export function StatusDot({ tone = "neutral", className }: { tone?: Tone; className?: string }) {
  const color =
    tone === "ok"
      ? "bg-ok"
      : tone === "warn"
        ? "bg-warn"
        : tone === "danger"
          ? "bg-danger"
          : tone === "info"
            ? "bg-info"
            : tone === "accent"
              ? "bg-accent"
              : "bg-faint";
  return <span className={cn("status-dot", color, className)} aria-hidden />;
}

type StatusMeta = { tone: Tone; label: string; Icon: Icon; spin?: boolean };

/**
 * Vocabulario único de estados del backend.
 * Traduce estados crudos a tono + icono + etiqueta legible.
 */
const STATUS_META: Record<string, StatusMeta> = {
  // OK
  healthy: { tone: "ok", label: "Saludable", Icon: CheckCircle },
  production: { tone: "ok", label: "Producción", Icon: CheckCircle },
  active: { tone: "ok", label: "Activo", Icon: CheckCircle },
  ready: { tone: "ok", label: "Listo", Icon: CheckCircle },
  completed: { tone: "ok", label: "Completado", Icon: CheckCircle },
  success: { tone: "ok", label: "Correcto", Icon: CheckCircle },
  indexed: { tone: "ok", label: "Indexado", Icon: CheckCircle },
  succeeded: { tone: "ok", label: "Ejecutado", Icon: CheckCircle },
  resolved: { tone: "ok", label: "Resuelto", Icon: CheckCircle },
  published: { tone: "ok", label: "Publicado", Icon: CheckCircle },
  approved: { tone: "ok", label: "Aprobado", Icon: CheckCircle },
  // En curso
  running: { tone: "accent", label: "En ejecución", Icon: CircleNotch, spin: true },
  processing: { tone: "accent", label: "Procesando", Icon: CircleNotch, spin: true },
  indexing: { tone: "accent", label: "Indexando", Icon: CircleNotch, spin: true },
  ingesting: { tone: "accent", label: "Ingiriendo", Icon: CircleNotch, spin: true },
  embedding: { tone: "accent", label: "Vectorizando", Icon: CircleNotch, spin: true },
  chunking: { tone: "accent", label: "Fragmentando", Icon: CircleNotch, spin: true },
  parsing: { tone: "accent", label: "Interpretando", Icon: CircleNotch, spin: true },
  uploading: { tone: "accent", label: "Subiendo", Icon: CircleNotch, spin: true },
  deploying: { tone: "accent", label: "Desplegando", Icon: CircleNotch, spin: true },
  syncing: { tone: "accent", label: "Sincronizando", Icon: CircleNotch, spin: true },
  scanning: { tone: "accent", label: "Escaneando", Icon: CircleNotch, spin: true },
  // Atención
  pending: { tone: "warn", label: "Pendiente", Icon: Clock },
  queued: { tone: "warn", label: "En cola", Icon: Clock },
  staged: { tone: "warn", label: "En cola", Icon: Clock },
  staging: { tone: "warn", label: "Staging", Icon: Clock },
  degraded: { tone: "warn", label: "Degradado", Icon: WarningCircle },
  warning: { tone: "warn", label: "Con avisos", Icon: WarningCircle },
  partial: { tone: "warn", label: "Parcial", Icon: WarningCircle },
  discovering: { tone: "warn", label: "Descubriendo", Icon: Clock },
  profiled: { tone: "warn", label: "Perfilado", Icon: Clock },
  paused: { tone: "warn", label: "Pausado", Icon: Clock },
  needs_attention: { tone: "warn", label: "Requiere atención", Icon: WarningCircle },
  waiting_review: { tone: "warn", label: "Esperando revisión", Icon: Clock },
  in_review: { tone: "warn", label: "En revisión", Icon: Clock },
  open: { tone: "warn", label: "Abierto", Icon: Clock },
  stale: { tone: "warn", label: "Desactualizado", Icon: WarningCircle },
  needs_review: { tone: "warn", label: "Requiere revisión", Icon: WarningCircle },
  // Error
  failed: { tone: "danger", label: "Falló", Icon: XCircle },
  error: { tone: "danger", label: "Error", Icon: XCircle },
  suspended: { tone: "danger", label: "Suspendido", Icon: XCircle },
  revoked: { tone: "danger", label: "Revocado", Icon: XCircle },
  // Neutro
  draft: { tone: "neutral", label: "Borrador", Icon: Question },
  created: { tone: "neutral", label: "Creado", Icon: Question },
  archived: { tone: "neutral", label: "Archivado", Icon: Question },
  inactive: { tone: "neutral", label: "Inactivo", Icon: Question },
  disconnected: { tone: "neutral", label: "Desconectado", Icon: Question },
  canceled: { tone: "neutral", label: "Cancelado", Icon: Question },
  rolled_back: { tone: "neutral", label: "Revertido", Icon: Question },
  deprecated: { tone: "neutral", label: "Obsoleto", Icon: Question },
  dead: { tone: "neutral", label: "Descartado", Icon: Question },
  discarded: { tone: "neutral", label: "Descartado", Icon: Question },
  skipped: { tone: "neutral", label: "Omitido", Icon: Question },
  not_found: { tone: "neutral", label: "Sin datos", Icon: Question },
  connected: { tone: "info", label: "Conectado", Icon: Info },
  listening: { tone: "ok", label: "Escuchando", Icon: CheckCircle },
  checking: { tone: "accent", label: "Revisando ahora", Icon: CircleNotch, spin: true },
  denied: { tone: "danger", label: "Denegado", Icon: XCircle },
  simulated: { tone: "neutral", label: "Simulado", Icon: Question },
  created_ok: { tone: "info", label: "Creado", Icon: Info },
};

/** Etiqueta en español para un estado crudo del backend. */
export function statusLabel(status: string): string {
  return STATUS_META[status]?.label ?? labelFromRaw(status);
}

function labelFromRaw(status: string): string {
  if (!status) return "—";
  const text = status.replace(/[_-]+/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export type StatusBadgeProps = {
  status: string;
  /** Sobrescribe la etiqueta traducida. */
  label?: string;
  /** Usa el texto crudo del backend en vez de la traducción. */
  raw?: boolean;
  /** Oculta el icono (queda solo texto + color). */
  hideIcon?: boolean;
  className?: string;
};

/** Estado del sistema con icono + color + etiqueta. Fuente única de verdad. */
export function StatusBadge({
  status,
  label,
  raw = false,
  hideIcon = false,
  className,
}: StatusBadgeProps) {
  const meta = STATUS_META[status];
  const tone: Tone = meta?.tone ?? "neutral";
  const text = label ?? (raw ? labelFromRaw(status) : statusLabel(status));
  const IconEl = meta?.Icon;
  return (
    <span className={cn("badge", TONE_CLASS[tone], className)} title={status}>
      {IconEl && !hideIcon && (
        <IconEl
          size={12}
          weight="fill"
          className={meta?.spin ? "animate-spin" : undefined}
          aria-hidden
        />
      )}
      {text}
    </span>
  );
}
