import type { Icon } from "@phosphor-icons/react";
import type { ReactNode } from "react";

export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
}) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-text">{title}</h1>
        {subtitle && (
          <p className="mt-1 max-w-[65ch] text-sm leading-relaxed text-muted">
            {subtitle}
          </p>
        )}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </header>
  );
}

export function StatCard({
  label,
  value,
  hint,
  help,
  icon: IconEl,
  tone = "default",
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  help?: string;
  icon?: Icon;
  tone?: "default" | "ok" | "warn" | "danger";
}) {
  const toneClass =
    tone === "ok"
      ? "text-ok"
      : tone === "warn"
        ? "text-warn"
        : tone === "danger"
          ? "text-danger"
          : "text-accent";
  return (
    <div className="stat">
      <div className="flex items-center justify-between gap-2">
        <span className="stat-label">{label}</span>
        <span className="flex items-center gap-1">
          {help && (
            <button
              type="button"
              className="inline-flex h-6 w-6 items-center justify-center rounded-full border border-border text-xs text-muted hover:text-text"
              aria-label={`Qué significa ${label}`}
              title={help}
            >
              ?
            </button>
          )}
          {IconEl && (
            <IconEl size={16} weight="regular" className={toneClass} aria-hidden />
          )}
        </span>
      </div>
      <div className="stat-value">{value}</div>
      {hint && <div className="mt-1 text-xs text-muted">{hint}</div>}
    </div>
  );
}

export function ErrorInline({ message }: { message: string }) {
  if (!message) return null;
  return (
    <div
      className="mb-4 flex items-start gap-2 rounded-md border border-danger/25 bg-danger-soft px-3 py-2.5 text-sm text-danger"
      role="alert"
    >
      {message}
    </div>
  );
}

export function SuccessInline({ message }: { message: string }) {
  if (!message) return null;
  return (
    <div
      className="mb-4 flex items-start gap-2 rounded-md border border-ok/25 bg-ok-soft px-3 py-2.5 text-sm text-ok"
      role="status"
    >
      {message}
    </div>
  );
}

export function Spinner({ size = 16 }: { size?: number }) {
  return (
    <span
      className="inline-block animate-spin rounded-full border-2 border-border-strong border-t-accent"
      style={{ width: size, height: size }}
      aria-label="Cargando"
    />
  );
}

export function LoadingDots() {
  return (
    <span className="inline-flex items-center gap-1" aria-label="Pensando">
      <span className="h-1.5 w-1.5 animate-pulse-soft rounded-full bg-muted" />
      <span className="h-1.5 w-1.5 animate-pulse-soft rounded-full bg-muted [animation-delay:150ms]" />
      <span className="h-1.5 w-1.5 animate-pulse-soft rounded-full bg-muted [animation-delay:300ms]" />
    </span>
  );
}

export function SkeletonBlock({ rows = 3 }: { rows?: number }) {
  return (
    <div className="flex flex-col gap-3 p-1" aria-hidden>
      {Array.from({ length: rows }).map((_, i) => (
        <div
          key={i}
          className="skeleton h-4"
          style={{ width: `${[92, 76, 84, 58, 66][i % 5]}%` }}
        />
      ))}
    </div>
  );
}

export function EmptyState({
  icon: IconEl,
  title,
  body,
  action,
}: {
  icon: Icon;
  title: string;
  body?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-2 px-6 py-10 text-center">
      <div className="flex h-11 w-11 items-center justify-center rounded-md border border-border bg-soft text-faint">
        <IconEl size={22} weight="regular" aria-hidden />
      </div>
      <p className="mt-1 text-sm font-medium text-text">{title}</p>
      {body && <p className="max-w-sm text-[13px] leading-relaxed text-muted">{body}</p>}
      {action && <div className="mt-3">{action}</div>}
    </div>
  );
}
