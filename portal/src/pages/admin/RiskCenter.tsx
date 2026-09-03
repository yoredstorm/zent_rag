import { ShieldWarning } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import { ErrorInline, PageHeader, SkeletonBlock } from "../../components/ui";
import { usePlatformAuth } from "../../platformAuth";

type Dash = { open_risks: number; mitigated_7d: number; by_risk_type: { risk_type: string; count: number; avg_score: number }[]; by_severity: { severity: string; count: number }[]; posture_by_framework: { framework: string; avg_score: number; organizations: number }[]; top_organizations: { org: string; open_risks: number; total_score: number }[] };

const SEV: Record<string, string> = { low: "badge-muted", medium: "badge-warning", high: "badge-danger", critical: "badge-danger" };

export default function AdminRiskCenterPage() {
  const { session } = usePlatformAuth();
  const [dash, setDash] = useState<Dash | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load() {
    if (!session) return;
    setError("");
    try {
      const d = await platformApi<Dash>("/api/v1/platform/risk-center/dashboard", { token: session.token });
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
      <PageHeader title="Risk & Compliance" subtitle="Riesgos de IA en todas las organizaciones: scoring automático, postura por framework y mitigaciones." />
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading ? (
        <SkeletonBlock className="h-40" />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <div className="panel p-4"><p className="text-2xl font-bold text-text">{dash?.open_risks ?? 0}</p><p className="text-xs text-faint">Riesgos abiertos</p></div>
            <div className="panel p-4"><p className="text-2xl font-bold text-text">{dash?.mitigated_7d ?? 0}</p><p className="text-xs text-faint">Mitigados 7d</p></div>
            <div className="panel p-4"><p className="text-2xl font-bold text-text">{(dash?.posture_by_framework ?? []).length}</p><p className="text-xs text-faint">Frameworks</p></div>
            <div className="panel p-4"><p className="text-2xl font-bold text-text">{(dash?.top_organizations ?? []).length}</p><p className="text-xs text-faint">Orgs en top riesgo</p></div>
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <section>
              <h3 className="mb-2 text-sm font-semibold text-text">Riesgos por tipo</h3>
              <div className="panel space-y-1 p-3">
                {(dash?.by_risk_type ?? []).map((r) => (
                  <div key={r.risk_type} className="flex items-center gap-2 rounded-md bg-soft px-3 py-1 text-xs">
                    <span className="flex-1 text-text">{r.risk_type}</span>
                    <span className="text-faint">{r.count} · score {r.avg_score}</span>
                  </div>
                ))}
                {(dash?.by_risk_type ?? []).length === 0 && <p className="text-xs text-faint">Sin riesgos.</p>}
              </div>
              <h3 className="mb-2 mt-4 text-sm font-semibold text-text">Por severidad</h3>
              <div className="panel flex flex-wrap gap-1 p-3">
                {(dash?.by_severity ?? []).map((s) => (
                  <span key={s.severity} className={`badge ${SEV[s.severity] ?? "badge-muted"}`}>{s.severity} · {s.count}</span>
                ))}
              </div>
            </section>
            <section>
              <h3 className="mb-2 text-sm font-semibold text-text">Postura por framework</h3>
              <div className="panel space-y-1 p-3">
                {(dash?.posture_by_framework ?? []).map((p) => (
                  <div key={p.framework} className="flex items-center gap-2 rounded-md bg-soft px-3 py-1 text-xs">
                    <span className="flex-1 text-text">{p.framework}</span>
                    <span className="text-faint">{p.avg_score}% · {p.organizations} orgs</span>
                  </div>
                ))}
                {(dash?.posture_by_framework ?? []).length === 0 && <p className="text-xs text-faint">Sin snapshots aún.</p>}
              </div>
            </section>
            <section>
              <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text"><ShieldWarning size={15} /> Top organizaciones en riesgo</h3>
              <div className="panel space-y-1 p-3">
                {(dash?.top_organizations ?? []).map((o) => (
                  <div key={o.org} className="flex items-center gap-2 rounded-md bg-soft px-3 py-1 text-xs">
                    <span className="flex-1 truncate text-text">{o.org}</span>
                    <span className="text-faint">{o.open_risks} riesgos · {o.total_score}</span>
                  </div>
                ))}
                {(dash?.top_organizations ?? []).length === 0 && <p className="text-xs text-faint">Sin riesgos registrados.</p>}
              </div>
            </section>
          </div>
        </>
      )}
    </div>
  );
}