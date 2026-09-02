import { Plus, ShieldCheck, WarningCircle } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import { ErrorInline, PageHeader, SkeletonBlock } from "../../components/ui";
import { usePlatformAuth } from "../../platformAuth";

type Incident = {
  id: string;
  organization_id: string;
  source: string;
  severity: string;
  status: string;
  title: string;
  description: string | null;
  occurred_at: string;
  detected_at: string;
  acknowledged_at: string | null;
  resolved_at: string | null;
  mttd_seconds: number | null;
  mttr_seconds: number | null;
};

type Runbook = { id: string; trigger_type: string; trigger_match: string; title: string; description: string | null; steps: unknown[]; enabled: boolean };
type Metric = { severity: string; total: number; resolved: number; avg_mttr_seconds: number | null; avg_mttd_seconds: number | null };

const SEV = { severe: "badge-danger", major: "badge-warning", minor: "badge-muted" } as Record<string, string>;
const ST = { open: "badge-danger", acknowledged: "badge-warning", resolved: "badge-ok" } as Record<string, string>;

export default function AdminOpsCenterPage() {
  const { session } = usePlatformAuth();
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [runbooks, setRunbooks] = useState<Runbook[]>([]);
  const [metrics, setMetrics] = useState<Metric[]>([]);
  const [detail, setDetail] = useState<Record<string, unknown> | null>(null);
  const [orgs, setOrgs] = useState<{ id: string }[]>([]);
  const [orgId, setOrgId] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [form, setForm] = useState({ title: "", description: "", severity: "major", source: "manual" });
  const [rbForm, setRbForm] = useState({ trigger_type: "cost_alert", trigger_match: "*", title: "", steps: '[]' });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [note, setNote] = useState("");

  async function loadAll() {
    if (!session) return;
    setError("");
    try {
      const q = new URLSearchParams();
      if (orgId) q.set("organization_id", orgId);
      if (statusFilter) q.set("status", statusFilter);
      const [i, r, m] = await Promise.all([
        platformApi<{ incidents: Incident[] }>(`/api/v1/platform/ops/incidents?${q}`, { token: session.token }),
        platformApi<{ runbooks: Runbook[] }>("/api/v1/platform/ops/runbooks", { token: session.token }),
        platformApi<{ by_severity: Metric[] }>("/api/v1/platform/ops/incidents/metrics", { token: session.token }),
      ]);
      setIncidents(i.incidents || []);
      setRunbooks(r.runbooks || []);
      setMetrics(m.by_severity || []);
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
    const id = setInterval(() => void loadAll(), 15000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  async function openIncident() {
    if (!session) return;
    setBusy("inc");
    setError("");
    try {
      const out = await platformApi<{ id: string }>("/api/v1/platform/ops/incidents", {
        method: "POST",
        token: session.token,
        body: JSON.stringify({ organization_id: orgId || undefined, ...form }),
      });
      setNote(`Incidente ${out.id.slice(0, 8)}… abierto (runbooks ejecutados).`);
      setForm({ title: "", description: "", severity: "major", source: "manual" });
      await loadAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function createRunbook() {
    if (!session) return;
    setBusy("rb");
    setError("");
    try {
      let steps: unknown[] = [];
      try {
        steps = JSON.parse(rbForm.steps || "[]");
      } catch {
        setError("steps JSON inválido");
        return;
      }
      await platformApi("/api/v1/platform/ops/runbooks", {
        method: "POST",
        token: session.token,
        body: JSON.stringify({ ...rbForm, steps }),
      });
      setRbForm({ trigger_type: "cost_alert", trigger_match: "*", title: "", steps: '[]' });
      await loadAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function act(incidentId: string, action: "ack" | "resolve") {
    if (!session) return;
    setBusy(`${action}-${incidentId.slice(0, 6)}`);
    setError("");
    try {
      await platformApi(`/api/v1/platform/ops/incidents/${incidentId}/${action}`, {
        method: "POST",
        token: session.token,
      });
      await loadAll();
      if (detail && (detail as { id: string }).id === incidentId) setDetail(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function showDetail(incidentId: string) {
    if (!session) return;
    setError("");
    try {
      const d = await platformApi<Record<string, unknown>>(`/api/v1/platform/ops/incidents/${incidentId}`, { token: session.token });
      setDetail(d);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Ops Center" subtitle="Runbooks por alerta, incidentes con SLA (MTTR/MTTD) y escalamiento automático." />
      {error && <ErrorInline>{error}</ErrorInline>}
      {note && <p className="rounded-md bg-soft px-3 py-2 text-xs text-text">{note}</p>}
      {loading ? (
        <SkeletonBlock className="h-40" />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-6">
            {metrics.map((m) => (
              <div key={m.severity} className="panel p-3">
                <p className={`badge ${SEV[m.severity] ?? "badge-muted"} mb-1`}>{m.severity}</p>
                <p className="stat-label">MTTR</p>
                <p className="stat-value">{m.avg_mttr_seconds != null ? `${(m.avg_mttr_seconds / 60).toFixed(0)}m` : "—"}</p>
                <p className="text-[10px] text-faint">{m.total} inc · {m.resolved} resueltos · MTTD {m.avg_mttd_seconds != null ? `${(m.avg_mttd_seconds / 60).toFixed(1)}m` : "—"}</p>
              </div>
            ))}
          </div>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
            <section className="lg:col-span-2">
              <div className="mb-2 flex items-center gap-2">
                <h3 className="text-sm font-semibold text-text">Incidentes</h3>
                <select className="rounded-md border border-border bg-soft px-2 py-1.5 text-xs" value={orgId} onChange={(e) => { setOrgId(e.target.value); }}>
                  {orgs.map((o) => (<option key={o.id} value={o.id}>{o.id.slice(0, 8)}</option>))}
                </select>
                <select className="rounded-md border border-border bg-soft px-2 py-1.5 text-xs" value={statusFilter} onChange={(e) => { setStatusFilter(e.target.value); }}>
                  <option value="">todos</option>
                  {["open", "acknowledged", "resolved"].map((s) => (<option key={s} value={s}>{s}</option>))}
                </select>
                <button type="button" className="btn btn-ghost min-h-8 px-2 text-xs" onClick={() => void loadAll()}>Refrescar</button>
              </div>
              <div className="panel overflow-x-auto">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Incidente</th>
                      <th>Severidad</th>
                      <th>Estado</th>
                      <th>Fuente</th>
                      <th>MTTR</th>
                      <th>Detectado</th>
                      <th className="text-right">Acciones</th>
                    </tr>
                  </thead>
                  <tbody>
                    {incidents.map((i) => (
                      <tr key={i.id}>
                        <td className="text-xs">
                          <button type="button" className="font-medium text-accent hover:underline" onClick={() => void showDetail(i.id)}>
                            {i.title}
                          </button>
                        </td>
                        <td><span className={`badge ${SEV[i.severity] ?? "badge-muted"}`}>{i.severity}</span></td>
                        <td><span className={`badge ${ST[i.status] ?? "badge-muted"}`}>{i.status}</span></td>
                        <td className="mono text-xs text-faint">{i.source}</td>
                        <td className="text-xs">{i.mttr_seconds != null ? `${(i.mttr_seconds / 60).toFixed(1)}m` : "—"}</td>
                        <td className="text-[10px] text-faint">{new Date(i.detected_at).toLocaleString()}</td>
                        <td className="text-right">
                          {i.status !== "resolved" && (
                            <>
                              <button type="button" className="btn btn-ghost min-h-8 px-2 text-xs" disabled={!!busy} onClick={() => void act(i.id, "ack")}>
                                Ack
                              </button>
                              <button type="button" className="btn btn-ghost min-h-8 px-2 text-xs" disabled={!!busy} onClick={() => void act(i.id, "resolve")}>
                                Resolver
                              </button>
                            </>
                          )}
                        </td>
                      </tr>
                    ))}
                    {incidents.length === 0 && <tr><td colSpan={7} className="p-4 text-center text-xs text-faint">Sin incidentes.</td></tr>}
                  </tbody>
                </table>
              </div>
              {detail && (
                <div className="panel mt-2 p-4">
                  <h4 className="mb-1 text-sm font-semibold text-text">
                    {(detail as { title: string }).title}
                  </h4>
                  <p className="mb-2 text-xs text-faint">{(detail as { description: string | null }).description ?? "—"}</p>
                  <div className="space-y-1">
                    {((detail as { timeline?: { id: string; type: string; detail: string; created_at: string }[] }).timeline ?? []).map((e) => (
                      <div key={e.id} className="flex items-center gap-2 rounded-md bg-soft px-3 py-1 text-[11px]">
                        <span className={`badge ${e.type === "resolved" ? "badge-ok" : e.type === "escalation" ? "badge-warning" : "badge-muted"}`}>{e.type}</span>
                        <span className="flex-1 text-text">{e.detail}</span>
                        <span className="text-faint">{new Date(e.created_at).toLocaleTimeString()}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </section>

            <div className="space-y-4">
              <section className="panel p-4">
                <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text">
                  <WarningCircle size={15} aria-hidden /> Abrir incidente
                </h3>
                <div className="grid grid-cols-1 gap-2">
                  <input className="rounded-md border border-border bg-soft px-3 py-2 text-xs" placeholder="Título" value={form.title} onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))} />
                  <input className="rounded-md border border-border bg-soft px-3 py-2 text-xs" placeholder="Descripción" value={form.description} onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))} />
                  <select className="rounded-md border border-border bg-soft px-2 py-2 text-xs" value={form.severity} onChange={(e) => setForm((f) => ({ ...f, severity: e.target.value }))}>
                    {["severe", "major", "minor"].map((s) => (<option key={s} value={s}>{s}</option>))}
                  </select>
                  <button type="button" className="btn btn-primary min-h-9 text-xs" disabled={!!busy || !form.title} onClick={() => void openIncident()}>
                    <ShieldCheck size={13} aria-hidden /> Abrir (auto-runbook)
                  </button>
                </div>
              </section>

              <section className="panel p-4">
                <h3 className="mb-2 text-sm font-semibold text-text">Runbooks</h3>
                <div className="grid grid-cols-1 gap-2">
                  <input className="rounded-md border border-border bg-soft px-3 py-2 text-xs" placeholder="Título" value={rbForm.title} onChange={(e) => setRbForm((f) => ({ ...f, title: e.target.value }))} />
                  <select className="rounded-md border border-border bg-soft px-2 py-2 text-xs" value={rbForm.trigger_type} onChange={(e) => setRbForm((f) => ({ ...f, trigger_type: e.target.value }))}>
                    {["cost_alert", "slo", "manual", "deployment"].map((t) => (<option key={t} value={t}>{t}</option>))}
                  </select>
                  <input className="rounded-md border border-border bg-soft px-3 py-2 text-xs" placeholder='steps JSON [{"action":"annotate","params":{}}]' value={rbForm.steps} onChange={(e) => setRbForm((f) => ({ ...f, steps: e.target.value }))} />
                  <button type="button" className="btn btn-secondary min-h-8 text-xs" disabled={!!busy} onClick={() => void createRunbook()}>
                    <Plus size={12} aria-hidden /> Crear runbook
                  </button>
                </div>
                <div className="mt-2 space-y-1">
                  {runbooks.map((r) => (
                    <div key={r.id} className="rounded-md bg-soft px-3 py-1.5 text-[11px]">
                      <p className="font-medium text-text">{r.title}</p>
                      <p className="text-faint">{r.trigger_type}{r.trigger_match !== "*" ? `:${r.trigger_match}` : ""} · {r.steps.length} pasos</p>
                    </div>
                  ))}
                </div>
              </section>
            </div>
          </div>
        </>
      )}
    </div>
  );
}