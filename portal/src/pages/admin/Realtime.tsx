import { Broadcast, WarningCircle } from "@phosphor-icons/react";
import { useEffect, useMemo, useRef, useState } from "react";
import { platformApi } from "../../api";
import {
  Badge,
  Button,
  CodeBlock,
  DataTable,
  Drawer,
  EmptyState,
  ErrorInline,
  KeyValue,
  Metric,
  MetricGrid,
  PageHeader,
  Panel,
  PanelHeader,
  SectionHeader,
  Skeleton,
  StatusBadge,
  type Column,
  type SortState,
} from "../../components/ui";
import { fmtCurrency, fmtNum } from "../../lib/format";
import { usePlatformAuth } from "../../platformAuth";

type Summary = {
  window_minutes: number;
  requests: number;
  errors: number;
  error_rate_pct: number;
  tokens: number;
  cost: number;
  active_organizations: number;
  by_model: { model: string; requests: number }[];
};

type LiveEvent = {
  event: string;
  ts: string;
  organization_id: string;
  deployment_id?: string | null;
  model?: string | null;
  tokens?: number;
  cost?: number;
  latency_ms?: number;
  status?: string | number;
};

const isErrorStatus = (status: unknown) =>
  typeof status === "string"
    ? ["error", "failed", "5xx"].includes(status)
    : typeof status === "number" && status >= 500;

export default function AdminRealtimePage() {
  const { session } = usePlatformAuth();
  const [summary, setSummary] = useState<Summary | null>(null);
  const [events, setEvents] = useState<LiveEvent[]>([]);
  const [selected, setSelected] = useState<LiveEvent | null>(null);
  const [autoCorrection, setAutoCorrection] = useState(false);
  const [connected, setConnected] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [sortModels, setSortModels] = useState<SortState>({ key: "requests", dir: "desc" });
  const abortRef = useRef<AbortController | null>(null);

  async function loadSummary() {
    if (!session) return;
    try {
      const [s, ac] = await Promise.all([
        platformApi<Summary>("/api/v1/platform/realtime/summary?minutes=15", { token: session.token }),
        platformApi<{ enabled: boolean }>("/api/v1/platform/realtime/auto-correction", { token: session.token }),
      ]);
      setSummary(s);
      setAutoCorrection(ac.enabled);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (!session) return;
    void loadSummary();
    // SSE con fetch (EventSource no soporta headers de auth).
    const controller = new AbortController();
    abortRef.current = controller;
    let buffer = "";
    const connect = async () => {
      try {
        const resp = await fetch("/api/v1/platform/realtime/stream", {
          headers: { Authorization: `Bearer ${session.token}` },
          signal: controller.signal,
        });
        if (!resp.ok || !resp.body) throw new Error(`SSE ${resp.status}`);
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        setConnected(true);
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const frames = buffer.split("\n\n");
          buffer = frames.pop() ?? "";
          for (const frame of frames) {
            const dataLine = frame.split("\n").find((l) => l.startsWith("data: "));
            if (!dataLine) continue;
            try {
              const payload = JSON.parse(dataLine.slice(6));
              setEvents((prev) => [payload, ...prev].slice(0, 60));
            } catch {
              /* heartbeat u otro */
            }
          }
        }
      } catch {
        // abort/desconexión
      } finally {
        setConnected(false);
      }
    };
    void connect();
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  async function toggleAutoCorrection() {
    if (!session) return;
    setError("");
    try {
      const out = await platformApi<{ enabled: boolean }>("/api/v1/platform/realtime/auto-correction", {
        method: "POST",
        token: session.token,
        body: JSON.stringify({ enabled: !autoCorrection }),
      });
      setAutoCorrection(out.enabled);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  const byModel = useMemo(() => {
    const rows = [...(summary?.by_model ?? [])];
    if (!sortModels) return rows;
    return rows.sort((a, b) =>
      sortModels.dir === "asc" ? a.requests - b.requests : b.requests - a.requests
    );
  }, [summary?.by_model, sortModels]);

  const errorEvents = events.filter((e) => isErrorStatus(e.status)).length;
  const modelColumns: Column<{ model: string; requests: number }>[] = [
    {
      key: "model",
      header: "Modelo",
      render: (row) => <span className="mono text-xs text-text">{row.model}</span>,
    },
    {
      key: "requests",
      header: "Requests",
      align: "right",
      sortable: true,
      width: "110px",
      render: (row) => <span className="mono text-xs text-muted">{fmtNum(row.requests)}</span>,
    },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Real-Time"
        subtitle="Eventos en vivo (SSE), resumen de la ventana y corrección automática."
        actions={
          <Button
            variant={autoCorrection ? "danger" : "secondary"}
            leadingIcon={WarningCircle}
            aria-pressed={autoCorrection}
            onClick={() => void toggleAutoCorrection()}
          >
            Auto-corrección: {autoCorrection ? "ON" : "OFF"}
          </Button>
        }
      />
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge
          status={connected ? "listening" : "disconnected"}
          label={connected ? "Streaming en vivo" : "Sin conexión"}
        />
        {events.length > 0 && <span className="text-xs text-muted">{fmtNum(events.length)} eventos en buffer</span>}
      </div>
      <ErrorInline message={error} />
      {loading ? (
        <div className="flex flex-col gap-3" aria-hidden>
          <Skeleton className="h-[86px] rounded-lg" />
          <Skeleton className="h-[300px] rounded-lg" />
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,3fr)]">
            <Metric
              label="Requests (15m)"
              value={fmtNum(summary?.requests ?? 0)}
              hint={`${fmtNum(summary?.active_organizations ?? 0)} organizaciones activas`}
              icon={Broadcast}
            />
            <MetricGrid cols={4} className="lg:grid-cols-4">
              <Metric
                label="Error rate"
                value={`${summary?.error_rate_pct ?? 0}%`}
                size="md"
                tone={(summary?.errors ?? 0) > 0 ? "warn" : "default"}
              />
              <Metric label="Costo" value={fmtCurrency(summary?.cost ?? 0, 3)} size="md" />
              <Metric label="Tokens" value={fmtNum(summary?.tokens ?? 0)} size="md" />
              <Metric label="Orgs activas" value={fmtNum(summary?.active_organizations ?? 0)} size="md" />
            </MetricGrid>
          </div>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
            <section className="min-w-0">
              <SectionHeader
                title="Por modelo (15m)"
                description="Volumen de requests de la ventana corta."
                className="mb-3"
              />
              <DataTable
                stickyHeader
                columns={modelColumns}
                rows={byModel}
                rowKey={(row) => row.model}
                sort={sortModels}
                onSortChange={setSortModels}
                empty={
                  <EmptyState compact icon={Broadcast} title="Sin tráfico en la ventana" body="No hay requests en los últimos 15 minutos." />
                }
              />
            </section>

            <section className="min-w-0 lg:col-span-2">
              <Panel className="overflow-hidden">
                <PanelHeader
                  title="Eventos en vivo"
                  description={
                    errorEvents > 0
                      ? `${fmtNum(events.length)} recibidos · ${errorEvents} con error`
                      : "Seleccioná un evento para inspeccionar su payload."
                  }
                />
                <div className="max-h-[420px] overflow-y-auto">
                  {events.length === 0 ? (
                    <EmptyState
                      compact
                      icon={Broadcast}
                      title="Esperando eventos"
                      body="El stream está conectado pero todavía no llegaron eventos."
                      hint="Ejecutá consultas para ver tráfico en vivo."
                    />
                  ) : (
                    <ul>
                      {events.map((e, i) => {
                        const failed = isErrorStatus(e.status);
                        return (
                          <li key={`${e.ts}-${i}`}>
                            <button
                              type="button"
                              onClick={() => setSelected(e)}
                              className="state-rail block w-full cursor-pointer px-4 py-2.5 text-left transition-colors duration-150 hover:bg-soft/55"
                              data-state={failed ? "failed" : "ready"}
                            >
                              <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
                                <span className="mono text-faint">{new Date(e.ts).toLocaleTimeString("es-PE")}</span>
                                <span className="text-text">{e.event}</span>
                                <span className="mono text-faint">org {e.organization_id.slice(0, 8)}</span>
                                {e.model && <span className="mono text-muted">{e.model}</span>}
                                {failed ? (
                                  <Badge tone="danger">{String(e.status)}</Badge>
                                ) : (
                                  <Badge tone="neutral">{String(e.status ?? "—")}</Badge>
                                )}
                                {e.latency_ms != null && <span className="mono text-faint">{e.latency_ms}ms</span>}
                                <span className="mono text-faint">${e.cost ?? 0}</span>
                              </span>
                            </button>
                          </li>
                        );
                      })}
                    </ul>
                  )}
                </div>
              </Panel>
            </section>
          </div>
        </>
      )}

      <Drawer
        open={Boolean(selected)}
        onOpenChange={(open) => {
          if (!open) setSelected(null);
        }}
        title={selected ? `Evento · ${selected.event}` : "Evento"}
        description={selected ? new Date(selected.ts).toLocaleString("es-PE") : undefined}
        width={520}
      >
        {selected && (
          <div className="space-y-5">
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge
                status={isErrorStatus(selected.status) ? "failed" : "completed"}
                label={String(selected.status ?? "Sin estado")}
              />
            </div>
            <KeyValue
              columns={2}
              items={[
                { key: "Evento", value: selected.event, mono: true },
                { key: "Organización", value: selected.organization_id.slice(0, 8), mono: true },
                ...(selected.deployment_id
                  ? [{ key: "Deployment", value: selected.deployment_id.slice(0, 8), mono: true }]
                  : []),
                ...(selected.model ? [{ key: "Modelo", value: selected.model, mono: true }] : []),
                ...(selected.tokens != null ? [{ key: "Tokens", value: fmtNum(selected.tokens) }] : []),
                ...(selected.latency_ms != null ? [{ key: "Latencia", value: `${selected.latency_ms} ms` }] : []),
                ...(selected.cost != null ? [{ key: "Costo", value: `$${selected.cost}` }] : []),
              ]}
            />
            <div>
              <p className="eyebrow mb-2">Payload</p>
              <CodeBlock code={JSON.stringify(selected, null, 2)} language="json" maxHeight={320} />
            </div>
          </div>
        )}
      </Drawer>
    </div>
  );
}
