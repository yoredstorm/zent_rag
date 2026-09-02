import { Smiley, TrendUp } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import { ErrorInline, PageHeader, SkeletonBlock } from "../../components/ui";
import { usePlatformAuth } from "../../platformAuth";

type Analytics = { total_feedback: number; csat: number; nps: number; by_agent: { agent_id: string | null; total: number; ups: number; downs: number; csat: number; nps: number }[] };
type Negative = { total_negative: number; by_reason: { reason: string; total: number; pct: number }[]; correlation: { avg_latency_ms: number | null; avg_tokens: number | null; max_latency_ms: number | null; avg_output_length: number | null } };
type Trend = { series: { day: string; ups: number; downs: number; csat: number | null }[] };

const REASON_LABELS: Record<string, string> = { wrong_answer: "Respuesta incorrecta", too_long: "Demasiado larga", too_slow: "Demasiado lenta", confusing: "Confusa", other: "Otro" };

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

  const maxReason = Math.max(...(negative?.by_reason ?? []).map((r) => r.total), 1);

  return (
    <div className="space-y-6">
      <PageHeader title="Sentiment & Feedback" subtitle="CSAT, NPS, causas del feedback negativo y tendencias." />
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading ? (
        <SkeletonBlock className="h-40" />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <div className="panel p-4">
              <p className="stat-label">CSAT</p>
              <p className="stat-value">{(analytics?.csat ?? 0) * 100}%</p>
              <p className="mt-1 text-xs text-faint">{analytics?.total_feedback ?? 0} feedbacks</p>
            </div>
            <div className="panel p-4">
              <p className="stat-label">NPS (proxy)</p>
              <p className="stat-value">{analytics?.nps ?? 0}</p>
            </div>
            <div className="panel p-4">
              <p className="stat-label">Feedback negativo</p>
              <p className="stat-value text-red-400">{negative?.total_negative ?? 0}</p>
            </div>
            <div className="panel p-4">
              <p className="stat-label">Causa principal</p>
              <p className="stat-value text-xs">{REASON_LABELS[negative?.by_reason[0]?.reason ?? "other"] ?? "—"}</p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <select className="rounded-md border border-border bg-soft px-2 py-2 text-sm" value={orgId} onChange={(e) => setOrgId(e.target.value)}>
              <option value="">todas</option>
              {orgs.map((o) => (<option key={o.id} value={o.id}>{o.id.slice(0, 8)}</option>))}
            </select>
            {[24, 168, 720].map((h) => (
              <button key={h} type="button" onClick={() => setHours(h)} className={`btn min-h-8 px-3 text-xs ${hours === h ? "btn-primary" : "btn-secondary"}`}>{h === 720 ? "30d" : `${h / 24}d`}</button>
            ))}
          </div>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
            <section className="lg:col-span-2">
              <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text">
                <Smiley size={15} /> Por agente
              </h3>
              <div className="panel overflow-x-auto">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Agente</th>
                      <th>Feedbacks</th>
                      <th>Útiles</th>
                      <th>No útiles</th>
                      <th>CSAT</th>
                      <th>NPS</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(analytics?.by_agent ?? []).map((a) => (
                      <tr key={a.agent_id ?? "sin"}>
                        <td className="mono text-xs">{a.agent_id?.slice(0, 8) ?? "sin-agente"}</td>
                        <td className="text-xs">{a.total}</td>
                        <td className="text-xs text-emerald-400">{a.ups}</td>
                        <td className="text-xs text-red-400">{a.downs}</td>
                        <td className="text-xs">{(a.csat * 100).toFixed(0)}%</td>
                        <td className="text-xs">{a.nps.toFixed(0)}</td>
                      </tr>
                    ))}
                    {(analytics?.by_agent ?? []).length === 0 && <tr><td colSpan={6} className="p-4 text-center text-xs text-faint">Sin feedback.</td></tr>}
                  </tbody>
                </table>
              </div>
              <h3 className="mb-2 mt-4 flex items-center gap-2 text-sm font-semibold text-text">
                <TrendUp size={15} /> Tendencia diaria
              </h3>
              <div className="panel p-4">
                <div className="space-y-1">
                  {(trend?.series ?? []).map((s) => (
                    <div key={s.day} className="flex items-center gap-2 text-[11px]">
                      <span className="w-20 text-faint">{s.day}</span>
                      <span className="w-6 text-emerald-400">{s.ups}</span>
                      <div className="h-2 flex-1 rounded-full bg-soft">
                        <div className="h-2 rounded-full bg-emerald-400" style={{ width: `${(s.ups / Math.max(s.ups + s.downs, 1)) * 100}%` }} />
                      </div>
                      <span className="w-6 text-red-400">{s.downs}</span>
                      <span className="mono w-14 text-right text-faint">{s.csat != null ? `${(s.csat * 100).toFixed(0)}%` : "—"}</span>
                    </div>
                  ))}
                  {(trend?.series ?? []).length === 0 && <p className="text-xs text-faint">Sin datos.</p>}
                </div>
              </div>
            </section>

            <section className="panel p-4">
              <h3 className="mb-2 text-sm font-semibold text-text">Causas del negativo</h3>
              <div className="space-y-1">
                {(negative?.by_reason ?? []).map((r) => (
                  <div key={r.reason} className="flex items-center gap-2 text-xs">
                    <span className="w-32 truncate text-text">{REASON_LABELS[r.reason] ?? r.reason}</span>
                    <div className="h-2 flex-1 rounded-full bg-soft">
                      <div className="h-2 rounded-full bg-red-400" style={{ width: `${(r.total / maxReason) * 100}%` }} />
                    </div>
                    <span className="mono text-faint">{r.total}</span>
                  </div>
                ))}
                {(negative?.by_reason ?? []).length === 0 && <p className="text-xs text-faint">Sin feedback negativo.</p>}
              </div>
              <h4 className="mb-1 mt-3 text-[11px] font-semibold text-text">Correlación</h4>
              <p className="text-[10px] text-faint">
                Latencia avg <span className="text-text">{negative?.correlation.avg_latency_ms != null ? `${negative.correlation.avg_latency_ms.toFixed(0)}ms` : "—"}</span> · max {negative?.correlation.max_latency_ms != null ? `${negative.correlation.max_latency_ms.toFixed(0)}ms` : "—"} · tokens {negative?.correlation.avg_tokens != null ? negative.correlation.avg_tokens.toFixed(0) : "—"} · output {negative?.correlation.avg_output_length != null ? `${negative.correlation.avg_output_length.toFixed(0)} chars` : "—"}
              </p>
            </section>
          </div>
        </>
      )}
    </div>
  );
}