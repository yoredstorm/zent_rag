import { Fingerprint, Scales } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import { ErrorInline, PageHeader, SkeletonBlock } from "../../components/ui";
import { usePlatformAuth } from "../../platformAuth";

type Dash = { organizations_governing: number; audit_entries: number; decisions_by_status: { status: string; count: number }[]; certifications: { certification: string; count: number }[]; recent_audit: { actor: string; action: string; detail: string; created_at: string }[] };

const ST: Record<string, string> = { pending: "badge-warning", approved: "badge-ok", rejected: "badge-danger" };

export default function AdminGovernancePage() {
  const { session } = usePlatformAuth();
  const [dash, setDash] = useState<Dash | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load() {
    if (!session) return;
    setError("");
    try {
      const d = await platformApi<Dash>("/api/v1/platform/governance/dashboard", { token: session.token });
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
      <PageHeader title="AI Governance" subtitle="Juntas de gobierno en todas las organizaciones: políticas, decisiones y auditoría." />
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading ? (
        <SkeletonBlock className="h-40" />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <div className="panel p-4"><p className="text-2xl font-bold text-text">{dash?.organizations_governing ?? 0}</p><p className="text-xs text-faint">Orgs con políticas</p></div>
            <div className="panel p-4"><p className="text-2xl font-bold text-text">{dash?.audit_entries ?? 0}</p><p className="text-xs text-faint">Entradas de auditoría</p></div>
            <div className="panel p-4"><p className="text-2xl font-bold text-text">{(dash?.decisions_by_status ?? []).reduce((n, d) => n + d.count, 0)}</p><p className="text-xs text-faint">Decisiones</p></div>
            <div className="panel p-4"><p className="text-2xl font-bold text-text">{(dash?.certifications ?? []).reduce((n, c) => n + c.count, 0)}</p><p className="text-xs text-faint">Certificaciones</p></div>
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <section>
              <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text"><Scales size={15} /> Decisiones por estado</h3>
              <div className="panel flex flex-wrap gap-1 p-3">
                {(dash?.decisions_by_status ?? []).map((d) => (
                  <span key={d.status} className={`badge ${ST[d.status] ?? "badge-muted"}`}>{d.status} · {d.count}</span>
                ))}
                {(dash?.decisions_by_status ?? []).length === 0 && <p className="text-xs text-faint">Sin decisiones.</p>}
              </div>
              <h3 className="mb-2 mt-4 text-sm font-semibold text-text">Certificaciones vigentes</h3>
              <div className="panel space-y-1 p-3">
                {(dash?.certifications ?? []).map((c) => (
                  <div key={c.certification} className="flex items-center gap-2 rounded-md bg-soft px-3 py-1 text-xs">
                    <span className="flex-1 text-text">{c.certification}</span>
                    <span className="text-faint">{c.count}</span>
                  </div>
                ))}
                {(dash?.certifications ?? []).length === 0 && <p className="text-xs text-faint">Sin certificaciones.</p>}
              </div>
            </section>
            <section className="lg:col-span-2">
              <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text"><Fingerprint size={15} /> Auditoría reciente</h3>
              <div className="panel space-y-1 p-3">
                {(dash?.recent_audit ?? []).map((a, i) => (
                  <div key={i} className="flex items-center gap-2 rounded-md bg-soft px-3 py-1.5 text-[11px]">
                    <span className="font-semibold text-text">{a.actor}</span>
                    <span className="text-faint">{a.action}</span>
                    <span className="flex-1 truncate text-faint">{a.detail}</span>
                    <span className="text-[10px] text-faint">{new Date(a.created_at).toLocaleTimeString()}</span>
                  </div>
                ))}
                {(dash?.recent_audit ?? []).length === 0 && <p className="text-xs text-faint">Sin actividad de auditoría.</p>}
              </div>
            </section>
          </div>
        </>
      )}
    </div>
  );
}