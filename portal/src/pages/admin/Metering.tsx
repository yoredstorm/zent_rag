import { Gauge, Plus, Warning } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import {
  Badge,
  Button,
  EmptyState,
  ErrorInline,
  Field,
  Input,
  PageHeader,
  Panel,
  PanelHeader,
  Progress,
  SectionHeader,
  Select,
  Skeleton,
  StatusDot,
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

type Throttle = { throttle_factor: number; throttled: boolean; usage_pct: number };

function throttleTone(usagePct: number): "ok" | "warn" | "danger" {
  if (usagePct >= 90) return "danger";
  if (usagePct >= 75) return "warn";
  return "ok";
}

export default function AdminMeteringPage() {
  const { session } = usePlatformAuth();
  const [meter, setMeter] = useState<{ totals: MeterOrg; organizations: MeterOrg[] } | null>(null);
  const [rules, setRules] = useState<Rule[]>([]);
  const [throttles, setThrottles] = useState<Record<string, Throttle>>({});
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
      const th: Record<string, Throttle> = {};
      for (const o of m.organizations.filter((x) => x.requests > 0).slice(0, 15)) {
        try {
          const t = await platformApi<Throttle>(
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

  const activeOrgs = (meter?.organizations ?? []).filter((o) => o.requests > 0);
  const totals = meter?.totals;
  const throttledCount = activeOrgs.filter((o) => throttles[o.organization_id]?.throttled).length;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Metering & Rate Limits"
        subtitle="Contadores en vivo (Redis), reglas por plan con burst y fair-use."
      />
      <ErrorInline message={error} />
      {loading ? (
        <Panel className="p-4">
          <Skeleton className="h-24" />
        </Panel>
      ) : (
        <>
          <Panel className="p-4">
            <div className="flex flex-wrap items-start justify-between gap-x-8 gap-y-4">
              <div className="min-w-0">
                <p className="eyebrow">Requests hoy</p>
                <p className="mt-2 text-[30px] leading-none font-semibold tracking-[-0.025em] tabular-nums text-text">
                  {(totals?.requests ?? 0).toLocaleString()}
                </p>
                <p className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-[13px] text-muted">
                  {throttledCount > 0 ? (
                    <>
                      <StatusDot tone="warn" />
                      <span className="text-warn">
                        {throttledCount} organización(es) con tráfico limitado ahora mismo.
                      </span>
                    </>
                  ) : (
                    <>
                      <StatusDot tone="ok" />
                      <span>Sin organizaciones limitadas en la última lectura.</span>
                    </>
                  )}
                </p>
              </div>
              <dl className="grid grid-cols-2 gap-x-8 gap-y-3 sm:grid-cols-4">
                <div>
                  <dt className="eyebrow">Tokens</dt>
                  <dd className="mt-1 text-sm tabular-nums text-text">
                    {(totals?.tokens ?? 0).toLocaleString()}
                  </dd>
                </div>
                <div>
                  <dt className="eyebrow">Costo</dt>
                  <dd className="mt-1 font-mono text-sm tabular-nums text-text">
                    ${(totals?.cost ?? 0).toFixed(2)}
                  </dd>
                </div>
                <div>
                  <dt className="eyebrow">Errores</dt>
                  <dd
                    className={`mt-1 text-sm tabular-nums ${(totals?.errors ?? 0) > 0 ? "text-danger" : "text-text"}`}
                  >
                    {totals?.errors ?? 0}
                  </dd>
                </div>
                <div>
                  <dt className="eyebrow">Burst 5 min</dt>
                  <dd className="mt-1 text-sm tabular-nums text-text">{totals?.burst_5min ?? 0}</dd>
                </div>
              </dl>
            </div>
          </Panel>

          <section>
            <SectionHeader
              title="Por organización"
              description="Lectura en vivo, refrescada cada 10 segundos."
              className="mb-3"
            />
            <Panel className="overflow-x-auto">
              <table className="table min-w-[880px]">
                <thead>
                  <tr>
                    <th>Organización</th>
                    <th className="text-right">Requests</th>
                    <th className="text-right">Tokens</th>
                    <th className="text-right">Costo</th>
                    <th className="text-right">Errores</th>
                    <th className="text-right">Burst 5m</th>
                    <th>Modelos</th>
                    <th className="w-44">Throttle</th>
                  </tr>
                </thead>
                <tbody>
                  {activeOrgs.map((o) => {
                    const t = throttles[o.organization_id];
                    return (
                      <tr key={o.organization_id}>
                        <td className="mono text-xs text-faint" title={o.organization_id}>
                          {o.organization_id.slice(0, 13)}…
                        </td>
                        <td className="text-right tabular-nums">{o.requests.toLocaleString()}</td>
                        <td className="text-right tabular-nums">{o.tokens.toLocaleString()}</td>
                        <td className="text-right font-mono tabular-nums">${o.cost.toFixed(3)}</td>
                        <td
                          className={`text-right tabular-nums ${o.errors > 0 ? "text-danger" : ""}`}
                        >
                          {o.errors}
                        </td>
                        <td className="text-right tabular-nums">{o.burst_5min}</td>
                        <td className="mono max-w-56 truncate text-[11px] text-faint">
                          {Object.entries(o.by_model)
                            .map(([m, n]) => `${m}:${n}`)
                            .join(" · ")}
                        </td>
                        <td>
                          {t ? (
                            <div className="flex items-center gap-2">
                              {t.throttled ? (
                                <Badge tone="danger" icon={Warning}>
                                  Limitado ×{t.throttle_factor}
                                </Badge>
                              ) : (
                                <Badge tone="ok">Normal</Badge>
                              )}
                              <Progress
                                value={t.usage_pct}
                                tone={throttleTone(t.usage_pct)}
                                className="min-w-20 flex-1"
                              />
                            </div>
                          ) : (
                            <span className="text-xs text-faint" title="Sin lectura de throttle para esta organización">
                              Sin lectura
                            </span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                  {activeOrgs.length === 0 && (
                    <tr>
                      <td colSpan={8}>
                        <EmptyState
                          icon={Gauge}
                          compact
                          title="Sin actividad hoy"
                          body="Ninguna organización registró requests en la ventana en vivo."
                        />
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </Panel>
          </section>

          <section>
            <SectionHeader
              title="Reglas por plan"
              description="Límite por minuto con burst por prefijo de endpoint. La prioridad más alta gana."
              className="mb-3"
            />
            <Panel>
              <PanelHeader title="Nueva regla" />
              <div className="grid grid-cols-1 gap-3 p-4 sm:grid-cols-2 lg:grid-cols-4 lg:items-end">
                <Field label="Plan">
                  <Select
                    value={ruleForm.plan_name}
                    onChange={(e) => setRuleForm((f) => ({ ...f, plan_name: e.target.value }))}
                  >
                    <option value="">Global</option>
                    {["trial", "starter", "pro", "enterprise"].map((p) => (
                      <option key={p} value={p}>
                        {p}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Field label="Prefijo de endpoint" hint="Ej. /api/v1/rag/query">
                  <Input
                    value={ruleForm.endpoint_prefix}
                    onChange={(e) => setRuleForm((f) => ({ ...f, endpoint_prefix: e.target.value }))}
                  />
                </Field>
                <Field label="Límite por minuto">
                  <Input
                    type="number"
                    value={ruleForm.limit_per_minute}
                    onChange={(e) => setRuleForm((f) => ({ ...f, limit_per_minute: Number(e.target.value) }))}
                  />
                </Field>
                <div className="flex gap-2">
                  <Field label="Burst" className="flex-1">
                    <Input
                      type="number"
                      value={ruleForm.burst}
                      onChange={(e) => setRuleForm((f) => ({ ...f, burst: Number(e.target.value) }))}
                    />
                  </Field>
                  <Button
                    variant="primary"
                    leadingIcon={Plus}
                    loading={busy === "rule"}
                    onClick={() => void createRule()}
                    className="self-end"
                  >
                    Crear
                  </Button>
                </div>
              </div>
              <div className="overflow-x-auto border-t border-border">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Plan</th>
                      <th>Prefijo</th>
                      <th className="text-right">Límite/min</th>
                      <th className="text-right">Burst</th>
                      <th className="text-right">Prioridad</th>
                      <th>Estado</th>
                      <th className="text-right">Acción</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rules.map((r) => (
                      <tr key={r.id}>
                        <td>{r.plan_name ?? "global"}</td>
                        <td className="mono text-xs">{r.endpoint_prefix}</td>
                        <td className="text-right tabular-nums">{r.limit_per_minute}</td>
                        <td className="text-right tabular-nums">{r.burst}</td>
                        <td className="text-right tabular-nums">{r.priority}</td>
                        <td>
                          <Badge tone={r.enabled ? "ok" : "neutral"} dot>
                            {r.enabled ? "Activa" : "Inactiva"}
                          </Badge>
                        </td>
                        <td className="text-right">
                          <Button size="sm" variant="ghost" onClick={() => void toggleRule(r)}>
                            {r.enabled ? "Desactivar" : "Activar"}
                          </Button>
                        </td>
                      </tr>
                    ))}
                    {rules.length === 0 && (
                      <tr>
                        <td colSpan={7}>
                          <EmptyState
                            icon={Gauge}
                            compact
                            title="Sin reglas de rate limit"
                            body="Las requests no se están limitando por plan ni por prefijo."
                            hint="Creá la primera regla con el formulario de arriba."
                          />
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </Panel>
          </section>
        </>
      )}
    </div>
  );
}
