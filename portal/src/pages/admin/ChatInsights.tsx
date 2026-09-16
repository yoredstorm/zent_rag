import { ChatText, TrendUp } from "@phosphor-icons/react";
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
  Metric,
  MetricGrid,
  PageHeader,
  Panel,
  PanelHeader,
  SectionHeader,
  Skeleton,
  type Column,
  type SortState,
} from "../../components/ui";
import { fmtDate, fmtNum } from "../../lib/format";
import { usePlatformAuth } from "../../platformAuth";

type Topic = { topic: string; message_count: number };
type DayPoint = { date: string; messages: number; resolution_rate: number };
type Dash = { sessions_30d: number; messages_30d: number; messages_per_session: number; organizations_using: number; escalations_30d: number; top_topics: Topic[]; daily_trend: DayPoint[] };

/** Tooltip del sistema: una sola superficie, tokens, sin cromo extra. */
function TrendTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: { payload: DayPoint }[];
}) {
  if (!active || !payload?.length) return null;
  const point = payload[0].payload;
  return (
    <div className="rounded-sm border border-border bg-overlay px-2.5 py-1.5 text-xs shadow-pop">
      <p className="text-muted">{fmtDate(point.date)}</p>
      <p className="mt-0.5 text-text">
        <span className="font-medium tabular-nums">{fmtNum(point.messages)}</span> mensajes
      </p>
      <p className="text-muted">
        Resolución <span className="tabular-nums">{point.resolution_rate}%</span>
      </p>
    </div>
  );
}

export default function AdminChatInsightsPage() {
  const { session } = usePlatformAuth();
  const [dash, setDash] = useState<Dash | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [sort, setSort] = useState<SortState>({ key: "message_count", dir: "desc" });
  const reduce = useReducedMotion();

  async function load() {
    if (!session) return;
    setError("");
    try {
      const d = await platformApi<Dash>("/api/v1/platform/chat-insights/dashboard", { token: session.token });
      setDash(d);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    const id = setInterval(() => void load(), 15000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  const topics = useMemo(() => {
    const rows = [...(dash?.top_topics ?? [])];
    if (!sort) return rows;
    return rows.sort((a, b) =>
      sort.dir === "asc"
        ? a.message_count - b.message_count
        : b.message_count - a.message_count
    );
  }, [dash?.top_topics, sort]);

  const trend = dash?.daily_trend ?? [];
  const topicColumns: Column<Topic>[] = [
    {
      key: "topic",
      header: "Tema",
      render: (row) => <span className="text-[13px] text-text">{row.topic}</span>,
    },
    {
      key: "message_count",
      header: "Mensajes",
      align: "right",
      sortable: true,
      width: "120px",
      render: (row) => <span className="mono text-xs text-muted">{fmtNum(row.message_count)}</span>,
    },
  ];

  return (
    <div className="space-y-6">
      <PageHeader title="Chat Insights" subtitle="Conversaciones en todas las organizaciones: volumen, temas, resolución y escalaciones." />
      <ErrorInline message={error} />
      {loading ? (
        <div className="flex flex-col gap-3" aria-hidden>
          <Skeleton className="h-[86px] rounded-lg" />
          <Skeleton className="h-[260px] rounded-lg" />
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
            <Metric
              label="Mensajes 30d"
              value={(dash?.messages_30d ?? 0).toLocaleString()}
              hint={`${(dash?.sessions_30d ?? 0).toLocaleString()} sesiones en el periodo`}
              icon={ChatText}
            />
            <MetricGrid cols={4} className="lg:grid-cols-4">
              <Metric label="Sesiones 30d" value={(dash?.sessions_30d ?? 0).toLocaleString()} size="md" />
              <Metric
                label="Msgs / sesión"
                value={dash?.messages_per_session ?? 0}
                size="md"
                hint="Promedio del periodo"
              />
              <Metric label="Organizaciones" value={(dash?.organizations_using ?? 0).toLocaleString()} size="md" />
              <Metric
                label="Escalaciones 30d"
                value={(dash?.escalations_30d ?? 0).toLocaleString()}
                size="md"
                tone={(dash?.escalations_30d ?? 0) > 0 ? "warn" : "default"}
              />
            </MetricGrid>
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <Panel className="lg:col-span-2">
              <PanelHeader
                title={
                  <span className="flex items-center gap-2">
                    <TrendUp size={15} aria-hidden /> Tendencia diaria
                  </span>
                }
                description="Mensajes por día y tasa de resolución de la ventana reportada."
              />
              {trend.length === 0 ? (
                <EmptyState
                  compact
                  icon={TrendUp}
                  title="Sin agregación diaria"
                  body="Aparecerá cuando la primera organización acumule conversaciones en el periodo."
                />
              ) : (
                <div className="panel-body">
                  <div
                    role="img"
                    aria-label={`Mensajes por día: ${trend.length} días con ${fmtNum(trend.reduce((n, d) => n + d.messages, 0))} mensajes en total.`}
                  >
                    <ResponsiveContainer width="100%" height={240}>
                      <BarChart data={trend} margin={{ top: 4, right: 8, bottom: 0, left: 0 }} accessibilityLayer>
                        <CartesianGrid stroke="var(--color-border-soft)" vertical={false} />
                        <XAxis
                          dataKey="date"
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
                          width={44}
                          tickFormatter={(value: number) => fmtNum(value)}
                        />
                        <Tooltip cursor={{ fill: "var(--color-soft)", fillOpacity: 0.55 }} content={<TrendTooltip />} />
                        <Bar
                          dataKey="messages"
                          name="Mensajes"
                          fill="var(--color-accent)"
                          radius={[4, 4, 0, 0]}
                          maxBarSize={26}
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

            <section className="min-w-0">
              <SectionHeader
                title={
                  <span className="flex items-center gap-2">
                    <ChatText size={15} aria-hidden /> Temas globales
                  </span>
                }
                description="Intenciones más frecuentes entre organizaciones."
                className="mb-3"
              />
              <DataTable
                stickyHeader
                columns={topicColumns}
                rows={topics}
                rowKey={(row) => row.topic}
                sort={sort}
                onSortChange={setSort}
                empty={
                  <EmptyState
                    compact
                    icon={ChatText}
                    title="Sin temas aún"
                    body="La clasificación aparece cuando hay mensajes suficientes."
                  />
                }
              />
            </section>
          </div>
        </>
      )}
    </div>
  );
}
