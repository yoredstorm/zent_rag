/**
 * InstanceTimeline — timeline de una WorkflowInstance durable (INSTANCE /
 * RUN / SIGNAL / WAIT / RESUME) + visor del estado de negocio.
 *
 * Solo lectura: consume `/api/v1/workflows/instances/{id}/timeline`. El estado
 * durable se muestra tal cual (nunca contiene secretos por diseño).
 */
import { CaretDown, CaretRight } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { Button } from "../ui";

export type InstanceRun = {
  run_id: string;
  status: string;
  trigger: string;
  instance_seq?: number | null;
  started_at?: string | null;
  completed_at?: string | null;
  error?: string | null;
};

export type InstanceSignal = {
  signal_id: string;
  event_type: string;
  external_event_id?: string | null;
  correlation_key?: string | null;
  status: string;
  source?: string;
  received_at?: string | null;
};

export type InstanceEvent = {
  id?: string;
  run_id?: string;
  kind: string;
  node_id?: string | null;
  payload?: Record<string, unknown>;
  created_at?: string | null;
};

export type InstanceSnapshot = {
  id: string;
  status: string;
  status_reason?: string | null;
  workflow_id?: string;
  current_node_id?: string | null;
  waiting_event_type?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  state?: Record<string, unknown>;
};

export type InstanceTimelineData = {
  instance: InstanceSnapshot;
  runs: InstanceRun[];
  signals: InstanceSignal[];
  events: InstanceEvent[];
};

const STATUS_TONE: Record<string, string> = {
  NEW: "text-muted",
  RUNNING: "text-accent",
  WAITING: "text-warn",
  SUSPENDED: "text-muted",
  COMPLETED: "text-ok",
  FAILED: "text-danger",
  CANCELLED: "text-muted",
  EXPIRED: "text-warn",
};

type TimelineItem = {
  key: string;
  at: string;
  label: string;
  detail?: string;
  tone: string;
};

function buildTimeline(data: InstanceTimelineData): TimelineItem[] {
  const items: TimelineItem[] = [];
  for (const run of data.runs ?? []) {
    items.push({
      key: `run-${run.run_id}`,
      at: run.started_at ?? "",
      label: `Run ${run.instance_seq ?? "?"} · ${run.trigger}`,
      detail: run.status,
      tone: run.status === "failed" ? "text-danger" : run.status === "waiting" ? "text-warn" : "text-muted",
    });
  }
  for (const signal of data.signals ?? []) {
    items.push({
      key: `sig-${signal.signal_id}`,
      at: signal.received_at ?? "",
      label: `Señal · ${signal.event_type}`,
      detail: [signal.status, signal.external_event_id].filter(Boolean).join(" · "),
      tone: signal.status === "consumed" ? "text-ok" : "text-muted",
    });
  }
  for (const event of data.events ?? []) {
    items.push({
      key: `evt-${event.id ?? `${event.kind}-${event.created_at}`}`,
      at: event.created_at ?? "",
      label: `${event.kind}${event.node_id ? ` · ${event.node_id}` : ""}`,
      tone: "text-faint",
    });
  }
  return items.sort((a, b) => (a.at < b.at ? -1 : a.at > b.at ? 1 : 0));
}

function fmtTime(value?: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function InstanceTimeline({ instanceId }: { instanceId: string }) {
  const { session } = useAuth();
  const [data, setData] = useState<InstanceTimelineData | null>(null);
  const [showState, setShowState] = useState(false);

  useEffect(() => {
    if (!session || !instanceId) return;
    let alive = true;
    api<InstanceTimelineData>(`/api/v1/workflows/instances/${instanceId}/timeline`, {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then((out) => {
        if (alive) setData(out);
      })
      .catch(() => null);
    return () => {
      alive = false;
    };
  }, [session, instanceId]);

  if (!data?.instance) return null;
  const instance = data.instance;
  const statusTone = STATUS_TONE[instance.status] ?? "text-muted";
  const items = buildTimeline(data);

  return (
    <div
      className="rounded-md border border-border bg-raised/50 px-3 py-2.5"
      data-testid="wf-instance-timeline"
    >
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <p className="eyebrow shrink-0">Proceso</p>
        <span
          className={`text-[11px] font-medium ${statusTone}`}
          data-testid="wf-instance-status"
        >
          {instance.status}
        </span>
        {instance.waiting_event_type && (
          <span className="truncate text-[11px] text-faint">
            espera {instance.waiting_event_type}
          </span>
        )}
        {instance.status_reason && (
          <span className="truncate text-[11px] text-faint">{instance.status_reason}</span>
        )}
        <span className="min-w-0 flex-1" />
        <Button
          variant="ghost"
          size="sm"
          leadingIcon={showState ? CaretDown : CaretRight}
          className="text-[11px]"
          data-testid="wf-instance-state-toggle"
          aria-expanded={showState}
          onClick={() => setShowState((v) => !v)}
        >
          Estado del proceso
        </Button>
      </div>

      <ol className="mt-2 flex flex-col gap-1" data-testid="wf-instance-timeline-items">
        {items.map((item) => (
          <li key={item.key} className="flex items-baseline gap-2 text-[11px] leading-relaxed">
            <span className="mono shrink-0 text-[10px] text-ghost tabular-nums">
              {fmtTime(item.at)}
            </span>
            <span className={`min-w-0 truncate ${item.tone}`}>{item.label}</span>
            {item.detail && <span className="shrink-0 text-faint">{item.detail}</span>}
          </li>
        ))}
      </ol>

      {showState && (
        <pre
          className="mt-2 max-h-64 overflow-auto rounded-sm border border-border-soft bg-surface p-2 text-[10px] leading-relaxed text-muted"
          data-testid="wf-instance-state"
        >
          {JSON.stringify(instance.state ?? {}, null, 2)}
        </pre>
      )}
    </div>
  );
}
