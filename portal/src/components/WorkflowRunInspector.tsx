import { CaretDown, CaretUp } from "@phosphor-icons/react";
import { useState } from "react";

export type RunStep = {
  step_index: number;
  step_type: string;
  node_id?: string | null;
  node_type?: string | null;
  status: string;
  output?: Record<string, unknown>;
  error?: string | null;
  retries?: number;
  duration_ms?: number | null;
  input?: Record<string, unknown>;
  idempotency_key?: string | null;
  attempt?: number;
};

export type RunDetail = {
  id: string;
  status: string;
  error?: string | null;
  duration_ms?: number | null;
  correlation_id?: string | null;
  steps?: RunStep[];
  planned_effects?: { node_id: string; node_type: string; planned: Record<string, unknown> }[];
  result?: { notifications?: unknown[]; errors?: unknown[]; cost_ms?: number };
};

const STATUS_BADGE: Record<string, string> = {
  succeeded: "badge-ok",
  simulated: "badge-muted",
  skipped: "badge-muted",
  failed: "badge-danger",
  denied: "badge-danger",
  pending: "badge-pending",
  pending_approval: "badge-pending",
  running: "badge-pending",
  approved: "badge-ok",
};

function Step({ s, onSelectNode }: { s: RunStep; onSelectNode?: (id: string) => void }) {
  const [open, setOpen] = useState(false);
  const label = (s.node_type || s.step_type || s.node_id) as string;
  const text = typeof (s.output ?? {})?.text === "string" ? String((s.output ?? {}).text) : "";
  return (
    <div className={`rounded-md border ${s.status === "failed" || s.status === "denied" ? "border-danger/40" : "border-border"}`}>
      <div className="flex items-center gap-2 px-2 py-1.5">
        <span className={`badge shrink-0 ${STATUS_BADGE[s.status] ?? "badge-muted"}`}>{s.status}</span>
        <button
          type="button"
          className="min-w-0 flex-1 truncate text-left text-[11px] text-text hover:text-accent"
          title={s.node_id ? `Ver ${label} en el lienzo` : label}
          data-testid="wf-step-jump"
          onClick={() => s.node_id && onSelectNode?.(s.node_id)}
        >
          {label}
        </button>
        <span className="shrink-0 text-[10px] text-faint">
          {s.duration_ms != null && `${s.duration_ms}ms`}
          {s.retries != null && s.retries > 0 && ` · ${s.retries} reintentos`}
        </span>
        <button
          type="button"
          className="btn btn-ghost min-h-6 shrink-0 px-1"
          aria-label={open ? "Ocultar detalle" : "Ver detalle"}
          onClick={() => setOpen((v) => !v)}
        >
          {open ? <CaretUp size={11} /> : <CaretDown size={11} />}
        </button>
      </div>
      {s.error && <p className="border-t border-danger/30 px-2 py-1 text-[10px] text-danger">{s.error}</p>}
      {!s.error && text && !open && (
        <p className="border-t border-border px-2 py-1 text-[10px] text-muted line-clamp-2">{text}</p>
      )}
      {open && (
        <div className="space-y-1 border-t border-border px-2 py-1 font-mono text-[9px] text-muted">
          <p className="text-faint">input: {JSON.stringify(s.input ?? {})}</p>
          <p className="break-all">output: {JSON.stringify(s.output ?? {})}</p>
          {s.idempotency_key && <p className="text-faint">idem: {s.idempotency_key}</p>}
        </div>
      )}
    </div>
  );
}

/** Lista de pasos del run: inline en el dock, cada paso salta al nodo. */
export function WorkflowRunInspector({
  run,
  plannedEffects,
  onSelectNode,
}: {
  run: RunDetail | null;
  plannedEffects?: { node_id: string; node_type: string; planned: Record<string, unknown> }[];
  onSelectNode?: (id: string) => void;
}) {
  if (!run) return null;
  const steps = run.steps ?? [];
  return (
    <div className="space-y-1.5" data-testid="wf-run-inspector">
      <div className="flex items-center gap-2">
        <span className={`badge ${STATUS_BADGE[run.status] ?? "badge-muted"}`}>{run.status}</span>
        <span className="min-w-0 flex-1 truncate font-mono text-[10px] text-faint">{run.id}</span>
        {run.duration_ms != null && <span className="text-[10px] text-faint">{run.duration_ms}ms</span>}
      </div>
      {run.error && (
        <p className="rounded-md border border-danger/30 bg-danger-soft px-2 py-1 text-[10px] text-danger">
          {run.error}
        </p>
      )}
      {plannedEffects && plannedEffects.length > 0 && (
        <div className="rounded-md border border-border bg-soft px-2 py-1.5">
          <p className="text-[10px] font-semibold text-muted">Efectos no ejecutados en la prueba</p>
          <ul className="mt-1 space-y-0.5">
            {plannedEffects.map((p) => (
              <li key={p.node_id} className="truncate text-[10px] text-faint">
                {p.node_type} — {JSON.stringify(p.planned).slice(0, 90)}
              </li>
            ))}
          </ul>
        </div>
      )}
      {steps.map((s) => (
        <Step key={`${s.node_id ?? s.step_index}`} s={s} onSelectNode={onSelectNode} />
      ))}
      {steps.length === 0 && <p className="text-[10px] text-faint">Sin pasos registrados.</p>}
    </div>
  );
}
