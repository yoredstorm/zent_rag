import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { Button, EmptyState, ErrorInline, Input, PageHeader, Panel, Skeleton } from "../components/ui";

type InstanceRow = {
  id: string;
  status: string;
  view_status?: string;
  workflow_id?: string;
  business_key?: string | null;
  workflow_version?: number;
  waiting_event_type?: string | null;
  started_at?: string | null;
  updated_at?: string | null;
};

type TimelineStep = {
  step: string;
  at?: string | null;
  status?: string | null;
  event_type?: string | null;
  fault?: string | null;
};

type OpsQueue = {
  total: number;
  summary: { failed: number; needs_human: number; expired: number; by_kind: Record<string, number> };
};

const VIEW_FILTERS = [
  "running",
  "waiting",
  "pending_approval",
  "needs_human",
  "retry_scheduled",
  "completed",
  "failed",
  "cancelled",
  "expired",
];

export default function OperationsPage() {
  const { session } = useAuth();
  const [rows, setRows] = useState<InstanceRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [view, setView] = useState("");
  const [keyFilter, setKeyFilter] = useState("");
  const [timeline, setTimeline] = useState<TimelineStep[] | null>(null);
  const [openId, setOpenId] = useState("");
  const [queue, setQueue] = useState<OpsQueue | null>(null);

  const load = useCallback(async () => {
    if (!session) return;
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams();
      if (keyFilter.trim()) params.set("business_key", keyFilter.trim());
      const [data, queueData] = await Promise.all([
        api<{ instances: InstanceRow[] }>(
          `/api/v1/workflows/instances${params.toString() ? `?${params}` : ""}`,
          { token: session.token, organizationId: session.organizationId },
        ),
        api<OpsQueue>("/api/v1/workflows/operations/queue", {
          token: session.token,
          organizationId: session.organizationId,
        }).catch(() => null),
      ]);
      setRows(data.instances || []);
      setQueue(queueData);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No pude leer las instancias");
    } finally {
      setLoading(false);
    }
  }, [session, keyFilter]);

  useEffect(() => {
    void load();
  }, [load]);

  const visible = useMemo(
    () => rows.filter((row) => !view || row.view_status === view),
    [rows, view],
  );

  async function openTimeline(instanceId: string) {
    if (!session) return;
    setOpenId(instanceId);
    setTimeline(null);
    try {
      const data = await api<{ business_timeline: TimelineStep[] }>(
        `/api/v1/workflows/instances/${instanceId}/timeline`,
        { token: session.token, organizationId: session.organizationId },
      );
      setTimeline(data.business_timeline || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No pude leer la línea de tiempo");
    }
  }

  async function cancel(instanceId: string) {
    if (!session) return;
    setError("");
    try {
      await api(`/api/v1/workflows/instances/${instanceId}/cancel`, {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
      });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "No pude cancelar");
    }
  }

  return (
    <div>
      <PageHeader
        title="Operación"
        subtitle="Procesos durables del motor. El estado de pantalla sale del estado guardado, no de una lista paralela."
      />
      <ErrorInline message={error} />
      {queue && (
        <div
          className="mb-3 flex flex-wrap gap-2 rounded-lg border border-border bg-surface px-3 py-2 text-[12px]"
          role="status"
          data-testid="ops-queue"
        >
          <span className="font-medium text-text">Cola de intervención</span>
          <span className="text-muted">{queue.total} en total</span>
          <span className="text-warn">{queue.summary.failed} fallos</span>
          <span className="text-warn">{queue.summary.needs_human} esperan humano</span>
          <span className="text-muted">{queue.summary.expired} expirados</span>
        </div>
      )}
      <div className="mb-3 flex flex-wrap items-end gap-2">
        <label className="text-[12px] text-muted">
          Identificador
          <Input
            value={keyFilter}
            onChange={(event) => setKeyFilter(event.target.value)}
            aria-label="Filtrar por identificador"
            data-testid="ops-key"
          />
        </label>
        <label className="text-[12px] text-muted">
          Estado
          <select
            className="mt-1 block min-h-11 rounded-md border border-border bg-surface px-2 text-[13px]"
            value={view}
            aria-label="Filtrar por estado"
            data-testid="ops-view"
            onChange={(event) => setView(event.target.value)}
          >
            <option value="">Todos</option>
            {VIEW_FILTERS.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </label>
        <Button variant="secondary" onClick={() => void load()}>
          Actualizar
        </Button>
      </div>
      {loading ? (
        <Skeleton className="h-24 rounded-md" />
      ) : visible.length === 0 ? (
        <Panel>
          <EmptyState title="Sin procesos en este filtro" body="Cuando un flujo espere o falle, aparece aquí." />
        </Panel>
      ) : (
        <ul className="divide-y divide-border rounded-lg border border-border bg-surface" data-testid="ops-list">
          {visible.map((row) => (
            <li key={row.id} className="flex flex-wrap items-center gap-2 px-3 py-2 text-[13px]">
              <span className="font-mono text-[11px] text-faint">{row.view_status || row.status}</span>
              <span className="min-w-0 flex-1 truncate text-text">{row.business_key || row.workflow_id}</span>
              <span className="text-[11px] text-faint">v{row.workflow_version ?? 1}</span>
              {row.status === "WAITING" || row.status === "RUNNING" || row.status === "SUSPENDED" ? (
                <Button size="sm" variant="ghost" data-testid={`ops-cancel-${row.id}`} onClick={() => void cancel(row.id)}>
                  Cancelar
                </Button>
              ) : null}
              <Button size="sm" variant="secondary" onClick={() => void openTimeline(row.id)}>
                Línea de tiempo
              </Button>
            </li>
          ))}
        </ul>
      )}
      {openId && (
        <section className="mt-3 rounded-lg border border-border p-3" data-testid="ops-timeline">
          <h2 className="text-[13px] font-medium text-text">Línea de tiempo</h2>
          {(timeline || []).length === 0 ? (
            <p className="mt-2 text-[12px] text-faint">Sin segmentos todavía.</p>
          ) : (
            <ol className="mt-2 space-y-1">
              {(timeline || []).map((step, index) => (
                <li key={`${step.step}-${index}`} className="text-[12px] text-muted">
                  {step.step}
                  {step.event_type ? ` · ${step.event_type}` : ""}
                  {step.fault ? ` · ${step.fault}` : ""}
                  {step.at ? ` · ${step.at}` : ""}
                </li>
              ))}
            </ol>
          )}
        </section>
      )}
    </div>
  );
}
