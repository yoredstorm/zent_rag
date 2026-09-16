import { GitBranch } from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";
import { platformApi } from "../../api";
import {
  Badge,
  Button,
  CodeBlock,
  DataTable,
  Drawer,
  EmptyState,
  ErrorInline,
  Input,
  KeyValue,
  Metric,
  MetricGrid,
  PageHeader,
  Pagination,
  Panel,
  ResultCount,
  SectionHeader,
  Select,
  Skeleton,
  StatusBadge,
  Tabs,
  TabsList,
  TabsTrigger,
  Toolbar,
  type Column,
  type SortState,
} from "../../components/ui";
import { fmtLatency, fmtNum } from "../../lib/format";
import { usePlatformAuth } from "../../platformAuth";

type Trace = {
  id: string;
  organization_id: string;
  agent_id: string | null;
  trace_id: string;
  status: string;
  model: string | null;
  input: string;
  total_latency_ms: number;
  total_tokens: number;
  cost: number;
  started_at: string;
};

type Span = { id: string; stage: string; name: string; status: string; started_ms: number; duration_ms: number; tokens: number; metadata: Record<string, unknown> };
type Markers = {
  llm_calls: number;
  models_used: string[];
  retries: number;
  fallback_detected: boolean;
  error_spans: number;
  bottleneck: { stage: string; name: string; duration_ms: number } | null;
};
type Feedback = { rating: string; reason: string | null; comment: string | null; created_at: string } | null;
type TraceDetail = Trace & { run_id: string | null; output: string | null; error: string | null; spans: Span[]; markers: Markers; feedback: Feedback; provider: string | null; environment: string | null; version_id: string | null; prompt_tokens: number; completion_tokens: number };
type RootCause = {
  probable_causes: { factor: string; label: string; evidence: string[] }[];
  possible_contributing_factors: { factor: string; label: string; evidence: string[] }[];
  signals: Record<string, unknown>;
};
type Compare = {
  same_input: boolean;
  a: { trace_id: string; status: string; model: string | null; latency_ms: number; tokens: number; cost: number; spans_count: number; error: string | null };
  b: { trace_id: string; status: string; model: string | null; latency_ms: number; tokens: number; cost: number; spans_count: number; error: string | null };
  deltas: { latency_ms: number; tokens: number; cost: number; spans_count: number };
  spans_diff: { stage: string; a_duration_ms: number | null; b_duration_ms: number | null; a_tokens: number | null; b_tokens: number | null }[];
  output_a: string;
  output_b: string;
};
type Stage = { stage: string; spans: number; avg_duration_ms: number; p95_duration_ms: number; tokens: number; errors: number; error_rate: number };

const STAGE_LABEL: Record<string, string> = { llm: "LLM", retrieval: "Retrieval", rerank: "Rerank", sql: "SQL", tool: "Tools", total: "Total" };
const WINDOWS = [
  { hours: 1, label: "1h" },
  { hours: 24, label: "24h" },
  { hours: 168, label: "7d" },
] as const;
const PAGE_SIZE = 20;

function compareTraces(a: Trace, b: Trace, sort: NonNullable<SortState>): number {
  const dir = sort.dir === "asc" ? 1 : -1;
  switch (sort.key) {
    case "status":
      return a.status.localeCompare(b.status) * dir;
    case "model":
      return (a.model ?? "").localeCompare(b.model ?? "") * dir;
    case "total_latency_ms":
      return (a.total_latency_ms - b.total_latency_ms) * dir;
    case "total_tokens":
      return (a.total_tokens - b.total_tokens) * dir;
    case "cost":
      return (a.cost - b.cost) * dir;
    case "input":
      return a.input.localeCompare(b.input) * dir;
    case "started_at":
      return (Date.parse(a.started_at) - Date.parse(b.started_at)) * dir;
    default:
      return a.trace_id.localeCompare(b.trace_id) * dir;
  }
}

export default function AdminTracesPage() {
  const { session } = usePlatformAuth();
  const [traces, setTraces] = useState<Trace[]>([]);
  const [stages, setStages] = useState<Stage[]>([]);
  const [detail, setDetail] = useState<TraceDetail | null>(null);
  const [rootCause, setRootCause] = useState<RootCause | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [compare, setCompare] = useState<Compare | null>(null);
  const [usage, setUsage] = useState<{ usage_events: unknown[]; api_logs: unknown[] } | null>(null);
  const [orgs, setOrgs] = useState<{ id: string }[]>([]);
  const [filters, setFilters] = useState({ organization_id: "", status: "", model: "", q: "" });
  const [selA, setSelA] = useState("");
  const [selB, setSelB] = useState("");
  const [hours, setHours] = useState(24);
  const [sort, setSort] = useState<SortState>({ key: "started_at", dir: "desc" });
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function loadAll() {
    if (!session) return;
    setError("");
    try {
      const params = new URLSearchParams();
      if (filters.organization_id) params.set("organization_id", filters.organization_id);
      if (filters.status) params.set("status", filters.status);
      if (filters.model) params.set("model", filters.model);
      if (filters.q) params.set("q", filters.q);
      params.set("hours", String(hours));
      const [t, s] = await Promise.all([
        platformApi<{ traces: Trace[] }>(`/api/v1/platform/observability/traces?${params}`, { token: session.token }),
        platformApi<{ stages: Stage[] }>(`/api/v1/platform/observability/stages?hours=${hours}`, { token: session.token }),
      ]);
      setTraces(t.traces || []);
      setStages(s.stages || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (!session) return;
    (async () => {
      try {
        const o = await platformApi<{ organizations: { id: string }[] }>("/api/v1/platform/organizations", { token: session.token });
        setOrgs(o.organizations || []);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Error");
      }
      await loadAll();
    })();
    const id = setInterval(() => void loadAll(), 10000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session, hours]);

  async function showDetail(traceId: string) {
    if (!session) return;
    setError("");
    setRootCause(null);
    try {
      const [d, u] = await Promise.all([
        platformApi<TraceDetail>(`/api/v1/platform/observability/traces/${traceId}`, { token: session.token }),
        platformApi<{ usage_events: unknown[]; api_logs: unknown[] }>(`/api/v1/platform/observability/traces/${traceId}/usage`, { token: session.token }),
      ]);
      setDetail(d);
      setUsage(u);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  async function analyze() {
    if (!session || !detail?.run_id) return;
    setAnalyzing(true);
    setError("");
    try {
      const r = await platformApi<RootCause>(
        `/api/v1/agents/runs/${detail.run_id}/analysis`,
        { method: "POST", token: session.token, body: "{}" }
      );
      setRootCause(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setAnalyzing(false);
    }
  }

  async function doCompare() {
    if (!session || !selA || !selB) return;
    setError("");
    try {
      const c = await platformApi<Compare>(`/api/v1/platform/observability/traces/compare?a=${selA}&b=${selB}`, { token: session.token });
      setCompare(c);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  const sorted = useMemo(() => {
    const rows = [...traces];
    if (!sort) return rows.reverse();
    return rows.sort((a, b) => compareTraces(a, b, sort));
  }, [traces, sort]);

  const maxPage = Math.max(1, Math.ceil(sorted.length / PAGE_SIZE));
  const safePage = Math.min(page, maxPage);
  const pageRows = sorted.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);

  const columns: Column<Trace>[] = [
    {
      key: "trace_id",
      header: "Trace",
      sortable: true,
      width: "140px",
      render: (row) => (
        <span className="mono text-xs text-faint" title={row.trace_id}>
          {row.trace_id.slice(0, 12)}
        </span>
      ),
    },
    {
      key: "status",
      header: "Estado",
      sortable: true,
      width: "130px",
      render: (row) => <StatusBadge status={row.status} />,
    },
    {
      key: "model",
      header: "Modelo",
      sortable: true,
      hideBelow: "md",
      render: (row) => <span className="mono text-xs text-muted">{row.model ?? "—"}</span>,
    },
    {
      key: "input",
      header: "Input",
      sortable: true,
      hideBelow: "lg",
      render: (row) => (
        <span className="block max-w-[280px] truncate text-xs text-faint" title={row.input}>
          {row.input}
        </span>
      ),
    },
    {
      key: "total_latency_ms",
      header: "Latencia",
      align: "right",
      sortable: true,
      width: "110px",
      render: (row) => <span className="mono text-xs text-muted">{row.total_latency_ms.toFixed(0)}ms</span>,
    },
    {
      key: "total_tokens",
      header: "Tokens",
      align: "right",
      sortable: true,
      hideBelow: "md",
      width: "100px",
      render: (row) => <span className="mono text-xs text-muted">{fmtNum(row.total_tokens)}</span>,
    },
    {
      key: "cost",
      header: "Costo",
      align: "right",
      sortable: true,
      hideBelow: "md",
      width: "100px",
      render: (row) => <span className="mono text-xs text-muted">${row.cost.toFixed(4)}</span>,
    },
  ];

  return (
    <div className="space-y-6">
      <PageHeader title="Traces & Spans" subtitle="Trazado distribuido de runs, comparación side-by-side y correlación con billing." />
      <ErrorInline message={error} />
      {loading ? (
        <div className="flex flex-col gap-3" aria-hidden>
          <Skeleton className="h-[86px] rounded-lg" />
          <Skeleton className="h-[320px] rounded-lg" />
        </div>
      ) : (
        <>
          <section>
            <SectionHeader
              title="Latencia por etapa"
              description="Promedio y p95 de cada etapa del pipeline en la ventana."
              className="mb-3"
            />
            {stages.length === 0 ? (
              <Panel>
                <EmptyState
                  compact
                  title="Sin spans en la ventana"
                  body="Ejecutá consultas o ampliá la ventana temporal para ver etapas."
                />
              </Panel>
            ) : (
              <MetricGrid cols={4}>
                {stages.map((s) => (
                  <Metric
                    key={s.stage}
                    label={`${STAGE_LABEL[s.stage] ?? s.stage} · ${fmtNum(s.spans)} spans`}
                    value={fmtLatency(s.avg_duration_ms)}
                    size="md"
                    tone={s.errors > 0 ? "danger" : "default"}
                    hint={`p95 ${fmtLatency(s.p95_duration_ms)} · ${fmtNum(s.tokens)} tok · ${s.errors} err`}
                  />
                ))}
              </MetricGrid>
            )}
          </section>

          <Toolbar>
            <Select
              aria-label="Organización"
              className="w-40"
              value={filters.organization_id}
              onChange={(e) => {
                setFilters((f) => ({ ...f, organization_id: e.target.value }));
                setPage(1);
              }}
              placeholder="Todas las orgs"
            >
              {orgs.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.id.slice(0, 8)}
                </option>
              ))}
            </Select>
            <Select
              aria-label="Estado"
              className="w-36"
              value={filters.status}
              onChange={(e) => {
                setFilters((f) => ({ ...f, status: e.target.value }));
                setPage(1);
              }}
              placeholder="Todos los estados"
            >
              {["completed", "error", "limit_reached"].map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </Select>
            <Input
              aria-label="Modelo"
              className="w-40"
              placeholder="modelo"
              value={filters.model}
              onChange={(e) => setFilters((f) => ({ ...f, model: e.target.value }))}
            />
            <Input
              aria-label="Buscar en input u output"
              className="w-56"
              placeholder="buscar en input/output…"
              value={filters.q}
              onChange={(e) => setFilters((f) => ({ ...f, q: e.target.value }))}
            />
            <Button
              variant="primary"
              size="sm"
              onClick={() => {
                setPage(1);
                void loadAll();
              }}
            >
              Filtrar
            </Button>
            <Tabs variant="pill" value={String(hours)} onValueChange={(value) => setHours(Number(value))}>
              <TabsList>
                {WINDOWS.map((w) => (
                  <TabsTrigger key={w.hours} value={String(w.hours)}>
                    {w.label}
                  </TabsTrigger>
                ))}
              </TabsList>
            </Tabs>
          </Toolbar>

          <section className="min-w-0">
            <SectionHeader
              title="Traces"
              description={`${traces.length} trazas en la ventana seleccionada.`}
              actions={
                <>
                  <Select
                    aria-label="Trace A"
                    className="w-52"
                    value={selA}
                    onChange={(e) => setSelA(e.target.value)}
                    placeholder="Trace A…"
                  >
                    {traces.slice(0, 30).map((t) => (
                      <option key={t.id} value={t.trace_id}>
                        {t.trace_id.slice(0, 12)} · {t.input?.slice(0, 40)}
                      </option>
                    ))}
                  </Select>
                  <Select
                    aria-label="Trace B"
                    className="w-52"
                    value={selB}
                    onChange={(e) => setSelB(e.target.value)}
                    placeholder="Trace B…"
                  >
                    {traces.slice(0, 30).map((t) => (
                      <option key={t.id} value={t.trace_id}>
                        {t.trace_id.slice(0, 12)} · {t.input?.slice(0, 40)}
                      </option>
                    ))}
                  </Select>
                  <Button variant="secondary" size="sm" disabled={!selA || !selB} onClick={() => void doCompare()}>
                    <GitBranch size={13} aria-hidden /> Comparar
                  </Button>
                </>
              }
              className="mb-3"
            />
            <DataTable
              stickyHeader
              columns={columns}
              rows={pageRows}
              rowKey={(row) => row.id}
              sort={sort}
              onSortChange={(next) => {
                setSort(next);
                setPage(1);
              }}
              onRowClick={(row) => void showDetail(row.trace_id)}
              rowActions={(row) => (
                <Button variant="ghost" size="sm" onClick={() => void showDetail(row.trace_id)}>
                  Ver
                </Button>
              )}
              empty={
                <EmptyState
                  title="Sin trazas"
                  body="No hay trazas con los filtros actuales."
                  hint="Ampliá la ventana temporal o limpiá la búsqueda."
                />
              }
              footer={
                sorted.length > PAGE_SIZE ? (
                  <>
                    <ResultCount shown={pageRows.length} total={sorted.length} noun="trazas" />
                    <Pagination page={safePage} pageSize={PAGE_SIZE} total={sorted.length} onPageChange={setPage} />
                  </>
                ) : (
                  <ResultCount shown={sorted.length} total={sorted.length} noun="trazas" />
                )
              }
            />
          </section>

          <Drawer
            open={Boolean(detail)}
            onOpenChange={(open) => {
              if (!open) setDetail(null);
            }}
            title={detail ? `Trace · ${detail.trace_id.slice(0, 12)}` : "Trace"}
            description={detail ? `Org ${detail.organization_id.slice(0, 8)} · ${detail.started_at ? new Date(detail.started_at).toLocaleString("es-PE") : ""}` : undefined}
            width={560}
            footer={
              detail?.run_id ? (
                <Button variant="secondary" loading={analyzing} onClick={() => void analyze()}>
                  Root cause
                </Button>
              ) : undefined
            }
          >
            {detail && (
              <div className="space-y-5">
                <div className="flex flex-wrap items-center gap-2">
                  <StatusBadge status={detail.status} />
                  {detail.feedback && (
                    <Badge tone={detail.feedback.rating === "down" ? "danger" : "ok"}>
                      Feedback {detail.feedback.rating === "down" ? "negativo" : "positivo"}
                      {detail.feedback.reason ? ` · ${detail.feedback.reason}` : ""}
                    </Badge>
                  )}
                </div>

                <TraceWaterfall spans={detail.spans} totalLatencyMs={detail.total_latency_ms} markers={detail.markers} />

                <KeyValue
                  columns={2}
                  items={[
                    { key: "Modelo", value: detail.model ?? "—", mono: true },
                    { key: "Provider", value: detail.provider ?? "—", mono: true },
                    { key: "Entorno", value: detail.environment ?? "—" },
                    { key: "Versión", value: detail.version_id ? detail.version_id.slice(0, 8) : "—", mono: true },
                    { key: "Tokens", value: `${fmtNum(detail.total_tokens)} (${fmtNum(detail.prompt_tokens)} + ${fmtNum(detail.completion_tokens)})` },
                    { key: "Latencia", value: fmtLatency(detail.total_latency_ms) },
                    { key: "Costo", value: `$${detail.cost.toFixed(5)}`, mono: true },
                    { key: "Spans", value: fmtNum(detail.spans.length) },
                  ]}
                />

                {detail.feedback?.comment && (
                  <p className="rounded-md bg-raised px-3 py-2 text-[13px] leading-relaxed text-muted">
                    {detail.feedback.comment}
                  </p>
                )}

                <div>
                  <p className="eyebrow mb-2">Input</p>
                  <CodeBlock code={detail.input} language="text" maxHeight={160} />
                </div>
                <div>
                  <p className="eyebrow mb-2">Output</p>
                  <CodeBlock code={detail.output ?? "—"} language="text" maxHeight={220} />
                </div>
                {detail.error && <ErrorInline className="mb-0">{detail.error}</ErrorInline>}

                <div>
                  <p className="eyebrow mb-2">Correlación con billing</p>
                  <p className="text-[13px] text-muted">
                    {fmtNum(usage?.usage_events.length ?? 0)} usage events ·{" "}
                    {fmtNum(usage?.api_logs.length ?? 0)} api logs
                  </p>
                </div>

                {rootCause && <RootCausePanel data={rootCause} />}
              </div>
            )}
          </Drawer>

          {compare && (
            <section className="min-w-0">
              <SectionHeader
                title={`Comparación ${compare.same_input ? "(mismo input)" : "(inputs distintos)"}`}
                description="Diferencias entre dos trazas del mismo recorte."
                className="mb-3"
              />
              <Panel>
                <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                  {[compare.a, compare.b].map((side, index) => (
                    <div key={side.trace_id} className="min-w-0">
                      <div className="mb-2 flex flex-wrap items-center gap-2">
                        <span className="mono text-[13px] font-medium text-text">
                          {index === 0 ? "A" : "B"} · {side.trace_id.slice(0, 12)}
                        </span>
                        <StatusBadge status={side.status} />
                      </div>
                      <KeyValue
                        columns={2}
                        items={[
                          { key: "Modelo", value: side.model ?? "—", mono: true },
                          { key: "Latencia", value: fmtLatency(side.latency_ms) },
                          { key: "Tokens", value: fmtNum(side.tokens) },
                          { key: "Costo", value: `$${side.cost.toFixed(4)}`, mono: true },
                          { key: "Spans", value: fmtNum(side.spans_count) },
                        ]}
                      />
                      <div className="mt-3">
                        <CodeBlock code={index === 0 ? compare.output_a : compare.output_b} language="text" maxHeight={140} />
                      </div>
                    </div>
                  ))}
                </div>
                <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-border pt-3 text-xs text-muted">
                  <span>
                    Δ latencia{" "}
                    <span className={`mono ${compare.deltas.latency_ms > 0 ? "text-danger" : "text-ok"}`}>
                      {compare.deltas.latency_ms > 0 ? "+" : ""}
                      {compare.deltas.latency_ms.toFixed(0)}ms
                    </span>
                  </span>
                  <span className="mono">
                    Δ tokens {compare.deltas.tokens > 0 ? "+" : ""}
                    {fmtNum(compare.deltas.tokens)}
                  </span>
                  <span className="mono">
                    Δ costo {compare.deltas.cost > 0 ? "+" : ""}${compare.deltas.cost.toFixed(4)}
                  </span>
                </div>
                {compare.spans_diff.length > 0 && (
                  <div className="mt-3 divide-y divide-border-soft">
                    {compare.spans_diff.map((s) => (
                      <div key={s.stage} className="flex items-center justify-between gap-3 py-2 text-xs">
                        <span className="text-text">{s.stage}</span>
                        <span className="mono text-faint">A: {s.a_duration_ms != null ? fmtLatency(s.a_duration_ms) : "—"}</span>
                        <span className="mono text-faint">B: {s.b_duration_ms != null ? fmtLatency(s.b_duration_ms) : "—"}</span>
                      </div>
                    ))}
                  </div>
                )}
              </Panel>
            </section>
          )}
        </>
      )}
    </div>
  );
}

function TraceWaterfall({
  spans,
  totalLatencyMs,
  markers,
}: {
  spans: Span[];
  totalLatencyMs: number;
  markers: Markers | undefined;
}) {
  const ordered = [...spans].sort((a, b) => a.started_ms - b.started_ms);
  const minStart = ordered.length ? Math.min(...ordered.map((s) => s.started_ms)) : 0;
  const maxEnd = ordered.length
    ? Math.max(...ordered.map((s) => s.started_ms + s.duration_ms))
    : totalLatencyMs;
  const total = Math.max(maxEnd - minStart, totalLatencyMs, 1);
  const mk = markers;
  const bottleneckName = mk?.bottleneck?.name;

  return (
    <div className="rounded-md border border-border bg-raised p-3">
      <p className="eyebrow mb-2">Waterfall</p>
      {mk && (
        <div className="mb-3 flex flex-wrap gap-1.5">
          {mk.bottleneck && (
            <Badge tone="warn">
              Cuello de botella: {STAGE_LABEL[mk.bottleneck.stage] ?? mk.bottleneck.stage} ·{" "}
              {fmtLatency(mk.bottleneck.duration_ms)}
            </Badge>
          )}
          {mk.retries > 0 && <Badge tone="warn">{mk.retries} reintentos</Badge>}
          {mk.fallback_detected && <Badge tone="warn">Fallback · {mk.models_used.join(", ")}</Badge>}
          {mk.error_spans > 0 && <Badge tone="danger">{mk.error_spans} spans con error</Badge>}
        </div>
      )}
      <div className="space-y-1.5">
        {ordered.map((s) => {
          const left = Math.max(0, ((s.started_ms - minStart) / total) * 100);
          const width = Math.max(1, (s.duration_ms / total) * 100);
          const isError = s.status === "error";
          const isBottleneck = bottleneckName === s.name;
          return (
            <div key={s.id} className="flex items-center gap-2 text-[11px]">
              <span className="w-20 shrink-0 truncate text-faint" title={s.name}>
                {STAGE_LABEL[s.stage] ?? s.stage}
              </span>
              <div className="relative h-3.5 flex-1 rounded-sm bg-bg">
                <div
                  className={`absolute inset-y-0 rounded-sm ${
                    isError ? "bg-danger" : isBottleneck ? "bg-warn" : "bg-accent"
                  }`}
                  style={{ left: `${left}%`, width: `${width}%` }}
                  title={`${s.name} · ${fmtLatency(s.duration_ms)} · ${fmtNum(s.tokens)} tok${isError ? " · error" : ""}`}
                />
              </div>
              <span className="mono w-16 shrink-0 text-right text-faint">{fmtLatency(s.duration_ms)}</span>
            </div>
          );
        })}
        {ordered.length === 0 && <p className="py-2 text-center text-xs text-faint">Sin spans registrados.</p>}
      </div>
    </div>
  );
}

function RootCausePanel({ data }: { data: RootCause }) {
  return (
    <div className="rounded-md border border-border bg-raised p-3">
      <p className="eyebrow mb-2">Análisis de causa</p>
      {data.probable_causes.length === 0 && data.possible_contributing_factors.length === 0 && (
        <p className="text-xs text-faint">Sin señales claras de fallo en este run.</p>
      )}
      {data.probable_causes.length > 0 && (
        <div className="mb-2">
          <p className="eyebrow mb-1 text-danger">Probable cause</p>
          {data.probable_causes.map((c) => (
            <CauseRow key={c.factor} label={c.label} evidence={c.evidence} tone="danger" />
          ))}
        </div>
      )}
      {data.possible_contributing_factors.length > 0 && (
        <div>
          <p className="eyebrow mb-1 text-warn">Possible contributing factor</p>
          {data.possible_contributing_factors.map((c) => (
            <CauseRow key={c.factor} label={c.label} evidence={c.evidence} tone="warn" />
          ))}
        </div>
      )}
    </div>
  );
}

function CauseRow({ label, evidence, tone }: { label: string; evidence: string[]; tone: "danger" | "warn" }) {
  return (
    <div className="mb-1.5 rounded-md bg-surface px-2 py-1.5">
      <p className={`text-[13px] font-medium ${tone === "danger" ? "text-danger" : "text-warn"}`}>{label}</p>
      <ul className="list-disc pl-4 text-xs text-faint">
        {evidence.map((e, i) => (
          <li key={i}>{e}</li>
        ))}
      </ul>
    </div>
  );
}
