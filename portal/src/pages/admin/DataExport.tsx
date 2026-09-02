import { DownloadSimple, Trash } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import { ErrorInline, PageHeader, SkeletonBlock } from "../../components/ui";
import { usePlatformAuth } from "../../platformAuth";

type Export = {
  id: string;
  organization_id: string;
  scope: string;
  anonymized: boolean;
  status: string;
  size_bytes: number;
  row_counts: Record<string, number>;
  requested_by: string | null;
  requested_at: string;
  completed_at: string | null;
};

type Policy = {
  id: string;
  organization_id: string | null;
  data_type: string;
  retention_days: number;
  enabled: boolean;
};

type Purge = { id: string; data_type: string; organization_id: string | null; purged_rows: number; ran_at: string };

const fmtBytes = (b: number) => (b > 1024 * 1024 ? `${(b / 1024 / 1024).toFixed(1)}MB` : `${(b / 1024).toFixed(1)}KB`);

export default function AdminDataExportPage() {
  const { session } = usePlatformAuth();
  const [exports, setExports] = useState<Export[]>([]);
  const [policies, setPolicies] = useState<Policy[]>([]);
  const [purges, setPurges] = useState<Purge[]>([]);
  const [orgs, setOrgs] = useState<{ id: string }[]>([]);
  const [orgId, setOrgId] = useState("");
  const [form, setForm] = useState({ scope: "all", anonymized: false });
  const [policyForm, setPolicyForm] = useState({ data_type: "inference_logs", retention_days: 90, enabled: true });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [note, setNote] = useState("");

  async function loadAll() {
    if (!session) return;
    setError("");
    try {
      const [e, p, g] = await Promise.all([
        platformApi<{ exports: Export[] }>(`/api/v1/platform/data-export/exports?organization_id=${orgId}`, { token: session.token }),
        platformApi<{ policies: Policy[] }>("/api/v1/platform/data-export/retention/policies", { token: session.token }),
        platformApi<{ purges: Purge[] }>("/api/v1/platform/data-export/retention/purges", { token: session.token }),
      ]);
      setExports(e.exports || []);
      setPolicies(p.policies || []);
      setPurges(g.purges || []);
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
        if (o.organizations?.length) setOrgId(o.organizations[0].id);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Error");
      }
      await loadAll();
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  async function createExport() {
    if (!session) return;
    setBusy("export");
    setError("");
    setNote("");
    try {
      const out = await platformApi<{ id: string; size_bytes: number }>("/api/v1/platform/data-export/export", {
        method: "POST",
        token: session.token,
        body: JSON.stringify({ organization_id: orgId, ...form }),
      });
      setNote(`Export ${out.id.slice(0, 8)}… listo (${fmtBytes(out.size_bytes)}).`);
      await loadAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function upsertPolicy() {
    if (!session) return;
    setBusy("policy");
    setError("");
    try {
      await platformApi("/api/v1/platform/data-export/retention/policies", {
        method: "POST",
        token: session.token,
        body: JSON.stringify(policyForm),
      });
      await loadAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function removePolicy(id: string) {
    if (!session) return;
    try {
      await platformApi(`/api/v1/platform/data-export/retention/policies/${id}`, {
        method: "DELETE",
        token: session.token,
      });
      await loadAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  async function purgeNow() {
    if (!session) return;
    setBusy("purge");
    setError("");
    try {
      const out = await platformApi<{ purged: Purge[] }>("/api/v1/platform/data-export/retention/purge", {
        method: "POST",
        token: session.token,
      });
      setNote(`${out.purged.length} tabla(s) purgada(s).`);
      await loadAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Data Export & Compliance" subtitle="Export ZIP con anonimización, auditoría de exportaciones y retención granular." />
      {error && <ErrorInline>{error}</ErrorInline>}
      {note && <p className="rounded-md bg-soft px-3 py-2 text-xs text-text">{note}</p>}
      {loading ? (
        <SkeletonBlock className="h-40" />
      ) : (
        <>
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
            <section className="lg:col-span-2">
              <div className="mb-2 flex items-center gap-2">
                <h3 className="text-sm font-semibold text-text">Exportaciones (auditoría)</h3>
                <select className="rounded-md border border-border bg-soft px-2 py-1.5 text-xs" value={orgId} onChange={(e) => setOrgId(e.target.value)}>
                  {orgs.map((o) => (<option key={o.id} value={o.id}>{o.id.slice(0, 8)}</option>))}
                </select>
                <select className="rounded-md border border-border bg-soft px-2 py-1.5 text-xs" value={form.scope} onChange={(e) => setForm((f) => ({ ...f, scope: e.target.value }))}>
                  {["all", "kb", "agents", "usage", "config"].map((s) => (<option key={s} value={s}>{s}</option>))}
                </select>
                <label className="flex items-center gap-1 text-xs text-text">
                  <input type="checkbox" checked={form.anonymized} onChange={(e) => setForm((f) => ({ ...f, anonymized: e.target.checked }))} />
                  Anonimizar
                </label>
                <button type="button" className="btn btn-primary min-h-9 text-xs" disabled={!!busy || !orgId} onClick={() => void createExport()}>
                  Exportar ZIP
                </button>
              </div>
              <div className="panel overflow-x-auto">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Fecha</th>
                      <th>Scope</th>
                      <th>Anon.</th>
                      <th>Filas</th>
                      <th>Tamaño</th>
                      <th>Solicitado por</th>
                      <th className="text-right">Descarga</th>
                    </tr>
                  </thead>
                  <tbody>
                    {exports.map((e) => (
                      <tr key={e.id}>
                        <td className="text-[10px] text-faint">{new Date(e.requested_at).toLocaleString()}</td>
                        <td className="text-xs">{e.scope}</td>
                        <td>{e.anonymized ? <span className="badge badge-ok">sí</span> : <span className="badge badge-muted">no</span>}</td>
                        <td className="mono text-[10px] text-faint">{Object.entries(e.row_counts).map(([k, v]) => `${k}:${v}`).join(" · ")}</td>
                        <td className="text-xs">{fmtBytes(e.size_bytes)}</td>
                        <td className="mono text-[10px] text-faint">{e.requested_by?.slice(0, 8) ?? "—"}</td>
                        <td className="text-right">
                          <button
                            type="button"
                            className="btn btn-ghost min-h-8 px-2 text-xs"
                            onClick={() => {
                              if (!session) return;
                              window.open(`/api/v1/platform/data-export/exports/${e.id}/download?token=${encodeURIComponent(session.token)}`, "_blank");
                            }}
                          >
                            <DownloadSimple size={13} aria-hidden />
                          </button>
                        </td>
                      </tr>
                    ))}
                    {exports.length === 0 && <tr><td colSpan={7} className="p-4 text-center text-xs text-faint">Sin exportaciones.</td></tr>}
                  </tbody>
                </table>
              </div>
            </section>

            <section className="panel p-4">
              <h3 className="mb-2 text-sm font-semibold text-text">Retención granular</h3>
              <div className="grid grid-cols-2 gap-2">
                <select className="rounded-md border border-border bg-soft px-2 py-2 text-xs" value={policyForm.data_type} onChange={(e) => setPolicyForm((f) => ({ ...f, data_type: e.target.value }))}>
                  {["usage_events", "inference_logs", "api_logs", "audit_logs", "agent_versions"].map((t) => (<option key={t} value={t}>{t}</option>))}
                </select>
                <input type="number" className="rounded-md border border-border bg-soft px-2 py-2 text-xs" value={policyForm.retention_days} onChange={(e) => setPolicyForm((f) => ({ ...f, retention_days: Number(e.target.value) }))} />
              </div>
              <button type="button" className="btn btn-primary mt-2 min-h-8 text-xs" disabled={!!busy} onClick={() => void upsertPolicy()}>
                Guardar política
              </button>
              <button type="button" className="btn btn-secondary mt-2 min-h-8 text-xs" disabled={!!busy} onClick={() => void purgeNow()}>
                Purgar ahora
              </button>
              <div className="mt-3 space-y-1">
                {policies.map((p) => (
                  <div key={p.id} className="flex items-center justify-between rounded-md bg-soft px-3 py-1.5 text-[11px]">
                    <span className="mono text-text">{p.data_type}</span>
                    <span className="text-faint">{p.retention_days}d {p.organization_id ? "· org" : "· global"}</span>
                    <span className={`badge ${p.enabled ? "badge-ok" : "badge-muted"}`}>{p.enabled ? "activa" : "off"}</span>
                    <button type="button" className="btn btn-ghost min-h-6 px-1.5 text-[10px]" onClick={() => void removePolicy(p.id)}>
                      <Trash size={11} aria-hidden />
                    </button>
                  </div>
                ))}
              </div>
            </section>
          </div>

          <section>
            <h3 className="mb-2 text-sm font-semibold text-text">Historial de purgas</h3>
            <div className="panel overflow-x-auto">
              <table className="table">
                <thead>
                  <tr><th>Hora</th><th>Tabla</th><th>Org</th><th>Filas purgadas</th></tr>
                </thead>
                <tbody>
                  {purges.map((g) => (
                    <tr key={g.id}>
                      <td className="text-[10px] text-faint">{new Date(g.ran_at).toLocaleString()}</td>
                      <td className="mono text-xs">{g.data_type}</td>
                      <td className="mono text-[10px] text-faint">{g.organization_id?.slice(0, 8) ?? "global"}</td>
                      <td className="text-xs">{g.purged_rows.toLocaleString()}</td>
                    </tr>
                  ))}
                  {purges.length === 0 && <tr><td colSpan={4} className="p-4 text-center text-xs text-faint">Sin purgas.</td></tr>}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </div>
  );
}