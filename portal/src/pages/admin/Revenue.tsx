import { DownloadSimple, TrendUp } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import { ErrorInline, PageHeader, SkeletonBlock } from "../../components/ui";
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

  return (
    <div className="space-y-6">
      <PageHeader title="Revenue Intelligence" subtitle="ARR/MRR, expansión/contracción, cohortes trial→paid y forecast." />
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading ? (
        <SkeletonBlock className="h-40" />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <div className="panel p-4">
              <p className="stat-label">MRR</p>
              <p className="stat-value">{fmtCents(summary?.mrr_cents ?? 0)}</p>
              <p className="mt-1 text-xs text-faint">ARR: {fmtCents(summary?.arr_cents ?? 0)}</p>
            </div>
            <div className="panel p-4">
              <p className="stat-label">Expansión (30d)</p>
              <p className="stat-value text-emerald-400">+{fmtCents(summary?.expansion_mrr_cents ?? 0)}</p>
              <p className="mt-1 text-xs text-faint">Neto: {fmtCents(summary?.net_mrr_delta_cents ?? 0)}</p>
            </div>
            <div className="panel p-4">
              <p className="stat-label">Contracción (30d)</p>
              <p className="stat-value text-red-400">-{fmtCents((summary?.contraction_mrr_cents ?? 0) + (summary?.churned_mrr_cents ?? 0))}</p>
              <p className="mt-1 text-xs text-faint">Downgrades + churn</p>
            </div>
            <div className="panel p-4">
              <p className="stat-label">Churn (30d)</p>
              <p className="stat-value">{(summary?.churn_rate ?? 0) * 100}%</p>
              <p className="mt-1 text-xs text-faint">{summary?.churned_subscribers ?? 0} de {summary?.subscribers_started ?? 0} · {summary?.trials_created ?? 0} trials</p>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <section className="panel p-4">
              <h3 className="mb-2 text-sm font-semibold text-text">MRR por plan</h3>
              <div className="space-y-1.5">
                {(summary?.by_plan ?? []).map((p) => (
                  <div key={p.plan} className="flex items-center gap-2 text-xs">
                    <span className="w-24 truncate text-text">{p.plan}{p.is_trial ? " (trial)" : ""}</span>
                    <div className="h-2.5 flex-1 rounded-full bg-soft">
                      <div className="h-2.5 rounded-full bg-accent" style={{ width: `${(p.mrr_cents / maxMrr) * 100}%` }} />
                    </div>
                    <span className="mono w-28 text-right text-faint">{fmtCents(p.mrr_cents)} · {p.subscribers} subs</span>
                  </div>
                ))}
              </div>
            </section>

            <section className="panel p-4">
              <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text">
                <TrendUp size={15} aria-hidden /> Forecast (6 meses)
              </h3>
              <p className="text-xs text-faint">
                Conv. media {(forecast?.avg_conversion_rate ?? 0) * 100}% · crecimiento trials ×{forecast?.trial_growth_rate ?? 1}
              </p>
              <div className="mt-2 space-y-1">
                {(forecast?.projected ?? []).map((p) => (
                  <div key={p.month} className="flex items-center justify-between rounded-md bg-soft px-3 py-1.5 text-xs">
                    <span className="mono text-text">{p.month}</span>
                    <span className="text-faint">{p.expected_trials} trials → {p.expected_conversions} conv</span>
                    <span className="mono text-text">+{fmtCents(p.new_mrr_cents)} MRR</span>
                  </div>
                ))}
              </div>
            </section>
          </div>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <section className="panel p-4">
              <h3 className="mb-2 text-sm font-semibold text-text">Cohortes trial→paid</h3>
              <div className="overflow-x-auto">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Mes</th>
                      <th>Trials</th>
                      <th>Convertidos</th>
                      <th>Tasa</th>
                      <th>Retenidos</th>
                      <th>MRR hoy</th>
                    </tr>
                  </thead>
                  <tbody>
                    {funnels.map((f) => (
                      <tr key={f.cohort}>
                        <td className="mono text-xs">{f.cohort}</td>
                        <td className="text-xs">
                          <span className="mr-1">{f.trials}</span>
                          <div className="inline-block h-1.5 w-20 rounded-full bg-soft align-middle">
                            <div className="h-1.5 rounded-full bg-accent" style={{ width: `${(f.trials / maxConv) * 100}%` }} />
                          </div>
                        </td>
                        <td className="text-xs">{f.converted}</td>
                        <td className="text-xs">{(f.conversion_rate * 100).toFixed(1)}%</td>
                        <td className="text-xs">{f.retained}</td>
                        <td className="mono text-xs">{fmtCents(f.mrr_cents_now)}</td>
                      </tr>
                    ))}
                    {funnels.length === 0 && <tr><td colSpan={6} className="p-4 text-center text-xs text-faint">Sin cohortes.</td></tr>}
                  </tbody>
                </table>
              </div>
            </section>

            <section className="panel p-4">
              <div className="mb-2 flex items-center justify-between">
                <h3 className="text-sm font-semibold text-text">Ledger (30d)</h3>
                <button
                  type="button"
                  className="btn btn-secondary min-h-8 px-2 text-xs"
                  onClick={() => {
                    if (!session) return;
                    window.open(`/api/v1/platform/revenue/export.csv?token=${encodeURIComponent(session.token)}`, "_blank");
                  }}
                >
                  <DownloadSimple size={13} aria-hidden /> CSV
                </button>
              </div>
              <div className="max-h-72 overflow-auto">
                {events.map((e) => (
                  <div key={e.id} className="flex items-center justify-between rounded-md bg-soft px-3 py-1.5 text-[11px]">
                    <span className="truncate text-text">{e.event_type} · {e.plan_name ?? "—"}</span>
                    <span className={`mono ${e.mrr_cents > 0 ? "text-emerald-400" : "text-faint"}`}>
                      {e.mrr_cents > 0 ? `+${fmtCents(e.mrr_cents)}` : fmtCents(e.mrr_cents)}
                    </span>
                    <span className="text-faint">{new Date(e.created_at).toLocaleString()}</span>
                  </div>
                ))}
                {events.length === 0 && <p className="text-xs text-faint">Sin eventos.</p>}
              </div>
            </section>
          </div>
        </>
      )}
    </div>
  );
}