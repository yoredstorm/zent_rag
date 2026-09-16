import { DownloadSimple, TrendUp } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import {
  Button,
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
} from "../../components/ui";
import { usePlatformAuth } from "../../platformAuth";

type Summary = {
  mrr_cents: number;
  arr_cents: number;
  by_plan: { plan: string; is_trial: boolean; subscribers: number; mrr_cents: number; arr_cents: number }[];
  trials_created: number;
  subscribers_started: number;
  churned_subscribers: number;
  churn_rate: number;
  expansion_mrr_cents: number;
  contraction_mrr_cents: number;
  churned_mrr_cents: number;
  net_mrr_delta_cents: number;
};

type Funnel = { cohort: string; trials: number; converted: number; conversion_rate: number; retained: number; mrr_cents_now: number };
type Forecast = { current_mrr_cents: number; avg_conversion_rate: number; trial_growth_rate: number; projected: { month: string; expected_trials: number; expected_conversions: number; new_mrr_cents: number }[] };
type Event = { id: string; organization_id: string; event_type: string; plan_name: string | null; mrr_cents: number; created_at: string };

const fmtCents = (c: number) => `$${(c / 100).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;

function pct(value: number) {
  return `${value.toFixed(1)}%`;
}

export default function AdminRevenuePage() {
  const { session } = usePlatformAuth();
  const [summary, setSummary] = useState<Summary | null>(null);
  const [funnels, setFunnels] = useState<Funnel[]>([]);
  const [forecast, setForecast] = useState<Forecast | null>(null);
  const [events, setEvents] = useState<Event[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load() {
    if (!session) return;
    setError("");
    try {
      const [s, f, fc, e] = await Promise.all([
        platformApi<Summary>("/api/v1/platform/revenue/summary?days=30", { token: session.token }),
        platformApi<{ funnels: Funnel[] }>("/api/v1/platform/revenue/funnels?months=12", { token: session.token }),
        platformApi<Forecast>("/api/v1/platform/revenue/forecast?months=6", { token: session.token }),
        platformApi<{ events: Event[] }>("/api/v1/platform/revenue/events?days=30", { token: session.token }),
      ]);
      setSummary(s);
      setFunnels(f.funnels || []);
      setForecast(fc);
      setEvents(e.events || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  const maxMrr = Math.max(...(summary?.by_plan ?? []).map((p) => p.mrr_cents), 1);
  const maxConv = Math.max(...funnels.map((f) => f.trials), 1);

  const cohortColumns: Column<Funnel>[] = [
    { key: "cohort", header: "Mes", render: (f) => <span className="mono text-xs">{f.cohort}</span> },
    {
      key: "trials",
      header: "Trials",
      render: (f) => (
        <span className="flex items-center gap-2">
          <span className="mono tabular-nums">{f.trials}</span>
          <span className="progress-track w-20">
            <span className="progress-fill block" style={{ width: `${(f.trials / maxConv) * 100}%` }} />
          </span>
        </span>
      ),
    },
    { key: "converted", header: "Convertidos", align: "right", render: (f) => <span className="mono">{f.converted}</span> },
    {
      key: "rate",
      header: "Tasa",
      align: "right",
      render: (f) => <span className="mono">{pct(f.conversion_rate * 100)}</span>,
    },
    {
      key: "retained",
      header: "Retenidos",
      align: "right",
      hideBelow: "md",
      render: (f) => <span className="mono">{f.retained}</span>,
    },
    {
      key: "mrr",
      header: "MRR hoy",
      align: "right",
      hideBelow: "md",
      render: (f) => <span className="mono">{fmtCents(f.mrr_cents_now)}</span>,
    },
  ];

  return (
    <div className="flex flex-col gap-3">
      <PageHeader
        title="Revenue Intelligence"
        subtitle="ARR/MRR, expansión/contracción, cohortes trial→paid y forecast."
      />
      {error && <ErrorInline message={error} />}
      {loading ? (
        <div className="flex flex-col gap-3" aria-hidden>
          <Skeleton className="h-[116px] rounded-lg" />
          <Skeleton className="h-[220px] rounded-lg" />
        </div>
      ) : (
        <>
          {/* Foco: el MRR manda; expansión/contracción quedan como contexto */}
          <Panel className="p-4">
            <p className="eyebrow">MRR · últimos 30 días</p>
            <p className="mt-1.5 text-display tabular-nums">{fmtCents(summary?.mrr_cents ?? 0)}</p>
            <p className="mt-2 text-[13px] text-muted">
              ARR <span className="mono text-text">{fmtCents(summary?.arr_cents ?? 0)}</span>
              <span className="mx-1.5 text-ghost">·</span>
              Neto 30d{" "}
              <span className="mono text-text">
                {summary ? `${summary.net_mrr_delta_cents >= 0 ? "+" : ""}${fmtCents(summary.net_mrr_delta_cents)}` : "—"}
              </span>
            </p>
          </Panel>

          <MetricGrid cols={3}>
            <Metric
              size="md"
              label="Expansión (30d)"
              value={`+${fmtCents(summary?.expansion_mrr_cents ?? 0)}`}
              tone="ok"
              icon={TrendUp}
            />
            <Metric
              size="md"
              label="Contracción (30d)"
              value={`-${fmtCents((summary?.contraction_mrr_cents ?? 0) + (summary?.churned_mrr_cents ?? 0))}`}
              tone="danger"
              hint="Downgrades + churn"
            />
            <Metric
              size="md"
              label="Churn (30d)"
              value={pct((summary?.churn_rate ?? 0) * 100)}
              hint={`${summary?.churned_subscribers ?? 0} de ${summary?.subscribers_started ?? 0} · ${summary?.trials_created ?? 0} trials`}
            />
          </MetricGrid>

          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
            <Panel>
              <PanelHeader title="MRR por plan" description="Contribución real de cada plan al MRR." />
              {(summary?.by_plan ?? []).length === 0 ? (
                <EmptyState compact title="Sin planes con suscriptores" body="No hay MRR atribuible a planes en la ventana de 30 días." />
              ) : (
                <ul className="flex flex-col gap-3 p-4">
                  {(summary?.by_plan ?? []).map((p) => (
                    <li key={p.plan} className="flex flex-col gap-1.5">
                      <div className="flex items-baseline justify-between gap-3 text-xs">
                        <span className="truncate text-text">
                          {p.plan}
                          {p.is_trial ? " (trial)" : ""}
                        </span>
                        <span className="mono shrink-0 text-faint">
                          {fmtCents(p.mrr_cents)} · {p.subscribers} subs
                        </span>
                      </div>
                      <span className="progress-track">
                        <span
                          className="progress-fill block"
                          style={{ width: `${(p.mrr_cents / maxMrr) * 100}%` }}
                        />
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>

            <Panel>
              <PanelHeader
                title="Forecast (6 meses)"
                description={
                  forecast
                    ? `Conv. media ${pct((forecast.avg_conversion_rate ?? 0) * 100)} · crecimiento trials ×${forecast.trial_growth_rate ?? 1}`
                    : "Proyección basada en cohortes reales."
                }
              />
              {(forecast?.projected ?? []).length === 0 ? (
                <EmptyState compact title="Sin proyecciones" body="No hay cohortes suficientes para proyectar MRR." />
              ) : (
                <ul className="flex flex-col gap-1.5 p-4">
                  {(forecast?.projected ?? []).map((p) => (
                    <li
                      key={p.month}
                      className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 rounded-sm bg-soft px-3 py-2 text-xs"
                    >
                      <span className="mono text-text">{p.month}</span>
                      <span className="text-faint">
                        {p.expected_trials} trials <span className="text-ghost">·</span> {p.expected_conversions} conv
                      </span>
                      <span className="mono text-text">+{fmtCents(p.new_mrr_cents)} MRR</span>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
          </div>

          <section>
            <SectionHeader
              title="Cohortes trial→paid"
              description="Últimos 12 meses de conversión y retención real."
              className="mb-3"
            />
            <DataTable
              columns={cohortColumns}
              rows={funnels}
              rowKey={(f) => f.cohort}
              caption="Cohortes trial a paid por mes"
              stickyHeader
              empty={
                <EmptyState
                  icon={TrendUp}
                  title="Sin cohortes"
                  body="No hay cohortes trial→paid en los últimos 12 meses."
                />
              }
            />
          </section>

          <section>
            <SectionHeader
              title="Ledger (30d)"
              description="Eventos de revenue registrados en los últimos 30 días."
              className="mb-3"
              actions={
                <Button
                  variant="secondary"
                  size="sm"
                  leadingIcon={DownloadSimple}
                  onClick={() => {
                    if (!session) return;
                    window.open(`/api/v1/platform/revenue/export.csv?token=${encodeURIComponent(session.token || "")}`, "_blank");
                  }}
                >
                  CSV
                </Button>
              }
            />
            <Panel className="max-h-72 overflow-auto">
              {events.length === 0 ? (
                <EmptyState compact title="Sin eventos" body="No se registraron eventos de revenue en la ventana." />
              ) : (
                <ul className="divide-y divide-border-soft px-4">
                  {events.map((e) => (
                    <li
                      key={e.id}
                      className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 py-2.5 text-[11px]"
                    >
                      <span className="truncate text-text">
                        {e.event_type} · {e.plan_name ?? "—"}
                      </span>
                      <span className={`mono ${e.mrr_cents > 0 ? "text-ok" : "text-faint"}`}>
                        {e.mrr_cents > 0 ? `+${fmtCents(e.mrr_cents)}` : fmtCents(e.mrr_cents)}
                      </span>
                      <span className="text-faint">{new Date(e.created_at).toLocaleString()}</span>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
          </section>
        </>
      )}
    </div>
  );
}
