import { CaretDown, CaretUp } from "@phosphor-icons/react";
import { useState } from "react";
import { DataView } from "./workflowStudio/DataView";

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

/** Contribución de contexto persistida por un nodo (Fase 8). */
export type RunContribution = {
  id?: string;
  node_id?: string | null;
  node_type?: string | null;
  section: string;
  value_type?: string;
  label?: string | null;
  payload?: Record<string, unknown>;
  provenance?: Record<string, unknown>;
  created_at?: string | null;
};

/** Acción con efecto observada en el run (notify/api/marketplace/...). */
export type RunAction = {
  node_id?: string | null;
  node_type?: string | null;
  status: string;
  simulated?: boolean;
  summary?: Record<string, unknown>;
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
  /** Contexto proyectado del run (sin `security`). */
  context?: Record<string, unknown>;
  contributions?: RunContribution[];
  evidence_refs?: RunContribution[];
  claim_refs?: RunContribution[];
  decisions?: RunContribution[];
  findings?: RunContribution[];
  artifacts?: RunContribution[];
  actions?: RunAction[];
  chain_of_thought_exposed?: boolean;
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
        <div className="space-y-2 border-t border-border px-2 py-2">
          <div>
            <p className="mb-1 text-[9px] font-semibold tracking-wide text-faint uppercase">Entrada</p>
            <DataView data={s.input} testId={`wf-step-input-${s.node_id ?? s.step_index}`} emptyHint="Sin entrada registrada." />
          </div>
          <div>
            <p className="mb-1 text-[9px] font-semibold tracking-wide text-faint uppercase">Salida</p>
            <DataView data={s.output} testId={`wf-step-output-${s.node_id ?? s.step_index}`} emptyHint="Sin salida registrada." />
          </div>
          {s.idempotency_key && <p className="font-mono text-[9px] text-faint">idem: {s.idempotency_key}</p>}
        </div>
      )}
    </div>
  );
}

function ContextSection({
  title,
  testId,
  entries,
  emptyHint,
}: {
  title: string;
  testId: string;
  entries: RunContribution[];
  emptyHint: string;
}) {
  if (entries.length === 0) return null;
  return (
    <details className="rounded-md border border-border bg-soft px-2 py-1.5" data-testid={testId}>
      <summary className="cursor-pointer text-[10px] font-semibold text-muted">
        {title} ({entries.length})
      </summary>
      <div className="mt-1.5 space-y-1.5">
        {entries.slice(0, 10).map((entry, index) => (
          <div key={entry.id ?? `${entry.section}-${index}`} className="rounded border border-border bg-bg px-2 py-1">
            <p className="truncate text-[10px] text-text">
              {entry.label || entry.section}
              {entry.provenance?.node_type ? (
                <span className="text-faint"> · {String(entry.provenance.node_type)}</span>
              ) : null}
            </p>
            <DataView
              data={entry.payload?.value ?? entry.payload}
              testId={`${testId}-${index}`}
              emptyHint={emptyHint}
            />
          </div>
        ))}
      </div>
    </details>
  );
}

function ActionsSection({ actions }: { actions: RunAction[] }) {
  if (actions.length === 0) return null;
  return (
    <details className="rounded-md border border-border bg-soft px-2 py-1.5" data-testid="wf-run-actions">
      <summary className="cursor-pointer text-[10px] font-semibold text-muted">
        Acciones del run ({actions.length})
      </summary>
      <div className="mt-1.5 space-y-1">
        {actions.map((action, index) => (
          <div
            key={action.node_id ?? index}
            className="flex items-center gap-2 rounded border border-border bg-bg px-2 py-1"
          >
            <span className={`badge shrink-0 ${STATUS_BADGE[action.status] ?? "badge-muted"}`}>
              {action.status}
            </span>
            <span className="min-w-0 flex-1 truncate text-[10px] text-text">
              {action.node_type ?? action.node_id ?? "acción"}
            </span>
            <span className="max-w-[45%] shrink-0 truncate text-[9px] text-faint">
              {JSON.stringify(action.summary ?? {})}
            </span>
          </div>
        ))}
      </div>
    </details>
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
      <ContextSection
        title="Datos y conocimiento"
        testId="wf-run-context"
        entries={(run.contributions ?? []).filter((c) => c.section === "data" || c.section === "knowledge")}
        emptyHint="Sin datos registrados."
      />
      <ContextSection
        title="Evidencia y claims"
        testId="wf-run-evidence"
        entries={[...(run.evidence_refs ?? []), ...(run.claim_refs ?? [])]}
        emptyHint="Sin evidencia."
      />
      <ContextSection
        title="Decisiones y hallazgos"
        testId="wf-run-decisions"
        entries={[...(run.decisions ?? []), ...(run.findings ?? [])]}
        emptyHint="Sin decisiones."
      />
      <ContextSection
        title="Artefactos"
        testId="wf-run-artifacts"
        entries={run.artifacts ?? []}
        emptyHint="Sin artefactos."
      />
      <ActionsSection actions={run.actions ?? []} />
    </div>
  );
}
