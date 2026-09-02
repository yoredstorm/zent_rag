import { PiggyBank, Plus, Warning } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import { ErrorInline, PageHeader, SkeletonBlock } from "../../components/ui";
import { usePlatformAuth } from "../../platformAuth";

type Tag = { id: string; organization_id: string; key: string; value: string };
type CostRow = { tag_value: string; requests: number; cost: number; tokens: number };
type TeamRow = { team: string; organization_id: string; cost: number; requests: number; share_pct: number };
type Rule = { id: string; category: string; dimension: string | null; threshold_pct: number; adaptive: boolean; enabled: boolean };
type Alert = { id: string; category: string; dimension: string | null; baseline_daily_cents: number; today_cents: number; triggered_at: string };
type Forecast = { total_cost: number; trend_per_day: number; projected_next_30d: number; by_plan: { plan: string; cost: number }[]; by_model: { model: string; cost: number }[] };

export default function AdminCostGovernancePage() {
  const { session } = usePlatformAuth();
  const [orgs, setOrgs] = useState<{ id: string }[]>([]);
  const [orgId, setOrgId] = useState("");
  const [tags, setTags] = useState<Tag[]>([]);
  const [costs, setCosts] = useState<{ key: string; total: number; breakdown: CostRow[] } | null>(null);
  const [showback, setShowback] = useState<{ total_cost: number; teams: TeamRow[] } | null>(null);
  const [forecast, setForecast] = useState<Forecast | null>(null);
  const [rules, setRules] = useState<Rule[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [tagForm, setTagForm] = useState({ key: "team", value: "" });
  const [ruleForm, setRuleForm] = useState({ category: "total", dimension: "", threshold_pct: 20, adaptive: true });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [note, setNote] = useState("");

  async function loadAll(oid: string) {
    if (!session) return;
    setError("");
    setNote("");
    try {
      const [t, c, s, f, r, a] = await Promise.all([
        platformApi<{ tags: Tag[] }>(`/api/v1/platform/cost-governance/tags?organization_id=${oid}`, { token: session.token }),
        platformApi<{ key: string; total: number; breakdown: CostRow[] }>(`/api/v1/platform/cost-governance/costs?key=team&days=30&organization_id=${oid}`, { token: session.token }),
        platformApi<{ total_cost: number; teams: TeamRow[] }>(`/api/v1/platform/cost-governance/showback?days=30&organization_id=${oid}`, { token: session.token }),
        platformApi<Forecast>(`/api/v1/platform/cost-governance/forecast?days=30&organization_id=${oid}`, { token: session.token }),
        platformApi<{ rules: Rule[] }>(`/api/v1/platform/cost-governance/alerts/rules?organization_id=${oid}`, { token: session.token }),
        platformApi<{ alerts: Alert[] }>(`/api/v1/platform/cost-governance/alerts?organization_id=${oid}`, { token: session.token }),
      ]);
      setTags(t.tags || []);
      setCosts(c);
      setShowback(s);
      setForecast(f);
      setRules(r.rules || []);
      setAlerts(a.alerts || []);
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
        if (o.organizations?.length) {
          setOrgId(o.organizations[0].id);
          await loadAll(o.organizations[0].id);
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : "Error");
        setLoading(false);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  async function createTag() {
    if (!session) return;
    setBusy("tag");
    setError("");
    try {
      const out = await platformApi<{ status?: string; id?: string }>("/api/v1/platform/cost-governance/tags", {
        method: "POST",
        token: session.token,
        body: JSON.stringify({ organization_id: orgId, key: tagForm.key, value: tagForm.value }),
      });
      setNote(out.status === "exists" ? "El tag ya existía." : `Tag ${tagForm.key}=${tagForm.value} creado.`);
      setTagForm({ key: "team", value: "" });
      await loadAll(orgId);
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
      await platformApi("/api/v1/platform/cost-governance/alerts/rules", {
        method: "POST",
        token: session.token,
        body: JSON.stringify({ organization_id: orgId, ...ruleForm, dimension: ruleForm.dimension || null }),
      });
      await loadAll(orgId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function runAlerts() {
    if (!session) return;
    setBusy("run");
    setError("");
    try {
      const out = await platformApi<{ fired: unknown[] }>(`/api/v1/platform/cost-governance/alerts/run?organization_id=${orgId}`, {
        method: "POST",
        token: session.token,
      });
      setNote(`${out.fired.length} alerta(s) disparada(s).`);
      await loadAll(orgId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  const maxCost = Math.max(...(costs?.breakdown ?? []).map((b) => b.cost), 0.001);

  return (
    <div className="space-y-6">
      <PageHeader title="Cost Governance & FinOps" subtitle="Costos por unidad de negocio, alertas adaptativas, showback por equipo y forecast." />
      {error && <ErrorInline>{error}</ErrorInline>}
      {note && <p className="rounded-md bg-soft px-3 py-2 text-xs text-text">{note}</p>}
      {loading ? (
        <SkeletonBlock className="h-40" />
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <select className="rounded-md border border-border bg-soft px-2 py-2 text-sm" value={orgId} onChange={(e) => { setOrgId(e.target.value); void loadAll(e.target.value); }}>
              {orgs.map((o) => (<option key={o.id} value={o.id}>{o.id.slice(0, 8)}</option>))}
            </select>
            <button type="button" className="btn btn-primary min-h-9 text-xs" disabled={!!busy} onClick={() => void runAlerts()}>
              <Warning size={13} aria-hidden /> Evaluar alertas ahora
            </button>
          </div>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
            <section className="panel p-4">
              <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text">
                <PiggyBank size={15} aria-hidden /> Costos por equipo (30d)
              </h3>
              <p className="stat-label">Total</p>
              <p className="stat-value">${costs?.total.toFixed(2) ?? "0.00"}</p>
              <div className="mt-2 space-y-1">
                {(costs?.breakdown ?? []).map((b) => (
                  <div key={b.tag_value} className="flex items-center gap-2 text-xs">
                    <span className="w-28 truncate text-text">{b.tag_value}</span>
                    <div className="h-2 flex-1 rounded-full bg-soft">
                      <div className="h-2 rounded-full bg-accent" style={{ width: `${(b.cost / maxCost) * 100}%` }} />
                    </div>
                    <span className="mono text-faint">${b.cost.toFixed(2)} · {b.requests}</span>
                  </div>
                ))}
                {(costs?.breakdown ?? []).length === 0 && <p className="text-xs text-faint">Sin eventos etiquetados.</p>}
              </div>
              <h3 className="mb-2 mt-4 text-sm font-semibold text-text">Tags</h3>
              <div className="grid grid-cols-2 gap-2">
                <input className="rounded-md border border-border bg-soft px-2 py-2 text-xs" placeholder="key (team)" value={tagForm.key} onChange={(e) => setTagForm((f) => ({ ...f, key: e.target.value }))} />
                <input className="rounded-md border border-border bg-soft px-2 py-2 text-xs" placeholder="value (finanzas)" value={tagForm.value} onChange={(e) => setTagForm((f) => ({ ...f, value: e.target.value }))} />
              </div>
              <button type="button" className="btn btn-primary mt-2 min-h-8 text-xs" disabled={!!busy || !orgId} onClick={() => void createTag()}>
                <Plus size={12} aria-hidden /> Crear tag
              </button>
              <div className="mt-2 flex flex-wrap gap-1">
                {tags.map((t) => (
                  <span key={t.id} className="badge badge-muted">{t.key}={t.value}</span>
                ))}
              </div>
            </section>

            <section className="panel p-4">
              <h3 className="mb-2 text-sm font-semibold text-text">Showback / Chargeback (30d)</h3>
              <p className="stat-label">Total asignado</p>
              <p className="stat-value">${showback?.total_cost.toFixed(2) ?? "0.00"}</p>
              <div className="mt-2 space-y-1">
                {(showback?.teams ?? []).map((t) => (
                  <div key={t.team} className="flex items-center justify-between rounded-md bg-soft px-3 py-1.5 text-xs">
                    <span className="truncate text-text">{t.team}</span>
                    <span className="mono text-faint">${t.cost.toFixed(2)} · {t.share_pct}% · {t.requests} req</span>
                  </div>
                ))}
                {(showback?.teams ?? []).length === 0 && <p className="text-xs text-faint">Sin costos en la ventana.</p>}
              </div>
            </section>

            <section className="panel p-4">
              <h3 className="mb-2 text-sm font-semibold text-text">Forecast (30d)</h3>
              <p className="stat-label">Proyectado próximos 30 días</p>
              <p className="stat-value">${forecast?.projected_next_30d.toFixed(2) ?? "0.00"}</p>
              <p className="text-xs text-faint">Actual: ${forecast?.total_cost.toFixed(2) ?? "0.00"} · trend ${forecast?.trend_per_day.toFixed(3) ?? "0.000"}/día</p>
              <div className="mt-2 grid grid-cols-2 gap-2 text-[11px]">
                <div className="rounded-md bg-soft p-2">
                  <p className="mb-1 font-medium text-text">Por plan</p>
                  {(forecast?.by_plan ?? []).map((p) => (
                    <p key={p.plan} className="flex justify-between text-faint"><span>{p.plan}</span><span className="mono">${p.cost.toFixed(2)}</span></p>
                  ))}
                </div>
                <div className="rounded-md bg-soft p-2">
                  <p className="mb-1 font-medium text-text">Por modelo</p>
                  {(forecast?.by_model ?? []).map((m) => (
                    <p key={m.model} className="flex justify-between text-faint"><span className="truncate">{m.model}</span><span className="mono">${m.cost.toFixed(2)}</span></p>
                  ))}
                </div>
              </div>
            </section>
          </div>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <section className="panel p-4">
              <h3 className="mb-2 text-sm font-semibold text-text">Reglas adaptativas (baseline semanal)</h3>
              <div className="grid grid-cols-5 gap-2">
                <select className="col-span-2 rounded-md border border-border bg-soft px-2 py-2 text-xs" value={ruleForm.category} onChange={(e) => setRuleForm((f) => ({ ...f, category: e.target.value }))}>
                  {["total", "model", "team"].map((c) => (<option key={c} value={c}>{c}</option>))}
                </select>
                <input className="rounded-md border border-border bg-soft px-2 py-2 text-xs" placeholder="dimension" value={ruleForm.dimension} onChange={(e) => setRuleForm((f) => ({ ...f, dimension: e.target.value }))} />
                <input type="number" className="rounded-md border border-border bg-soft px-2 py-2 text-xs" value={ruleForm.threshold_pct} onChange={(e) => setRuleForm((f) => ({ ...f, threshold_pct: Number(e.target.value) }))} />
                <button type="button" className="btn btn-primary min-h-8 text-xs" disabled={!!busy} onClick={() => void createRule()}>
                  <Plus size={12} aria-hidden /> Crear
                </button>
              </div>
              <div className="mt-2 space-y-1">
                {rules.map((r) => (
                  <div key={r.id} className="flex items-center justify-between rounded-md bg-soft px-3 py-1.5 text-xs">
                    <span className="text-text">{r.category}{r.dimension ? `:${r.dimension}` : ""}</span>
                    <span className="text-faint">{r.adaptive ? "adaptativa" : "fija"} · +{r.threshold_pct}%</span>
                    <span className={`badge ${r.enabled ? "badge-ok" : "badge-muted"}`}>{r.enabled ? "activa" : "inactiva"}</span>
                  </div>
                ))}
                {rules.length === 0 && <p className="text-xs text-faint">Sin reglas.</p>}
              </div>
            </section>

            <section className="panel p-4">
              <h3 className="mb-2 text-sm font-semibold text-text">Alertas disparadas</h3>
              <div className="space-y-1">
                {alerts.map((a) => (
                  <div key={a.id} className="flex items-center justify-between rounded-md bg-soft px-3 py-1.5 text-xs">
                    <span className="text-text">{a.category}{a.dimension ? `:${a.dimension}` : ""}</span>
                    <span className="mono text-faint">${(a.today_cents / 100).toFixed(2)} hoy vs ${(a.baseline_daily_cents / 100).toFixed(2)} base</span>
                    <span className="text-faint">{new Date(a.triggered_at).toLocaleString()}</span>
                  </div>
                ))}
                {alerts.length === 0 && <p className="text-xs text-faint">Sin alertas en la ventana.</p>}
              </div>
            </section>
          </div>
        </>
      )}
    </div>
  );
}