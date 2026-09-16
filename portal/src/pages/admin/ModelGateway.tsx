import { ArrowsLeftRight, Coins, Plus, Scales } from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";
import { platformApi } from "../../api";
import {
  Badge,
  Button,
  ButtonLink,
  DataTable,
  EmptyState,
  ErrorInline,
  Field,
  Input,
  Metric,
  MetricGrid,
  PageHeader,
  Panel,
  PanelHeader,
  SectionHeader,
  Select,
  Skeleton,
  StatusBadge,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  type Column,
  type SortState,
} from "../../components/ui";
import { fmtCurrency, fmtNum } from "../../lib/format";
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

type QualityRow = { model: string; requests: number; cost: number; cost_per_request: number; quality: number | null; last_eval_at: string | null };

function sortRows<T>(rows: T[], sort: SortState, get: (row: T, key: string) => string | number) {
  if (!sort) return rows;
  return [...rows].sort((a, b) => {
    const left = get(a, sort.key);
    const right = get(b, sort.key);
    if (typeof left === "string" && typeof right === "string") {
      return sort.dir === "asc" ? left.localeCompare(right) : right.localeCompare(left);
    }
    return sort.dir === "asc" ? Number(left) - Number(right) : Number(right) - Number(left);
  });
}

export default function AdminModelGatewayPage() {
  const { session } = usePlatformAuth();
  const [tab, setTab] = useState<"routing" | "budgets" | "performance" | "quality">("routing");
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
  const [sortRoutes, setSortRoutes] = useState<SortState>({ key: "name", dir: "asc" });
  const [sortBudgets, setSortBudgets] = useState<SortState>({ key: "usage_pct", dir: "desc" });
  const [sortModels, setSortModels] = useState<SortState>({ key: "requests", dir: "desc" });

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

  const routeRows = useMemo(
    () =>
      sortRows(routes, sortRoutes, (row, key) =>
        key === "organization_id"
          ? row.organization_id
          : key === "condition_type"
            ? row.condition_type
            : key === "model"
              ? row.model
              : key === "traffic_pct"
                ? row.traffic_pct
                : key === "active"
                  ? String(row.active)
                  : row.name
      ),
    [routes, sortRoutes]
  );
  const budgetRows = useMemo(
    () =>
      sortRows(budgets, sortBudgets, (row, key) =>
        key === "organization_id"
          ? row.organization_id
          : key === "model"
            ? row.model
            : key === "monthly_budget_cents"
              ? row.monthly_budget_cents
              : key === "spent_cents"
                ? row.spent_cents
                : key === "blocked"
                  ? String(row.blocked)
                  : row.usage_pct
      ),
    [budgets, sortBudgets]
  );
  const modelRows = useMemo(
    () =>
      sortRows(analytics, sortModels, (row, key) =>
        key === "model"
          ? row.model
          : key === "error_rate_pct"
            ? row.error_rate_pct
            : key === "p95_ms"
              ? row.p95_ms
              : key === "tokens"
                ? row.tokens
                : key === "cost"
                  ? row.cost
                  : key === "fallbacks"
                    ? row.fallbacks
                    : row.requests
      ),
    [analytics, sortModels]
  );

  const totals = analytics.reduce(
    (acc, m) => {
      acc.requests += m.requests;
      acc.cost += m.cost;
      acc.fallbacks += m.fallbacks;
      acc.weightedErrors += m.requests * m.error_rate_pct;
      return acc;
    },
    { requests: 0, cost: 0, fallbacks: 0, weightedErrors: 0 }
  );
  const weightedErrorRate = totals.requests > 0 ? totals.weightedErrors / totals.requests : 0;

  const routeColumns: Column<Route>[] = [
    {
      key: "organization_id",
      header: "Org",
      sortable: true,
      width: "110px",
      render: (row) => <span className="mono text-xs text-faint">{row.organization_id.slice(0, 8)}</span>,
    },
    {
      key: "name",
      header: "Nombre",
      sortable: true,
      render: (row) => <span className="text-[13px] text-text">{row.name}</span>,
    },
    {
      key: "condition_type",
      header: "Condición",
      sortable: true,
      hideBelow: "md",
      render: (row) => (
        <span className="text-xs text-muted">
          {row.condition_type}
          {row.condition_value != null ? ` > ${row.condition_value}` : ""}
        </span>
      ),
    },
    {
      key: "model",
      header: "Modelo",
      sortable: true,
      render: (row) => <span className="mono text-xs text-text">{row.model}</span>,
    },
    {
      key: "traffic_pct",
      header: "Traffic",
      align: "right",
      sortable: true,
      width: "100px",
      render: (row) => <span className="mono text-xs text-muted">{row.traffic_pct}%</span>,
    },
    {
      key: "active",
      header: "Estado",
      sortable: true,
      width: "120px",
      render: (row) => <StatusBadge status={row.active ? "active" : "inactive"} />,
    },
  ];

  const budgetColumns: Column<Budget>[] = [
    {
      key: "organization_id",
      header: "Org",
      sortable: true,
      width: "110px",
      render: (row) => <span className="mono text-xs text-faint">{row.organization_id.slice(0, 8)}</span>,
    },
    {
      key: "model",
      header: "Modelo",
      sortable: true,
      render: (row) => <span className="mono text-xs text-text">{row.model}</span>,
    },
    {
      key: "monthly_budget_cents",
      header: "Presupuesto",
      align: "right",
      sortable: true,
      width: "130px",
      render: (row) => <span className="mono text-xs text-muted">{fmtCurrency(row.monthly_budget_cents / 100)}</span>,
    },
    {
      key: "spent_cents",
      header: "Gastado",
      align: "right",
      sortable: true,
      width: "120px",
      render: (row) => <span className="mono text-xs text-muted">{fmtCurrency(row.spent_cents / 100)}</span>,
    },
    {
      key: "usage_pct",
      header: "Uso",
      align: "right",
      sortable: true,
      width: "160px",
      render: (row) => (
        <span className="flex items-center justify-end gap-2">
          <span className="h-1.5 w-16 shrink-0 overflow-hidden rounded-full bg-track" aria-hidden>
            <span
              className={`block h-full rounded-full ${row.blocked ? "bg-danger" : "bg-accent"}`}
              style={{ width: `${Math.min(100, row.usage_pct)}%` }}
            />
          </span>
          <span className="mono text-xs text-muted">{row.usage_pct}%</span>
        </span>
      ),
    },
    {
      key: "blocked",
      header: "Estado",
      sortable: true,
      width: "130px",
      render: (row) => <StatusBadge status={row.blocked ? "suspended" : "active"} label={row.blocked ? "Bloqueado" : "Activo"} />,
    },
  ];

  const modelColumns: Column<ModelStat>[] = [
    {
      key: "model",
      header: "Modelo",
      sortable: true,
      render: (row) => <span className="mono text-xs text-text">{row.model}</span>,
    },
    {
      key: "requests",
      header: "Requests",
      align: "right",
      sortable: true,
      width: "110px",
      render: (row) => <span className="mono text-xs text-muted">{fmtNum(row.requests)}</span>,
    },
    {
      key: "error_rate_pct",
      header: "Error %",
      align: "right",
      sortable: true,
      width: "110px",
      render: (row) => (
        <span className={`mono text-xs ${row.error_rate_pct > 0 ? "text-warn" : "text-muted"}`}>{row.error_rate_pct}%</span>
      ),
    },
    {
      key: "p50_ms",
      header: "p50",
      align: "right",
      hideBelow: "md",
      width: "100px",
      render: (row) => <span className="mono text-xs text-muted">{row.p50_ms.toFixed(0)}ms</span>,
    },
    {
      key: "p95_ms",
      header: "p95",
      align: "right",
      sortable: true,
      width: "100px",
      render: (row) => <span className="mono text-xs text-muted">{row.p95_ms.toFixed(0)}ms</span>,
    },
    {
      key: "tokens",
      header: "Tokens",
      align: "right",
      sortable: true,
      hideBelow: "md",
      width: "120px",
      render: (row) => <span className="mono text-xs text-muted">{fmtNum(row.tokens)}</span>,
    },
    {
      key: "cost",
      header: "Costo",
      align: "right",
      sortable: true,
      width: "110px",
      render: (row) => <span className="mono text-xs text-muted">{fmtCurrency(row.cost)}</span>,
    },
    {
      key: "fallbacks",
      header: "Fallbacks",
      align: "right",
      sortable: true,
      hideBelow: "lg",
      width: "110px",
      render: (row) => (
        <span className={`mono text-xs ${row.fallbacks > 0 ? "text-warn" : "text-muted"}`}>{fmtNum(row.fallbacks)}</span>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Model Gateway"
        subtitle="Routing por condiciones, A/B por tráfico, presupuestos por modelo y analytics."
        actions={
          <>
            <ButtonLink to="/control-center/inference-proxy" variant="secondary">
              Models (Inference)
            </ButtonLink>
            <ButtonLink to="/control-center/model-health" variant="secondary">
              Policies (Guardrails)
            </ButtonLink>
          </>
        }
      />
      <ErrorInline message={error} />
      {loading ? (
        <div className="flex flex-col gap-3" aria-hidden>
          <Skeleton className="h-10 w-96 rounded-lg" />
          <Skeleton className="h-[320px] rounded-lg" />
        </div>
      ) : (
        <Tabs value={tab} onValueChange={(value) => setTab(value as typeof tab)}>
          <TabsList>
            <TabsTrigger value="routing">Routing</TabsTrigger>
            <TabsTrigger value="budgets">Budgets</TabsTrigger>
            <TabsTrigger value="performance">Performance</TabsTrigger>
            <TabsTrigger value="quality">Costo vs Calidad</TabsTrigger>
          </TabsList>

          <TabsContent value="routing">
            <section className="min-w-0">
              <SectionHeader
                title={
                  <span className="flex items-center gap-2">
                    <ArrowsLeftRight size={15} aria-hidden /> Rutas
                  </span>
                }
                description="Usá el alias zent-routed en el agente para que apliquen estas condiciones."
                actions={
                  <Button variant="primary" size="sm" leadingIcon={Plus} onClick={() => setShowRoute((s) => !s)}>
                    Nueva ruta
                  </Button>
                }
                className="mb-3"
              />
              {showRoute && (
                <Panel className="mb-4">
                  <PanelHeader title="Nueva ruta" description="Condición de enrutamiento y porcentaje de tráfico." />
                  <div className="panel-body">
                    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
                      <Field label="Organización">
                        <Select
                          value={routeForm.organization_id}
                          onChange={(e) => setRouteForm((f) => ({ ...f, organization_id: e.target.value }))}
                          placeholder="Seleccionar…"
                        >
                          {orgs.map((o) => (
                            <option key={o.id} value={o.id}>
                              {o.id.slice(0, 8)}
                            </option>
                          ))}
                        </Select>
                      </Field>
                      <Field label="Nombre">
                        <Input
                          value={routeForm.name}
                          onChange={(e) => setRouteForm((f) => ({ ...f, name: e.target.value }))}
                          placeholder="ej. cheap-first"
                        />
                      </Field>
                      <Field label="Modelo o alias">
                        <Input
                          value={routeForm.model}
                          onChange={(e) => setRouteForm((f) => ({ ...f, model: e.target.value }))}
                          placeholder="zent-cheap"
                        />
                      </Field>
                      <Field label="Tráfico (%)">
                        <Input
                          type="number"
                          min={0}
                          max={100}
                          value={routeForm.traffic_pct}
                          onChange={(e) => setRouteForm((f) => ({ ...f, traffic_pct: Number(e.target.value) }))}
                        />
                      </Field>
                    </div>
                    <div className="mt-3 flex items-center gap-2">
                      <Button
                        variant="primary"
                        size="sm"
                        disabled={!routeForm.organization_id || !routeForm.name.trim()}
                        onClick={() => void createRoute()}
                      >
                        Crear
                      </Button>
                      <Button variant="ghost" size="sm" onClick={() => setShowRoute(false)}>
                        Cancelar
                      </Button>
                    </div>
                  </div>
                </Panel>
              )}
              <DataTable
                stickyHeader
                columns={routeColumns}
                rows={routeRows}
                rowKey={(row) => row.id}
                sort={sortRoutes}
                onSortChange={setSortRoutes}
                rowActions={(row) => (
                  <Button variant="ghost" size="sm" onClick={() => void toggleRoute(row)}>
                    {row.active ? "Desactivar" : "Activar"}
                  </Button>
                )}
                empty={
                  <EmptyState
                    icon={ArrowsLeftRight}
                    title="Sin rutas"
                    body="Creá rutas para A/B entre modelos por tenant."
                    hint="Sin rutas, el gateway usa el modelo por defecto del agente."
                  />
                }
              />
            </section>
          </TabsContent>

          <TabsContent value="budgets">
            <section className="min-w-0">
              <SectionHeader
                title={
                  <span className="flex items-center gap-2">
                    <Coins size={15} aria-hidden /> Presupuestos por modelo
                  </span>
                }
                description="Al alcanzar el límite, el modelo se excluye del router."
                className="mb-3"
              />
              <Panel className="mb-4">
                <PanelHeader title="Fijar presupuesto" description="Mensual por organización y modelo." />
                <div className="panel-body">
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
                    <Field label="Organización">
                      <Select
                        value={budgetForm.organization_id}
                        onChange={(e) => setBudgetForm((f) => ({ ...f, organization_id: e.target.value }))}
                        placeholder="Seleccionar…"
                      >
                        {orgs.map((o) => (
                          <option key={o.id} value={o.id}>
                            {o.id.slice(0, 8)}
                          </option>
                        ))}
                      </Select>
                    </Field>
                    <Field label="Modelo">
                      <Input
                        value={budgetForm.model}
                        onChange={(e) => setBudgetForm((f) => ({ ...f, model: e.target.value }))}
                        placeholder="zent-cheap"
                      />
                    </Field>
                    <Field label="Presupuesto (centavos USD)">
                      <Input
                        type="number"
                        min={0}
                        value={budgetForm.cents}
                        onChange={(e) => setBudgetForm((f) => ({ ...f, cents: Number(e.target.value) }))}
                      />
                    </Field>
                    <div className="flex items-end">
                      <Button
                        variant="primary"
                        size="sm"
                        disabled={!budgetForm.organization_id || !budgetForm.model.trim()}
                        onClick={() => void createBudget()}
                      >
                        Fijar presupuesto
                      </Button>
                    </div>
                  </div>
                </div>
              </Panel>
              <DataTable
                stickyHeader
                columns={budgetColumns}
                rows={budgetRows}
                rowKey={(row) => row.id}
                sort={sortBudgets}
                onSortChange={setSortBudgets}
                empty={
                  <EmptyState
                    icon={Coins}
                    title="Sin presupuestos"
                    body="Al alcanzar el límite, el modelo se excluye del router."
                  />
                }
              />
            </section>
          </TabsContent>

          <TabsContent value="performance">
            <section className="min-w-0">
              <SectionHeader
                title="Analytics por modelo (30d)"
                description="Agregados reales del periodo. La tasa de error se pondera por requests."
                className="mb-3"
              />
              <MetricGrid cols={4} className="mb-4">
                <Metric label="Requests" value={fmtNum(totals.requests)} size="md" hint="Suma de modelos" />
                <Metric label="Costo" value={fmtCurrency(totals.cost)} size="md" hint="Suma de modelos" />
                <Metric
                  label="Error rate"
                  value={`${weightedErrorRate.toFixed(2)}%`}
                  size="md"
                  tone={weightedErrorRate > 0 ? "warn" : "default"}
                  hint="Ponderado por requests"
                />
                <Metric
                  label="Fallbacks"
                  value={fmtNum(totals.fallbacks)}
                  size="md"
                  tone={totals.fallbacks > 0 ? "warn" : "default"}
                />
              </MetricGrid>
              <DataTable
                stickyHeader
                columns={modelColumns}
                rows={modelRows}
                rowKey={(row) => row.model}
                sort={sortModels}
                onSortChange={setSortModels}
                empty={
                  <EmptyState icon={ArrowsLeftRight} title="Sin uso" body="Ejecutá consultas para ver métricas por modelo." />
                }
              />
            </section>
          </TabsContent>

          <TabsContent value="quality">{session && <QualityCostPanel session={session} />}</TabsContent>
        </Tabs>
      )}
    </div>
  );
}

/** FASE 03 (S10): costo vs calidad por modelo — solo datos reales. */
function QualityCostPanel({ session }: { session: NonNullable<ReturnType<typeof usePlatformAuth>["session"]> }) {
  const [rows, setRows] = useState<QualityRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [sort, setSort] = useState<SortState>({ key: "cost", dir: "desc" });

  useEffect(() => {
    if (!session) return;
    platformApi<{ models: QualityRow[]; note: string }>("/api/v1/platform/finops/quality-cost", { token: session.token })
      .then((d) => setRows(d.models || []))
      .catch((e) => setError(e instanceof Error ? e.message : "Error"))
      .finally(() => setLoading(false));
  }, [session]);

  const sorted = useMemo(
    () =>
      sortRows(rows, sort, (row, key) => {
        if (key === "model") return row.model;
        if (key === "requests") return row.requests;
        if (key === "cost_per_request") return row.cost_per_request;
        if (key === "quality") return row.quality ?? -1;
        if (key === "last_eval_at") return row.last_eval_at ?? "";
        return row.cost;
      }),
    [rows, sort]
  );

  const columns: Column<QualityRow>[] = [
    {
      key: "model",
      header: "Modelo / target",
      sortable: true,
      render: (row) => <span className="mono text-xs text-text">{row.model}</span>,
    },
    {
      key: "requests",
      header: "Requests",
      align: "right",
      sortable: true,
      width: "110px",
      render: (row) => <span className="mono text-xs text-muted">{fmtNum(row.requests)}</span>,
    },
    {
      key: "cost",
      header: "Costo total",
      align: "right",
      sortable: true,
      width: "120px",
      render: (row) => <span className="mono text-xs text-muted">{fmtCurrency(row.cost)}</span>,
    },
    {
      key: "cost_per_request",
      header: "Costo / request",
      align: "right",
      sortable: true,
      hideBelow: "md",
      width: "150px",
      render: (row) => <span className="mono text-xs text-muted">{fmtCurrency(row.cost_per_request, 5)}</span>,
    },
    {
      key: "quality",
      header: "Calidad (composite)",
      align: "right",
      sortable: true,
      width: "170px",
      render: (row) =>
        row.quality != null ? (
          <Badge tone={row.quality >= 0.8 ? "ok" : row.quality >= 0.6 ? "warn" : "danger"}>
            {(row.quality * 100).toFixed(1)}%
          </Badge>
        ) : (
          <span className="text-xs text-faint">sin eval</span>
        ),
    },
    {
      key: "last_eval_at",
      header: "Última eval",
      align: "right",
      sortable: true,
      hideBelow: "lg",
      width: "170px",
      render: (row) => (
        <span className="text-xs text-faint">{row.last_eval_at ? row.last_eval_at.slice(0, 16) : "—"}</span>
      ),
    },
  ];

  return (
    <section className="min-w-0">
      <SectionHeader
        title={
          <span className="flex items-center gap-2">
            <Scales size={15} aria-hidden /> Costo vs calidad
          </span>
        }
        description="Solo datos reales. Los cambios de modelo requieren aprobación humana — aquí no se recomienda automáticamente nada."
        className="mb-3"
      />
      <ErrorInline message={error} />
      {loading ? (
        <Skeleton className="h-[240px] rounded-lg" />
      ) : (
        <DataTable
          stickyHeader
          columns={columns}
          rows={sorted}
          rowKey={(row) => row.model}
          sort={sort}
          onSortChange={setSort}
          empty={
            <EmptyState
              icon={Scales}
              title="Sin datos de costo/calidad"
              body="Cuando haya runs evaluados con costo asociado vas a ver el cruce acá."
            />
          }
        />
      )}
    </section>
  );
}
