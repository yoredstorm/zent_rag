import { ShieldCheck } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import { ErrorInline, PageHeader, SkeletonBlock } from "../../components/ui";
import { usePlatformAuth } from "../../platformAuth";

type Framework = { framework: string; pass: number; fail: number; review: number; na: number; score: number; controls: number };

export default function AdminCompliancePage() {
  const { session } = usePlatformAuth();
  const [frameworks, setFrameworks] = useState<Framework[]>([]);
  const [reports, setReports] = useState<{ id: string; organization_id: string; report_type: string; format: string; integrity_hash: string; prev_hash: string | null; created_at: string }[]>([]);
  const [orgs, setOrgs] = useState<{ id: string }[]>([]);
  const [orgId, setOrgId] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function loadAll() {
    if (!session) return;
    setError("");
    try {
      const q = orgId ? `?organization_id=${orgId}` : "";
      const [f, r] = await Promise.all([
        platformApi<{ frameworks: Framework[] }>(`/api/v1/platform/compliance/dashboard${q}`, { token: session.token }),
        platformApi<{ reports: typeof reports }>(`/api/v1/platform/audit/reports${q}`, { token: session.token }),
      ]);
      setFrameworks(f.frameworks || []);
      setReports(r.reports || []);
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
      <PageHeader title="Compliance" subtitle="Estado por control (SOC2 / GDPR / ISO27001) y reportes de auditoría." />
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading ? (
        <SkeletonBlock className="h-40" />
      ) : (
        <>
          <div className="flex items-center gap-2">
            <select className="rounded-md border border-border bg-soft px-2 py-2 text-sm" value={orgId} onChange={(e) => setOrgId(e.target.value)}>
              <option value="">todas (plantilla)</option>
              {orgs.map((o) => (<option key={o.id} value={o.id}>{o.id.slice(0, 8)}</option>))}
            </select>
          </div>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
            {frameworks.map((f) => (
              <div key={f.framework} className="panel p-4">
                <div className="flex items-center justify-between">
                  <p className="flex items-center gap-2 text-sm font-semibold text-text">
                    <ShieldCheck size={15} /> {f.framework.toUpperCase()}
                  </p>
                  <span className="stat-value">{f.score}%</span>
                </div>
                <p className="mt-1 text-xs text-faint">{f.controls} controles · {f.pass} pass · {f.fail} fail · {f.review} review · {f.na} n/a</p>
                <div className="mt-2 h-2 overflow-hidden rounded-full bg-soft">
                  <div className="h-2 rounded-full bg-emerald-400" style={{ width: `${f.score}%` }} />
                </div>
              </div>
            ))}
          </div>

          <section>
            <h3 className="mb-2 text-sm font-semibold text-text">Reportes de auditoría</h3>
            <div className="panel overflow-x-auto">
              <table className="table">
                <thead>
                  <tr>
                    <th>Fecha</th>
                    <th>Org</th>
                    <th>Tipo</th>
                    <th>Formato</th>
                    <th>Hash</th>
                    <th>Cadena</th>
                  </tr>
                </thead>
                <tbody>
                  {reports.map((r) => (
                    <tr key={r.id}>
                      <td className="text-[10px] text-faint">{new Date(r.created_at).toLocaleString()}</td>
                      <td className="mono text-[10px] text-faint">{r.organization_id.slice(0, 8)}</td>
                      <td className="text-xs">{r.report_type}</td>
                      <td className="text-xs">{r.format}</td>
                      <td className="mono text-[10px] text-faint">{r.integrity_hash.slice(0, 12)}…</td>
                      <td>{r.prev_hash ? <span className="badge badge-muted">encadenado</span> : <span className="text-xs text-faint">raíz</span>}</td>
                    </tr>
                  ))}
                  {reports.length === 0 && <tr><td colSpan={6} className="p-4 text-center text-xs text-faint">Sin reportes.</td></tr>}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </div>
  );
}