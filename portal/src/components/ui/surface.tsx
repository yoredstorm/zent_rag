import {
  ArrowLeft,
  CaretRight,
  Info,
  type Icon,
} from "@phosphor-icons/react";
import { motion } from "motion/react";
import type { HTMLAttributes, ReactNode } from "react";
import { Link } from "react-router-dom";
import { cn } from "./cn";
import { Tooltip } from "./overlay";

/* ------------------------------------------------------------------ */
/* Paneles y secciones                                                 */
/* ------------------------------------------------------------------ */

export function Panel({
  children,
  className,
  flat = false,
  ...rest
}: {
  children: ReactNode;
  className?: string;
  /** Sin borde ni sombra: solo superficie. Para agrupar sin ruido. */
  flat?: boolean;
} & HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn(flat ? "panel-quiet" : "panel", className)} {...rest}>
      {children}
    </div>
  );
}

export function PanelHeader({
  title,
  description,
  actions,
  className,
  ...rest
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  className?: string;
} & Omit<HTMLAttributes<HTMLDivElement>, "title">) {
  return (
    <div className={cn("panel-header", className)} {...rest}>
      <div className="min-w-0">
        <h2 className="text-h3">{title}</h2>
        {description && (
          <p className="mt-0.5 text-xs leading-relaxed text-muted">{description}</p>
        )}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

/** Encabezado de sección sin contenedor: jerarquía por espacio, no por caja. */
export function SectionHeader({
  eyebrow,
  title,
  description,
  actions,
  className,
}: {
  eyebrow?: string;
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-wrap items-end justify-between gap-3", className)}>
      <div className="min-w-0">
        {eyebrow && <p className="eyebrow mb-1">{eyebrow}</p>}
        <h2 className="text-h2">{title}</h2>
        {description && (
          <p className="prose-measure mt-1 text-[13px] leading-relaxed text-muted">
            {description}
          </p>
        )}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Section({
  children,
  className,
  divider = false,
  ...rest
}: {
  children: ReactNode;
  className?: string;
  divider?: boolean;
} & HTMLAttributes<HTMLElement>) {
  return (
    <section className={cn(divider && "border-t border-border pt-6", className)} {...rest}>
      {children}
    </section>
  );
}

/* ------------------------------------------------------------------ */
/* Página                                                              */
/* ------------------------------------------------------------------ */

export type BreadcrumbItem = { label: string; to?: string };

export function Breadcrumbs({ items, className }: { items: BreadcrumbItem[]; className?: string }) {
  if (items.length === 0) return null;
  return (
    <nav aria-label="Ruta" className={cn("flex min-w-0 items-center gap-1.5 text-xs", className)}>
      {items.map((item, i) => {
        const isLast = i === items.length - 1;
        return (
          <span key={`${item.label}-${i}`} className="flex min-w-0 items-center gap-1.5">
            {i > 0 && <CaretRight size={10} className="shrink-0 text-ghost" aria-hidden />}
            {item.to ? (
              <Link
                to={item.to}
                className="truncate text-muted transition-colors duration-150 hover:text-text"
              >
                {item.label}
              </Link>
            ) : (
              <span
                className={cn("truncate", isLast ? "text-text" : "text-muted")}
                aria-current={isLast ? "page" : undefined}
              >
                {item.label}
              </span>
            )}
          </span>
        );
      })}
    </nav>
  );
}

export function PageHeader({
  title,
  subtitle,
  actions,
  breadcrumbs,
  backTo,
  backLabel = "Volver",
  meta,
  className,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  breadcrumbs?: BreadcrumbItem[];
  backTo?: string;
  backLabel?: string;
  /** Badges o metadatos junto al título. */
  meta?: ReactNode;
  className?: string;
}) {
  return (
    <header className={cn("mb-6", className)}>
      {breadcrumbs && <Breadcrumbs items={breadcrumbs} className="mb-2" />}
      {backTo && (
        <Link
          to={backTo}
          className="mb-2 inline-flex items-center gap-1.5 text-[13px] text-muted transition-colors duration-150 hover:text-text"
        >
          <ArrowLeft size={14} aria-hidden />
          {backLabel}
        </Link>
      )}
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
            <h1 className="text-h1">{title}</h1>
            {meta}
          </div>
          {subtitle && (
            <p className="prose-measure mt-1.5 text-sm leading-relaxed text-muted">{subtitle}</p>
          )}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
    </header>
  );
}

/* ------------------------------------------------------------------ */
/* Métricas                                                            */
/* ------------------------------------------------------------------ */

export type MetricProps = {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  icon?: Icon;
  tone?: "default" | "ok" | "warn" | "danger" | "accent";
  /** Variación real (%, delta) ya formateada. */
  delta?: { value: string; direction: "up" | "down" | "flat"; good?: boolean };
  /** `md` demota el valor (22px) para que el foco de la vista sea otro. */
  size?: "md" | "lg";
  help?: string;
  className?: string;
};

const METRIC_TONE: Record<NonNullable<MetricProps["tone"]>, string> = {
  default: "text-text",
  accent: "text-accent",
  ok: "text-ok",
  warn: "text-warn",
  danger: "text-danger",
};

/**
 * Métrica decidida: label demotado, valor como focal, delta con significado.
 * El dato manda por peso + tamaño, no por color.
 */
export function Metric({
  label,
  value,
  hint,
  icon: IconEl,
  tone = "default",
  delta,
  size = "lg",
  help,
  className,
}: MetricProps) {
  return (
    <div className={cn("stat", className)}>
      <div className="flex items-center justify-between gap-2">
        <span className="stat-label">{label}</span>
        <span className="flex items-center gap-1.5">
          {help && (
            <Tooltip label={help}>
              <button
                type="button"
                className="inline-flex h-5 w-5 items-center justify-center rounded-full text-ghost transition-colors duration-150 hover:text-muted"
                aria-label={`Qué significa ${label}`}
              >
                <Info size={13} aria-hidden />
              </button>
            </Tooltip>
          )}
          {IconEl && <IconEl size={16} weight="regular" className="text-faint" aria-hidden />}
        </span>
      </div>
      <div className={cn("stat-value", size === "md" && "text-[22px]", METRIC_TONE[tone])}>{value}</div>
      <div className="mt-1.5 flex flex-wrap items-baseline gap-x-2 gap-y-1">
        {delta && (
          <span
            className={cn(
              "inline-flex items-center gap-1 text-xs font-medium tabular-nums",
              delta.direction === "flat"
                ? "text-muted"
                : delta.good === false
                  ? "text-danger"
                  : delta.good === true
                    ? "text-ok"
                    : "text-muted"
            )}
          >
            {delta.direction === "up" ? "↑" : delta.direction === "down" ? "↓" : "→"}
            {delta.value}
          </span>
        )}
        {hint && <span className="text-xs text-muted">{hint}</span>}
      </div>
    </div>
  );
}

export function MetricGrid({
  children,
  className,
  cols = 4,
}: {
  children: ReactNode;
  className?: string;
  cols?: 2 | 3 | 4;
}) {
  const grid =
    cols === 2
      ? "sm:grid-cols-2"
      : cols === 3
        ? "sm:grid-cols-2 lg:grid-cols-3"
        : "sm:grid-cols-2 lg:grid-cols-4";
  return <div className={cn("grid grid-cols-1 gap-3", grid, className)}>{children}</div>;
}

/* ------------------------------------------------------------------ */
/* Split pane                                                          */
/* ------------------------------------------------------------------ */

/**
 * Dos columnas con proporción declarada: el panel secundario inspecciona
 * sin destruir el contexto del primario. En móvil se apila.
 */
export function SplitPane({
  primary,
  secondary,
  secondaryWidth = 360,
  secondaryPosition = "right",
  className,
  ...rest
}: {
  primary: ReactNode;
  secondary: ReactNode;
  secondaryWidth?: number;
  secondaryPosition?: "left" | "right";
  className?: string;
} & HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("flex min-w-0 flex-col gap-4 lg:flex-row lg:items-start", className)}
      {...rest}
    >
      <div className={cn("min-w-0 flex-1", secondaryPosition === "left" && "lg:order-2")}>
        {primary}
      </div>
      <aside
        className={cn("min-w-0 shrink-0", secondaryPosition === "left" && "lg:order-1")}
        style={{ width: `min(100%, ${secondaryWidth}px)` }}
      >
        {secondary}
      </aside>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Barra de herramientas                                               */
/* ------------------------------------------------------------------ */

export function Toolbar({
  children,
  className,
  sticky = false,
  ...rest
}: {
  children: ReactNode;
  className?: string;
  sticky?: boolean;
} & HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-2",
        sticky && "sticky top-0 z-10 -mx-1 bg-bg/90 px-1 py-2 backdrop-blur-sm",
        className
      )}
      {...rest}
    >
      {children}
    </div>
  );
}

export function ToolbarSpacer() {
  return <span className="flex-1" aria-hidden />;
}

/** Mensaje temporal de confirmación de una acción (aparece y se desvanece). */
export function InlineFlash({
  children,
  tone = "ok",
  className,
}: {
  children: ReactNode;
  tone?: "ok" | "danger" | "neutral";
  className?: string;
}) {
  return (
    <motion.span
      initial={{ opacity: 0, y: -3 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.16, ease: [0.23, 1, 0.32, 1] }}
      className={cn(
        "inline-flex items-center gap-1.5 text-xs font-medium",
        tone === "ok" ? "text-ok" : tone === "danger" ? "text-danger" : "text-muted",
        className
      )}
      role="status"
    >
      {children}
    </motion.span>
  );
}
