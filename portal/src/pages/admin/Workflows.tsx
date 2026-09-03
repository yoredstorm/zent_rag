import { FlowArrow, TrendUp } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import { ErrorInline, PageHeader, SkeletonBlock } from "../../components/ui";
import { usePlatformAuth } from "../../platformAuth";

type Dash = { total_runs: number; success_rate: number; failed_runs: number; avg_duration_ms: number; active_workflows: number; by_trigger: { trigger_type: string; runs: number; ok: number }[]; recent_runs: { workflow: string; status: string; duration_ms: number | null; started_at: string }[]; failed_steps: { step_type: string; count: number }[] };

const ST: Record<string, string> = { succeeded: "badge-ok", failed: "badge-danger", running: "badge-warning" };

export default function AdminWorkflowsPage() {
  const { session } = usePlatformAuth();
  const [dash, setDash] = useState<Dash | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load() {
    if (!session) return;
    setError("");
    try {
      const d = await platformApi<Dash>("/api/v1/platform/workflows/dashboard", { token: session.token });
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

  return (
    <div className="space-y-6">
      <PageHeader title="Workflow Automation" subtitle="Automatizaciones en todas las organizaciones: éxito, duración y fallos por paso." />
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading ? (
        <SkeletonBlock className="h-40" />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
            <div className="panel p-4"><p className="text-2xl font-bold text-text">{dash?.total_runs ?? 0}</p><p className="text-xs text-faint">Runs totales</p></div>
            <div className="panel p-4"><p className="text-2xl font-bold text-text">{dash?.success_rate ?? 0}%</p><p className="text-xs text-faint">Tasa de éxito</p></div>
            <div className="panel p-4"><p className="text-2xl font-bold text-text">{dash?.failed_runs ?? 0}</p><p className="text-xs text-faint">Fallidos</p></div>
            <div className="panel p-4"><p className="text-2xl font-bold text-text">{dash?.avg_duration_ms ?? 0}ms</p><p className="text-xs text-faint">Duración media</p></div>
            <div className="panel p-4"><p className="text-2xl font-bold text-text">{dash?.active_workflows ?? 0}</p><p className="text-xs text-faint">Workflows activos</p></div>
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <section>
              <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text"><FlowArrow size={15} /> Runs por disparador</h3>
              <div className="panel space-y-1 p-3">
                {(dash?.by_trigger ?? []).map((t) => (
                  <div key={t.trigger_type} className="flex items-center gap-2 rounded-md bg-soft px-3 py-1 text-xs">
                    <span className="flex-1 text-text">{t.trigger_type}</span>
                    <span className="text-faint">{t.ok}/{t.runs} ok</span>
                  </div>
                ))}
              </div>
              <h3 className="mb-2 mt-4 flex items-center gap-2 text-sm font-semibold text-text"><TrendUp size={15} /> Fallos por paso</h3>
              <div className="panel space-y-1 p-3">
                {(dash?.failed_steps ?? []).map((s) => (
                  <div key={s.step_type} className="flex items-center gap-2 rounded-md bg-soft px-3 py-1 text-xs">
                    <span className="flex-1 text-text">{s.step_type}</span>
                    <span className="text-red-400">{s.count}</span>
                  </div>
                ))}
                {(dash?.failed_steps ?? []).length === 0 && <p className="text-xs text-faint">Sin fallos.</p>}
              </div>
            </section>
            <section className="lg:col-span-2">
              <h3 className="mb-2 text-sm font-semibold text-text">Runs recientes</h3>
              <div className="panel space-y-1 p-3">
                {(dash?.recent_runs ?? []).map((r, i) => (
                  <div key={i} className="flex items-center gap-2 rounded-md bg-soft px-3 py-1.5 text-xs">
                    <span className={`badge ${ST[r.status] ?? "badge-muted"}`}>{r.status}</span>
                    <span className="flex-1 text-text">{r.workflow}</span>
                    <span className="text-faint">{r.duration_ms != null ? `${r.duration_ms}ms` : "—"}</span>
                    <span className="text-[10px] text-faint">{new Date(r.started_at).toLocaleString()}</span>
                  </div>
                ))}
                {(dash?.recent_runs ?? []).length === 0 && <p className="text-xs text-faint">Sin runs.</p>}
              </div>
            </section>
          </div>
        </>
      )}
    </div>
  );
}