import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import { ErrorInline, PageHeader, SkeletonBlock, StatCard } from "../../components/ui";
import { usePlatformAuth } from "../../platformAuth";

type Metrics = {
  mrr_cents: number;
  arr_cents: number;
  customers: number;
  active_agents: number;
  ai_requests_30d: number;
  llm_cost_30d: number;
  gross_margin_pct: number | null;
};

type EvalSummary = {
  run_count: number;
  organizations: { organization_id: string; run_count: number }[];
};

function money(cents: number) {
  return new Intl.NumberFormat("es-CL", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(cents / 100);
}

export default function AdminDashboardPage() {
  const { session } = usePlatformAuth();
  const [data, setData] = useState<Metrics | null>(null);
  const [evalSummary, setEvalSummary] = useState<EvalSummary | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!session) return;
    (async () => {
      setLoading(true);
      try {
        setData(await platformApi<Metrics>("/api/v1/platform/metrics", { token: session.token }));
        setEvalSummary(
          await platformApi<EvalSummary>("/api/v1/platform/eval/summary", {
            token: session.token,
          }).catch(() => null)
        );
        setError("");
      } catch (err) {
        setError(err instanceof Error ? err.message : "Error cargando métricas");
      } finally {
        setLoading(false);
      }
    })();
  }, [session]);

  return (
    <div>
      <PageHeader
        title="Economía de la plataforma"
        subtitle="Cifras calculadas desde suscripciones y usage_events. No hay mocks de MRR."
      />
      <ErrorInline message={error} />
      {loading && <SkeletonBlock />}
      {data && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard label="MRR" value={money(data.mrr_cents)} />
          <StatCard label="ARR" value={money(data.arr_cents)} />
          <StatCard label="Clientes" value={data.customers} hint="active + trialing" />
          <StatCard label="Agentes activos" value={data.active_agents} />
          <StatCard label="AI requests (30d)" value={data.ai_requests_30d} />
          <StatCard
            label="LLM cost (30d)"
            value={new Intl.NumberFormat("es-CL", { style: "currency", currency: "USD" }).format(
              data.llm_cost_30d
            )}
          />
          <StatCard
            label="Gross margin"
            value={data.gross_margin_pct == null ? "—" : `${data.gross_margin_pct}%`}
          />
          {evalSummary && (
            <StatCard
              label="Eval runs"
              value={evalSummary.run_count}
              hint={`${evalSummary.organizations.length} orgs · sin texto de casos`}
            />
          )}
        </div>
      )}
    </div>
  );
}
