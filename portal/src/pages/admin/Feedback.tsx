import { ChartBar, Smiley, TrendUp } from "@phosphor-icons/react";
import { useReducedMotion } from "motion/react";
import { useEffect, useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { platformApi } from "../../api";
import {
  DataTable,
  EmptyState,
  ErrorInline,
  KeyValue,
  Metric,
  MetricGrid,
  PageHeader,
  Panel,
  PanelHeader,
  SectionHeader,
  Select,
  Skeleton,
  Tabs,
  TabsList,
  TabsTrigger,
  Toolbar,
  type Column,
  type SortState,
} from "../../components/ui";
import { fmtNum } from "../../lib/format";
import { usePlatformAuth } from "../../platformAuth";

type AgentRow = { agent_id: string | null; total: number; ups: number; downs: number; csat: number; nps: number };
type ReasonRow = { reason: string; total: number; pct: number };
type DayRow = { day: string; ups: number; downs: number; csat: number | null };
type Analytics = { total_feedback: number; csat: number; nps: number; by_agent: AgentRow[] };
type Negative = { total_negative: number; by_reason: ReasonRow[]; correlation: { avg_latency_ms: number | null; avg_tokens: number | null; max_latency_ms: number | null; avg_output_length: number | null } };
type Trend = { series: DayRow[] };

const REASON_LABELS: Record<string, string> = { wrong_answer: "Respuesta incorrecta", too_long: "Demasiado larga", too_slow: "Demasiado lenta", confusing: "Confusa", other: "Otro" };

const RANGES = [
  { hours: 24, label: "24h" },
  { hours: 168, label: "7d" },
  { hours: 720, label: "30d" },
] as const;

function TrendTooltip({ active, payload }: { active?: boolean; payload?: { payload: DayRow }[] }) {
  if (!active || !payload?.length) return null;
  const point = payload[0].payload;
  return (
    <div className="rounded-sm border border-border bg-overlay px-2.5 py-1.5 text-xs shadow-pop">
      <p className="text-muted">{point.day}</p>
      <p className="mt-0.5 text-text">
        <span className="font-medium tabular-nums text-ok">{point.ups}</span> útiles ·{" "}
        <span className="font-medium tabular-nums text-danger">{point.downs}</span> no útiles
      </p>
      <p className="text-muted">
        CSAT <span className="tabular-nums">{point.csat != null ? `${(point.csat * 100).toFixed(0)}%` : "—"}</span>
      </p>
    </div>
  );
}

export default function AdminFeedbackPage() {
  const { session } = usePlatformAuth();
  const [analytics, setAnalytics] = useState<Analytics | null>(null);
  const [negative, setNegative] = useState<Negative | null>(null);
  const [trend, setTrend] = useState<Trend | null>(null);
  const [orgs, setOrgs] = useState<{ id: string }[]>([]);
  const [orgId, setOrgId] = useState("");
  const [hours, setHours] = useState(168);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [sort, setSort] = useState<SortState>({ key: "total", dir: "desc" });
  const reduce = useReducedMotion();

  async function loadAll() {
    if (!session) return;
    setError("");
    try {
      const q = new URLSearchParams({ hours: String(hours) });
      if (orgId) q.set("organization_id", orgId);
      const [a, n, t] = await Promise.all([
        platformApi<Analytics>(`/api/v1/platform/feedback/analytics?${q}`, { token: session.token }),
        platformApi<Negative>(`/api/v1/platform/feedback/negative?${q}`, { token: session.token }),
        platformApi<Trend>(`/api/v1/platform/feedback/trends${orgId ? `?organization_id=${orgId}` : ""}`, { token: session.token }),
      ]);
      setAnalytics(a);
      setNegative(n);
      setTrend(t);
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
    const id = setInterval(() => void loadAll(), 15000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session, orgId, hours]);

  const rows = useMemo(() => {
    const list = [...(analytics?.by_agent ?? [])];
    if (!sort) return list;
    const value = (row: AgentRow, key: string) =>
      key === "csat" ? row.csat : key === "nps" ? row.nps : key === "ups" ? row.ups : key === "downs" ? row.downs : row.total;
    return list.sort((a, b) =>
      sort.dir === "asc" ? value(a, sort.key) - value(b, sort.key) : value(b, sort.key) - value(a, sort.key)
    );
  }, [analytics?.by_agent, sort]);

  const reasons = negative?.by_reason ?? [];
  const series = trend?.series ?? [];
  const maxReason = Math.max(1, ...reasons.map((r) => r.total));
  const mainReason = reasons[0]?.reason;

  const columns: Column<AgentRow>[] = [
    {
      key: "agent_id",
      header: "Agente",
      render: (row) => <span className="mono text-xs text-faint">{row.agent_id?.slice(0, 8) ?? "sin-agente"}</span>,
    },
    {
      key: "total",
      header: "Feedbacks",
      align: "right",
      sortable: true,
      width: "110px",
      render: (row) => <span className="mono text-xs text-muted">{fmtNum(row.total)}</span>,
    },
    {
      key: "ups",
      header: "Útiles",
      align: "right",
      sortable: true,
      width: "100px",
      render: (row) => <span className="mono text-xs text-ok">{fmtNum(row.ups)}</span>,
    },
    {
      key: "downs",
      header: "No útiles",
      align: "right",
      sortable: true,
      width: "110px",
      render: (row) => <span className="mono text-xs text-danger">{fmtNum(row.downs)}</span>,
    },
    {
      key: "csat",
      header: "CSAT",
      align: "right",
      sortable: true,
      hideBelow: "md",
      width: "100px",
      render: (row) => <span className="mono text-xs text-muted">{(row.csat * 100).toFixed(0)}%</span>,
    },
    {
      key: "nps",
      header: "NPS",
      align: "right",
      sortable: true,
      hideBelow: "md",
      width: "90px",
      render: (row) => <span className="mono text-xs text-muted">{row.nps.toFixed(0)}</span>,
    },
  ];

  return (
    <div className="space-y-6">
      <PageHeader title="Sentiment & Feedback" subtitle="CSAT, NPS, causas del feedback negativo y tendencias." />
      <ErrorInline message={error} />
      {loading ? (
        <div className="flex flex-col gap-3" aria-hidden>
          <Skeleton className="h-[86px] rounded-lg" />
          <Skeleton className="h-[240px] rounded-lg" />
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
            <Metric
              label="CSAT"
              value={`${((analytics?.csat ?? 0) * 100).toFixed(1)}%`}
              hint={`${fmtNum(analytics?.total_feedback ?? 0)} feedbacks en la ventana`}
              icon={Smiley}
            />
            <MetricGrid cols={3} className="lg:grid-cols-3">
              <Metric label="NPS (proxy)" value={(analytics?.nps ?? 0).toFixed(0)} size="md" />
              <Metric
                label="Feedback negativo"
                value={fmtNum(negative?.total_negative ?? 0)}
                size="md"
                tone={(negative?.total_negative ?? 0) > 0 ? "danger" : "default"}
              />
              <Metric
                label="Causa principal"
                value={
                  <span className="text-[15px] font-medium">
                    {mainReason ? REASON_LABELS[mainReason] ?? mainReason : "—"}
                  </span>
                }
                size="md"
                hint={reasons[0] ? `${fmtNum(reasons[0].total)} casos` : "Sin feedback negativo"}
              />
            </MetricGrid>
          </div>

          <Toolbar>
            <Select
              aria-label="Organización"
              className="w-44"
              value={orgId}
              onChange={(e) => setOrgId(e.target.value)}
              placeholder="Todas las organizaciones"
            >
              {orgs.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.id.slice(0, 8)}
                </option>
              ))}
            </Select>
            <Tabs variant="pill" value={String(hours)} onValueChange={(value) => setHours(Number(value))}>
              <TabsList>
                {RANGES.map((range) => (
                  <TabsTrigger key={range.hours} value={String(range.hours)}>
                    {range.label}
                  </TabsTrigger>
                ))}
              </TabsList>
            </Tabs>
          </Toolbar>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
            <section className="min-w-0 lg:col-span-2">
              <SectionHeader
                title={
                  <span className="flex items-center gap-2">
                    <Smiley size={15} aria-hidden /> Por agente
                  </span>
                }
                className="mb-3"
              />
              <DataTable
                stickyHeader
                columns={columns}
                rows={rows}
                rowKey={(row) => row.agent_id ?? "sin-agente"}
                sort={sort}
                onSortChange={setSort}
                empty={
                  <EmptyState compact icon={Smiley} title="Sin feedback" body="Cuando los usuarios califiquen respuestas vas a ver el detalle por agente." />
                }
              />

              <div className="mt-6">
                <SectionHeader
                  title={
                    <span className="flex items-center gap-2">
                      <TrendUp size={15} aria-hidden /> Tendencia diaria
                    </span>
                  }
                  className="mb-3"
                />
                <Panel>
                  {series.length === 0 ? (
                    <EmptyState compact icon={TrendUp} title="Sin datos en la ventana" body="La serie diaria se construye con feedback calificado." />
                  ) : (
                    <div className="panel-body">
                      <div
                        role="img"
                        aria-label={`Feedback diario: ${series.reduce((n, d) => n + d.ups, 0)} útiles y ${series.reduce((n, d) => n + d.downs, 0)} no útiles en ${series.length} días.`}
                      >
                        <ResponsiveContainer width="100%" height={220}>
                          <BarChart data={series} margin={{ top: 4, right: 8, bottom: 0, left: 0 }} accessibilityLayer>
                            <CartesianGrid stroke="var(--color-border-soft)" vertical={false} />
                            <XAxis
                              dataKey="day"
                              tick={{ fill: "var(--color-muted)", fontSize: 11 }}
                              tickLine={false}
                              axisLine={{ stroke: "var(--color-border)" }}
                              minTickGap={24}
                              tickFormatter={(value: string) => (value.length >= 10 ? value.slice(5) : value)}
                            />
                            <YAxis
                              allowDecimals={false}
                              tick={{ fill: "var(--color-muted)", fontSize: 11 }}
                              tickLine={false}
                              axisLine={false}
                              width={36}
                              tickFormatter={(value: number) => fmtNum(value)}
                            />
                            <Tooltip cursor={{ fill: "var(--color-soft)", fillOpacity: 0.55 }} content={<TrendTooltip />} />
                            <Bar
                              dataKey="ups"
                              name="Útiles"
                              fill="var(--color-ok)"
                              radius={[3, 3, 0, 0]}
                              maxBarSize={18}
                              isAnimationActive={!reduce}
                              animationDuration={340}
                              animationEasing="ease-out"
                            />
                            <Bar
                              dataKey="downs"
                              name="No útiles"
                              fill="var(--color-danger)"
                              radius={[3, 3, 0, 0]}
                              maxBarSize={18}
                              isAnimationActive={!reduce}
                              animationDuration={340}
                              animationEasing="ease-out"
                            />
                          </BarChart>
                        </ResponsiveContainer>
                      </div>
                    </div>
                  )}
                </Panel>
              </div>
            </section>

            <section className="min-w-0">
              <Panel>
                <PanelHeader
                  title={
                    <span className="flex items-center gap-2">
                      <ChartBar size={15} aria-hidden /> Causas del negativo
                    </span>
                  }
                  description={`${fmtNum(negative?.total_negative ?? 0)} casos en la ventana.`}
                />
                {reasons.length === 0 ? (
                  <EmptyState compact icon={Smiley} title="Sin feedback negativo" body="Ninguna respuesta fue calificada como no útil." />
                ) : (
                  <ul className="divide-y divide-border-soft">
                    {reasons.map((r) => (
                      <li key={r.reason} className="px-4 py-2.5">
                        <div className="flex items-baseline justify-between gap-3">
                          <span className="min-w-0 truncate text-[13px] text-text">{REASON_LABELS[r.reason] ?? r.reason}</span>
                          <span className="mono shrink-0 text-xs text-muted">{fmtNum(r.total)}</span>
                        </div>
                        <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-track" aria-hidden>
                          <div className="h-full rounded-full bg-danger" style={{ width: `${(r.total / maxReason) * 100}%` }} />
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
                <div className="border-t border-border px-4 py-3">
                  <p className="eyebrow mb-3">Correlación del negativo</p>
                  <KeyValue
                    columns={2}
                    items={[
                      { key: "Latencia media", value: negative?.correlation.avg_latency_ms != null ? `${negative.correlation.avg_latency_ms.toFixed(0)} ms` : "—", mono: true },
                      { key: "Latencia máx", value: negative?.correlation.max_latency_ms != null ? `${negative.correlation.max_latency_ms.toFixed(0)} ms` : "—", mono: true },
                      { key: "Tokens promedio", value: negative?.correlation.avg_tokens != null ? negative.correlation.avg_tokens.toFixed(0) : "—", mono: true },
                      { key: "Output promedio", value: negative?.correlation.avg_output_length != null ? `${negative.correlation.avg_output_length.toFixed(0)} chars` : "—", mono: true },
                    ]}
                  />
                </div>
              </Panel>
            </section>
          </div>
        </>
      )}
    </div>
  );
}
