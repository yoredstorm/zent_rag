import { CheckCircle, WarningCircle } from "@phosphor-icons/react";
import { Link } from "react-router-dom";

export type AttentionItem = { id: string; label: string; to: string };

/**
 * Bloque "Necesita atención" reutilizable (FASE 12).
 * Muestra problemas reales con CTA directo al recurso. Si no hay nada,
 * lo dice explícitamente en vez de dejar el panel vacío.
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
  const hasIssues = items.length > 0;
  return (
    <div className="panel">
      <div className="panel-header">
        <div className="flex items-center gap-2.5">
          <h2 className="text-h3">{title}</h2>
          {hasIssues ? (
            <span className="badge badge-pending">{items.length}</span>
          ) : (
            <span className="badge badge-ok">
              <CheckCircle size={12} weight="fill" aria-hidden />
              Sin pendientes
            </span>
          )}
        </div>
        <span className="mono text-[11px] text-faint">eventos reales</span>
      </div>
      {!hasIssues ? (
        <div className="flex items-start gap-3 px-5 py-5">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-ok/25 bg-ok-soft text-ok">
            <CheckCircle size={18} aria-hidden />
          </span>
          <span className="min-w-0">
            <span className="block text-[13px] font-medium text-text">{emptyTitle}</span>
            <span className="mt-0.5 block text-[12.5px] leading-relaxed text-muted">{emptyBody}</span>
          </span>
        </div>
      ) : (
        <ul className="px-2 pb-2">
          {items.map((item) => (
            <li
              key={item.id}
              className="state-rail flex items-center justify-between gap-3 border-b border-border-soft py-3 pr-3 pl-4 last:border-b-0"
              data-state="warning"
            >
              <span className="flex min-w-0 items-center gap-2 text-[13px] text-text">
                <WarningCircle size={15} weight="regular" className="shrink-0 text-warn" aria-hidden />
                <span className="line-clamp-2 min-w-0" title={item.label}>
                  {item.label}
                </span>
              </span>
              <Link
                to={item.to}
                className="shrink-0 text-[13px] font-medium text-accent hover:underline"
              >
                Revisar
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
