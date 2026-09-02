import { RocketLaunch } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import { ErrorInline, PageHeader, SkeletonBlock } from "../../components/ui";
import { usePlatformAuth } from "../../platformAuth";

type Metrics = { total_orgs: number; completed: number; activation_rate: number; avg_time_to_first_value_seconds: number | null; funnel: { step: string; orgs: number }[] };
type OrgRow = { organization_id: string; done_steps: string[]; current_step: string; started_at: string; completed_at: string | null; time_to_first_value_seconds: number | null };

const STEPS = ["create_kb", "add_documents", "create_agent", "deploy_agent", "first_query"];
const LABELS: Record<string, string> = { create_kb: "KB", add_documents: "Docs", create_agent: "Agente", deploy_agent: "Deploy", first_query: "Query" };

export default function AdminOnboardingPage() {
  const { session } = usePlatformAuth();
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [orgs, setOrgs] = useState<OrgRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load() {
    if (!session) return;
    setError("");
    try {
      const [m, o] = await Promise.all([
        platformApi<Metrics>("/api/v1/platform/onboarding/metrics", { token: session.token }),
        platformApi<{ organizations: OrgRow[] }>("/api/v1/platform/onboarding/status", { token: session.token }),
      ]);
      setMetrics(m);
      setOrgs(o.organizations || []);
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

  const maxFunnel = Math.max(...(metrics?.funnel ?? []).map((f) => f.orgs), 1);

  return (
    <div className="space-y-6">
      <PageHeader title="Onboarding & Activación" subtitle="TTFV, tasa de completación y funnel por paso." />
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading ? (
        <SkeletonBlock className="h-40" />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <div className="panel p-4">
              <p className="stat-label">Orgs</p>
              <p className="stat-value">{metrics?.total_orgs ?? 0}</p>
            </div>
            <div className="panel p-4">
              <p className="stat-label">Activadas</p>
              <p className="stat-value">{(metrics?.activation_rate ?? 0) * 100}%</p>
              <p className="text-xs text-faint">{metrics?.completed ?? 0} completaron</p>
            </div>
            <div className="panel p-4">
              <p className="stat-label">TTFV promedio</p>
              <p className="stat-value">{metrics?.avg_time_to_first_value_seconds != null ? `${Math.round(metrics.avg_time_to_first_value_seconds / 60)}m` : "—"}</p>
            </div>
            <div className="panel p-4">
              <p className="stat-label">Funnel</p>
              <p className="stat-value text-xs">{metrics?.funnel[0]?.orgs ?? 0} iniciaron</p>
            </div>
          </div>

          <section className="panel p-4">
            <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text">
              <RocketLaunch size={15} /> Funnel de pasos
            </h3>
            <div className="space-y-2">
              {(metrics?.funnel ?? []).map((f) => (
                <div key={f.step} className="flex items-center gap-2 text-xs">
                  <span className="w-24 text-text">{LABELS[f.step] ?? f.step}</span>
                  <div className="h-3 flex-1 rounded-full bg-soft">
                    <div className="h-3 rounded-full bg-accent" style={{ width: `${(f.orgs / maxFunnel) * 100}%` }} />
                  </div>
                  <span className="mono w-16 text-right text-faint">{f.orgs} orgs</span>
                </div>
              ))}
            </div>
          </section>

          <section>
            <h3 className="mb-2 text-sm font-semibold text-text">Progreso por organización</h3>
            <div className="panel overflow-x-auto">
              <table className="table">
                <thead>
                  <tr>
                    <th>Org</th>
                    <th>Pasos</th>
                    <th>Estado</th>
                    <th>TTFV</th>
                    <th>Inicio</th>
                  </tr>
                </thead>
                <tbody>
                  {orgs.map((o) => (
                    <tr key={o.organization_id}>
                      <td className="mono text-[10px] text-faint">{o.organization_id.slice(0, 8)}</td>
                      <td>
                        <div className="flex gap-1">
                          {STEPS.map((s) => (
                            <span key={s} className={`badge ${o.done_steps.includes(s) ? "badge-ok" : "badge-muted"}`} title={s}>
                              {LABELS[s]}
                            </span>
                          ))}
                        </div>
                      </td>
                      <td>{o.completed_at ? <span className="badge badge-ok">completado</span> : <span className="badge badge-warning">{o.current_step}</span>}</td>
                      <td className="text-xs">{o.time_to_first_value_seconds != null ? `${Math.round(o.time_to_first_value_seconds / 60)}m` : "—"}</td>
                      <td className="text-[10px] text-faint">{new Date(o.started_at).toLocaleString()}</td>
                    </tr>
                  ))}
                  {orgs.length === 0 && <tr><td colSpan={5} className="p-4 text-center text-xs text-faint">Sin datos.</td></tr>}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </div>
  );
}