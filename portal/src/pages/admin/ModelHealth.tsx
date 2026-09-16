import { Plus, Pulse, ShieldCheck, WarningCircle } from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";
import { platformApi } from "../../api";
import {
  Button,
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
  TabsList,
  TabsTrigger,
  Toolbar,
  type Column,
  type SortState,
} from "../../components/ui";
import { fmtCurrency, fmtNum } from "../../lib/format";
import { usePlatformAuth } from "../../platformAuth";

type Health = {
  model: string;
  requests: number;
  tokens: number;
  cost: number;
  errors: number;
  error_rate: number;
  avg_latency_ms: number;
  p95_latency_ms: number;
  circuit_state: string;
};

type Budget = {
  organization_id: string;
  model: string;
  budget_cents: number | null;
  allowed: boolean;
  throttle_factor: number;
  usage_pct: number;
  note: string | null;
};

type Guardrail = {
  id: string;
  organization_id: string;
  name: string;
  kind: string;
  config: Record<string, unknown>;
  action: string;
  enabled: boolean;
};

type Circuit = {
  model: string;
  state: string;
  failures: number;
  failure_threshold: number;
  window_seconds: number;
  cooldown_seconds: number;
  opened_until: string | null;
};

const KINDS = ["toxicity", "pii", "banned_topics", "length_limit", "custom_pattern"];
const ACTIONS = ["mask", "block", "warn"];
const WINDOWS = [
  { hours: 1, label: "1h" },
  { hours: 6, label: "6h" },
  { hours: 24, label: "24h" },
] as const;

/**
 * Los estados de circuit breaker no existen en el vocabulario de StatusBadge
 * (`components/ui/Badge.tsx`), así que se mapean a estados equivalentes.
 */
const CIRCUIT_STATUS: Record<string, { status: string; label: string }> = {
  open: { status: "failed", label: "Abierto" },
  half_open: { status: "degraded", label: "Semiabierto" },
  closed: { status: "healthy", label: "Cerrado" },
};

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

export default function AdminModelHealthPage() {
  const { session } = usePlatformAuth();
  const [health, setHealth] = useState<Health[]>([]);
  const [budgets, setBudgets] = useState<Budget[]>([]);
  const [guardrails, setGuardrails] = useState<Guardrail[]>([]);
  const [circuits, setCircuits] = useState<Circuit[]>([]);
  const [orgs, setOrgs] = useState<{ id: string }[]>([]);
  const [orgId, setOrgId] = useState("");
  const [hours, setHours] = useState(24);
  const [grForm, setGrForm] = useState({ name: "", kind: "banned_topics", action: "mask", config: "" });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [sortHealth, setSortHealth] = useState<SortState>({ key: "requests", dir: "desc" });
  const [sortBudgets, setSortBudgets] = useState<SortState>({ key: "usage_pct", dir: "desc" });
  const [sortCircuits, setSortCircuits] = useState<SortState>({ key: "model", dir: "asc" });

  async function loadAll() {
    if (!session) return;
    setError("");
    try {
      const q = orgId ? `?organization_id=${orgId}` : "";
      const [h, b, g, c] = await Promise.all([
        platformApi<{ models: Health[] }>(`/api/v1/platform/model-health/dashboard?hours=${hours}`, { token: session.token }),
        platformApi<{ budgets: Budget[] }>(`/api/v1/platform/model-health/budgets${q}`, { token: session.token }),
        platformApi<{ guardrails: Guardrail[] }>(`/api/v1/platform/model-health/guardrails${q}`, { token: session.token }),
        platformApi<{ circuits: Circuit[] }>("/api/v1/platform/model-health/circuits", { token: session.token }),
      ]);
      setHealth(h.models || []);
      setBudgets(b.budgets || []);
      setGuardrails(g.guardrails || []);
      setCircuits(c.circuits || []);
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
        if (o.organizations?.length) setOrgId(o.organizations[0].id);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Error");
      }
      await loadAll();
    })();
    const id = setInterval(() => void loadAll(), 10000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session, orgId, hours]);

  async function createGuardrail() {
    if (!session) return;
    setBusy("gr");
    setError("");
    try {
      let config: Record<string, unknown> = {};
      try {
        config = JSON.parse(grForm.config || "{}");
      } catch {
        setError("config JSON inválido");
        return;
      }
      await platformApi("/api/v1/platform/model-health/guardrails", {
        method: "POST",
        token: session.token,
        body: JSON.stringify({ organization_id: orgId, name: grForm.name, kind: grForm.kind, action: grForm.action, config }),
      });
      setGrForm({ name: "", kind: "banned_topics", action: "mask", config: "" });
      await loadAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function toggle(g: Guardrail) {
    if (!session) return;
    try {
      await platformApi(`/api/v1/platform/model-health/guardrails/${g.id}/toggle`, {
        method: "POST",
        token: session.token,
        body: JSON.stringify({ enabled: !g.enabled }),
      });
      await loadAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  async function circuit(model: string, action: "trip" | "reset") {
    if (!session) return;
    setBusy(`${action}-${model}`);
    try {
      await platformApi(`/api/v1/platform/model-health/circuits/${model}/${action}`, {
        method: "POST",
        token: session.token,
      });
      await loadAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  const openCircuits = circuits.filter((c) => c.state === "open").length;
  const blockedBudgets = budgets.filter((b) => !b.allowed).length;
  const activeGuardrails = guardrails.filter((g) => g.enabled).length;

  const healthRows = useMemo(
    () =>
      sortRows(health, sortHealth, (row, key) =>
        key === "model" ? row.model : key === "errors" ? row.errors : key === "cost" ? row.cost : key === "error_rate" ? row.error_rate : key === "p95_latency_ms" ? row.p95_latency_ms : key === "tokens" ? row.tokens : row.requests
      ),
    [health, sortHealth]
  );
  const budgetRows = useMemo(
    () =>
      sortRows(budgets, sortBudgets, (row, key) =>
        key === "model" ? row.model : key === "budget_cents" ? (row.budget_cents ?? 0) : key === "allowed" ? String(row.allowed) : row.usage_pct
      ),
    [budgets, sortBudgets]
  );
  const circuitRows = useMemo(
    () =>
      sortRows(circuits, sortCircuits, (row, key) =>
        key === "state" ? row.state : key === "failures" ? row.failures : row.model
      ),
    [circuits, sortCircuits]
  );

  const healthColumns: Column<Health>[] = [
    {
      key: "model",
      header: "Modelo",
      sortable: true,
      render: (row) => (
        <span className="flex items-center gap-2">
          <span className="mono text-xs text-text">{row.model}</span>
          <StatusBadge status={CIRCUIT_STATUS[row.circuit_state]?.status ?? row.circuit_state} label={CIRCUIT_STATUS[row.circuit_state]?.label} hideIcon />
        </span>
      ),
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
      hideBelow: "md",
      width: "110px",
      render: (row) => <span className="mono text-xs text-muted">{fmtCurrency(row.cost, 3)}</span>,
    },
    {
      key: "errors",
      header: "Errores",
      align: "right",
      sortable: true,
      width: "120px",
      render: (row) => (
        <span className={`mono text-xs ${row.errors > 0 ? "text-danger" : "text-muted"}`}>
          {fmtNum(row.errors)} · {(row.error_rate * 100).toFixed(1)}%
        </span>
      ),
    },
    {
      key: "p95_latency_ms",
      header: "p95",
      align: "right",
      sortable: true,
      hideBelow: "lg",
      width: "110px",
      render: (row) => <span className="mono text-xs text-muted">{row.p95_latency_ms.toFixed(0)}ms</span>,
    },
  ];

  const budgetColumns: Column<Budget>[] = [
    {
      key: "model",
      header: "Modelo",
      sortable: true,
      render: (row) => <span className="mono text-xs text-text">{row.model}</span>,
    },
    {
      key: "budget_cents",
      header: "Presupuesto",
      align: "right",
      sortable: true,
      width: "120px",
      render: (row) => <span className="mono text-xs text-muted">{fmtCurrency((row.budget_cents ?? 0) / 100, 2)}</span>,
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
              className={`block h-full rounded-full ${row.allowed ? (row.throttle_factor < 1 ? "bg-warn" : "bg-accent") : "bg-danger"}`}
              style={{ width: `${Math.min(100, row.usage_pct)}%` }}
            />
          </span>
          <span className="mono text-xs text-muted">{row.usage_pct}%</span>
        </span>
      ),
    },
    {
      key: "allowed",
      header: "Estado",
      align: "right",
      sortable: true,
      width: "130px",
      render: (row) =>
        row.allowed ? (
          row.throttle_factor < 1 ? (
            <StatusBadge status="degraded" label={`Throttled ×${row.throttle_factor}`} />
          ) : (
            <StatusBadge status="active" />
          )
        ) : (
          <StatusBadge status="suspended" label="Bloqueado" />
        ),
    },
    {
      key: "note",
      header: "Nota",
      hideBelow: "lg",
      render: (row) => (
        <span className="block max-w-[220px] truncate text-xs text-faint" title={row.note ?? ""}>
          {row.note ?? "—"}
        </span>
      ),
    },
  ];

  const circuitColumns: Column<Circuit>[] = [
    {
      key: "model",
      header: "Modelo",
      sortable: true,
      render: (row) => <span className="mono text-xs text-text">{row.model}</span>,
    },
    {
      key: "state",
      header: "Estado",
      sortable: true,
      width: "150px",
      render: (row) => (
        <StatusBadge
          status={CIRCUIT_STATUS[row.state]?.status ?? row.state}
          label={CIRCUIT_STATUS[row.state]?.label}
        />
      ),
    },
    {
      key: "failures",
      header: "Fallos",
      align: "right",
      sortable: true,
      width: "110px",
      render: (row) => (
        <span className={`mono text-xs ${row.failures > 0 ? "text-warn" : "text-muted"}`}>
          {row.failures}/{row.failure_threshold}
        </span>
      ),
    },
    {
      key: "window",
      header: "Ventana",
      align: "right",
      hideBelow: "md",
      width: "120px",
      render: (row) => <span className="mono text-xs text-muted">{fmtNum(row.window_seconds)}s</span>,
    },
    {
      key: "cooldown",
      header: "Cooldown",
      align: "right",
      hideBelow: "md",
      width: "110px",
      render: (row) => <span className="mono text-xs text-muted">{fmtNum(row.cooldown_seconds)}s</span>,
    },
    {
      key: "opened_until",
      header: "Abierto hasta",
      align: "right",
      hideBelow: "lg",
      width: "170px",
      render: (row) => (
        <span className="text-xs text-faint">
          {row.opened_until ? new Date(row.opened_until).toLocaleString("es-PE") : "—"}
        </span>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <PageHeader title="Model Health" subtitle="Budgets con throttling, guardrails de salida y circuit breakers por modelo." />
      <ErrorInline message={error} />
      {loading ? (
        <div className="flex flex-col gap-3" aria-hidden>
          <Skeleton className="h-[86px] rounded-lg" />
          <Skeleton className="h-[300px] rounded-lg" />
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
            <Metric
              label="Circuitos abiertos"
              value={openCircuits}
              hint={openCircuits > 0 ? "Fallback activo en el router" : "Todos los modelos responden"}
              icon={openCircuits > 0 ? WarningCircle : Pulse}
              tone={openCircuits > 0 ? "danger" : "default"}
            />
            <MetricGrid cols={3} className="lg:grid-cols-3">
              <Metric label="Modelos con tráfico" value={fmtNum(health.length)} size="md" hint={`Ventana ${hours}h`} />
              <Metric label="Budgets bloqueados" value={fmtNum(blockedBudgets)} size="md" tone={blockedBudgets > 0 ? "warn" : "default"} />
              <Metric label="Guardrails activos" value={fmtNum(activeGuardrails)} size="md" />
            </MetricGrid>
          </div>

          <Toolbar>
            <Select aria-label="Organización" className="w-48" value={orgId} onChange={(e) => setOrgId(e.target.value)}>
              {orgs.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.id.slice(0, 8)}
                </option>
              ))}
            </Select>
            <Tabs variant="pill" value={String(hours)} onValueChange={(value) => setHours(Number(value))}>
              <TabsList>
                {WINDOWS.map((w) => (
                  <TabsTrigger key={w.hours} value={String(w.hours)}>
                    {w.label}
                  </TabsTrigger>
                ))}
              </TabsList>
            </Tabs>
          </Toolbar>

          <section className="min-w-0">
            <SectionHeader
              title="Salud por modelo"
              description="Requests, errores y latencia en la ventana. El estado es el circuit breaker."
              className="mb-3"
            />
            <DataTable
              stickyHeader
              columns={healthColumns}
              rows={healthRows}
              rowKey={(row) => row.model}
              sort={sortHealth}
              onSortChange={setSortHealth}
              empty={
                <EmptyState
                  icon={Pulse}
                  title="Sin tráfico en la ventana"
                  body="No hay requests registrados para esta selección."
                  hint="Ampliá la ventana o elegí otra organización."
                />
              }
            />
          </section>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <section className="min-w-0">
              <SectionHeader
                title="Budgets por modelo (mes)"
                description="Consumo real contra el límite configurado en Model Gateway."
                className="mb-3"
              />
              <DataTable
                stickyHeader
                columns={budgetColumns}
                rows={budgetRows}
                rowKey={(row) => `${row.organization_id}:${row.model}`}
                sort={sortBudgets}
                onSortChange={setSortBudgets}
                empty={
                  <EmptyState compact icon={Pulse} title="Sin budgets configurados" body="Definí límites por modelo en Model Gateway." />
                }
              />
            </section>

            <section className="min-w-0">
              <SectionHeader
                title={
                  <span className="flex items-center gap-2">
                    <ShieldCheck size={15} aria-hidden /> Guardrails de salida
                  </span>
                }
                description="Filtros aplicados a las respuestas antes de salir."
                className="mb-3"
              />
              <Panel className="mb-4">
                <PanelHeader
                  title="Nuevo guardrail"
                  description="Se aplica a la organización seleccionada."
                />
                <div className="panel-body">
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    <Field label="Nombre">
                      <Input
                        value={grForm.name}
                        onChange={(e) => setGrForm((f) => ({ ...f, name: e.target.value }))}
                        placeholder="ej. PII en soporte"
                      />
                    </Field>
                    <Field label="Tipo">
                      <Select value={grForm.kind} onChange={(e) => setGrForm((f) => ({ ...f, kind: e.target.value }))}>
                        {KINDS.map((k) => (
                          <option key={k} value={k}>
                            {k}
                          </option>
                        ))}
                      </Select>
                    </Field>
                    <Field label="Acción">
                      <Select value={grForm.action} onChange={(e) => setGrForm((f) => ({ ...f, action: e.target.value }))}>
                        {ACTIONS.map((a) => (
                          <option key={a} value={a}>
                            {a}
                          </option>
                        ))}
                      </Select>
                    </Field>
                    <Field label="Config JSON" hint='ej. {"words":["x"]}'>
                      <Input
                        className="font-mono text-xs"
                        value={grForm.config}
                        onChange={(e) => setGrForm((f) => ({ ...f, config: e.target.value }))}
                        placeholder='{"words":["x"]}'
                      />
                    </Field>
                  </div>
                  <div className="mt-3">
                    <Button
                      variant="primary"
                      size="sm"
                      leadingIcon={Plus}
                      loading={busy === "gr"}
                      disabled={!orgId || !grForm.name.trim()}
                      onClick={() => void createGuardrail()}
                    >
                      Crear guardrail
                    </Button>
                  </div>
                </div>
              </Panel>
              {guardrails.length === 0 ? (
                <Panel>
                  <EmptyState compact icon={ShieldCheck} title="Sin guardrails" body="Creá el primero para filtrar salidas de esta organización." />
                </Panel>
              ) : (
                <ul className="panel divide-y divide-border-soft">
                  {guardrails.map((g) => (
                    <li key={g.id} className="flex items-center gap-3 px-4 py-2.5">
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-[13px] text-text" title={g.name}>
                          {g.name}
                        </p>
                        <p className="text-xs text-faint">
                          {g.kind} · {g.action}
                        </p>
                      </div>
                      <StatusBadge status={g.enabled ? "active" : "inactive"} />
                      <Button variant="ghost" size="sm" onClick={() => void toggle(g)}>
                        {g.enabled ? "Desactivar" : "Activar"}
                      </Button>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>

          <section className="min-w-0">
            <SectionHeader
              title={
                <span className="flex items-center gap-2">
                  <Pulse size={15} aria-hidden /> Circuit breakers
                </span>
              }
              description="Auto-fallback: el runtime salta al siguiente candidato del router si el modelo está abierto."
              className="mb-3"
            />
            <DataTable
              stickyHeader
              columns={circuitColumns}
              rows={circuitRows}
              rowKey={(row) => row.model}
              sort={sortCircuits}
              onSortChange={setSortCircuits}
              rowActions={(row) => (
                <>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={busy === `trip-${row.model}`}
                    onClick={() => void circuit(row.model, "trip")}
                  >
                    Trip
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={busy === `reset-${row.model}`}
                    onClick={() => void circuit(row.model, "reset")}
                  >
                    Reset
                  </Button>
                </>
              )}
              empty={
                <EmptyState compact icon={Pulse} title="Sin circuit breakers" body="Aparecen cuando el runtime registra fallos por modelo." />
              }
            />
          </section>
        </>
      )}
    </div>
  );
}
