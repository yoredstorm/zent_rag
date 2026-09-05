import { Bell, Coins, Gauge, WarningCircle } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import { PageTabs } from "../../components/PageTabs";
import {
  EmptyState,
  ErrorInline,
  PageHeader,
  SkeletonBlock,
  StatCard,
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

function CostTable({ title, rows }: { title: string; rows?: Row[] }) {
  const list = rows ?? [];
  const total = list.reduce((sum, row) => sum + row.cost, 0);
  return (
    <div className="overflow-x-auto">
      <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-faint">{title}</p>
      <table className="table">
        <thead>
          <tr>
            <th>Dimensión</th>
            <th>Requests</th>
            <th>Tokens</th>
            <th>Costo</th>
            <th>%</th>
          </tr>
        </thead>
        <tbody>
          {list.length === 0 ? (
            <tr>
              <td colSpan={5} className="text-sm text-muted">
                Sin datos.
              </td>
            </tr>
          ) : (
            list.map((r) => (
              <tr key={r.label}>
                <td className="text-sm text-text">{r.label}</td>
                <td className="text-xs text-muted">{r.requests}</td>
                <td className="text-xs text-muted">{r.tokens.toLocaleString()}</td>
                <td className="text-sm">{usd(r.cost, 4)}</td>
                <td className="text-xs text-faint">
                  {total > 0 ? ((r.cost / total) * 100).toFixed(1) : "0.0"}%
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
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
    try {
      const out = await platformApi<{ alerts_created?: { type: string }[] }>(
        "/api/v1/platform/finops/check",
        { method: "POST", token: session.token, body: "{}" }
      );
      const created = out.alerts_created?.length ?? 0;
      setError(created ? `${created} alertas creadas` : "Sin alertas nuevas");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  const groups: { title: string; rows: Row[] }[] = breakdown
    ? [
        { title: "Por provider", rows: breakdown.by_provider ?? [] },
        { title: "Por modelo", rows: breakdown.by_model ?? [] },
        { title: "Por workspace", rows: breakdown.by_workspace ?? [] },
        { title: "Por agente", rows: breakdown.by_agent ?? [] },
        { title: "Por deployment", rows: breakdown.by_deployment ?? [] },
      ]
    : [];

  return (
    <div className="space-y-6">
      <PageHeader
        title="AI Costs (FinOps)"
        subtitle="Revenue, costos, margen y desglose por dimensión. Las alertas detectan budget, margen negativo y spikes."
        actions={
          <button type="button" className="btn btn-primary min-h-11" onClick={() => void runChecks()}>
            <Gauge size={15} aria-hidden /> Ejecutar checks
          </button>
        }
      />
      <ErrorInline message={error} />
      <div className="mb-4">
        <PageTabs
          idPrefix="finops"
          tabs={[
            { id: "overview", label: "Overview" },
            { id: "costs", label: "Costs" },
          ]}
          active={tab}
          onChange={(next) => setTab(next as "overview" | "costs")}
        />
      </div>
      {loading ? (
        <SkeletonBlock />
      ) : tab === "overview" ? (
        <>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {summary && (
              <>
                <StatCard label="Revenue (cash)" value={usdCents(summary.revenue_cents)} />
                <StatCard label="MRR" value={usdCents(summary.mrr_cents)} />
                <StatCard label="AI cost" value={usd(summary.costs.llm + summary.costs.embedding, 2)} />
                <StatCard
                  label="Gross margin"
                  value={summary.gross_margin_pct != null ? `${summary.gross_margin_pct.toFixed(1)}%` : "—"}
                  tone={summary.gross_margin_pct != null && summary.gross_margin_pct < 0 ? "danger" : "default"}
                />
              </>
            )}
            {economics && (
              <>
                <StatCard label="Requests" value={economics.requests} />
                <StatCard label="Cost/request" value={economics.cost_per_request != null ? usd(economics.cost_per_request, 6) : "—"} />
                <StatCard
                  label="Cost/customer"
                  value={summary?.economics.cost_per_customer != null ? usd(summary.economics.cost_per_customer, 4) : "—"}
                />
                <StatCard label="Tokens/request" value={economics.tokens_per_request ?? "—"} />
              </>
            )}
          </div>
          <p className="text-xs text-faint">
            Desglose por provider, modelo, workspace, agente y deployment en la pestaña Costs.
          </p>
        </>
      ) : (
        <>
          <section>
            <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text">
              <Bell size={15} aria-hidden /> Alertas FinOps
            </h3>
            <div className="panel">
              {alerts.length === 0 ? (
                <EmptyState icon={Bell} title="Sin alertas" body="Ejecuta los checks para detectar problemas." />
              ) : (
                <ul className="space-y-2">
                  {alerts.map((al) => (
                    <li
                      key={al.id}
                      className={`flex flex-wrap items-center justify-between gap-2 rounded-md border p-2.5 ${
                        al.acknowledged ? "border-border bg-soft" : "border-warn-soft bg-warn-soft/30"
                      }`}
                    >
                      <div className="min-w-0">
                        <p className="text-sm text-text">
                          {!al.acknowledged && <WarningCircle size={14} className="mr-1 inline text-warn" aria-hidden />}
                          {al.message}
                        </p>
                        <p className="text-xs text-faint">
                          {al.alert_type} · {new Date(al.created_at).toLocaleString("es-PE")}
                        </p>
                      </div>
                      {!al.acknowledged && (
                        <span className="text-xs text-faint">Pendiente</span>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </section>

          <section>
            <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text">
              <Coins size={15} aria-hidden /> Desglose de costos
            </h3>
            <div className="panel grid grid-cols-1 gap-6 xl:grid-cols-2">
              {groups.map((g) => (
                <CostTable key={g.title} title={g.title} rows={g.rows} />
              ))}
            </div>
          </section>
        </>
      )}
    </div>
  );
}