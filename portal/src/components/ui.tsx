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


const STATUS_TONES: Record<string, string> = {
  healthy: "badge-ok",
  production: "badge-ok",
  active: "badge-ok",
  ready: "badge-ok",
  completed: "badge-ok",
  success: "badge-ok",
  pending: "badge-pending",
  deploying: "badge-pending",
  staging: "badge-pending",
  draft: "badge-muted",
  degraded: "badge-pending",
  rolled_back: "badge-muted",
  failed: "badge-danger",
  archived: "badge-muted",
  suspended: "badge-danger",
  inactive: "badge-muted",
  created: "badge-muted",
  connected: "badge-muted",
  discovering: "badge-pending",
  profiled: "badge-pending",
  ingesting: "badge-pending",
  indexed: "badge-ok",
};

export function StatusBadge({ status }: { status: string }) {
  const tone = STATUS_TONES[status] || "badge-muted";
  return (
    <span className={`badge ${tone}`} title={status}>
      {status}
    </span>
  );
}

export function VersionBadge({ versionNumber, status }: { versionNumber: number; status: string }) {
  return (
    <span className="inline-flex items-center gap-2">
      <span className="badge badge-muted">v{versionNumber}</span>
      <StatusBadge status={status} />
    </span>
  );
}

export function EnvironmentBadge({ name }: { name: string }) {
  const tone =
    name === "production" ? "badge-ok" : name === "staging" ? "badge-pending" : "badge-muted";
  return <span className={`badge ${tone}`}>{name}</span>;
}


const ROLE_TONES: Record<string, string> = {
  owner: "badge-ok",
  admin: "badge-ok",
  super_admin: "badge-ok",
  platform_admin: "badge-ok",
  ai_engineer: "badge-ok",
  data_engineer: "badge-pending",
  developer: "badge-pending",
  analyst: "badge-muted",
  billing: "badge-pending",
  operations: "badge-pending",
  support: "badge-pending",
  security_auditor: "badge-pending",
  member: "badge-muted",
  viewer: "badge-muted",
  read_only: "badge-muted",
};

export function RoleBadge({ role }: { role: string }) {
  const tone = ROLE_TONES[role] || "badge-muted";
  return <span className={`badge ${tone}`}>{role}</span>;
}

export function TenantHealthBadge({
  label,
  score,
}: {
  label: string;
  score: number;
}) {
  const tone =
    label === "HEALTHY" ? "badge-ok" : label === "WATCH" ? "badge-pending" : "badge-danger";
  return (
    <span className="inline-flex items-center gap-1.5" title={`Score: ${score}/100`}>
      <span className={`badge ${tone}`}>{label}</span>
      <span className="text-xs text-faint">{score}%</span>
    </span>
  );
}

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
              <td className="font-mono text-xs text-muted">{perm}</td>
              {roles.map((r) => (
                <td key={r.name} className="text-center">
                  {r.permissions.includes(perm) ? (
                    <span className="text-ok">&#10003;</span>
                  ) : (
                    <span className="text-faint">&#183;</span>
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
  items: { action: string; resource_type: string; created_at: string | null; metadata?: Record<string, unknown> }[];
}) {
  if (items.length === 0) {
    return <p className="text-sm text-muted">Sin actividad reciente.</p>;
  }
  return (
    <ul className="divide-y divide-border">
      {items.slice(0, 10).map((item, i) => (
        <li key={i} className="flex items-start justify-between gap-3 py-2">
          <div className="min-w-0">
            <p className="truncate text-sm text-text">{item.action}</p>
            <p className="text-xs text-faint">{item.resource_type}</p>
          </div>
          <span className="shrink-0 text-xs text-faint">
            {item.created_at ? new Date(item.created_at).toLocaleString("es-PE") : ""}
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
    <div className="panel">
      <div className="flex items-center justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between">
            <p className="text-sm font-semibold text-text">Production Readiness</p>
            <p className="text-2xl font-semibold text-text">{score}%</p>
          </div>
          <div className="mt-2 h-2 overflow-hidden rounded-full bg-soft">
            <div className={`h-full rounded-full ${tone}`} style={{ width: `${score}%` }} />
          </div>
        </div>
      </div>
      <ul className="mt-3 grid grid-cols-1 gap-1 sm:grid-cols-2">
        {items.map((item) => (
          <li key={item.key} className="flex items-center gap-2 text-xs">
            <span className={item.met ? "text-ok" : "text-faint"}>
              {item.met ? "\u2713" : "\u25CB"}
            </span>
            <span className="text-text">{item.label}</span>
            <span className="ml-auto text-faint">+{item.weight}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
