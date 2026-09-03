import { CheckCircle, ShieldWarning, TrendUp, WarningOctagon } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { ErrorInline, PageHeader, SkeletonBlock } from "../components/ui";

type Risk = { id: string; agent_id: string | null; agent_name: string | null; risk_type: string; severity: string; likelihood: number; impact: number; score: number; status: string; source: string; evidence: Record<string, unknown>; mitigations: number; created_at: string };
type Heatmap = { heatmap: { agent_id: string; agent_name: string; risks: Record<string, { severity: string; score: number }> }[] };
type Posture = { framework: string; total_controls: number; implemented: number; in_review: number; not_implemented: number; score: number; by_risk_type: Record<string, { total: number; implemented: number; pct: number }>; controls: { control_id: string; title: string; risk_type: string | null; status: string }[] };
type Trend = { trend: { date: string; score: number }[] };
type Mitigation = { id: string; risk_id: string; action_type: string; description: string | null; created_at: string; risk_type: string; severity: string };

const SEV: Record<string, string> = { low: "badge-muted", medium: "badge-warning", high: "badge-danger", critical: "badge-danger" };
const FRAMEWORKS = ["eu_ai_act", "soc2", "gdpr", "iso27001"];

export default function RiskCenterPage() {
  const { session } = useAuth();
  const [risks, setRisks] = useState<Risk[]>([]);
  const [heatmap, setHeatmap] = useState<Heatmap | null>(null);
  const [posture, setPosture] = useState<Posture | null>(null);
  const [trend, setTrend] = useState<Trend | null>(null);
  const [mitigations, setMitigations] = useState<Mitigation[]>([]);
  const [framework, setFramework] = useState("eu_ai_act");
  const [draft, setDraft] = useState({ risk_type: "bias", severity: "medium", notes: "" });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  async function load() {
    if (!session) return;
    setError("");
    try {
      const [r, hm, p, t, m] = await Promise.all([
        api<{ risks: Risk[] }>("/api/v1/risk-center/register", { token: session.token, organizationId: session.organizationId }),
        api<Heatmap>("/api/v1/risk-center/heatmap", { token: session.token, organizationId: session.organizationId }),
        api<Posture>(`/api/v1/risk-center/compliance/posture?framework=${framework}`, { token: session.token, organizationId: session.organizationId }),
        api<Trend>(`/api/v1/risk-center/compliance/trend?framework=${framework}`, { token: session.token, organizationId: session.organizationId }),
        api<{ mitigations: Mitigation[] }>("/api/v1/risk-center/mitigations", { token: session.token, organizationId: session.organizationId }),
      ]);
      setRisks(r.risks || []);
      setHeatmap(hm);
      setPosture(p);
      setTrend(t);
      setMitigations(m.mitigations || []);
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

  async function assess() {
    if (!session) return;
    setBusy("assess");
    setError("");
    try {
      const out = await api<{ assessments: { risk_type: string; created: boolean }[] }>("/api/v1/risk-center/assess", { method: "POST", token: session.token, organizationId: session.organizationId });
      const created = out.assessments.filter((a) => a.created).map((a) => a.risk_type);
      setError(`Assess: ${created.length ? `nuevos riesgos: ${created.join(", ")}` : "sin nuevos riesgos"}`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function addRisk() {
    if (!session) return;
    setBusy("add");
    setError("");
    try {
      await api("/api/v1/risk-center/risks", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify(draft),
      });
      setDraft({ risk_type: "bias", severity: "medium", notes: "" });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function act(id: string, action: "mitigate" | "accept") {
    if (!session) return;
    setBusy(`${action}-${id.slice(0, 6)}`);
    setError("");
    try {
      const body = action === "mitigate" ? JSON.stringify({ description: "Mitigación registrada" }) : JSON.stringify({ reason: "Riesgo aceptado por el equipo" });
      await api(`/api/v1/risk-center/risks/${id}/${action}`, { method: "POST", token: session.token, organizationId: session.organizationId, body });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Risk & Compliance Center" subtitle="Registro de riesgos de IA con scoring automático, mitigaciones, heatmap y postura de cumplimiento." />
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading ? (
        <SkeletonBlock className="h-64" />
      ) : (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <section className="panel p-4">
            <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text"><WarningOctagon size={14} /> Registro de riesgos</h2>
            <div className="grid grid-cols-1 gap-2">
              <select className="rounded-md border border-border bg-soft px-2 py-2 text-sm" value={draft.risk_type} onChange={(e) => setDraft((d) => ({ ...d, risk_type: e.target.value }))}>
                {["bias", "hallucination", "pii_leak", "security", "safety"].map((t) => (<option key={t} value={t}>{t}</option>))}
              </select>
              <select className="rounded-md border border-border bg-soft px-2 py-2 text-sm" value={draft.severity} onChange={(e) => setDraft((d) => ({ ...d, severity: e.target.value }))}>
                {["low", "medium", "high", "critical"].map((s) => (<option key={s} value={s}>{s}</option>))}
              </select>
              <input className="rounded-md border border-border bg-soft px-2 py-2 text-sm" placeholder="notas…" value={draft.notes} onChange={(e) => setDraft((d) => ({ ...d, notes: e.target.value }))} />
              <div className="flex gap-2">
                <button type="button" className="btn btn-primary min-h-8 flex-1 text-xs" disabled={!!busy} onClick={() => void addRisk()}>Registrar</button>
                <button type="button" className="btn btn-secondary min-h-8 text-xs" disabled={!!busy} onClick={() => void assess()}><ShieldWarning size={13} /> Assess</button>
              </div>
            </div>
            <div className="mt-3 space-y-1">
              {risks.map((r) => (
                <div key={r.id} className="rounded-md bg-soft px-3 py-2 text-xs">
                  <div className="flex items-center gap-2">
                    <span className={`badge ${SEV[r.severity] ?? "badge-muted"}`}>{r.severity}</span>
                    <span className="flex-1 font-medium text-text">{r.risk_type}</span>
                    <span className="text-faint">{r.score}</span>
                    <span className="badge badge-muted">{r.source}</span>
                  </div>
                  <p className="mt-0.5 text-[10px] text-faint">{r.agent_name ?? "General"} · like {r.likelihood} · impact {r.impact} · {r.mitigations} mitigaciones</p>
                  <div className="mt-1 flex gap-1">
                    <button type="button" className="btn btn-ghost min-h-6 px-2 text-[10px]" disabled={!!busy} onClick={() => void act(r.id, "mitigate")}><CheckCircle size={10} /> Mitigar</button>
                    <button type="button" className="btn btn-ghost min-h-6 px-2 text-[10px]" disabled={!!busy} onClick={() => void act(r.id, "accept")}>Aceptar</button>
                  </div>
                </div>
              ))}
              {risks.length === 0 && <p className="text-xs text-faint">Sin riesgos abiertos. Corre "Assess" para detectar automáticamente.</p>}
            </div>
          </section>

          <section className="lg:col-span-2">
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <div className="panel p-4">
                <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text"><TrendUp size={14} /> Postura {framework}</h3>
                <p className="text-3xl font-bold text-text">{posture?.score ?? 0}%</p>
                <p className="text-xs text-faint">{posture?.implemented ?? 0}/{posture?.total_controls ?? 0} controles implementados · {posture?.in_review ?? 0} en revisión</p>
                <div className="mt-3 flex flex-wrap gap-1">
                  {FRAMEWORKS.map((f) => (
                    <button key={f} type="button" className={`btn min-h-6 px-2 text-[10px] ${framework === f ? "btn-primary" : "btn-ghost"}`} onClick={() => setFramework(f)}>{f}</button>
                  ))}
                </div>
                <div className="mt-3 space-y-1">
                  {Object.entries(posture?.by_risk_type ?? {}).map(([rt, v]) => (
                    <div key={rt} className="flex justify-between text-[11px]"><span className="text-text">{rt}</span><span className="text-faint">{v.implemented}/{v.total} · {v.pct}%</span></div>
                  ))}
                </div>
                <h4 className="mb-1 mt-3 text-xs font-semibold text-text">Tendencia</h4>
                <div className="flex h-16 items-end gap-1">
                  {(trend?.trend ?? []).slice(-14).map((t) => (
                    <div key={t.date} className="flex-1 rounded-t bg-accent/60" style={{ height: `${t.score}%` }} title={`${t.date}: ${t.score}%`} />
                  ))}
                </div>
              </div>

              <div className="panel p-4">
                <h3 className="mb-2 text-sm font-semibold text-text">Heatmap por agente</h3>
                <div className="space-y-2">
                  {(heatmap?.heatmap ?? []).map((a) => (
                    <div key={a.agent_id} className="rounded-md bg-soft p-2 text-[11px]">
                      <p className="font-medium text-text">{a.agent_name}</p>
                      <div className="mt-1 flex flex-wrap gap-1">
                        {Object.entries(a.risks).map(([rt, v]) => (
                          <span key={rt} className={`badge ${SEV[v.severity] ?? "badge-muted"}`}>{rt} {v.score}</span>
                        ))}
                      </div>
                    </div>
                  ))}
                  {(heatmap?.heatmap ?? []).length === 0 && <p className="text-xs text-faint">Sin riesgos abiertos.</p>}
                </div>
                <h4 className="mb-1 mt-3 text-xs font-semibold text-text">Mitigaciones</h4>
                <div className="max-h-40 space-y-1 overflow-y-auto">
                  {mitigations.slice(0, 8).map((m) => (
                    <p key={m.id} className="rounded bg-soft px-2 py-1 text-[10px] text-faint">{m.action_type} · {m.risk_type} · {m.description?.slice(0, 50)}</p>
                  ))}
                </div>
              </div>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}