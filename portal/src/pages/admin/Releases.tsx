import { GitCommit } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import { ErrorInline, PageHeader, SkeletonBlock } from "../../components/ui";
import { usePlatformAuth } from "../../platformAuth";

type Release = { id: string; agent_id: string; agent_name: string; version_id: string; version_number: number; channel: string; traffic_pct: number; status: string; health_score: number | null; created_at: string; promoted_at: string | null; rolled_back_at: string | null };
type Dash = { agents: { agent_id: string; agent_name: string; releases: number; canary: { version: number; status: string; health: number | null } | null; stable: { version: number; status: string; health: number | null } | null; last_status: string }[]; total_releases: number };

const ST: Record<string, string> = { running: "badge-ok", promoted: "badge-ok", rolled_back: "badge-danger", paused: "badge-warning" };
const CH: Record<string, string> = { canary: "badge-warning", stable: "badge-ok" };

export default function AdminReleasesPage() {
  const { session } = usePlatformAuth();
  const [dash, setDash] = useState<Dash | null>(null);
  const [releases, setReleases] = useState<Release[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load() {
    if (!session) return;
    setError("");
    try {
      const [d, r] = await Promise.all([
        platformApi<Dash>("/api/v1/platform/releases/dashboard", { token: session.token }),
        platformApi<{ releases: Release[] }>("/api/v1/platform/releases", { token: session.token }),
      ]);
      setDash(d);
      setReleases(r.releases || []);
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
      <PageHeader title="Agent Releases" subtitle="Canales canary/stable, health-gate y promoción gradual con rollbacks." />
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading ? (
        <SkeletonBlock className="h-40" />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {(dash?.agents ?? []).map((a) => (
              <div key={a.agent_id} className="panel p-4">
                <p className="truncate text-sm font-semibold text-text">{a.agent_name}</p>
                <div className="mt-1 space-y-0.5 text-[11px]">
                  <p className="flex justify-between"><span className="text-faint">Canary</span>
                    <span>{a.canary ? `v${a.canary.version} · ${a.canary.health ?? "—"}` : "—"}</span></p>
                  <p className="flex justify-between"><span className="text-faint">Stable</span>
                    <span>{a.stable ? `v${a.stable.version} · ${a.stable.health ?? "—"}` : "—"}</span></p>
                </div>
                <p className="mt-1 text-[10px] text-faint">{a.releases} releases · {a.last_status}</p>
              </div>
            ))}
            {(dash?.agents ?? []).length === 0 && <div className="panel p-4 text-xs text-faint">Sin releases.</div>}
          </div>

          <section>
            <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text">
              <GitCommit size={15} /> Historial de releases ({dash?.total_releases ?? 0})
            </h3>
            <div className="panel overflow-x-auto">
              <table className="table">
                <thead>
                  <tr>
                    <th>Agente</th>
                    <th>Versión</th>
                    <th>Canal</th>
                    <th>Tráfico</th>
                    <th>Health</th>
                    <th>Estado</th>
                    <th>Promovido</th>
                    <th>Rollback</th>
                  </tr>
                </thead>
                <tbody>
                  {releases.map((r) => (
                    <tr key={r.id}>
                      <td className="text-xs">{r.agent_name}</td>
                      <td className="text-xs">v{r.version_number}</td>
                      <td><span className={`badge ${CH[r.channel] ?? "badge-muted"}`}>{r.channel}</span></td>
                      <td className="text-xs">{r.traffic_pct}%</td>
                      <td className="text-xs">{r.health_score != null ? `${r.health_score}%` : "—"}</td>
                      <td><span className={`badge ${ST[r.status] ?? "badge-muted"}`}>{r.status}</span></td>
                      <td className="text-[10px] text-faint">{r.promoted_at ? new Date(r.promoted_at).toLocaleString() : "—"}</td>
                      <td className="text-[10px] text-faint">{r.rolled_back_at ? new Date(r.rolled_back_at).toLocaleString() : "—"}</td>
                    </tr>
                  ))}
                  {releases.length === 0 && <tr><td colSpan={8} className="p-4 text-center text-xs text-faint">Sin releases.</td></tr>}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </div>
  );
}