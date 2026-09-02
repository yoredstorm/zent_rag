import { Bell, Coins, Gauge, WarningCircle } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
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

function CostTable({ title, rows }: { title: string; rows: Row[] }) {
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
          {rows.map((r) => (
            <tr key={r.label}>
              <td className="text-sm text-text">{r.label}</td>
              <td className="text-xs text-muted">{r.requests}</td>
              <td className="text-xs text-muted">{r.tokens.toLocaleString()}</td>
              <td className="text-sm">{usd(r.cost, 4)}</td>
              <td className="text-xs text-faint">
                {total > 0 ? ((r.cost / total) * 100).toFixed(1) : "0.0"}%
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
let total = 0;

export default function AdminFinOpsPage() {
  const { session } = usePlatformAuth();
  const [summary, setSummary] = useState<Summary | null>(null);
  const [breakdown, setBreakdown] = useState<{
    by_agent: Row[];
    by_workspace: Row[];
    by_deployment: Row[];
    by_provider: Row[];
    by_model: Row[];
  } | null>(null);
  const [economics, setEconomics] = useState<Economics | null>(null);
  const [alerts, setAlerts] = useState<FinOpsAlert[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [orgId, setOrgId] = useState("");

  async function load(oid = "") {
    if (!session) return;
    setError("");
    try {
      const base = oid ? `/organizations/${oid}` : "";
      const [s, b, e, a] = await Promise.all([
        platformApi<Summary>(`/api/v1/platform/finops/summary${oid ? `/organizations/${oid}` : ""}`, {
          token: session.token,
        }).catch(() => null),
        platformApi<{
          by_agent: Row[];
          by_workspace: Row[];
          by_deployment: Row[];
          by_provider: Row[];
          by_model: Row[];
        }>(`/api/v1/platform/finops/breakdown?organization_id=${oid}`, { token: session.token }),
        platformApi<Economics>(`/api/v1/platform/finops/economics?organization_id=${oid}`, {
          token: session.token,
        }),
        oid
          ? platformApi<{ alerts: FinOpsAlert[] }>(`/api/v1/platform/finops/alerts?organization_id=${oid}`, {
              token: session.token,
            })
          : Promise.resolve({ alerts: [] as FinOpsAlert[] }),
      ]);
      setSummary(s);
      setBreakdown(b);
      setEconomics(e);
      setAlerts(a.alerts || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load(orgId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session, orgId]);

  async function runChecks() {
    if (!session) return;
    try {
      const out = await platformApi<{ alerts_created: { type: string }[] }>(
        "/api/v1/platform/finops/check",
        { method: "POST", token: session.token, body: "{}" }
      );
      setError(out.alerts_created.length ? `${out.alerts_created.length} alertas creadas` : "Sin alertas nuevas");
      await load(orgId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  async function ack(alertId: string) {
    if (!session) return;
    try {
      await platformApi(
        `/api/v1/platform/finops/alerts/${alertId}/ack?organization_id=${orgId}`,
        { method: "POST", token: session.token, body: "{}" }
      );
      await load(orgId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  const groups: { title: string; rows: Row[] }[] = breakdown
    ? [
        { title: "Por provider", rows: breakdown.by_provider },
        { title: "Por modelo", rows: breakdown.by_model },
        { title: "Por workspace", rows: breakdown.by_workspace },
        { title: "Por agente", rows: breakdown.by_agent },
        { title: "Por deployment", rows: breakdown.by_deployment },
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
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading ? (
        <SkeletonBlock className="h-40" />
      ) : (
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
                <StatCard label="Cost/1K requests" value={economics.cost_per_1k_requests != null ? usd(economics.cost_per_1k_requests, 4) : "—"} />
                <StatCard label="Tokens/request" value={economics.tokens_per_request ?? "—"} />
              </>
            )}
          </div>

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
                        <button type="button" className="btn btn-ghost min-h-8 text-xs" onClick={() => void ack(al.id)}>
                          Reconocer
                        </button>
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