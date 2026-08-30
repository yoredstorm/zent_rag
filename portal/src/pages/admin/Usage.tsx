import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import { ErrorInline, PageHeader, SkeletonBlock, StatCard } from "../../components/ui";
import { usePlatformAuth } from "../../platformAuth";

type Costs = {
  llm: number;
  embedding: number;
  storage: number;
  infra: number;
};

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

function ratio(value: number | null) {
  if (value == null) return "—";
  return usd(value);
}

export default function AdminUsagePage() {
  const { session } = usePlatformAuth();
  const [data, setData] = useState<Summary | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!session) return;
    (async () => {
      setLoading(true);
      try {
        setData(
          await platformApi<Summary>("/api/v1/platform/finops/summary", {
            token: session.token,
          })
        );
        setError("");
      } catch (err) {
        setError(err instanceof Error ? err.message : "Error cargando FinOps");
      } finally {
        setLoading(false);
      }
    })();
  }, [session]);

  return (
    <div>
      <PageHeader
        title="FinOps"
        subtitle="Ingresos de facturas pagadas frente a costes LLM, embeddings, storage e infra. Sin cifras de demo."
      />
      <ErrorInline message={error} />
      {loading && <SkeletonBlock />}
      {data && (
        <div className="space-y-8">
          <p className="text-sm text-muted">
            Periodo {new Date(data.period.start).toLocaleDateString("es-CL")} –{" "}
            {new Date(data.period.end).toLocaleDateString("es-CL")}. Base de
            ingresos: {data.revenue_basis === "invoices_paid" ? "facturas pagadas" : data.revenue_basis}.
            MRR activo (nota): {usdCents(data.mrr_cents)}.
          </p>

          <section aria-labelledby="finops-revenue">
            <h2 id="finops-revenue" className="mb-3 text-sm font-semibold text-text">
              Ingresos
            </h2>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <StatCard label="Revenue (cash)" value={usdCents(data.revenue_cents)} />
              <StatCard label="MRR activo" value={usdCents(data.mrr_cents)} hint="suscripciones active/trialing" />
              <StatCard label="Clientes nuevos" value={data.customers.new} />
              <StatCard label="Churn" value={data.customers.churned} />
              <StatCard
                label="ARPU"
                value={
                  data.customers.arpu_cents == null
                    ? "—"
                    : usdCents(data.customers.arpu_cents)
                }
              />
              <StatCard
                label="Gross profit"
                value={usd(data.gross_profit)}
                tone={data.gross_profit >= 0 ? "ok" : "danger"}
              />
              <StatCard
                label="Gross margin"
                value={
                  data.gross_margin_pct == null ? "—" : `${data.gross_margin_pct}%`
                }
              />
            </div>
          </section>

          <section aria-labelledby="finops-costs">
            <h2 id="finops-costs" className="mb-3 text-sm font-semibold text-text">
              Costes
            </h2>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <StatCard label="LLM" value={usd(data.costs.llm)} />
              <StatCard label="Embeddings" value={usd(data.costs.embedding)} />
              <StatCard label="Storage" value={usd(data.costs.storage)} />
              <StatCard
                label="Infra"
                value={usd(data.costs.infra)}
                hint="rate configurable por org/mes"
              />
            </div>
          </section>

          <section aria-labelledby="finops-economics">
            <h2 id="finops-economics" className="mb-3 text-sm font-semibold text-text">
              Economía AI
            </h2>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <StatCard label="Requests" value={data.economics.requests} />
              <StatCard label="Coste / request" value={ratio(data.economics.cost_per_request)} />
              <StatCard label="Coste / customer" value={ratio(data.economics.cost_per_customer)} />
              <StatCard
                label="Revenue / request"
                value={ratio(data.economics.revenue_per_request)}
              />
              <StatCard
                label="Margen / customer"
                value={ratio(data.economics.margin_per_customer)}
              />
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
