import { CaretRight, Crosshair, WarningCircle } from "@phosphor-icons/react";
import { useState, type ReactNode } from "react";
import { fmtLatency } from "../lib/format";
import { Button, Drawer, ErrorInline, IconButton, StatusBadge } from "./ui";
import { WorkflowApprovalPanel } from "./WorkflowApprovalPanel";
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

/** Evento append-only del timeline del run (D6). */
export type RunEvent = {
  id?: string;
  kind: string;
  node_id?: string | null;
  payload?: Record<string, unknown>;
  created_at?: string | null;
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
  events?: RunEvent[];
  /** Narrativa de negocio del run (Fase 8; sin chain of thought). */
  story?: string[];
  chain_of_thought_exposed?: boolean;
};

type RailState = "queued" | "running" | "ready" | "warning" | "failed";

/**
 * Estados del run/paso → vocabulario de StatusBadge (tono + icono).
 * `denied` y `simulated` no existen en el vocabulario central: se traducen acá.
 */
const RUN_STATUS_META: Record<string, { status: string; label?: string }> = {
  succeeded: { status: "succeeded" },
  failed: { status: "failed" },
  denied: { status: "failed", label: "Denegado" },
  skipped: { status: "skipped" },
  pending: { status: "pending" },
  running: { status: "running" },
  simulated: { status: "succeeded", label: "Simulado" },
  pending_approval: { status: "pending_approval" },
  approved: { status: "approved" },
};

/** Estado real del paso → rail de actividad. */
function stepRail(status: string): RailState {
  if (status === "failed" || status === "denied") return "failed";
  if (status === "running") return "running";
  if (status === "succeeded" || status === "approved") return "ready";
  return "queued";
}

function stepLabel(step: RunStep): string {
  return step.node_type || step.step_type || step.node_id || `paso ${step.step_index + 1}`;
}

function StepStatusBadge({ status }: { status: string }) {
  const meta = RUN_STATUS_META[status] ?? { status };
  return <StatusBadge status={meta.status} label={meta.label} className="shrink-0" />;
}

function StepRow({
  step,
  onSelectNode,
  onInspect,
}: {
  step: RunStep;
  onSelectNode?: (id: string) => void;
  onInspect: (step: RunStep) => void;
}) {
  const label = stepLabel(step);
  const text = typeof step.output?.text === "string" ? String(step.output.text) : "";
  return (
    <li data-state={stepRail(step.status)} className="state-rail py-2.5">
      <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
        <StepStatusBadge status={step.status} />
        {step.node_id ? (
          <button
            type="button"
            className="min-w-0 flex-1 truncate rounded-xs text-left text-[12px] font-medium text-text transition-colors duration-150 hover:text-accent"
            title={`Ver ${label} en el lienzo`}
            data-testid="wf-step-jump"
            onClick={() => onSelectNode?.(step.node_id as string)}
          >
            {label}
          </button>
        ) : (
          <span className="min-w-0 flex-1 truncate text-[12px] font-medium text-text">{label}</span>
        )}
        <span className="ml-auto shrink-0 text-[11px] text-faint tabular-nums">
          {step.duration_ms != null ? fmtLatency(step.duration_ms) : ""}
          {step.retries ? ` · ${step.retries} reintentos` : ""}
        </span>
        <IconButton
          label={`Ver detalle del paso ${label}`}
          icon={CaretRight}
          iconSize={13}
          className="h-7 w-7 min-h-0"
          onClick={() => onInspect(step)}
        />
      </div>
      {step.error && (
        <p className="mt-1.5 flex items-start gap-2 rounded-md border border-danger/25 bg-danger-soft px-2.5 py-2 text-[11px] leading-relaxed text-danger">
          <WarningCircle size={13} className="mt-px shrink-0" aria-hidden />
          <span>{step.error}</span>
        </p>
      )}
      {!step.error && text && (
        <p className="mt-1 line-clamp-2 text-[11px] leading-relaxed text-muted">{text}</p>
      )}
    </li>
  );
}

function Disclosure({
  title,
  testId,
  count,
  children,
}: {
  title: string;
  testId: string;
  count: number;
  children: ReactNode;
}) {
  return (
    <details className="group rounded-md border border-border bg-raised/50" data-testid={testId}>
      <summary className="flex cursor-pointer items-center gap-2 rounded-md px-3 py-2 text-[11px] font-medium text-muted transition-colors duration-150 select-none hover:bg-soft/60 [&::-webkit-details-marker]:hidden">
        <CaretRight
          size={11}
          className="shrink-0 text-ghost transition-transform duration-200 group-open:rotate-90"
          aria-hidden
        />
        {title} ({count})
      </summary>
      <div className="border-t border-border-soft px-3 py-2.5">{children}</div>
    </details>
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
    <Disclosure title={title} testId={testId} count={entries.length}>
      <div className="flex flex-col gap-2">
        {entries.slice(0, 10).map((entry, index) => (
          <div
            key={entry.id ?? `${entry.section}-${index}`}
            className="rounded-md border border-border bg-surface px-2.5 py-2"
          >
            <p className="truncate text-[11px] text-text">
              {entry.label || entry.section}
              {entry.provenance?.node_type ? (
                <span className="text-faint"> · {String(entry.provenance.node_type)}</span>
              ) : null}
            </p>
            <div className="mt-1.5">
              <DataView
                data={entry.payload?.value ?? entry.payload}
                testId={`${testId}-${index}`}
                emptyHint={emptyHint}
              />
            </div>
          </div>
        ))}
      </div>
    </Disclosure>
  );
}

function ActionsSection({ actions }: { actions: RunAction[] }) {
  if (actions.length === 0) return null;
  return (
    <Disclosure title="Acciones del run" testId="wf-run-actions" count={actions.length}>
      <ul className="flex flex-col gap-1.5">
        {actions.map((action, index) => (
          <li
            key={action.node_id ?? index}
            className="flex items-center gap-2 rounded-md border border-border bg-surface px-2.5 py-1.5"
          >
            <StepStatusBadge status={action.status} />
            <span className="min-w-0 flex-1 truncate text-[11px] text-text">
              {action.node_type ?? action.node_id ?? "acción"}
            </span>
            <span
              className="max-w-[45%] shrink-0 truncate font-mono text-[10px] text-faint"
              title={JSON.stringify(action.summary ?? {})}
            >
              {JSON.stringify(action.summary ?? {})}
            </span>
          </li>
        ))}
      </ul>
    </Disclosure>
  );
}

function EventsSection({ events }: { events: RunEvent[] }) {
  if (events.length === 0) return null;
  return (
    <Disclosure title="Timeline del run" testId="wf-run-events" count={events.length}>
      <ol className="flex flex-col gap-1">
        {events.slice(0, 50).map((event, index) => (
          <li key={event.id ?? index} className="flex items-center gap-2 text-[11px] text-muted">
            <span className="shrink-0 font-mono text-[10px] text-faint">{event.kind}</span>
            {event.node_id ? <span className="shrink-0 truncate text-text">{event.node_id}</span> : null}
            <span
              className="min-w-0 flex-1 truncate font-mono text-[10px] text-ghost"
              title={JSON.stringify(event.payload ?? {})}
            >
              {JSON.stringify(event.payload ?? {})}
            </span>
          </li>
        ))}
      </ol>
    </Disclosure>
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
  const [detail, setDetail] = useState<RunStep | null>(null);
  if (!run) return null;
  const steps = run.steps ?? [];
  const status = RUN_STATUS_META[run.status] ?? { status: run.status };
  const failed = steps.filter((s) => s.status === "failed" || s.status === "denied").length;

  return (
    <div className="flex flex-col gap-2.5" data-testid="wf-run-inspector">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <StatusBadge status={status.status} label={status.label} />
        <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-faint" title={run.id}>
          {run.id}
        </span>
        {run.duration_ms != null && (
          <span className="shrink-0 text-[11px] text-faint tabular-nums">
            {fmtLatency(run.duration_ms)}
          </span>
        )}
      </div>
      {run.correlation_id && (
        <p className="truncate font-mono text-[10px] text-ghost" title={run.correlation_id}>
          corr {run.correlation_id}
        </p>
      )}

      <ErrorInline message={run.error} className="mb-0" />

      {run.status === "pending_approval" && <WorkflowApprovalPanel runId={run.id} />}

      {(run.story ?? []).length > 0 && (
        <ol
          className="flex flex-col gap-1 rounded-md border border-border bg-raised/50 px-3 py-2.5"
          data-testid="wf-run-story"
        >
          {(run.story ?? []).map((line, index) => (
            <li key={index} className="flex gap-2 text-[11px] leading-relaxed text-muted">
              <span className="mono shrink-0 text-[10px] text-ghost">{index + 1}</span>
              <span className="min-w-0">{line}</span>
            </li>
          ))}
        </ol>
      )}

      {plannedEffects && plannedEffects.length > 0 && (
        <div className="rounded-md border border-border bg-raised/50 px-3 py-2.5">
          <p className="text-[11px] font-medium text-muted">Efectos no ejecutados en la prueba</p>
          <ul className="mt-1.5 flex flex-col gap-1">
            {plannedEffects.map((p) => (
              <li key={p.node_id} className="truncate text-[11px] text-faint" title={`${p.node_type} — ${JSON.stringify(p.planned)}`}>
                <span className="text-muted">{p.node_type}</span> — {JSON.stringify(p.planned)}
              </li>
            ))}
          </ul>
        </div>
      )}

      {steps.length === 0 ? (
        <p className="text-[11px] text-faint">Sin pasos registrados.</p>
      ) : (
        <div>
          <div className="mb-1 flex items-center gap-2">
            <p className="eyebrow">Pasos ({steps.length})</p>
            {failed > 0 && (
              <span className="text-[11px] font-medium text-danger">
                {failed === 1 ? "1 paso falló" : `${failed} pasos fallaron`}
              </span>
            )}
          </div>
          <ol className="divide-y divide-border-soft border-y border-border-soft">
            {steps.map((s) => (
              <StepRow
                key={`${s.node_id ?? s.step_index}`}
                step={s}
                onSelectNode={onSelectNode}
                onInspect={setDetail}
              />
            ))}
          </ol>
        </div>
      )}

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
      <EventsSection events={run.events ?? []} />

      <Drawer
        open={detail !== null}
        onOpenChange={(open) => {
          if (!open) setDetail(null);
        }}
        title={detail ? stepLabel(detail) : "Paso"}
        description={
          detail
            ? `Paso ${detail.step_index + 1}${detail.duration_ms != null ? ` · ${fmtLatency(detail.duration_ms)}` : ""}`
            : undefined
        }
        width={520}
        footer={
          detail?.node_id && onSelectNode ? (
            <>
              <Button variant="ghost" onClick={() => setDetail(null)}>
                Cerrar
              </Button>
              <Button
                variant="secondary"
                leadingIcon={Crosshair}
                onClick={() => {
                  onSelectNode(detail.node_id as string);
                  setDetail(null);
                }}
              >
                Ver en el lienzo
              </Button>
            </>
          ) : undefined
        }
      >
        {detail && (
          <div className="flex flex-col gap-4">
            <div className="flex flex-wrap items-center gap-2">
              <StepStatusBadge status={detail.status} />
              {detail.attempt != null && (
                <span className="text-[11px] text-faint tabular-nums">intento {detail.attempt}</span>
              )}
              {detail.retries ? (
                <span className="text-[11px] text-faint tabular-nums">
                  {detail.retries} reintentos
                </span>
              ) : null}
            </div>

            {detail.error && <ErrorInline message={detail.error} className="mb-0" />}

            <section>
              <p className="eyebrow mb-1.5">Entrada</p>
              <DataView
                data={detail.input}
                testId={`wf-step-input-${detail.node_id ?? detail.step_index}`}
                emptyHint="Sin entrada registrada."
              />
            </section>
            <section>
              <p className="eyebrow mb-1.5">Salida</p>
              <DataView
                data={detail.output}
                testId={`wf-step-output-${detail.node_id ?? detail.step_index}`}
                emptyHint="Sin salida registrada."
              />
            </section>
            {detail.idempotency_key && (
              <p className="font-mono text-[10px] break-all text-faint">
                idem: {detail.idempotency_key}
              </p>
            )}
          </div>
        )}
      </Drawer>
    </div>
  );
}
