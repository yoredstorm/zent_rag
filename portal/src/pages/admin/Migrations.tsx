import { ArrowsLeftRight } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import { ErrorInline, PageHeader, SkeletonBlock } from "../../components/ui";
import { usePlatformAuth } from "../../platformAuth";

type Migration = { id: string; organization_id: string; kind: string; direction: string; status: string; rows_total: number; rows_valid: number; rows_applied: number; rows_failed: number; created_at: string };
type Dash = { total: number; by_status: Record<string, number>; by_kind: Record<string, number>; rows_applied_total: number; rows_failed_total: number };

export default function AdminMigrationsPage() {
  const { session } = usePlatformAuth();
  const [migrations, setMigrations] = useState<Migration[]>([]);
  const [dash, setDash] = useState<Dash | null>(null);
  const [orgs, setOrgs] = useState<{ id: string }[]>([]);
  const [orgId, setOrgId] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function loadAll() {
    if (!session) return;
    setError("");
    try {
      const q = orgId ? `?organization_id=${orgId}` : "";
      const [m, d] = await Promise.all([
        platformApi<{ migrations: Migration[] }>(`/api/v1/platform/migrations${q}`, { token: session.token }),
        platformApi<Dash>("/api/v1/platform/migrations/dashboard", { token: session.token }),
      ]);
      setMigrations(m.migrations || []);
      setDash(d);
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session, orgId]);

  return (
    <div className="space-y-6">
      <PageHeader title="Migraciones de datos" subtitle="Historial global, estados y re-versión de agentes." />
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading ? (
        <SkeletonBlock className="h-40" />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <div className="panel p-4">
              <p className="stat-label">Migraciones</p>
              <p className="stat-value">{dash?.total ?? 0}</p>
            </div>
            <div className="panel p-4">
              <p className="stat-label">Filas aplicadas</p>
              <p className="stat-value text-emerald-400">{dash?.rows_applied_total ?? 0}</p>
            </div>
            <div className="panel p-4">
              <p className="stat-label">Filas fallidas</p>
              <p className="stat-value text-red-400">{dash?.rows_failed_total ?? 0}</p>
            </div>
            <div className="panel p-4">
              <p className="stat-label">Por estado</p>
              <p className="text-xs text-faint">{JSON.stringify(dash?.by_status ?? {})}</p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <select className="rounded-md border border-border bg-soft px-2 py-2 text-sm" value={orgId} onChange={(e) => setOrgId(e.target.value)}>
              <option value="">todas</option>
              {orgs.map((o) => (<option key={o.id} value={o.id}>{o.id.slice(0, 8)}</option>))}
            </select>
          </div>

          <section>
            <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text">
              <ArrowsLeftRight size={15} /> Historial
            </h3>
            <div className="panel overflow-x-auto">
              <table className="table">
                <thead>
                  <tr>
                    <th>Fecha</th>
                    <th>Org</th>
                    <th>Dirección</th>
                    <th>Kind</th>
                    <th>Estado</th>
                    <th>Válidas</th>
                    <th>Aplicadas</th>
                    <th>Fallidas</th>
                  </tr>
                </thead>
                <tbody>
                  {migrations.map((m) => (
                    <tr key={m.id}>
                      <td className="text-[10px] text-faint">{new Date(m.created_at).toLocaleString()}</td>
                      <td className="mono text-[10px] text-faint">{m.organization_id.slice(0, 8)}</td>
                      <td className="text-xs">{m.direction}</td>
                      <td className="text-xs">{m.kind}</td>
                      <td><span className={`badge ${m.status === "applied" || m.status === "exported" ? "badge-ok" : m.status === "failed" ? "badge-danger" : "badge-warning"}`}>{m.status}</span></td>
                      <td className="text-xs">{m.rows_valid}</td>
                      <td className="text-xs">{m.rows_applied}</td>
                      <td className="text-xs text-red-400">{m.rows_failed}</td>
                    </tr>
                  ))}
                  {migrations.length === 0 && <tr><td colSpan={8} className="p-4 text-center text-xs text-faint">Sin migraciones.</td></tr>}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </div>
  );
}