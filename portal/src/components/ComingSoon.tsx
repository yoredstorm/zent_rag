import type { ReactNode } from "react";

/** Estado visual para funcionalidad futura planificada pero no implementada. */
export function ComingSoon({
  label = "Próximamente",
  children,
}: {
  label?: string;
  children?: ReactNode;
}) {
  return (
    <div className="panel flex flex-col items-center gap-2 px-6 py-10 text-center">
      <span className="badge badge-pending">{label}</span>
      {children && (
        <div className="max-w-sm text-[13px] leading-relaxed text-muted">{children}</div>
      )}
    </div>
  );
}

/** Badge compacto para tarjetas de conectores futuros. */
export function ComingSoonBadge() {
  return <span className="badge badge-pending">Próximamente</span>;
}