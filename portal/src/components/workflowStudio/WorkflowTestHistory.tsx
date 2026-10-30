import { StatusBadge } from "../ui";
import type { WorkflowRun } from "./types";

export function WorkflowTestHistory({
  runs,
  open,
  activeRunId,
  onToggle,
  onOpen,
}: {
  runs: WorkflowRun[];
  open: boolean;
  activeRunId?: string;
  onToggle: (open: boolean) => void;
  onOpen: (runId: string) => void;
}) {
  return (
    <details
      className="rounded-md border border-border bg-raised/40 px-3 py-2"
      open={open}
      onToggle={(event) => onToggle((event.currentTarget as HTMLDetailsElement).open)}
      data-testid="wf-test-history"
    >
      <summary className="cursor-pointer text-[12px] font-medium text-muted select-none">
        Historial ({runs.length})
      </summary>
      {runs.length === 0 ? (
        <p className="mt-2 text-[11.5px] text-muted">Todavía no hay corridas registradas.</p>
      ) : (
        <ul className="mt-1.5 space-y-1">
          {runs.slice(0, 12).map((run) => (
            <li key={run.id}>
              <button
                type="button"
                className={`flex w-full items-center gap-2 rounded-sm px-1.5 py-1.5 text-left text-[11px] transition-colors duration-150 hover:bg-soft ${
                  activeRunId === run.id ? "bg-soft" : ""
                }`}
                onClick={() => onOpen(run.id)}
                data-testid="wf-history-run"
              >
                <StatusBadge status={run.status} hideIcon className="shrink-0" />
                <span className="min-w-0 flex-1 truncate text-text">
                  {run.simulate === false ? "Ejecución real" : run.simulate === true ? "Simulación" : "Run"}
                  {" · "}
                  {new Date(run.started_at).toLocaleString()}
                </span>
                <span className="shrink-0 text-faint tabular-nums">
                  {run.duration_ms != null ? `${run.duration_ms} ms` : "—"}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-1.5 text-[10.5px] leading-relaxed text-faint">
        Abrir una corrida antigua no cambia el workflow. Si el grafo actual es distinto, el resultado
        se marca como histórico.
      </p>
    </details>
  );
}
