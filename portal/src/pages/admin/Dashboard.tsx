import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import { AttentionList } from "../../components/AttentionList";
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

type Incident = { id: string; status: string; title: string; severity: string };
type ObsAlert = { id: string; status: string; severity: string; message: string };
type Circuit = { model: string; state: string };
type FinOpsAlert = { id: string; acknowledged: boolean; message: string; alert_type: string };
type CapacityOrg = { organization_id: string; soft_limit_exceeded: boolean; hard_limit_exceeded: boolean };

type Issue = { id: string; label: string; to: string };

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
  const [issues, setIssues] = useState<Issue[]>([]);
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
        const [inc, obs, circ, fin, cap] = await Promise.all([
          platformApi<{ incidents: Incident[] }>("/api/v1/platform/ops/incidents", { token: session.token }).catch(() => ({ incidents: [] })),
          platformApi<{ alerts: ObsAlert[] }>("/api/v1/platform/obs/alerts", { token: session.token }).catch(() => ({ alerts: [] })),
          platformApi<{ circuits: Circuit[] }>("/api/v1/platform/model-health/circuits", { token: session.token }).catch(() => ({ circuits: [] })),
          platformApi<{ alerts: FinOpsAlert[] }>("/api/v1/platform/finops/alerts", { token: session.token }).catch(() => ({ alerts: [] })),
          platformApi<{ near_limit: CapacityOrg[] }>("/api/v1/platform/capacity/summary", { token: session.token }).catch(() => ({ near_limit: [] })),
        ]);
        const next: Issue[] = [];
        const openIncidents = (inc.incidents || []).filter((i) => i.status === "open" || i.status === "acknowledged");
        if (openIncidents.length > 0) {
          next.push({ id: "incidents", label: `${openIncidents.length} incidente(s) sin resolver.`, to: "/control-center/ops-center" });
        }
        const openAlerts = (obs.alerts || []).filter((a) => a.status === "open");
        if (openAlerts.length > 0) {
          next.push({ id: "obs", label: `${openAlerts.length} alerta(s) de observabilidad abiertas.`, to: "/control-center/status" });
        }
        const openCircuits = (circ.circuits || []).filter((c) => c.state === "open");
        if (openCircuits.length > 0) {
          next.push({ id: "circuits", label: `${openCircuits.length} circuito(s) abierto(s): ${openCircuits.map((c) => c.model).join(", ")}.`, to: "/control-center/model-health" });
        }
        const pendingFinops = (fin.alerts || []).filter((a) => !a.acknowledged);
        if (pendingFinops.length > 0) {
          next.push({ id: "finops", label: `${pendingFinops.length} alerta(s) FinOps pendiente(s).`, to: "/control-center/costs" });
        }
        const nearLimit = (cap.near_limit || []).filter((o) => o.soft_limit_exceeded || o.hard_limit_exceeded);
        if (nearLimit.length > 0) {
          next.push({ id: "capacity", label: `${nearLimit.length} tenant(s) cerca o sobre el límite.`, to: "/control-center/capacity" });
        }
        setIssues(next.slice(0, 6));
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
        <>
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

          <AttentionList
            items={issues}
            emptyBody="Sin incidentes abiertos, alertas pendientes ni circuitos abiertos."
          />
        </>
      )}
    </div>
  );
}
