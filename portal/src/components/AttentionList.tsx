import { Heartbeat, WarningCircle } from "@phosphor-icons/react";
import { Link } from "react-router-dom";

export type AttentionItem = { id: string; label: string; to: string };

/**
 * Bloque "Necesita atención" reutilizable (FASE 12).
 * Muestra problemas reales con CTA directo al recurso.
 */
export function AttentionList({
  items,
  emptyTitle = "Todo en orden",
  emptyBody = "No se detectaron problemas.",
  title = "Necesita atención",
}: {
  items: AttentionItem[];
  emptyTitle?: string;
  emptyBody?: string;
  title?: string;
}) {
  return (
    <div className="panel">
      <div className="flex items-center justify-between border-b border-border px-5 py-4">
        <h2 className="text-sm font-semibold text-text">{title}</h2>
        <span className="mono text-[11px] text-faint">eventos reales</span>
      </div>
      {items.length === 0 ? (
        <div className="flex flex-col items-center gap-2 px-6 py-10 text-center">
          <span className="flex h-11 w-11 items-center justify-center rounded-md border border-border bg-soft text-ok">
            <Heartbeat size={22} aria-hidden />
          </span>
          <p className="mt-1 text-sm font-medium text-text">{emptyTitle}</p>
          <p className="max-w-sm text-[13px] leading-relaxed text-muted">{emptyBody}</p>
        </div>
      ) : (
        <ul className="divide-y divide-border/60 px-2">
          {items.map((item) => (
            <li key={item.id} className="flex items-center justify-between gap-3 px-3 py-3">
              <span className="flex items-center gap-2 text-[13px] text-text">
                <WarningCircle size={15} className="shrink-0 text-warn" aria-hidden />
                {item.label}
              </span>
              <Link to={item.to} className="shrink-0 text-xs text-accent hover:underline">
                Revisar
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}