import { ShieldCheck } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import { ErrorInline, PageHeader, SkeletonBlock } from "../../components/ui";
import { usePlatformAuth } from "../../platformAuth";

type Dash = { policies_total: number; policies_active: number; organizations_covered: number; drills_30d: number; drill_success_rate: number; backups_total: number; restores_30d: number; drills_by_region: { region: string; count: number; success: number }[] };

export default function AdminDisasterRecoveryPage() {
  const { session } = usePlatformAuth();
  const [dash, setDash] = useState<Dash | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load() {
    if (!session) return;
    setError("");
    try {
      const d = await platformApi<Dash>("/api/v1/platform/dr/dashboard", { token: session.token });
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
      <PageHeader title="Disaster Recovery" subtitle="Continuidad en todas las organizaciones: políticas, drills de failover y backups." />
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading ? (
        <SkeletonBlock className="h-40" />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
            <div className="panel p-4"><p className="text-2xl font-bold text-text">{dash?.policies_total ?? 0}</p><p className="text-xs text-faint">Políticas</p></div>
            <div className="panel p-4"><p className="text-2xl font-bold text-text">{dash?.policies_active ?? 0}</p><p className="text-xs text-faint">Activas</p></div>
            <div className="panel p-4"><p className="text-2xl font-bold text-text">{dash?.organizations_covered ?? 0}</p><p className="text-xs text-faint">Orgs cubiertas</p></div>
            <div className="panel p-4"><p className="text-2xl font-bold text-text">{dash?.drills_30d ?? 0} · {dash?.drill_success_rate ?? 0}%</p><p className="text-xs text-faint">Drills 30d</p></div>
            <div className="panel p-4"><p className="text-2xl font-bold text-text">{dash?.backups_total ?? 0} · {dash?.restores_30d ?? 0}</p><p className="text-xs text-faint">Backups · restores</p></div>
          </div>

          <section>
            <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text"><ShieldCheck size={15} /> Drills por región</h3>
            <div className="panel space-y-1 p-3">
              {(dash?.drills_by_region ?? []).map((r) => (
                <div key={r.region} className="flex items-center gap-2 rounded-md bg-soft px-3 py-1 text-xs">
                  <span className="flex-1 text-text">{r.region}</span>
                  <span className="text-faint">{r.success}/{r.count} exitosos</span>
                </div>
              ))}
              {(dash?.drills_by_region ?? []).length === 0 && <p className="text-xs text-faint">Sin drills aún.</p>}
            </div>
          </section>
        </>
      )}
    </div>
  );
}