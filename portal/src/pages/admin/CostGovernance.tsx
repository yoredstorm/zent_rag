import { PiggyBank, Plus, Tag, Warning } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import {
  Badge,
  Button,
  EmptyState,
  ErrorInline,
  Field,
  InfoInline,
  Input,
  Metric,
  MetricGrid,
  PageHeader,
  Panel,
  PanelHeader,
  SectionHeader,
  Select,
  Skeleton,
  Toolbar,
  ToolbarSpacer,
} from "../../components/ui";
import { usePlatformAuth } from "../../platformAuth";

type Tag = { id: string; organization_id: string; key: string; value: string };
type CostRow = { tag_value: string; requests: number; cost: number; tokens: number };
type TeamRow = { team: string; organization_id: string; cost: number; requests: number; share_pct: number };
type Rule = { id: string; category: string; dimension: string | null; threshold_pct: number; adaptive: boolean; enabled: boolean };
type Alert = { id: string; category: string; dimension: string | null; baseline_daily_cents: number; today_cents: number; triggered_at: string };
type Forecast = { total_cost: number; trend_per_day: number; projected_next_30d: number; by_plan: { plan: string; cost: number }[]; by_model: { model: string; cost: number }[] };

function money(value: number | null | undefined, digits = 2) {
  return value == null ? "—" : `$${value.toFixed(digits)}`;
}

/** Barra de participación: el ancho es el dato, el texto lo confirma. */
function ShareBar({ value }: { value: number }) {
  return (
    <span className="flex min-w-28 items-center gap-2">
      <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-track" aria-hidden>
        <span
          className="block h-full rounded-full bg-accent"
          style={{ width: `${Math.min(Math.max(value, 0), 100)}%` }}
        />
      </span>
      <span className="w-12 text-right text-xs text-faint tabular-nums">{value.toFixed(1)}%</span>
    </span>
  );
}

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

  const breakdown = costs?.breakdown ?? [];
  const maxCost = Math.max(...breakdown.map((b) => b.cost), 0.001);
  const teams = showback?.teams ?? [];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Cost Governance & FinOps"
        subtitle="Costos por unidad de negocio, alertas adaptativas, showback por equipo y forecast."
      />
      <ErrorInline message={error} />
      {note && <InfoInline>{note}</InfoInline>}
      {loading ? (
        <Panel className="p-4">
          <Skeleton className="h-32" />
        </Panel>
      ) : (
        <>
          <Toolbar>
            <Field label="Organización" className="w-full sm:w-56">
              <Select
                value={orgId}
                onChange={(e) => {
                  setOrgId(e.target.value);
                  void loadAll(e.target.value);
                }}
              >
                {orgs.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.id.slice(0, 8)}
                  </option>
                ))}
              </Select>
            </Field>
            <ToolbarSpacer />
            <Button
              variant="primary"
              leadingIcon={Warning}
              loading={busy === "run"}
              onClick={() => void runAlerts()}
              className="self-end"
            >
              Evaluar alertas ahora
            </Button>
          </Toolbar>

          <Panel className="p-4">
            <p className="eyebrow">Costo etiquetado · últimos 30 días</p>
            <p className="mt-2 text-[30px] leading-none font-semibold tracking-[-0.025em] tabular-nums text-text">
              {money(costs?.total)}
            </p>
            <p className="mt-2 max-w-[68ch] text-[13px] leading-relaxed text-muted">
              {forecast
                ? `Tendencia real de ${money(forecast.trend_per_day, 3)}/día. El backend proyecta ${money(forecast.projected_next_30d)} para los próximos 30 días.`
                : "Sin forecast calculado: hace falta más historial de costos en la ventana."}
            </p>
          </Panel>

          <MetricGrid cols={3}>
            <Metric
              size="md"
              label="Showback asignado"
              value={money(showback?.total_cost)}
              hint={`${teams.length} equipo(s) en la ventana`}
            />
            <Metric
              size="md"
              label="Proyección 30d"
              value={money(forecast?.projected_next_30d)}
              hint="Cálculo del backend"
            />
            <Metric
              size="md"
              label="Unidades etiquetadas"
              value={breakdown.length.toLocaleString()}
              hint={`Clave activa: ${costs?.key ?? "—"}`}
            />
          </MetricGrid>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <section>
              <SectionHeader title="Costos por unidad de negocio" description="30 días, agrupado por tag." className="mb-3" />
              <Panel className="overflow-x-auto">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Unidad</th>
                      <th className="text-right">Requests</th>
                      <th className="text-right">Costo</th>
                      <th className="w-36">Participación</th>
                    </tr>
                  </thead>
                  <tbody>
                    {breakdown.map((b) => (
                      <tr key={b.tag_value}>
                        <td className="max-w-40 truncate">{b.tag_value}</td>
                        <td className="text-right tabular-nums">{b.requests.toLocaleString()}</td>
                        <td className="text-right font-mono tabular-nums">{money(b.cost)}</td>
                        <td>
                          <ShareBar value={(b.cost / maxCost) * 100} />
                        </td>
                      </tr>
                    ))}
                    {breakdown.length === 0 && (
                      <tr>
                        <td colSpan={4}>
                          <EmptyState
                            icon={Tag}
                            compact
                            title="Sin costos etiquetados"
                            body="Ningún evento de costo tiene un tag asignado en la ventana."
                            hint="Creá un tag abajo y aplicálo desde el cliente para ver el desglose."
                          />
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </Panel>
            </section>

            <section>
              <SectionHeader title="Showback / Chargeback" description="Costos asignados por equipo." className="mb-3" />
              <Panel className="overflow-x-auto">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Equipo</th>
                      <th className="text-right">Requests</th>
                      <th className="text-right">Costo</th>
                      <th className="w-36">Share</th>
                    </tr>
                  </thead>
                  <tbody>
                    {teams.map((t) => (
                      <tr key={t.team}>
                        <td className="max-w-40 truncate">{t.team}</td>
                        <td className="text-right tabular-nums">{t.requests.toLocaleString()}</td>
                        <td className="text-right font-mono tabular-nums">{money(t.cost)}</td>
                        <td>
                          <ShareBar value={t.share_pct} />
                        </td>
                      </tr>
                    ))}
                    {teams.length === 0 && (
                      <tr>
                        <td colSpan={4}>
                          <EmptyState
                            icon={PiggyBank}
                            compact
                            title="Sin costos asignados"
                            body="Ningún equipo tiene costos atribuidos en esta ventana."
                          />
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </Panel>
              {teams.length > 0 && (
                <p className="mt-2 text-xs text-faint">
                  El share se calcula sobre el total asignado ({money(showback?.total_cost)}).
                </p>
              )}
            </section>
          </div>

          <section>
            <SectionHeader
              title="Tags de costo"
              description="Etiquetas con las que se atribuye cada evento a una unidad de negocio."
              className="mb-3"
            />
            <Panel>
              <div className="flex flex-wrap items-end gap-3 p-4">
                <Field label="Clave" className="w-full sm:w-44">
                  <Input
                    value={tagForm.key}
                    onChange={(e) => setTagForm((f) => ({ ...f, key: e.target.value }))}
                  />
                </Field>
                <Field label="Valor" className="w-full sm:w-44">
                  <Input
                    value={tagForm.value}
                    onChange={(e) => setTagForm((f) => ({ ...f, value: e.target.value }))}
                  />
                </Field>
                <Button
                  variant="primary"
                  leadingIcon={Plus}
                  loading={busy === "tag"}
                  disabled={!orgId}
                  onClick={() => void createTag()}
                >
                  Crear tag
                </Button>
              </div>
              <div className="flex flex-wrap gap-1.5 border-t border-border px-4 py-3">
                {tags.length === 0 ? (
                  <p className="text-xs text-faint">Sin tags registrados para esta organización.</p>
                ) : (
                  tags.map((t) => (
                    <Badge key={t.id} tone="neutral">
                      {t.key}={t.value}
                    </Badge>
                  ))
                )}
              </div>
            </Panel>
          </section>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <section>
              <SectionHeader
                title="Reglas adaptativas"
                description="Comparan el gasto diario contra el baseline semanal."
                className="mb-3"
              />
              <Panel>
                <div className="grid grid-cols-1 gap-3 p-4 sm:grid-cols-3 sm:items-end">
                  <Field label="Categoría">
                    <Select
                      value={ruleForm.category}
                      onChange={(e) => setRuleForm((f) => ({ ...f, category: e.target.value }))}
                    >
                      {["total", "model", "team"].map((c) => (
                        <option key={c} value={c}>
                          {c}
                        </option>
                      ))}
                    </Select>
                  </Field>
                  <Field label="Dimensión" hint="Opcional">
                    <Input
                      value={ruleForm.dimension}
                      onChange={(e) => setRuleForm((f) => ({ ...f, dimension: e.target.value }))}
                    />
                  </Field>
                  <div className="flex gap-2">
                    <Field label="Umbral %" className="flex-1">
                      <Input
                        type="number"
                        value={ruleForm.threshold_pct}
                        onChange={(e) => setRuleForm((f) => ({ ...f, threshold_pct: Number(e.target.value) }))}
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
                        <th>Regla</th>
                        <th>Baseline</th>
                        <th className="text-right">Umbral</th>
                        <th>Estado</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rules.map((r) => (
                        <tr key={r.id}>
                          <td>
                            {r.category}
                            {r.dimension ? `:${r.dimension}` : ""}
                          </td>
                          <td className="text-xs text-muted">{r.adaptive ? "Semanal adaptativa" : "Fija"}</td>
                          <td className="text-right tabular-nums">+{r.threshold_pct}%</td>
                          <td>
                            <Badge tone={r.enabled ? "ok" : "neutral"} dot>
                              {r.enabled ? "Activa" : "Inactiva"}
                            </Badge>
                          </td>
                        </tr>
                      ))}
                      {rules.length === 0 && (
                        <tr>
                          <td colSpan={4}>
                            <EmptyState
                              icon={Warning}
                              compact
                              title="Sin reglas adaptativas"
                              body="Ningún umbral compara el gasto diario contra su baseline."
                            />
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </Panel>
            </section>

            <section>
              <SectionHeader
                title="Alertas disparadas"
                description="Comparación del gasto de hoy contra el baseline diario."
                className="mb-3"
              />
              <Panel>
                {alerts.length === 0 ? (
                  <EmptyState
                    icon={Warning}
                    compact
                    tone="accent"
                    title="Sin alertas en la ventana"
                    body="El gasto diario se mantiene dentro del baseline."
                  />
                ) : (
                  <ol className="divide-y divide-border-soft">
                    {alerts.map((a) => {
                      const delta = a.today_cents - a.baseline_daily_cents;
                      return (
                        <li key={a.id} className="state-rail px-4 py-3" data-state="warning">
                          <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
                            <p className="text-sm text-text">
                              {a.category}
                              {a.dimension ? `:${a.dimension}` : ""}
                            </p>
                            <time dateTime={a.triggered_at} className="text-xs text-faint tabular-nums">
                              {new Date(a.triggered_at).toLocaleString("es-PE")}
                            </time>
                          </div>
                          <p className="mt-0.5 text-xs text-faint">
                            Hoy <span className="font-mono text-text">{money(a.today_cents / 100)}</span> contra baseline{" "}
                            <span className="font-mono text-text">{money(a.baseline_daily_cents / 100)}</span> ·{" "}
                            <span className={delta > 0 ? "text-warn tabular-nums" : "tabular-nums"}>
                              {delta > 0 ? "+" : ""}
                              {money(delta / 100)}
                            </span>
                          </p>
                        </li>
                      );
                    })}
                  </ol>
                )}
              </Panel>
            </section>
          </div>

          {Boolean(forecast?.by_plan?.length || forecast?.by_model?.length) && (
            <Panel>
              <PanelHeader
                title="Composición del forecast"
                description="Peso real de cada plan y modelo en el costo proyectado."
              />
              <div className="grid grid-cols-1 gap-6 p-4 sm:grid-cols-2">
                <div>
                  <h4 className="eyebrow mb-2">Por plan</h4>
                  <ul className="space-y-1.5">
                    {(forecast?.by_plan ?? []).map((p) => (
                      <li key={p.plan} className="flex items-center justify-between gap-3 text-[13px]">
                        <span className="truncate text-text">{p.plan}</span>
                        <span className="font-mono tabular-nums text-muted">{money(p.cost)}</span>
                      </li>
                    ))}
                  </ul>
                </div>
                <div>
                  <h4 className="eyebrow mb-2">Por modelo</h4>
                  <ul className="space-y-1.5">
                    {(forecast?.by_model ?? []).map((m) => (
                      <li key={m.model} className="flex items-center justify-between gap-3 text-[13px]">
                        <span className="truncate text-text">{m.model}</span>
                        <span className="font-mono tabular-nums text-muted">{money(m.cost)}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            </Panel>
          )}
        </>
      )}
    </div>
  );
}
