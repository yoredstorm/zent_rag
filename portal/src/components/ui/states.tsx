import {
  ArrowClockwise,
  CheckCircle,
  Info,
  Lock,
  Sparkle,
  WarningCircle,
  XCircle,
  type Icon,
} from "@phosphor-icons/react";
import type { ReactNode } from "react";
import { cn } from "./cn";

export function Spinner({ size = 16, label = "Cargando" }: { size?: number; label?: string }) {
  return (
    <span
      role="status"
      className="inline-block shrink-0 animate-spin rounded-full border-2 border-border-strong border-t-accent"
      style={{ width: size, height: size }}
      aria-label={label}
    />
  );
}

export function LoadingDots({ label = "Procesando" }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-1" role="status" aria-label={label}>
      <span className="h-1.5 w-1.5 animate-pulse-soft rounded-full bg-muted" />
      <span className="h-1.5 w-1.5 animate-pulse-soft rounded-full bg-muted [animation-delay:150ms]" />
      <span className="h-1.5 w-1.5 animate-pulse-soft rounded-full bg-muted [animation-delay:300ms]" />
    </span>
  );
}

export function Skeleton({
  className,
  width,
  height,
}: {
  className?: string;
  width?: number | string;
  height?: number | string;
}) {
  return (
    <span
      className={cn("skeleton block", className)}
      style={{ width, height }}
      aria-hidden
    />
  );
}

/** Bloque de líneas de texto. Compat con el SkeletonBlock histórico. */
export function SkeletonBlock({ rows = 3, className = "" }: { rows?: number; className?: string }) {
  return (
    <div className={`flex flex-col gap-3 p-1 ${className}`} aria-hidden>
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="h-4" width={`${[92, 76, 84, 58, 66][i % 5]}%`} />
      ))}
    </div>
  );
}

/** Skeleton con la forma de una tabla: evita el salto de layout al cargar. */
export function SkeletonTable({ rows = 6, cols = 4 }: { rows?: number; cols?: number }) {
  return (
    <div className="flex flex-col gap-0" aria-hidden>
      <div className="flex gap-3 border-b border-border px-3 py-3">
        {Array.from({ length: cols }).map((_, i) => (
          <Skeleton key={i} className="h-3 flex-1" />
        ))}
      </div>
      {Array.from({ length: rows }).map((_, r) => (
        <div key={r} className="flex gap-3 border-b border-border-soft px-3 py-3.5">
          {Array.from({ length: cols }).map((_, c) => (
            <Skeleton key={c} className="h-3.5 flex-1" width={c === 0 ? "70%" : undefined} />
          ))}
        </div>
      ))}
    </div>
  );
}

export function SkeletonCards({ count = 3, height = 96 }: { count?: number; height?: number }) {
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3" aria-hidden>
      {Array.from({ length: count }).map((_, i) => (
        <Skeleton key={i} className="rounded-lg" height={height} />
      ))}
    </div>
  );
}

export type EmptyStateProps = {
  icon?: Icon;
  title: string;
  body?: string;
  /** Segunda línea: qué ocurrirá después o qué falta. */
  hint?: string;
  action?: ReactNode;
  secondaryAction?: ReactNode;
  compact?: boolean;
  tone?: "neutral" | "accent";
  className?: string;
};

/**
 * Estado vacío accionable: dice qué falta, por qué importa y qué hacer ahora.
 * No es un "No hay datos".
 */
export function EmptyState({
  icon: IconEl = Sparkle,
  title,
  body,
  hint,
  action,
  secondaryAction,
  compact = false,
  tone = "neutral",
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center text-center",
        compact ? "gap-1.5 px-4 py-6" : "gap-2 px-6 py-12",
        className
      )}
    >
      <div
        className={cn(
          "flex items-center justify-center rounded-md border",
          compact ? "h-9 w-9" : "h-11 w-11",
          tone === "accent"
            ? "border-accent-line bg-accent-soft text-accent"
            : "border-border bg-raised text-faint"
        )}
      >
        <IconEl size={compact ? 18 : 21} weight="regular" aria-hidden />
      </div>
      <p className={cn("mt-1 font-medium text-text", compact ? "text-[13px]" : "text-sm")}>
        {title}
      </p>
      {body && (
        <p className="max-w-sm text-[13px] leading-relaxed text-muted text-pretty">{body}</p>
      )}
      {hint && <p className="max-w-sm text-xs leading-relaxed text-faint">{hint}</p>}
      {(action || secondaryAction) && (
        <div className="mt-3 flex flex-wrap items-center justify-center gap-2">
          {action}
          {secondaryAction}
        </div>
      )}
    </div>
  );
}

type InlineProps = { message?: ReactNode; children?: ReactNode; className?: string };

/** Contenido del aviso: acepta string o JSX (para incluir acciones dentro del mensaje). */
function inlineContent(message: ReactNode, children: ReactNode): ReactNode {
  const content = message ?? children;
  if (content === null || content === undefined || content === "" || content === false) return null;
  return content;
}

export function ErrorInline({ message, children, className }: InlineProps) {
  const content = inlineContent(message, children);
  if (!content) return null;
  return (
    <div
      className={cn(
        "mb-4 flex items-start gap-2.5 rounded-md border border-danger/25 bg-danger-soft px-3 py-2.5 text-sm text-danger",
        className
      )}
      role="alert"
    >
      <XCircle size={17} weight="regular" className="mt-px shrink-0" aria-hidden />
      <span className="leading-relaxed">{content}</span>
    </div>
  );
}

export function SuccessInline({ message, children, className }: InlineProps) {
  const content = inlineContent(message, children);
  if (!content) return null;
  return (
    <div
      className={cn(
        "mb-4 flex items-start gap-2.5 rounded-md border border-ok/25 bg-ok-soft px-3 py-2.5 text-sm text-ok",
        className
      )}
      role="status"
    >
      <CheckCircle size={17} weight="regular" className="mt-px shrink-0" aria-hidden />
      <span className="leading-relaxed">{content}</span>
    </div>
  );
}

export function InfoInline({ message, children, className }: InlineProps) {
  const content = inlineContent(message, children);
  if (!content) return null;
  return (
    <div
      className={cn(
        "mb-4 flex items-start gap-2.5 rounded-md border border-border bg-raised px-3 py-2.5 text-sm text-muted",
        className
      )}
    >
      <Info size={17} weight="regular" className="mt-px shrink-0" aria-hidden />
      <span className="leading-relaxed">{content}</span>
    </div>
  );
}

export function WarningInline({ message, children, className }: InlineProps) {
  const content = inlineContent(message, children);
  if (!content) return null;
  return (
    <div
      className={cn(
        "mb-4 flex items-start gap-2.5 rounded-md border border-warn/25 bg-warn-soft px-3 py-2.5 text-sm text-warn",
        className
      )}
      role="status"
    >
      <WarningCircle size={17} weight="regular" className="mt-px shrink-0" aria-hidden />
      <span className="leading-relaxed">{content}</span>
    </div>
  );
}

/** Estado de permiso insuficiente: dice qué falta y cómo pedirlo. */
export function NoAccessState({
  title = "Sin acceso",
  body = "Tu rol actual no incluye este permiso. Pedile a un owner o admin de la organización que te lo habilite.",
  action,
}: {
  title?: string;
  body?: string;
  action?: ReactNode;
}) {
  return (
    <EmptyState icon={Lock} title={title} body={body} action={action} />
  );
}

export function OfflineState({ onRetry }: { onRetry?: () => void }) {
  return (
    <EmptyState
      icon={WarningCircle}
      title="Sin conexión con el servidor"
      body="No pudimos contactar la API. Revisá tu red o el estado del servicio."
      action={
        onRetry && (
          <button type="button" className="btn btn-secondary btn-sm" onClick={onRetry}>
            <ArrowClockwise size={14} aria-hidden />
            Reintentar
          </button>
        )
      }
    />
  );
}

export function Progress({
  value,
  max = 100,
  label,
  tone = "accent",
  showValue = false,
  className,
}: {
  value: number;
  max?: number;
  label?: string;
  tone?: "accent" | "ok" | "warn" | "danger";
  showValue?: boolean;
  className?: string;
}) {
  const pct = max > 0 ? Math.max(0, Math.min(100, (value / max) * 100)) : 0;
  const fill =
    tone === "ok" ? "bg-ok" : tone === "warn" ? "bg-warn" : tone === "danger" ? "bg-danger" : "bg-accent";
  return (
    <div className={className}>
      {(label || showValue) && (
        <div className="mb-1.5 flex items-baseline justify-between gap-3">
          {label && <span className="text-xs text-muted">{label}</span>}
          {showValue && <span className="mono text-xs text-faint">{Math.round(pct)}%</span>}
        </div>
      )}
      <div
        className="progress-track"
        role="progressbar"
        aria-valuenow={Math.round(pct)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={label || "Progreso"}
      >
        <div className={cn("progress-fill", fill)} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

/** Fila de estado para jobs con progreso real y rail de actividad. */
export function StatusRow({
  state,
  title,
  meta,
  progress,
  actions,
  className,
}: {
  state: "queued" | "running" | "ready" | "warning" | "failed" | "processing" | "indexing";
  title: ReactNode;
  meta?: ReactNode;
  progress?: number;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn("state-rail flex items-start gap-3 py-2.5", className)}
      data-state={state}
    >
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">{title}</div>
        {meta && <div className="mt-0.5 text-xs text-faint">{meta}</div>}
        {typeof progress === "number" && (
          <Progress value={progress} className="mt-2 max-w-sm" tone={state === "failed" ? "danger" : "accent"} />
        )}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-1.5">{actions}</div>}
    </div>
  );
}

/** Fallback de ruta: skeleton con forma de página. Reemplaza al spinner centrado. */
export function PageSkeleton({ header = true }: { header?: boolean }) {
  return (
    <div className="flex flex-col gap-5" aria-hidden>
      {header && (
        <div className="flex items-end justify-between gap-4">
          <div className="flex flex-col gap-2">
            <Skeleton className="h-6 w-52" />
            <Skeleton className="h-3.5 w-80" />
          </div>
          <Skeleton className="h-9 w-28" />
        </div>
      )}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-[86px] rounded-lg" />
        ))}
      </div>
      <Skeleton className="h-[220px] rounded-lg" />
    </div>
  );
}
