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

function Tip({ s }: { s: RunStep }) {
  const [open, setOpen] = useState(false);
  const label = (s.node_id || s.node_type || s.step_type) as string;
  return (
    <div className={`rounded-md border px-2 py-1.5 text-[10px] ${s.status === "failed" ? "border-danger/40" : "border-border"}`}>
      <button type="button" className="flex w-full items-center gap-2 text-left" onClick={() => setOpen((v) => !v)}>
        <span className={`badge ${STATUS_BADGE[s.status] ?? "badge-muted"}`}>{s.status}</span>
        <span className="min-w-0 flex-1 truncate font-mono text-text">{label}</span>
        <span className="text-faint">
          {s.duration_ms != null && `${s.duration_ms}ms`}
          {s.retries != null && s.retries > 0 && ` · ${s.retries} reintentos`}
        </span>
        {open ? <CaretUp size={11} /> : <CaretDown size={11} />}
      </button>
      {open && (
        <div className="mt-1 space-y-1 border-t border-border pt-1 font-mono text-[9px] text-muted">
          {s.error && <p className="text-danger">error: {s.error}</p>}
          <p className="text-faint">input: {JSON.stringify(s.input ?? {})}</p>
          <p>output: {JSON.stringify(s.output ?? {})}</p>
          {s.idempotency_key && <p className="text-faint">idem: {s.idempotency_key}</p>}
        </div>
      )}
    </div>
  );
}

const STATUS_BADGE: Record<string, string> = {
  succeeded: "badge-ok",
  simulated: "badge-info",
  skipped: "badge-muted",
  failed: "badge-danger",
  denied: "badge-danger",
  pending: "badge-warning",
  pending_approval: "badge-warning",
  running: "badge-warning",
  approved: "badge-ok",
};

export function WorkflowRunInspector({
  run,
  plannedEffects,
  onClose,
  onHoverNode,
}: {
  run: RunDetail | null;
  plannedEffects?: { node_id: string; node_type: string; planned: Record<string, unknown> }[];
  onClose: () => void;
  onHoverNode?: (id: string | null) => void;
}) {
  if (!run) return null;
  const steps = run.steps ?? [];
  return (
    <div className="fixed right-8 bottom-24 z-40 w-[min(560px,90vw)] rounded-md border border-border bg-raised shadow-pop" data-testid="wf-run-inspector">
      <div className="flex items-center gap-2 border-b border-border px-3 py-2">
        <span className={`badge ${STATUS_BADGE[run.status] ?? "badge-muted"}`}>{run.status}</span>
        <span className="min-w-0 flex-1 truncate font-mono text-[10px] text-faint">{run.id}</span>
        {run.duration_ms != null && <span className="text-[10px] text-faint">{run.duration_ms}ms</span>}
        {run.correlation_id && <span className="hidden truncate text-[9px] text-faint sm:block">{run.correlation_id}</span>}
        <button type="button" className="btn btn-ghost min-h-6 px-1.5 text-[10px]" onClick={onClose}>cerrar</button>
      </div>
      {run.error && <p className="border-b border-danger/30 bg-danger-soft px-3 py-1 text-[10px] text-danger">run error: {run.error}</p>}
      {plannedEffects && plannedEffects.length > 0 && (
        <div className="border-b border-info/30 bg-info/5 px-3 py-2">
          <p className="text-[10px] font-semibold text-info">Dry-run — efectos planeados (no ejecutados)</p>
          <ul className="mt-1 space-y-0.5">
            {plannedEffects.map((p) => (
              <li key={p.node_id} className="flex items-start gap-1 text-[9px] text-muted">
                <span className="font-mono">{p.node_type}</span>
                <span className="truncate font-mono text-faint">= {JSON.stringify(p.planned).slice(0, 140)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      <div className="max-h-64 space-y-1 overflow-y-auto p-2">
        {steps.map((s) => (
          <div key={`${s.node_id ?? s.step_index}`} onMouseEnter={() => onHoverNode?.(s.node_id ?? null)} onMouseLeave={() => onHoverNode?.(null)}>
            <Tip s={s} />
          </div>
        ))}
        {steps.length === 0 && <p className="p-2 text-[10px] text-faint">Sin pasos registrados.</p>}
      </div>
    </div>
  );
}