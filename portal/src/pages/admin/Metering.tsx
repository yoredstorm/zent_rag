import { Gauge, Plus, Warning } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import {
  ErrorInline,
  PageHeader,
  SkeletonBlock,
} from "../../components/ui";
import { usePlatformAuth } from "../../platformAuth";

type MeterOrg = {
  organization_id: string;
  requests: number;
  tokens: number;
  cost: number;
  errors: number;
  burst_5min: number;
  by_model: Record<string, number>;
};

type Rule = {
  id: string;
  plan_name: string | null;
  endpoint_prefix: string;
  limit_per_minute: number;
  burst: number;
  enabled: boolean;
  priority: number;
};

export default function AdminMeteringPage() {
  const { session } = usePlatformAuth();
  const [meter, setMeter] = useState<{ totals: MeterOrg; organizations: MeterOrg[] } | null>(null);
  const [rules, setRules] = useState<Rule[]>([]);
  const [throttles, setThrottles] = useState<Record<string, { throttle_factor: number; throttled: boolean; usage_pct: number }>>({});
  const [ruleForm, setRuleForm] = useState({ plan_name: "pro", endpoint_prefix: "/", limit_per_minute: 100, burst: 25 });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  async function load() {
    if (!session) return;
    setError("");
    try {
      const [m, r] = await Promise.all([
        platformApi<{ totals: MeterOrg; organizations: MeterOrg[] }>("/api/v1/platform/metering/realtime", {
          token: session.token,
        }),
        platformApi<{ rules: Rule[] }>("/api/v1/platform/rate-limits/rules", { token: session.token }),
      ]);
      setMeter(m);
      setRules(r.rules || []);
      // Throttle de las orgs con uso.
      const th: Record<string, { throttle_factor: number; throttled: boolean; usage_pct: number }> = {};
      for (const o of m.organizations.filter((x) => x.requests > 0).slice(0, 15)) {
        try {
          const t = await platformApi<{ throttle_factor: number; throttled: boolean; usage_pct: number }>(
            `/api/v1/platform/metering/throttle?organization_id=${o.organization_id}`,
            { token: session.token }
          );
          th[o.organization_id] = t;
        } catch {
          /* noop */
        }
      }
      setThrottles(th);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    const id = setInterval(() => void load(), 10000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  async function createRule() {
    if (!session) return;
    setBusy("rule");
    setError("");
    try {
      await platformApi("/api/v1/platform/rate-limits/rules", {
        method: "POST",
        token: session.token,
        body: JSON.stringify(ruleForm),
      });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function toggleRule(rule: Rule) {
    if (!session) return;
    try {
      await platformApi(`/api/v1/platform/rate-limits/rules/${rule.id}`, {
        method: "PUT",
        token: session.token,
        body: JSON.stringify({ ...rule, enabled: !rule.enabled }),
      });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Metering & Rate Limits" subtitle="Contadores en vivo (Redis), reglas por plan con burst y fair-use." />
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading ? (
        <SkeletonBlock className="h-40" />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
            <div className="panel p-4">
              <p className="stat-label">Requests hoy</p>
              <p className="stat-value">{(meter?.totals.requests ?? 0).toLocaleString()}</p>
            </div>
            <div className="panel p-4">
              <p className="stat-label">Tokens hoy</p>
              <p className="stat-value">{(meter?.totals.tokens ?? 0).toLocaleString()}</p>
            </div>
            <div className="panel p-4">
              <p className="stat-label">Costo hoy</p>
              <p className="stat-value">${(meter?.totals.cost ?? 0).toFixed(2)}</p>
            </div>
            <div className="panel p-4">
              <p className="stat-label">Burst 5 min</p>
              <p className="stat-value">{meter?.totals.burst_5min ?? 0}</p>
            </div>
            <div className="panel p-4">
              <p className="stat-label">Errores hoy</p>
              <p className="stat-value">{meter?.totals.errors ?? 0}</p>
            </div>
          </div>

          <section>
            <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text">
              <Gauge size={15} aria-hidden /> Por organización (poll 10s)
            </h3>
            <div className="panel overflow-x-auto">
              <table className="table">
                <thead>
                  <tr>
                    <th>Org</th>
                    <th>Requests</th>
                    <th>Tokens</th>
                    <th>Costo</th>
                    <th>Errores</th>
                    <th>Burst 5m</th>
                    <th>Modelos</th>
                    <th>Throttle</th>
                  </tr>
                </thead>
                <tbody>
                  {(meter?.organizations ?? []).filter((o) => o.requests > 0).map((o) => (
                    <tr key={o.organization_id}>
                      <td className="mono text-xs text-faint">{o.organization_id.slice(0, 13)}…</td>
                      <td className="text-xs">{o.requests}</td>
                      <td className="text-xs">{o.tokens.toLocaleString()}</td>
                      <td className="text-xs">${o.cost.toFixed(3)}</td>
                      <td className="text-xs">{o.errors}</td>
                      <td className="text-xs">{o.burst_5min}</td>
                      <td className="mono text-[10px] text-faint">{Object.entries(o.by_model).map(([m, n]) => `${m}:${n}`).join(" · ")}</td>
                      <td>
                        {throttles[o.organization_id]?.throttled ? (
                          <span className="badge badge-danger">
                            <Warning size={11} className="mr-1 inline" aria-hidden />
                            ×{throttles[o.organization_id].throttle_factor}
                          </span>
                        ) : (
                          <span className="text-xs text-faint">normal</span>
                        )}
                      </td>
                    </tr>
                  ))}
                  {(meter?.organizations ?? []).filter((o) => o.requests > 0).length === 0 && (
                    <tr><td colSpan={8} className="p-4 text-center text-xs text-faint">Sin actividad hoy.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>

          <section>
            <h3 className="mb-2 text-sm font-semibold text-text">Reglas por plan (con burst)</h3>
            <div className="panel grid grid-cols-1 gap-2 p-4 lg:grid-cols-6">
              <select className="rounded-md border border-border bg-soft px-2 py-2 text-sm" value={ruleForm.plan_name} onChange={(e) => setRuleForm((f) => ({ ...f, plan_name: e.target.value }))}>
                <option value="">Global</option>
                {["trial", "starter", "pro", "enterprise"].map((p) => (
                  <option key={p} value={p}>{p}</option>
                ))}
              </select>
              <input className="rounded-md border border-border bg-soft px-2 py-2 text-sm" placeholder="/api/v1/rag/query" value={ruleForm.endpoint_prefix} onChange={(e) => setRuleForm((f) => ({ ...f, endpoint_prefix: e.target.value }))} />
              <input type="number" className="rounded-md border border-border bg-soft px-2 py-2 text-sm" value={ruleForm.limit_per_minute} onChange={(e) => setRuleForm((f) => ({ ...f, limit_per_minute: Number(e.target.value) }))} />
              <input type="number" className="rounded-md border border-border bg-soft px-2 py-2 text-sm" placeholder="burst" value={ruleForm.burst} onChange={(e) => setRuleForm((f) => ({ ...f, burst: Number(e.target.value) }))} />
              <button type="button" className="btn btn-primary min-h-9 text-xs" disabled={!!busy} onClick={() => void createRule()}>
                <Plus size={13} aria-hidden /> Crear
              </button>
            </div>
            <div className="panel mt-2 overflow-x-auto">
              <table className="table">
                <thead>
                  <tr>
                    <th>Plan</th>
                    <th>Prefijo</th>
                    <th>Límite/min</th>
                    <th>Burst</th>
                    <th>Prioridad</th>
                    <th>Estado</th>
                    <th className="text-right">Toggle</th>
                  </tr>
                </thead>
                <tbody>
                  {rules.map((r) => (
                    <tr key={r.id}>
                      <td className="text-xs">{r.plan_name ?? "global"}</td>
                      <td className="mono text-xs">{r.endpoint_prefix}</td>
                      <td className="text-xs">{r.limit_per_minute}</td>
                      <td className="text-xs">{r.burst}</td>
                      <td className="text-xs">{r.priority}</td>
                      <td>
                        <span className={`badge ${r.enabled ? "badge-ok" : "badge-muted"}`}>{r.enabled ? "activa" : "inactiva"}</span>
                      </td>
                      <td className="text-right">
                        <button type="button" className="btn btn-ghost min-h-8 px-2 text-xs" onClick={() => void toggleRule(r)}>
                          {r.enabled ? "Desactivar" : "Activar"}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </div>
  );
}