import { ListMagnifyingGlass, Plus } from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";
import { platformApi } from "../../api";
import {
  Badge,
  Button,
  DataTable,
  EmptyState,
  ErrorInline,
  Field,
  Input,
  Metric,
  MetricGrid,
  PageHeader,
  Pagination,
  Panel,
  PanelHeader,
  ResultCount,
  SectionHeader,
  Select,
  Skeleton,
  StatusBadge,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  Toolbar,
  type Column,
  type SortState,
} from "../../components/ui";
import { fmtCurrency, fmtLatency, fmtNum } from "../../lib/format";
import { usePlatformAuth } from "../../platformAuth";

type Model = {
  id: string;
  model_name: string;
  backend: string;
  capacity: number;
  status: string;
};

type Perf = {
  model: string;
  backend: string;
  requests: number;
  tokens: number;
  cost: number;
  avg_latency_ms: number;
  p95_latency_ms: number;
  avg_queue_ms: number;
  throughput_per_min: number;
  errors: number;
};

type Log = {
  id: string;
  model: string;
  backend: string;
  status: string;
  total_tokens: number;
  latency_ms: number;
  queue_wait_ms: number;
  cost: number;
  created_at: string;
};

type Queue = { plan: string; model: string; depth: number; priority: number };

const WINDOWS = [
  { hours: 1, label: "1h" },
  { hours: 6, label: "6h" },
  { hours: 24, label: "24h" },
] as const;
const LOG_PAGE_SIZE = 25;

function sortRows<T>(rows: T[], sort: SortState, get: (row: T, key: string) => string | number) {
  if (!sort) return rows;
  return [...rows].sort((a, b) => {
    const left = get(a, sort.key);
    const right = get(b, sort.key);
    if (typeof left === "string" && typeof right === "string") {
      return sort.dir === "asc" ? left.localeCompare(right) : right.localeCompare(left);
    }
    return sort.dir === "asc" ? Number(left) - Number(right) : Number(right) - Number(left);
  });
}

export default function AdminInferenceProxyPage() {
  const { session } = usePlatformAuth();
  const [models, setModels] = useState<Model[]>([]);
  const [perf, setPerf] = useState<Perf[]>([]);
  const [logs, setLogs] = useState<Log[]>([]);
  const [queue, setQueue] = useState<Queue[]>([]);
  const [hours, setHours] = useState(24);
  const [modelFilter, setModelFilter] = useState("");
  const [modelForm, setModelForm] = useState({ model_name: "", backend: "openai", capacity: 50 });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [sortModels, setSortModels] = useState<SortState>({ key: "model_name", dir: "asc" });
  const [sortLogs, setSortLogs] = useState<SortState>({ key: "created_at", dir: "desc" });
  const [logPage, setLogPage] = useState(1);

  async function load() {
    if (!session) return;
    setError("");
    try {
      const [m, p, l, q] = await Promise.all([
        platformApi<{ models: Model[] }>("/api/v1/platform/proxy/models", { token: session.token }),
        platformApi<{ models: Perf[] }>(`/api/v1/platform/proxy/performance?hours=${hours}`, { token: session.token }),
        platformApi<{ logs: Log[] }>("/api/v1/platform/proxy/inference-logs?hours=24&limit=50", { token: session.token }),
        platformApi<{ queues: Queue[] }>("/api/v1/platform/proxy/queue", { token: session.token }),
      ]);
      setModels(m.models || []);
      setPerf(p.models || []);
      setLogs(l.logs || []);
      setQueue(q.queues || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    const id = setInterval(() => void load(), 8000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session, hours]);

  async function upsertModel() {
    if (!session) return;
    setBusy("model");
    setError("");
    try {
      await platformApi("/api/v1/platform/proxy/models", {
        method: "POST",
        token: session.token,
        body: JSON.stringify(modelForm),
      });
      setModelForm({ model_name: "", backend: "openai", capacity: 50 });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  const shown = perf.filter((p) => !modelFilter || p.model === modelFilter);
  const totals = shown.reduce(
    (acc, p) => {
      acc.requests += p.requests;
      acc.tokens += p.tokens;
      acc.cost += p.cost;
      acc.errors += p.errors;
      return acc;
    },
    { requests: 0, tokens: 0, cost: 0, errors: 0 }
  );

  const modelRows = useMemo(
    () =>
      sortRows(models, sortModels, (row, key) =>
        key === "backend" ? row.backend : key === "capacity" ? row.capacity : key === "status" ? row.status : row.model_name
      ),
    [models, sortModels]
  );
  const logRows = useMemo(
    () =>
      sortRows(logs, sortLogs, (row, key) => {
        if (key === "model") return row.model;
        if (key === "status") return row.status;
        if (key === "total_tokens") return row.total_tokens;
        if (key === "latency_ms") return row.latency_ms;
        if (key === "queue_wait_ms") return row.queue_wait_ms;
        if (key === "cost") return row.cost;
        return row.created_at;
      }),
    [logs, sortLogs]
  );
  const maxLogPage = Math.max(1, Math.ceil(logRows.length / LOG_PAGE_SIZE));
  const safeLogPage = Math.min(logPage, maxLogPage);
  const pageLogs = logRows.slice((safeLogPage - 1) * LOG_PAGE_SIZE, safeLogPage * LOG_PAGE_SIZE);

  const modelColumns: Column<Model>[] = [
    {
      key: "model_name",
      header: "Modelo",
      sortable: true,
      render: (row) => <span className="mono text-xs text-text">{row.model_name}</span>,
    },
    {
      key: "backend",
      header: "Backend",
      sortable: true,
      width: "120px",
      render: (row) => <Badge tone="neutral">{row.backend}</Badge>,
    },
    {
      key: "capacity",
      header: "Capacidad",
      align: "right",
      sortable: true,
      width: "120px",
      render: (row) => <span className="mono text-xs text-muted">{fmtNum(row.capacity)}</span>,
    },
    {
      key: "status",
      header: "Estado",
      sortable: true,
      width: "130px",
      render: (row) => <StatusBadge status={row.status} />,
    },
  ];

  const logColumns: Column<Log>[] = [
    {
      key: "created_at",
      header: "Hora",
      sortable: true,
      width: "120px",
      render: (row) => <span className="mono text-xs text-faint">{new Date(row.created_at).toLocaleTimeString()}</span>,
    },
    {
      key: "model",
      header: "Modelo",
      sortable: true,
      render: (row) => <span className="mono text-xs text-text">{row.model}</span>,
    },
    {
      key: "backend",
      header: "Backend",
      hideBelow: "md",
      width: "110px",
      render: (row) => <span className="text-xs text-muted">{row.backend}</span>,
    },
    {
      key: "total_tokens",
      header: "Tokens",
      align: "right",
      sortable: true,
      width: "110px",
      render: (row) => <span className="mono text-xs text-muted">{fmtNum(row.total_tokens)}</span>,
    },
    {
      key: "latency_ms",
      header: "Latencia",
      align: "right",
      sortable: true,
      width: "110px",
      render: (row) => <span className="mono text-xs text-muted">{fmtLatency(row.latency_ms)}</span>,
    },
    {
      key: "queue_wait_ms",
      header: "Cola",
      align: "right",
      sortable: true,
      hideBelow: "md",
      width: "100px",
      render: (row) => <span className="mono text-xs text-muted">{fmtLatency(row.queue_wait_ms)}</span>,
    },
    {
      key: "cost",
      header: "Costo",
      align: "right",
      sortable: true,
      hideBelow: "lg",
      width: "110px",
      render: (row) => <span className="mono text-xs text-muted">{fmtCurrency(row.cost, 5)}</span>,
    },
    {
      key: "status",
      header: "Estado",
      sortable: true,
      width: "130px",
      render: (row) => <StatusBadge status={row.status} />,
    },
  ];

  return (
    <div className="space-y-6">
      <PageHeader title="Inference Proxy" subtitle="Cola por plan, routing por capacidad, logs de inferencia y performance por modelo." />
      <ErrorInline message={error} />
      {loading ? (
        <div className="flex flex-col gap-3" aria-hidden>
          <Skeleton className="h-[86px] rounded-lg" />
          <Skeleton className="h-[320px] rounded-lg" />
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,3fr)]">
            <Metric
              label={`Requests (${hours}h)`}
              value={fmtNum(totals.requests)}
              hint={modelFilter ? `Filtrado: ${modelFilter}` : `${shown.length} modelos con tráfico`}
            />
            <MetricGrid cols={4} className="lg:grid-cols-4">
              <Metric label="Tokens" value={fmtNum(totals.tokens)} size="md" />
              <Metric label="Costo" value={fmtCurrency(totals.cost, 3)} size="md" />
              <Metric
                label="Errores"
                value={fmtNum(totals.errors)}
                size="md"
                tone={totals.errors > 0 ? "danger" : "default"}
              />
              <Metric label="Modelos en catálogo" value={fmtNum(models.length)} size="md" />
            </MetricGrid>
          </div>

          <Toolbar>
            <Tabs variant="pill" value={String(hours)} onValueChange={(value) => setHours(Number(value))}>
              <TabsList>
                {WINDOWS.map((w) => (
                  <TabsTrigger key={w.hours} value={String(w.hours)}>
                    {w.label}
                  </TabsTrigger>
                ))}
              </TabsList>
            </Tabs>
            <Select
              aria-label="Filtrar por modelo"
              className="w-48"
              value={modelFilter}
              onChange={(e) => {
                setModelFilter(e.target.value);
                setLogPage(1);
              }}
              placeholder="Todos los modelos"
            >
              {perf.map((p) => (
                <option key={p.model} value={p.model}>
                  {p.model}
                </option>
              ))}
            </Select>
          </Toolbar>

          <Tabs defaultValue="traffic">
            <TabsList>
              <TabsTrigger value="traffic">Tráfico</TabsTrigger>
              <TabsTrigger value="catalog">Catálogo</TabsTrigger>
              <TabsTrigger value="logs">Logs</TabsTrigger>
            </TabsList>

            <TabsContent value="traffic">
              <section className="min-w-0">
                <SectionHeader
                  title="Performance por modelo"
                  description="Latencia p95, volumen, cola y costo de la ventana seleccionada."
                  className="mb-3"
                />
                {shown.length === 0 ? (
                  <Panel className="mb-4">
                    <EmptyState
                      icon={ListMagnifyingGlass}
                      title="Sin tráfico en la ventana"
                      body="No hay requests registrados para esta selección."
                      hint="Ampliá la ventana o quitá el filtro de modelo."
                    />
                  </Panel>
                ) : (
                  <MetricGrid cols={4} className="mb-4">
                    {shown.map((p) => (
                      <Metric
                        key={p.model}
                        label={`${p.model} · ${p.backend}`}
                        value={fmtLatency(p.p95_latency_ms)}
                        size="md"
                        tone={p.errors > 0 ? "warn" : "default"}
                        hint={`${fmtNum(p.requests)} req · ${p.throughput_per_min}/min · cola ${fmtLatency(p.avg_queue_ms)} · ${p.errors} err · ${fmtCurrency(p.cost, 3)}`}
                        help={`p95 en la ventana; promedio ${fmtLatency(p.avg_latency_ms)}.`}
                      />
                    ))}
                  </MetricGrid>
                )}

                <Panel>
                  <PanelHeader
                    title={
                      <span className="flex items-center gap-2">
                        <ListMagnifyingGlass size={15} aria-hidden /> Cola viva por plan
                      </span>
                    }
                    description="Profundidad actual y prioridad de atención."
                  />
                  {queue.length === 0 ? (
                    <EmptyState compact icon={ListMagnifyingGlass} title="Cola vacía" body="No hay trabajos esperando en este momento." />
                  ) : (
                    <ul className="divide-y divide-border-soft">
                      {queue.map((q) => (
                        <li key={`${q.plan}:${q.model}`} className="flex items-center gap-3 px-4 py-2.5">
                          <span className="min-w-0 flex-1 truncate text-[13px] text-text">{q.plan}</span>
                          <span className="mono min-w-0 truncate text-xs text-muted">{q.model}</span>
                          <Badge tone={q.depth > 10 ? "danger" : "neutral"}>{q.depth} esperando</Badge>
                        </li>
                      ))}
                    </ul>
                  )}
                </Panel>
              </section>
            </TabsContent>

            <TabsContent value="catalog">
              <section className="min-w-0">
                <SectionHeader
                  title={
                    <span className="flex items-center gap-2">
                      <Plus size={15} aria-hidden /> Modelo del proxy
                    </span>
                  }
                  description="Alta o actualización de un modelo del catálogo."
                  className="mb-3"
                />
                <Panel className="mb-4">
                  <PanelHeader title="Upsert de modelo" description="Se identifica por nombre; la capacidad es el cupo concurrente." />
                  <div className="panel-body">
                    <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                      <Field label="Modelo">
                        <Input
                          value={modelForm.model_name}
                          onChange={(e) => setModelForm((f) => ({ ...f, model_name: e.target.value }))}
                          placeholder="ej. zent-fast"
                        />
                      </Field>
                      <Field label="Backend">
                        <Select
                          value={modelForm.backend}
                          onChange={(e) => setModelForm((f) => ({ ...f, backend: e.target.value }))}
                        >
                          {["openai", "vllm", "tgi"].map((b) => (
                            <option key={b} value={b}>
                              {b}
                            </option>
                          ))}
                        </Select>
                      </Field>
                      <Field label="Capacidad">
                        <Input
                          type="number"
                          min={1}
                          value={modelForm.capacity}
                          onChange={(e) => setModelForm((f) => ({ ...f, capacity: Number(e.target.value) }))}
                        />
                      </Field>
                    </div>
                    <div className="mt-3">
                      <Button
                        variant="primary"
                        size="sm"
                        loading={busy === "model"}
                        disabled={!modelForm.model_name.trim()}
                        onClick={() => void upsertModel()}
                      >
                        Guardar
                      </Button>
                    </div>
                  </div>
                </Panel>
                <DataTable
                  stickyHeader
                  columns={modelColumns}
                  rows={modelRows}
                  rowKey={(row) => row.id}
                  sort={sortModels}
                  onSortChange={setSortModels}
                  empty={
                    <EmptyState
                      icon={ListMagnifyingGlass}
                      title="Catálogo vacío"
                      body="Agregá el primer modelo para que el proxy pueda enrutar."
                    />
                  }
                />
              </section>
            </TabsContent>

            <TabsContent value="logs">
              <section className="min-w-0">
                <SectionHeader
                  title="Logs de inferencia"
                  description="Últimas 50 inferencias servidas por el proxy."
                  className="mb-3"
                />
                <DataTable
                  stickyHeader
                  columns={logColumns}
                  rows={pageLogs}
                  rowKey={(row) => row.id}
                  sort={sortLogs}
                  onSortChange={(next) => {
                    setSortLogs(next);
                    setLogPage(1);
                  }}
                  empty={
                    <EmptyState
                      icon={ListMagnifyingGlass}
                      title="Sin logs en la ventana"
                      body="No hay inferencias registradas."
                      hint="Cuando el proxy reciba tráfico vas a verlas acá."
                    />
                  }
                  footer={
                    logRows.length > LOG_PAGE_SIZE ? (
                      <>
                        <ResultCount shown={pageLogs.length} total={logRows.length} noun="logs" />
                        <Pagination page={safeLogPage} pageSize={LOG_PAGE_SIZE} total={logRows.length} onPageChange={setLogPage} />
                      </>
                    ) : (
                      <ResultCount shown={logRows.length} total={logRows.length} noun="logs" />
                    )
                  }
                />
              </section>
            </TabsContent>
          </Tabs>
        </>
      )}
    </div>
  );
}
