import { ShieldWarning } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import { ErrorInline, PageHeader, SkeletonBlock } from "../../components/ui";
import { usePlatformAuth } from "../../platformAuth";

type Dash = { events_7d: number; open_events: number; resolved_7d: number; avg_threat_score: number; by_type: { event_type: string; count: number; criticals: number }[]; by_severity: { severity: string; count: number }[]; responses: { action_type: string; count: number }[]; top_organizations: { org: string; events: number; total_score: number }[] };

const SEV: Record<string, string> = { low: "badge-muted", medium: "badge-warning", high: "badge-danger", critical: "badge-danger" };

export default function AdminSecurityCenterPage() {
  const { session } = usePlatformAuth();
  const [dash, setDash] = useState<Dash | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load() {
    if (!session) return;
    setError("");
    try {
      const d = await platformApi<Dash>("/api/v1/platform/soc/dashboard", { token: session.token });
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
      <PageHeader title="Security Operations Center" subtitle="Amenazas en todas las organizaciones: detección, severidad y respuestas automáticas." />
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading ? (
        <SkeletonBlock className="h-40" />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
            <div className="panel p-4"><p className="text-2xl font-bold text-text">{dash?.events_7d ?? 0}</p><p className="text-xs text-faint">Eventos 7d</p></div>
            <div className="panel p-4"><p className="text-2xl font-bold text-text">{dash?.open_events ?? 0}</p><p className="text-xs text-faint">Abiertos</p></div>
            <div className="panel p-4"><p className="text-2xl font-bold text-text">{dash?.resolved_7d ?? 0}</p><p className="text-xs text-faint">Resueltos 7d</p></div>
            <div className="panel p-4"><p className="text-2xl font-bold text-text">{dash?.avg_threat_score ?? 0}</p><p className="text-xs text-faint">Threat score medio</p></div>
            <div className="panel p-4"><p className="text-2xl font-bold text-text">{(dash?.responses ?? []).reduce((n, r) => n + r.count, 0)}</p><p className="text-xs text-faint">Respuestas 7d</p></div>
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <section>
              <h3 className="mb-2 text-sm font-semibold text-text">Por tipo</h3>
              <div className="panel space-y-1 p-3">
                {(dash?.by_type ?? []).map((t) => (
                  <div key={t.event_type} className="flex items-center gap-2 rounded-md bg-soft px-3 py-1 text-xs">
                    <span className="flex-1 text-text">{t.event_type}</span>
                    <span className="text-faint">{t.count} · {t.criticals} críticos</span>
                  </div>
                ))}
                {(dash?.by_type ?? []).length === 0 && <p className="text-xs text-faint">Sin eventos.</p>}
              </div>
              <h3 className="mb-2 mt-4 text-sm font-semibold text-text">Por severidad</h3>
              <div className="panel flex flex-wrap gap-1 p-3">
                {(dash?.by_severity ?? []).map((s) => (
                  <span key={s.severity} className={`badge ${SEV[s.severity] ?? "badge-muted"}`}>{s.severity} · {s.count}</span>
                ))}
              </div>
            </section>
            <section>
              <h3 className="mb-2 text-sm font-semibold text-text">Respuestas automáticas</h3>
              <div className="panel space-y-1 p-3">
                {(dash?.responses ?? []).map((r) => (
                  <div key={r.action_type} className="flex items-center gap-2 rounded-md bg-soft px-3 py-1 text-xs">
                    <span className="flex-1 text-text">{r.action_type}</span>
                    <span className="text-faint">{r.count}</span>
                  </div>
                ))}
                {(dash?.responses ?? []).length === 0 && <p className="text-xs text-faint">Sin respuestas.</p>}
              </div>
            </section>
            <section>
              <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text"><ShieldWarning size={15} /> Top organizaciones</h3>
              <div className="panel space-y-1 p-3">
                {(dash?.top_organizations ?? []).map((o) => (
                  <div key={o.org} className="flex items-center gap-2 rounded-md bg-soft px-3 py-1 text-xs">
                    <span className="flex-1 truncate text-text">{o.org}</span>
                    <span className="text-faint">{o.events} eventos · {o.total_score}</span>
                  </div>
                ))}
                {(dash?.top_organizations ?? []).length === 0 && <p className="text-xs text-faint">Sin actividad.</p>}
              </div>
            </section>
          </div>
        </>
      )}
    </div>
  );
}