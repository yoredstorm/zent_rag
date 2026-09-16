import { Bell, Coins, Gauge, WarningCircle } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import { PageTabs } from "../../components/PageTabs";
import {
  Badge,
  Button,
  EmptyState,
  ErrorInline,
  Metric,
  MetricGrid,
  PageHeader,
  Panel,
  PanelHeader,
  Progress,
  SectionHeader,
  SkeletonTable,
  SuccessInline,
} from "../../components/ui";
import { usePlatformAuth } from "../../platformAuth";

type Costs = { llm: number; embedding: number; storage: number; infra: number };
type Summary = {
  period: { start: string; end: string };
  revenue_cents: number;
  revenue_basis: string;
  mrr_cents: number;
  costs: Costs;
  gross_profit: number;
  gross_margin_pct: number | null;
  customers: { new: number; churned: number; arpu_cents: number | null };
  economics: {
    cost_per_request: number | null;
    cost_per_customer: number | null;
    revenue_per_request: number | null;
    margin_per_customer: number | null;
    requests: number;
  };
};

type Row = { label: string; requests: number; cost: number; tokens: number };
type Economics = {
  requests: number;
  tokens: number;
  total_cost: number;
  cost_per_request: number | null;
  cost_per_1k_requests: number | null;
  tokens_per_request: number | null;
};

type FinOpsAlert = {
  id: string;
  alert_type: string;
  message: string;
  threshold_value: number | null;
  actual_value: number | null;
  acknowledged: boolean;
  created_at: string;
};

function usd(amount: number, digits = 2) {
  return new Intl.NumberFormat("es-CL", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: digits,
  }).format(amount);
}

function usdCents(cents: number) {
  return usd(cents / 100, 0);
}

function aiCost(summary: Summary) {
  return (summary.costs?.llm ?? 0) + (summary.costs?.embedding ?? 0);
}

function asRows(value: unknown): Row[] {
  return Array.isArray(value) ? (value as Row[]) : [];
}

function mergeRows(groups: Row[][]): Row[] {
  const acc = new Map<string, Row>();
  for (const rows of groups) {
    for (const row of rows) {
      const current = acc.get(row.label) ?? { label: row.label, requests: 0, cost: 0, tokens: 0 };
      current.requests += row.requests;
      current.cost += row.cost;
      current.tokens += row.tokens;
      acc.set(row.label, current);
    }
  }
  return [...acc.values()].sort((a, b) => b.cost - a.cost);
}

type Breakdown = {
  by_agent: Row[];
  by_workspace: Row[];
  by_deployment: Row[];
  by_provider: Row[];
  by_model: Row[];
};

function normalizeBreakdown(payload: {
  by_agent?: Row[];
  by_workspace?: Row[];
  by_deployment?: Row[];
  by_provider?: Row[];
  by_model?: Row[];
  organizations?: Array<Partial<Breakdown>>;
} | null): Breakdown | null {
  if (!payload) return null;
  const orgs = payload.organizations;
  if (Array.isArray(orgs) && !payload.by_provider && !payload.by_agent) {
    return {
      by_agent: mergeRows(orgs.map((item) => asRows(item.by_agent))),
      by_workspace: mergeRows(orgs.map((item) => asRows(item.by_workspace))),
      by_deployment: mergeRows(orgs.map((item) => asRows(item.by_deployment))),
      by_provider: mergeRows(orgs.map((item) => asRows(item.by_provider))),
      by_model: mergeRows(orgs.map((item) => asRows(item.by_model))),
    };
  }
  return {
    by_agent: asRows(payload.by_agent),
    by_workspace: asRows(payload.by_workspace),
    by_deployment: asRows(payload.by_deployment),
    by_provider: asRows(payload.by_provider),
    by_model: asRows(payload.by_model),
  };
}

function normalizeEconomics(
  payload: (Economics & { organizations?: Economics[] }) | null
): Economics | null {
  if (!payload) return null;
  if (typeof payload.requests === "number") return payload;
  const orgs = payload.organizations;
  if (!Array.isArray(orgs) || orgs.length === 0) return null;
  const requests = orgs.reduce((sum, item) => sum + (item.requests || 0), 0);
  const tokens = orgs.reduce((sum, item) => sum + (item.tokens || 0), 0);
  const totalCost = orgs.reduce((sum, item) => sum + (item.total_cost || 0), 0);
  return {
    requests,
    tokens,
    total_cost: totalCost,
    cost_per_request: requests ? totalCost / requests : null,
    cost_per_1k_requests: requests ? (totalCost / requests) * 1000 : null,
    tokens_per_request: requests ? tokens / requests : null,
  };
}

/** Desglose denso: montos a la derecha y participación con barra real. */
function CostTable({ title, rows }: { title: string; rows?: Row[] }) {
  const list = rows ?? [];
  const total = list.reduce((sum, row) => sum + row.cost, 0);
  return (
    <section className="min-w-0">
      <h3 className="eyebrow mb-2">{title}</h3>
      <div className="overflow-x-auto">
        <table className="table">
          <thead>
            <tr>
              <th>Dimensión</th>
              <th className="text-right">Requests</th>
              <th className="text-right">Tokens</th>
              <th className="text-right">Costo</th>
              <th className="w-32">Participación</th>
            </tr>
          </thead>
          <tbody>
            {list.length === 0 ? (
              <tr>
                <td colSpan={5}>
                  <p className="py-2 text-[13px] text-muted">Sin eventos de costo en el período.</p>
                </td>
              </tr>
            ) : (
              list.map((r) => {
                const share = total > 0 ? (r.cost / total) * 100 : 0;
                return (
                  <tr key={r.label}>
                    <td className="max-w-56 truncate">{r.label}</td>
                    <td className="text-right tabular-nums">{r.requests.toLocaleString()}</td>
                    <td className="text-right tabular-nums">{r.tokens.toLocaleString()}</td>
                    <td className="text-right font-mono tabular-nums">{usd(r.cost, 4)}</td>
                    <td>
                      <span className="flex items-center gap-2">
                        <span className="h-1.5 w-14 shrink-0 overflow-hidden rounded-full bg-track" aria-hidden>
                          <span
                            className="block h-full rounded-full bg-accent"
                            style={{ width: `${Math.min(share, 100)}%` }}
                          />
                        </span>
                        <span className="text-xs text-faint tabular-nums">{share.toFixed(1)}%</span>
                      </span>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export default function AdminFinOpsPage() {
  const { session } = usePlatformAuth();
  const [tab, setTab] = useState<"overview" | "costs">("overview");
  const [summary, setSummary] = useState<Summary | null>(null);
  const [breakdown, setBreakdown] = useState<Breakdown | null>(null);
  const [economics, setEconomics] = useState<Economics | null>(null);
  const [alerts, setAlerts] = useState<FinOpsAlert[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");

  async function load() {
    if (!session) return;
    setError("");
    try {
      const [s, b, e, al] = await Promise.all([
        platformApi<Summary>("/api/v1/platform/finops/summary", {
          token: session.token,
        }).catch(() => null),
        platformApi<{
          by_agent?: Row[];
          by_workspace?: Row[];
          by_deployment?: Row[];
          by_provider?: Row[];
          by_model?: Row[];
          organizations?: Array<Partial<Breakdown>>;
        }>("/api/v1/platform/finops/breakdown", { token: session.token }),
        platformApi<Economics & { organizations?: Economics[] }>(
          "/api/v1/platform/finops/economics",
          { token: session.token }
        ),
        platformApi<{ alerts: FinOpsAlert[] }>("/api/v1/platform/finops/alerts", {
          token: session.token,
        }).catch(() => ({ alerts: [] as FinOpsAlert[] })),
      ]);
      setSummary(s);
      setBreakdown(normalizeBreakdown(b));
      setEconomics(normalizeEconomics(e));
      setAlerts(al.alerts || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  async function runChecks() {
    if (!session) return;
    setNote("");
    try {
      const out = await platformApi<{ alerts_created?: { type: string }[] }>(
        "/api/v1/platform/finops/check",
        { method: "POST", token: session.token, body: "{}" }
      );
      const created = out.alerts_created?.length ?? 0;
      setError("");
      setNote(created ? `${created} alertas creadas.` : "Sin alertas nuevas.");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  const groups: { title: string; rows: Row[] }[] = breakdown
    ? [
        { title: "Por provider", rows: breakdown.by_provider ?? [] },
        { title: "Por modelo", rows: breakdown.by_model ?? [] },
        { title: "Por tenant / workspace", rows: breakdown.by_workspace ?? [] },
        { title: "Por agente", rows: breakdown.by_agent ?? [] },
        { title: "Por deployment", rows: breakdown.by_deployment ?? [] },
      ]
    : [];

  const aiCostValue = summary ? aiCost(summary) : null;
  const revenue = summary ? summary.revenue_cents / 100 : null;
  const aiSharePct = revenue != null && revenue > 0 && aiCostValue != null ? (aiCostValue / revenue) * 100 : null;
  const marginTone =
    summary?.gross_margin_pct == null
      ? "default"
      : summary.gross_margin_pct < 0
        ? "danger"
        : summary.gross_margin_pct < 20
          ? "warn"
          : "ok";
  const shareTone = aiSharePct == null ? "accent" : aiSharePct > 60 ? "danger" : aiSharePct > 35 ? "warn" : "ok";
  const pendingAlerts = alerts.filter((al) => !al.acknowledged).length;

  return (
    <div className="space-y-6">
      <PageHeader
        title="AI Costs (FinOps)"
        subtitle="Revenue, costos, margen y desglose por dimensión. Las alertas detectan budget, margen negativo y spikes."
        actions={
          <Button variant="primary" leadingIcon={Gauge} onClick={() => void runChecks()}>
            Ejecutar checks
          </Button>
        }
      />
      <ErrorInline message={error} />
      {note && <SuccessInline>{note}</SuccessInline>}
      <PageTabs
        idPrefix="finops"
        tabs={[
          { id: "overview", label: "Overview" },
          { id: "costs", label: "Costs" },
        ]}
        active={tab}
        onChange={(next) => setTab(next as "overview" | "costs")}
      />
      {loading ? (
        <Panel className="overflow-hidden">
          <SkeletonTable rows={6} cols={4} />
        </Panel>
      ) : tab === "overview" ? (
        <>
          <Panel className="p-4">
            {summary ? (
              <div className="flex flex-wrap items-start justify-between gap-x-8 gap-y-4">
                <div className="min-w-0">
                  <p className="eyebrow">Margen bruto del período</p>
                  <p className="mt-2 text-[30px] leading-none font-semibold tracking-[-0.025em] tabular-nums">
                    <span
                      className={
                        marginTone === "danger"
                          ? "text-danger"
                          : marginTone === "warn"
                            ? "text-warn"
                            : "text-text"
                      }
                    >
                      {summary.gross_margin_pct != null ? `${summary.gross_margin_pct.toFixed(1)}%` : "—"}
                    </span>
                  </p>
                  <p className="mt-2 max-w-[68ch] text-[13px] leading-relaxed text-muted">
                    {summary.gross_margin_pct == null
                      ? "Todavía no hay revenue ni costos suficientes para calcular el margen."
                      : summary.gross_margin_pct < 0
                        ? "Los costos de AI superan los ingresos del período. Revisá el desglose antes de ampliar cuota."
                        : `Revenue ${usdCents(summary.revenue_cents)} contra AI cost ${usd(aiCostValue ?? 0, 2)}.`}
                  </p>
                </div>
                <div className="min-w-[220px] flex-1 sm:max-w-sm">
                  {aiSharePct != null ? (
                    <Progress
                      value={aiSharePct}
                      tone={shareTone === "danger" ? "danger" : shareTone === "warn" ? "warn" : "ok"}
                      label="AI cost sobre revenue"
                      showValue
                    />
                  ) : (
                    <p className="text-xs text-faint">Sin revenue en el período para medir la proporción.</p>
                  )}
                  {summary.gross_margin_pct == null && (
                    <p className="mt-2 text-xs text-faint">
                      El margen se calcula cuando hay revenue y costos en la misma ventana.
                    </p>
                  )}
                </div>
              </div>
            ) : (
              <EmptyState
                icon={Coins}
                compact
                title="Sin resumen de FinOps"
                body="El endpoint de summary no respondió. El desglose por dimensión sigue disponible en Costs."
              />
            )}
          </Panel>

          {(summary || economics) && (
            <section>
              <SectionHeader title="Ingresos y costos" className="mb-3" />
              <MetricGrid cols={4}>
                {summary && (
                  <>
                    <Metric size="md" label="Revenue (cash)" value={usdCents(summary.revenue_cents)} />
                    <Metric size="md" label="MRR" value={usdCents(summary.mrr_cents)} />
                    <Metric size="md" label="AI cost" value={usd(aiCostValue ?? 0, 2)} />
                    <Metric
                      size="md"
                      label="Gross profit"
                      value={usd(summary.gross_profit, 2)}
                      tone={summary.gross_profit < 0 ? "danger" : "default"}
                    />
                  </>
                )}
              </MetricGrid>
            </section>
          )}

          {economics && (
            <section>
              <SectionHeader title="Unit economics" className="mb-3" />
              <MetricGrid cols={4}>
                <Metric size="md" label="Requests" value={economics.requests.toLocaleString()} />
                <Metric
                  size="md"
                  label="Cost/request"
                  value={economics.cost_per_request != null ? usd(economics.cost_per_request, 6) : "—"}
                />
                <Metric
                  size="md"
                  label="Cost/customer"
                  value={
                    summary?.economics?.cost_per_customer != null
                      ? usd(summary.economics.cost_per_customer, 4)
                      : "—"
                  }
                />
                <Metric
                  size="md"
                  label="Tokens/request"
                  value={economics.tokens_per_request != null ? economics.tokens_per_request.toFixed(0) : "—"}
                />
              </MetricGrid>
            </section>
          )}

          <section>
            <SectionHeader
              title="Atención"
              description="Alertas de budget, margen y spikes detectadas por los checks."
              className="mb-3"
            />
            <Panel>
              {alerts.length === 0 ? (
                <EmptyState
                  icon={Bell}
                  compact
                  tone="accent"
                  title="Sin alertas de costo"
                  body="Ningún umbral de budget, margen o spike se disparó."
                  hint="Ejecutá los checks para evaluar los umbrales ahora."
                />
              ) : (
                <ul className="divide-y divide-border-soft">
                  {alerts.map((al) => (
                    <li
                      key={al.id}
                      className="state-rail flex flex-wrap items-center justify-between gap-x-4 gap-y-2 px-4 py-3"
                      data-state={al.acknowledged ? "ready" : "warning"}
                    >
                      <div className="min-w-0">
                        <p className="text-sm text-text">{al.message}</p>
                        <p className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-faint">
                          <span className="mono">{al.alert_type}</span>
                          <span aria-hidden>·</span>
                          <span className="tabular-nums">{new Date(al.created_at).toLocaleString("es-PE")}</span>
                          {al.actual_value != null && (
                            <>
                              <span aria-hidden>·</span>
                              <span className="tabular-nums">
                                actual {al.actual_value.toLocaleString()}
                                {al.threshold_value != null ? ` / umbral ${al.threshold_value.toLocaleString()}` : ""}
                              </span>
                            </>
                          )}
                        </p>
                      </div>
                      <Badge tone={al.acknowledged ? "neutral" : "warn"} icon={WarningCircle}>
                        {al.acknowledged ? "Reconocida" : "Pendiente"}
                      </Badge>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
            {pendingAlerts > 0 && (
              <p className="text-xs text-warn">{pendingAlerts} alerta(s) sin reconocer.</p>
            )}
          </section>
        </>
      ) : (
        <Panel>
          <PanelHeader
            title="Desglose de costos"
            description="Costo, requests y tokens por dimensión en el período consultado."
          />
          <div className="grid grid-cols-1 gap-x-8 gap-y-6 p-4 xl:grid-cols-2">
            {groups.map((g) => (
              <CostTable key={g.title} title={g.title} rows={g.rows} />
            ))}
          </div>
        </Panel>
      )}
    </div>
  );
}
