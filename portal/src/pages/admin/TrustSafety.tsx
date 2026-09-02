import { Plus, ShieldWarning } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import { ErrorInline, PageHeader, SkeletonBlock } from "../../components/ui";
import { usePlatformAuth } from "../../platformAuth";

type Terms = { latest: { version: number; title: string; content: string } | null; versions: { version: number; title: string }[] };
type Consent = { organization_id: string; terms_version: number; consented_by: string | null; consented_at: string };
type Rule = { id: string; organization_id: string | null; name: string; category: string; patterns: string[]; min_score: number; action: string; enabled: boolean };
type Incident = { id: string; organization_id: string; direction: string; rule_name: string; score: number; snippet: string; action: string; status: string; resolution_note: string | null; created_at: string };
type Trust = { queries: number; blocked: number; warned: number; inputs: number; outputs: number; block_rate: number; by_rule: { rule_name: string; direction: string; action: string; total: number; resolved: number; dismissed: number; resolution_rate: number; avg_score: number }[] };

const ST = { open: "badge-danger", resolved: "badge-ok", dismissed: "badge-muted" } as Record<string, string>;

export default function AdminTrustSafetyPage() {
  const { session } = usePlatformAuth();
  const [terms, setTerms] = useState<Terms | null>(null);
  const [consents, setConsents] = useState<Consent[]>([]);
  const [rules, setRules] = useState<Rule[]>([]);
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [trust, setTrust] = useState<Trust | null>(null);
  const [orgs, setOrgs] = useState<{ id: string }[]>([]);
  const [orgId, setOrgId] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [ruleForm, setRuleForm] = useState({ name: "", category: "prohibited_topics", action: "block", min_score: 0.6, patterns: "" });
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
      const [t, c, r, i, d] = await Promise.all([
        platformApi<Terms>("/api/v1/platform/trust/aup/terms", { token: session.token }),
        platformApi<{ consents: Consent[] }>("/api/v1/platform/trust/aup/consents", { token: session.token }),
        platformApi<{ rules: Rule[] }>(`/api/v1/platform/trust/rules${orgId ? `?organization_id=${orgId}` : ""}`, { token: session.token }),
        platformApi<{ incidents: Incident[] }>(`/api/v1/platform/trust/incidents?${q}`, { token: session.token }),
        platformApi<Trust>("/api/v1/platform/trust/dashboard?hours=24", { token: session.token }),
      ]);
      setTerms(t);
      setConsents(c.consents || []);
      setRules(r.rules || []);
      setIncidents(i.incidents || []);
      setTrust(d);
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
    const id = setInterval(() => void loadAll(), 15000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session, orgId, statusFilter]);

  async function acceptAup() {
    if (!session) return;
    setBusy("aup");
    setError("");
    try {
      await platformApi("/api/v1/platform/trust/aup/accept", {
        method: "POST",
        token: session.token,
        body: JSON.stringify({ organization_id: orgId, terms_version: terms?.latest?.version ?? 1 }),
      });
      setNote("AUP aceptada por la org.");
      await loadAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function createRule() {
    if (!session) return;
    setBusy("rule");
    setError("");
    try {
      const patterns = ruleForm.patterns.split(",").map((p) => p.trim()).filter(Boolean);
      await platformApi("/api/v1/platform/trust/rules", {
        method: "POST",
        token: session.token,
        body: JSON.stringify({ ...ruleForm, patterns, organization_id: orgId }),
      });
      setRuleForm({ name: "", category: "prohibited_topics", action: "block", min_score: 0.6, patterns: "" });
      await loadAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function toggle(rule: Rule) {
    if (!session) return;
    try {
      await platformApi(`/api/v1/platform/trust/rules/${rule.id}/toggle`, {
        method: "POST",
        token: session.token,
        body: JSON.stringify({ enabled: !rule.enabled }),
      });
      await loadAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  async function act(incidentId: string, action: "resolve" | "dismiss") {
    if (!session) return;
    setBusy(`${action}-${incidentId.slice(0, 6)}`);
    try {
      await platformApi(`/api/v1/platform/trust/incidents/${incidentId}/${action}`, {
        method: "POST",
        token: session.token,
        body: JSON.stringify({ note: action === "resolve" ? "Revisado por el equipo de seguridad" : "Falso positivo" }),
      });
      await loadAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  const myConsent = consents.find((c) => c.organization_id === orgId);

  return (
    <div className="space-y-6">
      <PageHeader title="Trust & Safety Center" subtitle="AUP versionada, moderación de contenido con puntuación e incidentes." />
      {error && <ErrorInline>{error}</ErrorInline>}
      {note && <p className="rounded-md bg-soft px-3 py-2 text-xs text-text">{note}</p>}
      {loading ? (
        <SkeletonBlock className="h-40" />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
            <div className="panel p-4">
              <p className="stat-label">Consultas (24h)</p>
              <p className="stat-value">{(trust?.queries ?? 0).toLocaleString()}</p>
            </div>
            <div className="panel p-4">
              <p className="stat-label">Bloqueos</p>
              <p className="stat-value text-red-400">{trust?.blocked ?? 0}</p>
            </div>
            <div className="panel p-4">
              <p className="stat-label">Warnings</p>
              <p className="stat-value text-amber-400">{trust?.warned ?? 0}</p>
            </div>
            <div className="panel p-4">
              <p className="stat-label">Block rate</p>
              <p className="stat-value">{((trust?.block_rate ?? 0) * 100).toFixed(2)}%</p>
            </div>
            <div className="panel p-4">
              <p className="stat-label">Input/Output</p>
              <p className="stat-value text-xs">{trust?.inputs ?? 0}/{trust?.outputs ?? 0}</p>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
            <section className="panel p-4">
              <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text">
                <ShieldWarning size={15} aria-hidden /> AUP
              </h3>
              <p className="text-xs font-medium text-text">v{terms?.latest?.version ?? "?"}: {terms?.latest?.title ?? "—"}</p>
              <p className="mt-1 max-h-28 overflow-auto whitespace-pre-wrap rounded-md bg-soft p-2 text-[10px] text-faint">
                {terms?.latest?.content ?? "Sin términos."}
              </p>
              <div className="mt-2 flex items-center gap-2">
                <select className="rounded-md border border-border bg-soft px-2 py-1.5 text-xs" value={orgId} onChange={(e) => setOrgId(e.target.value)}>
                  {orgs.map((o) => (<option key={o.id} value={o.id}>{o.id.slice(0, 8)}</option>))}
                </select>
                <button type="button" className="btn btn-primary min-h-8 text-xs" disabled={!!busy || !orgId} onClick={() => void acceptAup()}>
                  Aceptar
                </button>
              </div>
              {myConsent ? (
                <p className="mt-1 text-[10px] text-faint">
                  Consentimiento v{myConsent.terms_version} · {new Date(myConsent.consented_at).toLocaleString()}
                </p>
              ) : (
                <p className="mt-1 text-[10px] text-amber-400">Sin consentimiento de esta org.</p>
              )}
            </section>

            <section className="panel p-4">
              <h3 className="mb-2 text-sm font-semibold text-text">Reglas de moderación</h3>
              <div className="grid grid-cols-2 gap-2">
                <input className="rounded-md border border-border bg-soft px-2 py-2 text-xs" placeholder="nombre" value={ruleForm.name} onChange={(e) => setRuleForm((f) => ({ ...f, name: e.target.value }))} />
                <select className="rounded-md border border-border bg-soft px-2 py-2 text-xs" value={ruleForm.category} onChange={(e) => setRuleForm((f) => ({ ...f, category: e.target.value }))}>
                  {["prohibited_topics", "toxicity", "malware", "financial_advice", "legal", "medical", "pii"].map((c) => (<option key={c} value={c}>{c}</option>))}
                </select>
                <input className="col-span-2 rounded-md border border-border bg-soft px-2 py-2 text-xs" placeholder='patterns separados por coma: "hackear cuenta, ransomware"' value={ruleForm.patterns} onChange={(e) => setRuleForm((f) => ({ ...f, patterns: e.target.value }))} />
                <select className="rounded-md border border-border bg-soft px-2 py-2 text-xs" value={ruleForm.action} onChange={(e) => setRuleForm((f) => ({ ...f, action: e.target.value }))}>
                  {["block", "warn"].map((a) => (<option key={a} value={a}>{a}</option>))}
                </select>
                <input type="number" step="0.1" min="0" max="1" className="rounded-md border border-border bg-soft px-2 py-2 text-xs" value={ruleForm.min_score} onChange={(e) => setRuleForm((f) => ({ ...f, min_score: Number(e.target.value) }))} />
              </div>
              <button type="button" className="btn btn-primary mt-2 min-h-8 text-xs" disabled={!!busy} onClick={() => void createRule()}>
                <Plus size={12} aria-hidden /> Crear
              </button>
              <div className="mt-2 space-y-1">
                {rules.map((r) => (
                  <div key={r.id} className="flex items-center justify-between rounded-md bg-soft px-3 py-1.5 text-[11px]">
                    <span className="truncate text-text">{r.name}</span>
                    <span className="text-faint">{r.category} · ≥{r.min_score} · {r.action}</span>
                    <button type="button" className="btn btn-ghost min-h-6 px-1.5 text-[10px]" onClick={() => void toggle(r)}>
                      {r.enabled ? "On" : "Off"}
                    </button>
                  </div>
                ))}
              </div>
            </section>

            <section className="panel p-4">
              <h3 className="mb-2 text-sm font-semibold text-text">Tasas por regla (24h)</h3>
              <div className="space-y-1">
                {(trust?.by_rule ?? []).map((r) => (
                  <div key={`${r.rule_name}:${r.direction}`} className="rounded-md bg-soft px-3 py-1.5 text-[11px]">
                    <div className="flex items-center justify-between">
                      <span className="truncate text-text">{r.rule_name} ({r.direction})</span>
                      <span className={`badge ${r.action === "block" ? "badge-danger" : "badge-warning"}`}>{r.action}</span>
                    </div>
                    <p className="text-faint">{r.total} inc · resuelto {r.resolved} ({(r.resolution_rate * 100).toFixed(0)}%) · score avg {r.avg_score}</p>
                  </div>
                ))}
                {(trust?.by_rule ?? []).length === 0 && <p className="text-xs text-faint">Sin incidentes en la ventana.</p>}
              </div>
            </section>
          </div>

          <section>
            <div className="mb-2 flex items-center gap-2">
              <h3 className="text-sm font-semibold text-text">Incidentes de contenido</h3>
              <select className="rounded-md border border-border bg-soft px-2 py-1.5 text-xs" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
                <option value="">todos</option>
                {["open", "resolved", "dismissed"].map((s) => (<option key={s} value={s}>{s}</option>))}
              </select>
            </div>
            <div className="panel overflow-x-auto">
              <table className="table">
                <thead>
                  <tr>
                    <th>Hora</th>
                    <th>Dir.</th>
                    <th>Regla</th>
                    <th>Score</th>
                    <th>Snippet</th>
                    <th>Estado</th>
                    <th className="text-right">Acción</th>
                  </tr>
                </thead>
                <tbody>
                  {incidents.map((i) => (
                    <tr key={i.id}>
                      <td className="text-[10px] text-faint">{new Date(i.created_at).toLocaleTimeString()}</td>
                      <td className="text-xs">{i.direction}</td>
                      <td className="text-xs">{i.rule_name}</td>
                      <td className="mono text-xs">{(i.score * 100).toFixed(0)}%</td>
                      <td className="max-w-56 truncate text-[10px] text-faint" title={i.snippet}>{i.snippet}</td>
                      <td><span className={`badge ${ST[i.status] ?? "badge-muted"}`}>{i.status}</span></td>
                      <td className="text-right">
                        {i.status === "open" && (
                          <>
                            <button type="button" className="btn btn-ghost min-h-8 px-2 text-xs" disabled={!!busy} onClick={() => void act(i.id, "resolve")}>Resolver</button>
                            <button type="button" className="btn btn-ghost min-h-8 px-2 text-xs" disabled={!!busy} onClick={() => void act(i.id, "dismiss")}>Desestimar</button>
                          </>
                        )}
                      </td>
                    </tr>
                  ))}
                  {incidents.length === 0 && <tr><td colSpan={7} className="p-4 text-center text-xs text-faint">Sin incidentes.</td></tr>}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </div>
  );
}