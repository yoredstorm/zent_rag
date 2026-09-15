import { Buildings } from "@phosphor-icons/react";
import { cn } from "./ui/cn";

/**
 * Marca Zent: prisma de señal (rombo en rombo).
 * Conocimiento + señal de actividad, lo bastante simple para leerse a 16px.
 */
export function BrandMark({ size = 18, className }: { size?: number; className?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      className={className}
      aria-hidden
    >
      <path
        d="M12 3.4 20.6 12 12 20.6 3.4 12 12 3.4Z"
        stroke="var(--color-accent)"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
      <path d="M12 8.5 15.5 12 12 15.5 8.5 12 12 8.5Z" fill="var(--color-accent)" fillOpacity="0.85" />
    </svg>
  );
}

export function Brand({
  compact = false,
  className,
}: {
  /** Solo el isotipo, sin wordmark. */
  compact?: boolean;
  className?: string;
}) {
  return (
    <span className={cn("flex min-w-0 items-center gap-2.5", className)}>
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-accent-line bg-accent-soft shadow-glow">
        <BrandMark size={16} />
      </span>
      {!compact && (
        <span className="flex min-w-0 flex-col leading-none">
          <span className="truncate text-[15px] font-semibold tracking-[-0.01em] text-text">Zent</span>
          <span className="mt-0.5 truncate text-[10px] font-medium tracking-[0.06em] text-faint uppercase">
            Intelligence
          </span>
        </span>
      )}
    </span>
  );
}

/** Avatar cuadrado para identidad (workspace, cuenta, tenant). */
export function IdentityTile({
  label,
  kind = "workspace",
  size = 28,
  className,
}: {
  label: string;
  kind?: "workspace" | "tenant" | "account";
  size?: number;
  className?: string;
}) {
  const initial = (label.trim().charAt(0) || "Z").toUpperCase();
  return (
    <span
      className={cn(
        "flex shrink-0 items-center justify-center rounded-sm font-semibold",
        kind === "account"
          ? "border border-border bg-raised text-muted"
          : "bg-accent-soft text-accent",
        className
      )}
      style={{ width: size, height: size, fontSize: Math.round(size * 0.42) }}
      aria-hidden
    >
      {kind === "tenant" ? <Buildings size={Math.round(size * 0.5)} /> : initial}
    </span>
  );
}
