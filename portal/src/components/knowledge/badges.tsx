// =============================================================================
// Badges del Knowledge OS — procedencia, evidencia y salud
// =============================================================================
import { FileText, LinkSimple, SealCheck, WarningCircle } from "@phosphor-icons/react";
import { cn } from "../ui";

export function SourceBadge({
  name,
  count,
  className,
}: {
  name: string;
  count?: number;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex max-w-full items-center gap-1.5 rounded-sm border border-border bg-raised px-2 py-0.5 text-[11px] text-muted",
        className
      )}
    >
      <FileText size={11} className="shrink-0 text-faint" aria-hidden />
      <span className="truncate">{name}</span>
      {count != null && <span className="mono text-faint">{count}</span>}
    </span>
  );
}

export function EvidenceBadge({
  count,
  className,
}: {
  count: number;
  className?: string;
}) {
  const strong = count >= 3;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-sm px-2 py-0.5 text-[11px]",
        strong ? "bg-ok-soft text-ok" : count > 0 ? "bg-info-soft text-info" : "bg-soft text-faint",
        className
      )}
      title={`${count} evidencia(s) localizables`}
    >
      <LinkSimple size={11} aria-hidden />
      {count} evidencia{count === 1 ? "" : "s"}
    </span>
  );
}

export function VerifiedBadge({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-sm bg-ok-soft px-2 py-0.5 text-[11px] text-ok",
        className
      )}
    >
      <SealCheck size={11} aria-hidden />
      Verificado
    </span>
  );
}

export function ConflictBadge({
  count,
  className,
}: {
  count: number;
  className?: string;
}) {
  if (count <= 0) return null;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-sm bg-warn-soft px-2 py-0.5 text-[11px] text-warn",
        className
      )}
      title={`${count} conflicto(s) abiertos`}
    >
      <WarningCircle size={11} aria-hidden />
      {count} conflicto{count === 1 ? "" : "s"}
    </span>
  );
}

export function HealthIndicator({
  value,
  size = 64,
  className,
}: {
  value: number | null;
  size?: number;
  className?: string;
}) {
  const stroke = Math.max(4, Math.round(size / 12));
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const measured = value != null;
  const pct = measured ? Math.max(0, Math.min(100, value)) : 0;
  const tone =
    !measured ? "text-faint" : value >= 75 ? "text-ok" : value >= 50 ? "text-warn" : "text-danger";
  return (
    <div
      className={cn("relative inline-flex shrink-0 items-center justify-center", className)}
      style={{ width: size, height: size }}
      role="img"
      aria-label={
        measured ? `Knowledge Health ${Math.round(value)} por ciento` : "Knowledge Health no medido"
      }
    >
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="var(--zent-track)"
          strokeWidth={stroke}
        />
        {measured && (
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke="currentColor"
            className={tone}
            strokeWidth={stroke}
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={circumference * (1 - pct / 100)}
            transform={`rotate(-90 ${size / 2} ${size / 2})`}
            style={{ transition: "stroke-dashoffset 420ms var(--ease-out)" }}
          />
        )}
      </svg>
      <span className={cn("absolute mono text-[15px] font-semibold tabular-nums", tone)}>
        {measured ? Math.round(value) : "—"}
      </span>
    </div>
  );
}
