import { CaretDown, CaretRight, WarningCircle } from "@phosphor-icons/react";
import { fmtDateTime } from "../../lib/format";
import { humanizeActivityTitle, type ActivityPayload } from "./assistantCopy";

export function AssistantActivity({
  activity,
  openTech,
  onToggleTech,
}: {
  activity: ActivityPayload | null;
  openTech: number | null;
  onToggleTech: (index: number | null) => void;
}) {
  return (
    <section className="panel space-y-2 p-4" data-testid="assistant-activity">
      <h2 className="text-sm font-semibold text-text">Actividad reciente</h2>
      {(activity?.items.length ?? 0) === 0 && (
        <p className="text-xs text-muted">
          Sin actividad todavía. Cuando una automatización se active, verás aquí qué pasó.
        </p>
      )}
      <ul className="space-y-2">
        {activity?.items.map((item, index) => (
          <li key={`${item.at}-${index}`} className="rounded-md border border-border/60 bg-soft/40 p-2.5">
            <div className="flex flex-wrap items-baseline gap-2">
              <span className="text-[10px] text-faint">{fmtDateTime(item.at)}</span>
              {item.status === "failed" && <WarningCircle size={12} className="text-danger" aria-hidden />}
              <span className="text-[11px] font-medium text-text">{humanizeActivityTitle(item.title)}</span>
            </div>
            {item.detail && <p className="mt-0.5 text-[11px] text-muted">{item.detail}</p>}
            <button
              type="button"
              className="btn btn-ghost mt-1 min-h-5 gap-1 px-1 text-[9px] text-faint"
              data-testid={`assistant-tech-${index}`}
              onClick={() => onToggleTech(openTech === index ? null : index)}
            >
              {openTech === index ? <CaretDown size={10} /> : <CaretRight size={10} />} Ver detalles técnicos
            </button>
            {openTech === index && (
              <dl className="mt-1 grid grid-cols-2 gap-x-3 gap-y-0.5 rounded border border-border bg-surface p-2 font-mono text-[9px] text-muted">
                {Object.entries(item.tech).map(([key, value]) => (
                  <div key={key} className="contents">
                    <dt className="text-faint">{key}</dt>
                    <dd className="truncate">{String(value ?? "—")}</dd>
                  </div>
                ))}
              </dl>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
