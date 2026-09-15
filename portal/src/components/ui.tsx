/**
 * Capa de compatibilidad del design system.
 *
 * Las primitivas viven en `./ui/` (ver `.interface-design/system.md`).
 * Este módulo conserva los exports históricos para no romper consumidores:
 * las páginas nuevas importan de `./ui`.
 */
import { SquaresFour, type Icon } from "@phosphor-icons/react";
import type { ReactNode } from "react";
import { fmtDateTime } from "../lib/format";
import { Badge } from "./ui/Badge";
import { StatusBadge as StatusBadgePrimitive } from "./ui/Badge";
import { Tooltip } from "./ui/overlay";
import { cn } from "./ui/cn";

/* --- Primitivas re-exportadas (fuente única en ./ui) --------------- */
/* `export *` + definiciones locales: lo local gana, sin duplicados. */
export * from "./ui/index";

/* --- StatCard (compat) -------------------------------------------- */

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
        <span className="flex items-center gap-1.5">
          {help && (
            <Tooltip label={help}>
              <button
                type="button"
                className="inline-flex h-5 w-5 items-center justify-center rounded-full text-ghost transition-colors duration-150 hover:text-muted"
                aria-label={`Qué significa ${label}`}
              >
                <SquaresFour size={12} aria-hidden />
              </button>
            </Tooltip>
          )}
          {IconEl && <IconEl size={16} weight="regular" className={toneClass} aria-hidden />}
        </span>
      </div>
      <div className={cn("stat-value", tone === "default" ? undefined : toneClass)}>{value}</div>
      {hint && <div className="stat-hint">{hint}</div>}
    </div>
  );
}

/* --- Estados ------------------------------------------------------ */

const STATUS_ALIASES: Record<string, string> = {
  HEALTHY: "healthy",
  WATCH: "degraded",
  "AT RISK": "failed",
};

/**
 * Compat: el `StatusBadge` histórico traduce aliases de health y reenvía
 * todas las props de la primitiva (label, hideIcon, className).
 */
export function StatusBadge({
  status,
  raw = false,
  label,
  hideIcon,
  className,
}: {
  status: string;
  /** Muestra el texto crudo del backend en vez de la etiqueta traducida. */
  raw?: boolean;
  label?: string;
  hideIcon?: boolean;
  className?: string;
}) {
  return (
    <StatusBadgePrimitive
      status={STATUS_ALIASES[status] ?? status}
      raw={raw}
      label={label}
      hideIcon={hideIcon}
      className={className}
    />
  );
}

export function VersionBadge({ versionNumber, status }: { versionNumber: number; status: string }) {
  return (
    <span className="inline-flex items-center gap-2">
      <Badge tone="neutral">v{versionNumber}</Badge>
      <StatusBadgePrimitive status={status} />
    </span>
  );
}

export function EnvironmentBadge({ name }: { name: string }) {
  const tone = name === "production" ? "ok" : name === "staging" ? "warn" : "neutral";
  return <Badge tone={tone}>{name}</Badge>;
}

const ROLE_TONES: Record<string, "ok" | "warn" | "neutral"> = {
  owner: "ok",
  admin: "ok",
  super_admin: "ok",
  platform_admin: "ok",
  ai_engineer: "ok",
  data_engineer: "warn",
  developer: "warn",
  analyst: "neutral",
  billing: "warn",
  operations: "warn",
  support: "warn",
  security_auditor: "warn",
  member: "neutral",
  viewer: "neutral",
  read_only: "neutral",
};

export function RoleBadge({ role }: { role: string }) {
  return <Badge tone={ROLE_TONES[role] ?? "neutral"}>{role}</Badge>;
}

export function TenantHealthBadge({ label, score }: { label: string; score: number }) {
  const tone = label === "HEALTHY" ? "ok" : label === "WATCH" ? "warn" : "danger";
  return (
    <span className="inline-flex items-center gap-1.5" title={`Score: ${score}/100`}>
      <Badge tone={tone}>{label}</Badge>
      <span className="mono text-xs text-faint">{score}%</span>
    </span>
  );
}

/** Alias genérico de health con semántica HEALTHY / WATCH / AT RISK. */
export const HealthBadge = TenantHealthBadge;

/* --- Tablas de apoyo --------------------------------------------- */

export function PermissionMatrix({
  roles,
}: {
  roles: { name: string; description: string | null; permissions: string[] }[];
}) {
  return (
    <div className="overflow-x-auto">
      <table className="table">
        <thead>
          <tr>
            <th>Rol</th>
            {roles.map((r) => (
              <th key={r.name} className="text-center">
                {r.name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {Array.from(new Set(roles.flatMap((r) => r.permissions))).map((perm) => (
            <tr key={perm}>
              <td className="mono text-xs text-muted">{perm}</td>
              {roles.map((r) => (
                <td key={r.name} className="text-center">
                  {r.permissions.includes(perm) ? (
                    <span className="text-ok" aria-label="Sí">
                      &#10003;
                    </span>
                  ) : (
                    <span className="text-ghost" aria-label="No">
                      &#183;
                    </span>
                  )}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function RecentActivity({
  items,
}: {
  items: {
    action: string;
    resource_type: string;
    created_at: string | null;
    metadata?: Record<string, unknown>;
  }[];
}) {
  if (items.length === 0) {
    return <p className="text-sm text-muted">Sin actividad reciente.</p>;
  }
  return (
    <ul className="divide-y divide-border-soft">
      {items.slice(0, 10).map((item, i) => (
        <li key={i} className="flex items-start justify-between gap-3 py-2.5">
          <div className="min-w-0">
            <p className="truncate text-[13px] text-text">{item.action}</p>
            <p className="text-xs text-faint">{item.resource_type}</p>
          </div>
          <span className="shrink-0 text-xs text-faint tabular-nums">
            {fmtDateTime(item.created_at)}
          </span>
        </li>
      ))}
    </ul>
  );
}

export function ReadinessScore({
  score,
  items,
}: {
  score: number;
  items: { key: string; label: string; met: boolean; weight: number; detail: string }[];
}) {
  const tone = score >= 80 ? "bg-ok" : score >= 50 ? "bg-warn" : "bg-danger";
  return (
    <div className="panel p-4">
      <div className="flex items-center justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between">
            <p className="text-sm font-semibold text-text">Listo para producción</p>
            <p className="mono text-2xl font-semibold text-text">{score}%</p>
          </div>
          <div className="mt-2 h-2 overflow-hidden rounded-full bg-track">
            <div className={`h-full rounded-full ${tone}`} style={{ width: `${score}%` }} />
          </div>
        </div>
      </div>
      <ul className="mt-3 grid grid-cols-1 gap-1 sm:grid-cols-2">
        {items.map((item) => (
          <li key={item.key} className="flex items-center gap-2 text-xs">
            <span className={item.met ? "text-ok" : "text-ghost"} aria-hidden>
              {item.met ? "\u2713" : "\u25CB"}
            </span>
            <span className="text-text">{item.label}</span>
            <span className="ml-auto text-faint tabular-nums">+{item.weight}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
