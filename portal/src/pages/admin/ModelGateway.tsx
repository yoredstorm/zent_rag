import { ArrowsLeftRight, Coins, Plus } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import {
  EmptyState,
  ErrorInline,
  PageHeader,
  SkeletonBlock,
} from "../../components/ui";
import { usePlatformAuth } from "../../platformAuth";

type Route = {
  id: string;
  organization_id: string;
  name: string;
  condition_type: string;
  condition_value: number | null;
  model: string;
  traffic_pct: number;
  priority: number;
  active: boolean;
};

type Budget = {
  id: string;
  organization_id: string;
  model: string;
  monthly_budget_cents: number;
  spent_cents: number;
  blocked: boolean;
  usage_pct: number;
};

type ModelStat = {
  model: string;
  requests: number;
  error_rate_pct: number;
  p50_ms: number;
  p95_ms: number;
  tokens: number;
  cost: number;
  fallbacks: number;
};

export default function AdminModelGatewayPage() {
  const { session } = usePlatformAuth();
  const [routes, setRoutes] = useState<Route[]>([]);
  const [budgets, setBudgets] = useState<Budget[]>([]);
  const [analytics, setAnalytics] = useState<ModelStat[]>([]);
  const [orgs, setOrgs] = useState<{ id: string }[]>([]);
  const [showRoute, setShowRoute] = useState(false);
  const [routeForm, setRouteForm] = useState({
    organization_id: "",
    name: "",
    model: "zent-cheap",
    traffic_pct: 50,
    condition_type: "default",
  });
  const [budgetForm, setBudgetForm] = useState({ organization_id: "", model: "", cents: 1000 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load() {
    if (!session) return;
    setError("");
    try {
      const [r, b, a, o] = await Promise.all([
        platformApi<{ routes: Route[] }>("/api/v1/platform/model-gateway/routes", { token: session.token }),
        platformApi<{ budgets: Budget[] }>("/api/v1/platform/model-gateway/budgets", { token: session.token }),
        platformApi<{ models: ModelStat[] }>("/api/v1/platform/model-gateway/analytics", { token: session.token }),
        platformApi<{ organizations: { id: string }[] }>("/api/v1/platform/organizations", { token: session.token }),
      ]);
      setRoutes(r.routes || []);
      setBudgets(b.budgets || []);
      setAnalytics(a.models || []);
      setOrgs(o.organizations || []);
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

  async function createRoute() {
    if (!session) return;
    setError("");
    try {
      await platformApi("/api/v1/platform/model-gateway/routes", {
        method: "POST",
        token: session.token,
        body: JSON.stringify({ ...routeForm, priority: 0 }),
      });
      setShowRoute(false);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  async function toggleRoute(route: Route) {
    if (!session) return;
    try {
      await platformApi(`/api/v1/platform/model-gateway/routes/${route.id}`, {
        method: "PUT",
        token: session.token,
        body: JSON.stringify({ ...route, active: !route.active }),
      });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  async function createBudget() {
    if (!session) return;
    setError("");
    try {
      await platformApi("/api/v1/platform/model-gateway/budgets", {
        method: "POST",
        token: session.token,
        body: JSON.stringify({
          organization_id: budgetForm.organization_id,
          model: budgetForm.model,
          monthly_budget_cents: Number(budgetForm.cents),
        }),
      });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Model Gateway"
        subtitle="Routing por condiciones, A/B por tráfico, presupuestos por modelo y analytics."
      />
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading ? (
        <SkeletonBlock className="h-40" />
      ) : (
        <>
          <section>
            <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text">
              <ArrowsLeftRight size={15} aria-hidden /> Rutas (usar alias zent-routed en el agente)
            </h3>
            <div className="panel">
              <div className="flex justify-end p-2">
                <button type="button" className="btn btn-primary min-h-9 text-xs" onClick={() => setShowRoute((s) => !s)}>
                  <Plus size={13} aria-hidden /> Nueva ruta
                </button>
              </div>
              {showRoute && (
                <div className="grid grid-cols-2 gap-2 p-3 lg:grid-cols-5">
                  <select
                    className="rounded-md border border-border bg-soft px-2 py-2 text-sm"
                    value={routeForm.organization_id}
                    onChange={(e) => setRouteForm((f) => ({ ...f, organization_id: e.target.value }))}
                  >
                    <option value="">Org…</option>
                    {orgs.map((o) => (
                      <option key={o.id} value={o.id}>{o.id.slice(0, 8)}</option>
                    ))}
                  </select>
                  <input
                    className="rounded-md border border-border bg-soft px-2 py-2 text-sm"
                    placeholder="Nombre"
                    value={routeForm.name}
                    onChange={(e) => setRouteForm((f) => ({ ...f, name: e.target.value }))}
                  />
                  <input
                    className="rounded-md border border-border bg-soft px-2 py-2 text-sm"
                    placeholder="modelo (o alias)"
                    value={routeForm.model}
                    onChange={(e) => setRouteForm((f) => ({ ...f, model: e.target.value }))}
                  />
                  <input
                    type="number"
                    className="rounded-md border border-border bg-soft px-2 py-2 text-sm"
                    placeholder="traffic %"
                    value={routeForm.traffic_pct}
                    onChange={(e) => setRouteForm((f) => ({ ...f, traffic_pct: Number(e.target.value) }))}
                  />
                  <button type="button" className="btn btn-secondary min-h-9 text-xs" onClick={() => void createRoute()}>
                    Crear
                  </button>
                </div>
              )}
              {routes.length === 0 ? (
                <EmptyState icon={ArrowsLeftRight} title="Sin rutas" body="Crea rutas para A/B entre modelos por tenant." />
              ) : (
                <table className="table">
                  <thead>
                    <tr>
                      <th>Org</th>
                      <th>Nombre</th>
                      <th>Condición</th>
                      <th>Modelo</th>
                      <th>Traffic</th>
                      <th>Estado</th>
                      <th className="text-right">Toggle</th>
                    </tr>
                  </thead>
                  <tbody>
                    {routes.map((r) => (
                      <tr key={r.id}>
                        <td className="mono text-xs text-faint">{r.organization_id.slice(0, 8)}</td>
                        <td className="text-sm text-text">{r.name}</td>
                        <td className="text-xs">
                          {r.condition_type}
                          {r.condition_value != null ? ` > ${r.condition_value}` : ""}
                        </td>
                        <td className="mono text-xs">{r.model}</td>
                        <td className="text-xs">{r.traffic_pct}%</td>
                        <td>
                          <span className={`badge ${r.active ? "badge-ok" : "badge-muted"}`}>
                            {r.active ? "activa" : "inactiva"}
                          </span>
                        </td>
                        <td className="text-right">
                          <button type="button" className="btn btn-ghost min-h-8 px-2 py-1 text-xs" onClick={() => void toggleRoute(r)}>
                            {r.active ? "Desactivar" : "Activar"}
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </section>

          <section>
            <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text">
              <Coins size={15} aria-hidden /> Presupuestos por modelo
            </h3>
            <div className="panel">
              <div className="grid grid-cols-2 gap-2 p-3 lg:grid-cols-4">
                <select
                  className="rounded-md border border-border bg-soft px-2 py-2 text-sm"
                  value={budgetForm.organization_id}
                  onChange={(e) => setBudgetForm((f) => ({ ...f, organization_id: e.target.value }))}
                >
                  <option value="">Org…</option>
                  {orgs.map((o) => (
                    <option key={o.id} value={o.id}>{o.id.slice(0, 8)}</option>
                  ))}
                </select>
                <input
                  className="rounded-md border border-border bg-soft px-2 py-2 text-sm"
                  placeholder="modelo"
                  value={budgetForm.model}
                  onChange={(e) => setBudgetForm((f) => ({ ...f, model: e.target.value }))}
                />
                <input
                  type="number"
                  className="rounded-md border border-border bg-soft px-2 py-2 text-sm"
                  placeholder="USD/mes"
                  value={budgetForm.cents}
                  onChange={(e) => setBudgetForm((f) => ({ ...f, cents: Number(e.target.value) }))}
                />
                <button type="button" className="btn btn-secondary min-h-9 text-xs" onClick={() => void createBudget()}>
                  Fijar presupuesto
                </button>
              </div>
              {budgets.length === 0 ? (
                <EmptyState icon={Coins} title="Sin presupuestos" body="Al alcanzar el límite, el modelo se excluye del router." />
              ) : (
                <table className="table">
                  <thead>
                    <tr>
                      <th>Org</th>
                      <th>Modelo</th>
                      <th>Presupuesto</th>
                      <th>Gastado</th>
                      <th>Uso</th>
                      <th>Estado</th>
                    </tr>
                  </thead>
                  <tbody>
                    {budgets.map((b) => (
                      <tr key={b.id}>
                        <td className="mono text-xs text-faint">{b.organization_id.slice(0, 8)}</td>
                        <td className="mono text-xs">{b.model}</td>
                        <td className="text-xs">${(b.monthly_budget_cents / 100).toFixed(2)}</td>
                        <td className="text-xs">${(b.spent_cents / 100).toFixed(2)}</td>
                        <td className="text-xs">{b.usage_pct}%</td>
                        <td>
                          <span className={`badge ${b.blocked ? "badge-danger" : "badge-ok"}`}>
                            {b.blocked ? "bloqueado" : "activo"}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </section>

          <section>
            <h3 className="mb-2 text-sm font-semibold text-text">Analytics por modelo (30d)</h3>
            <div className="panel overflow-x-auto">
              {analytics.length === 0 ? (
                <EmptyState icon={ArrowsLeftRight} title="Sin uso" body="Ejecuta consultas para ver métricas por modelo." />
              ) : (
                <table className="table">
                  <thead>
                    <tr>
                      <th>Modelo</th>
                      <th>Requests</th>
                      <th>Error %</th>
                      <th>p50</th>
                      <th>p95</th>
                      <th>Tokens</th>
                      <th>Costo</th>
                      <th>Fallbacks</th>
                    </tr>
                  </thead>
                  <tbody>
                    {analytics.map((m) => (
                      <tr key={m.model}>
                        <td className="mono text-xs">{m.model}</td>
                        <td className="text-xs">{m.requests}</td>
                        <td className="text-xs">{m.error_rate_pct}%</td>
                        <td className="text-xs">{m.p50_ms.toFixed(0)}ms</td>
                        <td className="text-xs">{m.p95_ms.toFixed(0)}ms</td>
                        <td className="text-xs">{m.tokens.toLocaleString()}</td>
                        <td className="text-xs">${m.cost.toFixed(2)}</td>
                        <td className="text-xs">{m.fallbacks}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </section>
        </>
      )}
    </div>
  );
}