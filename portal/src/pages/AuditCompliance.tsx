import { FileText, ShieldCheck } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { ErrorInline, PageHeader, SkeletonBlock } from "../components/ui";

type Report = { id: string; report_type: string; period_start: string; period_end: string; format: string; size_bytes: number; integrity_hash: string; prev_hash: string | null; created_at: string };
type Control = { framework: string; control_id: string; title: string; category: string; required_evidence: string | null; status: string; evidence: string | null };
type Compliance = { framework: string; controls: Control[]; counts: Record<string, number>; score: number };

const STATUS_BADGE: Record<string, string> = { pass: "badge-ok", fail: "badge-danger", review: "badge-warning", na: "badge-muted" };

export default function AuditCompliancePage() {
  const { session } = useAuth();
  const [reports, setReports] = useState<Report[]>([]);
  const [compliance, setCompliance] = useState<Compliance | null>(null);
  const [framework, setFramework] = useState("soc2");
  const [form, setForm] = useState({ report_type: "activity", format: "csv" });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  async function load() {
    if (!session) return;
    setError("");
    try {
      const [r, c] = await Promise.all([
        api<{ reports: Report[] }>("/api/v1/audit/reports", { token: session.token, organizationId: session.organizationId }),
        api<Compliance>(`/api/v1/audit/compliance?framework=${framework}`, { token: session.token, organizationId: session.organizationId }),
      ]);
      setReports(r.reports || []);
      setCompliance(c);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session, framework]);

  async function generate() {
    if (!session) return;
    setBusy("gen");
    setError("");
    try {
      const end = new Date().toISOString().slice(0, 10);
      const start = new Date(Date.now() - 30 * 86400000).toISOString().slice(0, 10);
      await api("/api/v1/audit/reports/generate", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ ...form, period_start: start, period_end: end }),
      });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function verify(id: string) {
    if (!session) return;
    try {
      const v = await api<{ verified: boolean; chain_ok: boolean; current_hash: string }>(
        `/api/v1/audit/reports/${id}/verify`,
        { token: session.token, organizationId: session.organizationId }
      );
      setError(`Integridad: ${v.verified && v.chain_ok ? "OK (hash + cadena)" : "ALTERADA"}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  async function updateControl(controlId: string, status: string) {
    if (!session) return;
    setBusy(`c-${controlId}`);
    try {
      await api("/api/v1/audit/compliance", {
        method: "PUT",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ framework, control_id: controlId, status, evidence: "Revisado en CC" }),
      });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  return (
    <div>
      <PageHeader title="Audit & Compliance" subtitle={`Score ${framework}: ${compliance?.score ?? 0}% · reportes con hash encadenado.`} />
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading ? (
        <SkeletonBlock className="h-40" />
      ) : (
        <div className="space-y-6">
          <section className="panel p-4">
            <h2 className="mb-2 text-sm font-semibold text-text">Generar reporte</h2>
            <div className="flex flex-wrap items-center gap-2">
              <select className="rounded-md border border-border bg-soft px-2 py-2 text-sm" value={form.report_type} onChange={(e) => setForm((f) => ({ ...f, report_type: e.target.value }))}>
                {["activity", "config_changes", "exports", "incidents", "full"].map((t) => (<option key={t} value={t}>{t}</option>))}
              </select>
              <select className="rounded-md border border-border bg-soft px-2 py-2 text-sm" value={form.format} onChange={(e) => setForm((f) => ({ ...f, format: e.target.value }))}>
                {["csv", "pdf"].map((f) => (<option key={f} value={f}>{f}</option>))}
              </select>
              <button type="button" className="btn btn-primary min-h-9 text-xs" disabled={!!busy} onClick={() => void generate()}>
                Generar (30 días)
              </button>
            </div>
            <div className="mt-3 space-y-1">
              {reports.map((r) => (
                <div key={r.id} className="flex items-center gap-2 rounded-md bg-soft px-3 py-1.5 text-[11px]">
                  <FileText size={13} className="text-faint" />
                  <span className="text-text">{r.report_type} · {r.format}</span>
                  <span className="text-faint">{r.period_start} → {r.period_end} · {(r.size_bytes / 1024).toFixed(1)}KB</span>
                  <span className="mono text-faint">hash {r.integrity_hash.slice(0, 10)}…</span>
                  {r.prev_hash && <span className="badge badge-muted">encadenado</span>}
                  <span className="flex-1" />
                  <button
                    type="button"
                    className="btn btn-ghost min-h-7 px-2 text-[11px]"
                    onClick={() => session && window.open(`/api/v1/audit/reports/${r.id}/download?token=${encodeURIComponent(session.token)}&organizationId=${encodeURIComponent(session.organizationId)}`, "_blank")}
                  >
                    Descargar
                  </button>
                  <button type="button" className="btn btn-ghost min-h-7 px-2 text-[11px]" onClick={() => void verify(r.id)}>Verificar</button>
                </div>
              ))}
              {reports.length === 0 && <p className="text-xs text-faint">Sin reportes.</p>}
            </div>
          </section>

          <section className="panel p-4">
            <div className="mb-2 flex items-center gap-2">
              <h2 className="flex items-center gap-2 text-sm font-semibold text-text">
                <ShieldCheck size={15} /> Cumplimiento
              </h2>
              <select className="rounded-md border border-border bg-soft px-2 py-1.5 text-xs" value={framework} onChange={(e) => setFramework(e.target.value)}>
                {["soc2", "gdpr", "iso27001"].map((f) => (<option key={f} value={f}>{f}</option>))}
              </select>
              <span className="text-xs text-faint">
                {compliance?.counts.pass ?? 0} pass · {compliance?.counts.fail ?? 0} fail · {compliance?.counts.review ?? 0} review
              </span>
            </div>
            <div className="overflow-x-auto">
              <table className="table">
                <thead>
                  <tr>
                    <th>Control</th>
                    <th>Título</th>
                    <th>Categoría</th>
                    <th>Evidencia</th>
                    <th>Estado</th>
                    <th className="text-right">Cambiar</th>
                  </tr>
                </thead>
                <tbody>
                  {(compliance?.controls ?? []).map((c) => (
                    <tr key={c.control_id}>
                      <td className="mono text-xs">{c.control_id}</td>
                      <td className="text-xs">{c.title}</td>
                      <td className="text-xs text-faint">{c.category}</td>
                      <td className="text-[10px] text-faint">{c.required_evidence ?? "—"}</td>
                      <td><span className={`badge ${STATUS_BADGE[c.status] ?? "badge-muted"}`}>{c.status}</span></td>
                      <td className="text-right">
                        {["pass", "fail", "na", "review"].map((s) => (
                          <button
                            key={s}
                            type="button"
                            className={`btn min-h-6 px-1.5 text-[10px] ${c.status === s ? "btn-primary" : "btn-ghost"}`}
                            disabled={!!busy}
                            onClick={() => void updateControl(c.control_id, s)}
                          >
                            {s}
                          </button>
                        ))}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}