import { ChartLineUp, Queue, Rocket } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import {
  ErrorInline,
  PageHeader,
  SkeletonBlock,
} from "../../components/ui";
import { usePlatformAuth } from "../../platformAuth";

type CapacityOrg = {
  organization_id: string;
  plan_limits: {
    requests_per_month: number;
    tokens_per_month: number;
    monthly_cost_limit: number;
    included_storage: number;
  };
  usage: { used_requests: number; used_tokens: number; used_cost: number };
  utilization_pct: { requests: number; tokens: number; cost: number };
  soft_limit_exceeded: boolean;
  hard_limit_exceeded: boolean;
  forecast_30d: { requests: number; utilization_pct: number };
  days_until_limit: number | null;
  projected_exceed_date: string | null;
};

type QueueDepth = { queue: string; depth: number; backend: string; error?: string };

export default function AdminCapacityPage() {
  const { session } = usePlatformAuth();
  const [summary, setSummary] = useState<{ near_limit: CapacityOrg[]; queues: QueueDepth[]; scaling_events: unknown[] } | null>(null);
  const [orgs, setOrgs] = useState<{ id: string }[]>([]);
  const [simulate, setSimulate] = useState({ org: "", growth_pct: 50, days: 30 });
  const [simResult, setSimResult] = useState("");
  const [autoScale, setAutoScale] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  async function load() {
    if (!session) return;
    setError("");
    try {
      const [s, o, ac] = await Promise.all([
        platformApi<{ near_limit: CapacityOrg[]; queues: QueueDepth[]; scaling_events: unknown[] }>(
          "/api/v1/platform/capacity/summary",
          { token: session.token }
        ),
        platformApi<{ organizations: { id: string }[] }>("/api/v1/platform/organizations", {
          token: session.token,
        }),
        platformApi<{ enabled: boolean }>("/api/v1/platform/capacity/workers/auto-scale", {
          token: session.token,
        }),
      ]);
      setSummary(s);
      setOrgs(o.organizations || []);
      setAutoScale(ac.enabled);
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

  async function doSimulate() {
    if (!session) return;
    setBusy("sim");
    setError("");
    setSimResult("");
    try {
      const out = await platformApi<Record<string, unknown>>("/api/v1/platform/capacity/simulate", {
        method: "POST",
        token: session.token,
        body: JSON.stringify({ organization_id: simulate.org, growth_pct: simulate.growth_pct, days: simulate.days }),
      });
      setSimResult(JSON.stringify(out, null, 2));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function toggleAutoScale() {
    if (!session) return;
    try {
      const out = await platformApi<{ enabled: boolean }>("/api/v1/platform/capacity/workers/auto-scale", {
        method: "POST",
        token: session.token,
        body: JSON.stringify({ enabled: !autoScale }),
      });
      setAutoScale(out.enabled);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Capacity Planning"
        subtitle="Forecast vs límites de plan, colas de workers y simulación de crecimiento."
        actions={
          <button type="button" className={`btn min-h-11 ${autoScale ? "btn-danger" : "btn-secondary"}`} onClick={() => void toggleAutoScale()}>
            <Rocket size={15} aria-hidden /> Auto-scaling: {autoScale ? "ON" : "OFF"}
          </button>
        }
      />
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading ? (
        <SkeletonBlock className="h-40" />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <div className="panel p-4">
              <p className="stat-label">Org cerca del límite</p>
              <p className="stat-value">{summary?.near_limit.length ?? 0}</p>
            </div>
            <div className="panel p-4">
              <p className="stat-label">Cola knowledge</p>
              <p className="stat-value">{summary?.queues.find((q) => q.queue === "knowledge")?.depth ?? 0}</p>
            </div>
            <div className="panel p-4">
              <p className="stat-label">Ingestión pending</p>
              <p className="stat-value">{summary?.queues.find((q) => q.queue === "ingestion_pending")?.depth ?? 0}</p>
            </div>
            <div className="panel p-4">
              <p className="stat-label">Eventos de escala</p>
              <p className="stat-value">{summary?.scaling_events.length ?? 0}</p>
            </div>
          </div>

          <section>
            <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text">
              <ChartLineUp size={15} aria-hidden /> Tenants cerca del límite
            </h3>
            <div className="panel overflow-x-auto">
              {(summary?.near_limit ?? []).length === 0 ? (
                <p className="p-4 text-sm text-muted">Ningún tenant cerca del límite (soft ≥80% o forecast ≥80% o ≤15 días).</p>
              ) : (
                <table className="table">
                  <thead>
                    <tr>
                      <th>Org</th>
                      <th>Requests</th>
                      <th>Uso</th>
                      <th>Soft</th>
                      <th>Hard</th>
                      <th>Forecast 30d</th>
                      <th>Días a límite</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(summary?.near_limit ?? []).map((o) => (
                      <tr key={o.organization_id}>
                        <td className="mono text-xs text-faint">{o.organization_id.slice(0, 13)}…</td>
                        <td className="text-xs">
                          {o.usage.used_requests.toLocaleString()} / {o.plan_limits.requests_per_month.toLocaleString()}
                        </td>
                        <td className="text-xs">
                          <div className="flex items-center gap-2">
                            <div className="h-2 w-20 overflow-hidden rounded bg-soft">
                              <div className={`h-full ${o.utilization_pct.requests >= 80 ? "bg-danger" : "bg-accent/70"}`} style={{ width: `${Math.min(o.utilization_pct.requests, 100)}%` }} />
                            </div>
                            {o.utilization_pct.requests}%
                          </div>
                        </td>
                        <td className="text-xs">{o.soft_limit_exceeded ? "✓" : "—"}</td>
                        <td className="text-xs">{o.hard_limit_exceeded ? "⚠" : "—"}</td>
                        <td className="text-xs">{o.forecast_30d.utilization_pct}%</td>
                        <td className="text-xs">{o.days_until_limit ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </section>

          <section>
            <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text">
              <Queue size={15} aria-hidden /> Colas de workers
            </h3>
            <div className="panel overflow-x-auto">
              <table className="table">
                <thead>
                  <tr>
                    <th>Cola</th>
                    <th>Backend</th>
                    <th>Profundidad</th>
                  </tr>
                </thead>
                <tbody>
                  {(summary?.queues ?? []).map((q) => (
                    <tr key={q.queue}>
                      <td className="mono text-xs">{q.queue}</td>
                      <td className="text-xs">{q.backend}</td>
                      <td className={`text-xs ${q.depth >= 50 ? "font-semibold text-danger" : ""}`}>{q.depth}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section>
            <h3 className="mb-2 text-sm font-semibold text-text">Simulación de crecimiento</h3>
            <div className="panel grid grid-cols-1 gap-3 p-4 lg:grid-cols-4">
              <select className="rounded-md border border-border bg-soft px-2 py-2 text-sm" value={simulate.org} onChange={(e) => setSimulate((f) => ({ ...f, org: e.target.value }))}>
                <option value="">Organización…</option>
                {orgs.map((o) => (
                  <option key={o.id} value={o.id}>{o.id.slice(0, 8)}</option>
                ))}
              </select>
              <input type="number" className="rounded-md border border-border bg-soft px-3 py-2 text-sm" placeholder="Growth %" value={simulate.growth_pct} onChange={(e) => setSimulate((f) => ({ ...f, growth_pct: Number(e.target.value) }))} />
              <input type="number" className="rounded-md border border-border bg-soft px-3 py-2 text-sm" placeholder="Días" value={simulate.days} onChange={(e) => setSimulate((f) => ({ ...f, days: Number(e.target.value) }))} />
              <button type="button" className="btn btn-secondary min-h-9 text-xs" disabled={!!busy} onClick={() => void doSimulate()}>
                Simular
              </button>
            </div>
            {simResult && (
              <pre className="mt-2 whitespace-pre-wrap rounded-md bg-soft p-3 text-xs text-text">{simResult}</pre>
            )}
          </section>
        </>
      )}
    </div>
  );
}