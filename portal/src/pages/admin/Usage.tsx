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
              <StatCard
                label="Revenue (cash)"
                value={usdCents(data.revenue_cents)}
                help="Suma de invoices.total_cents con status paid y paid_at en el periodo. Es cash cobrado, no MRR."
              />
              <StatCard
                label="MRR activo"
                value={usdCents(data.mrr_cents)}
                hint="suscripciones active/trialing"
                help="Run-rate de planes active + trialing (anual / 12). No es cash y no se suma a Revenue."
              />
              <StatCard
                label="Clientes nuevos"
                value={data.customers.new}
                help="Organizaciones con created_at dentro del periodo seleccionado."
              />
              <StatCard
                label="Churn"
                value={data.customers.churned}
                help="Suscripciones canceled con canceled_at en el periodo. Puede quedar en 0 si canceled_at no está poblado."
              />
              <StatCard
                label="ARPU"
                value={
                  data.customers.arpu_cents == null
                    ? "—"
                    : usdCents(data.customers.arpu_cents)
                }
                help="Revenue cash del periodo dividido entre orgs con al menos una factura pagada. Null si nadie pagó."
              />
              <StatCard
                label="Gross profit"
                value={usd(data.gross_profit)}
                tone={data.gross_profit >= 0 ? "ok" : "danger"}
                help="Revenue cash menos LLM, embeddings, storage e infra del periodo."
              />
              <StatCard
                label="Gross margin"
                value={
                  data.gross_margin_pct == null ? "—" : `${data.gross_margin_pct}%`
                }
                help="Gross profit / revenue cash × 100. Null si el revenue del periodo es 0."
              />
            </div>
          </section>

          <section aria-labelledby="finops-costs">
            <h2 id="finops-costs" className="mb-3 text-sm font-semibold text-text">
              Costes
            </h2>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <StatCard
                label="LLM"
                value={usd(data.costs.llm)}
                help="Coste de usage_events clasificados como LLM (COALESCE actual_cost, estimated_cost)."
              />
              <StatCard
                label="Embeddings"
                value={usd(data.costs.embedding)}
                help="Eventos de embedding (tokens de embed o modelos embed/bge/e5)."
              />
              <StatCard
                label="Storage"
                value={usd(data.costs.storage)}
                help="Estimación Qdrant × dimensión × overage_storage del plan. 0 si Qdrant no responde."
              />
              <StatCard
                label="Infra"
                value={usd(data.costs.infra)}
                hint="rate configurable por org/mes"
                help="RAG_FINOPS_INFRA_COST_PER_ORG_MONTH_CENTS × orgs activas × (días del periodo / 30). Default 0."
              />
            </div>
          </section>

          <section aria-labelledby="finops-economics">
            <h2 id="finops-economics" className="mb-3 text-sm font-semibold text-text">
              Economía AI
            </h2>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <StatCard
                label="Requests"
                value={data.economics.requests}
                help="Número de usage_events de AI en el periodo (denominador de coste/revenue por request)."
              />
              <StatCard
                label="Coste / request"
                value={ratio(data.economics.cost_per_request)}
                help="(LLM + embeddings + storage + infra) / requests del periodo."
              />
              <StatCard
                label="Coste / customer"
                value={ratio(data.economics.cost_per_customer)}
                help="Costes del periodo divididos entre clientes con actividad o factura en el recorte FinOps."
              />
              <StatCard
                label="Revenue / request"
                value={ratio(data.economics.revenue_per_request)}
                help="Revenue cash del periodo dividido entre requests. Sube si hay pocas queries y cobros grandes."
              />
              <StatCard
                label="Margen / customer"
                value={ratio(data.economics.margin_per_customer)}
                help="Gross profit del periodo por cliente. No es margen de un tenant individual."
              />
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
