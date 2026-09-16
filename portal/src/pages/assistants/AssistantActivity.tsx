import { CaretDown, CaretRight, ClockCountdown } from "@phosphor-icons/react";
import { fmtDateTime } from "../../lib/format";
import { EmptyState, Panel, PanelHeader, StatusBadge } from "../../components/ui";
import { humanizeActivityTitle, type ActivityPayload } from "./assistantCopy";

/** Estado real del item para el activity rail. */
function railState(status: string): "running" | "ready" | "failed" | "queued" {
  if (status === "running") return "running";
  if (status === "succeeded" || status === "success" || status === "completed") return "ready";
  if (status === "failed" || status === "error") return "failed";
  return "queued";
}

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
    <Panel data-testid="assistant-activity">
      <PanelHeader
        title="Actividad reciente"
        description="Cada ejecución de sus automatizaciones, con el detalle técnico bajo demanda."
        actions={
          activity ? (
            <span className="text-xs text-faint tabular-nums">
              {activity.run_count} ejecuciones · {activity.automation_count} automatizaciones
            </span>
          ) : undefined
        }
      />
      {(activity?.items.length ?? 0) === 0 ? (
        <EmptyState
          icon={ClockCountdown}
          title="Sin actividad todavía"
          body="Cuando una automatización se active, verás aquí qué pasó."
          compact
        />
      ) : (
        <ul className="grid gap-2 p-4">
          {activity?.items.map((item, index) => (
            <li
              key={`${item.at}-${index}`}
              data-state={railState(item.status)}
              className="state-rail rounded-md border border-border-soft bg-raised py-2.5 pr-3 pl-4"
            >
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <StatusBadge status={item.status} />
                <span className="text-[10px] text-faint tabular-nums">{fmtDateTime(item.at)}</span>
                <span className="text-[13px] font-medium text-text">
                  {humanizeActivityTitle(item.title)}
                </span>
              </div>
              {item.detail && (
                <p className="mt-1 text-xs leading-relaxed text-muted">{item.detail}</p>
              )}
              <button
                type="button"
                className="mt-1.5 inline-flex items-center gap-1 text-[11px] font-medium text-faint transition-colors duration-150 hover:text-muted"
                data-testid={`assistant-tech-${index}`}
                aria-expanded={openTech === index}
                onClick={() => onToggleTech(openTech === index ? null : index)}
              >
                {openTech === index ? <CaretDown size={11} aria-hidden /> : <CaretRight size={11} aria-hidden />}
                Ver detalles técnicos
              </button>
              {openTech === index && (
                <dl className="mt-2 grid grid-cols-1 gap-x-4 gap-y-1 rounded-sm border border-border bg-surface p-3 sm:grid-cols-2">
                  {Object.entries(item.tech).map(([key, value]) => (
                    <div key={key} className="flex items-baseline justify-between gap-3">
                      <dt className="text-[11px] text-faint">{key}</dt>
                      <dd className="mono truncate text-[11px] text-muted">{String(value ?? "—")}</dd>
                    </div>
                  ))}
                </dl>
              )}
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
