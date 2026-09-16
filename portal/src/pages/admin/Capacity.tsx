import { ChartLineUp, Queue, Rocket, Warning } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import {
  Badge,
  Button,
  CodeBlock,
  ConfirmDialog,
  EmptyState,
  ErrorInline,
  Field,
  Input,
  Metric,
  MetricGrid,
  PageHeader,
  Panel,
  Progress,
  SectionHeader,
  Select,
  SkeletonTable,
  StatusDot,
} from "../../components/ui";
import { usePlatformAuth } from "../../platformAuth";

type CapacityOrg = {
  organization_id: string;
  plan_limits: {
    requests_per_month: number;
    tokens_per_month: number;
    monthly_cost_limit: number;
    included_storage: number;
  };
  usage: { used_requests: number; used_tokens: number; used_cost: number };
  utilization_pct: { requests: number; tokens: number; cost: number };
  soft_limit_exceeded: boolean;
  hard_limit_exceeded: boolean;
  forecast_30d: { requests: number; utilization_pct: number };
  days_until_limit: number | null;
  projected_exceed_date: string | null;
};

type QueueDepth = { queue: string; depth: number; backend: string; error?: string };

/** Regla del backend para marcar presión de capacidad: soft/forecast ≥80% o ≤15 días. */
const SOFT_LIMIT_PCT = 80;
const NEAR_DAYS = 15;
const QUEUE_DEPTH_ALERT = 50;

function utilizationTone(pct: number): "ok" | "warn" | "danger" {
  if (pct >= 100) return "danger";
  if (pct >= SOFT_LIMIT_PCT) return "warn";
  return "ok";
}

export default function AdminCapacityPage() {
  const { session } = usePlatformAuth();
  const [summary, setSummary] = useState<{ near_limit: CapacityOrg[]; queues: QueueDepth[]; scaling_events: unknown[] } | null>(null);
  const [orgs, setOrgs] = useState<{ id: string }[]>([]);
  const [simulate, setSimulate] = useState({ org: "", growth_pct: 50, days: 30 });
  const [simResult, setSimResult] = useState("");
  const [autoScale, setAutoScale] = useState(false);
  const [confirmScale, setConfirmScale] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  async function load() {
    if (!session) return;
    setError("");
    try {
      const [s, o, ac] = await Promise.all([
        platformApi<{ near_limit: CapacityOrg[]; queues: QueueDepth[]; scaling_events: unknown[] }>(
          "/api/v1/platform/capacity/summary",
          { token: session.token }
        ),
        platformApi<{ organizations: { id: string }[] }>("/api/v1/platform/organizations", {
          token: session.token,
        }),
        platformApi<{ enabled: boolean }>("/api/v1/platform/capacity/workers/auto-scale", {
          token: session.token,
        }),
      ]);
      setSummary(s);
      setOrgs(o.organizations || []);
      setAutoScale(ac.enabled);
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

  async function doSimulate() {
    if (!session) return;
    setBusy("sim");
    setError("");
    setSimResult("");
    try {
      const out = await platformApi<Record<string, unknown>>("/api/v1/platform/capacity/simulate", {
        method: "POST",
        token: session.token,
        body: JSON.stringify({ organization_id: simulate.org, growth_pct: simulate.growth_pct, days: simulate.days }),
      });
      setSimResult(JSON.stringify(out, null, 2));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function toggleAutoScale(next: boolean) {
    if (!session) return;
    setConfirmScale(false);
    try {
      const out = await platformApi<{ enabled: boolean }>("/api/v1/platform/capacity/workers/auto-scale", {
        method: "POST",
        token: session.token,
        body: JSON.stringify({ enabled: next }),
      });
      setAutoScale(out.enabled);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  const nearLimit = summary?.near_limit ?? [];
  const queues = summary?.queues ?? [];
  const knowledgeQueue = queues.find((q) => q.queue === "knowledge");
  const ingestionQueue = queues.find((q) => q.queue === "ingestion_pending");
  const worst = nearLimit.reduce<CapacityOrg | null>(
    (acc, o) => (!acc || o.utilization_pct.requests > acc.utilization_pct.requests ? o : acc),
    null
  );
  const worstTone = worst ? utilizationTone(worst.utilization_pct.requests) : "ok";

  return (
    <div className="space-y-6">
      <PageHeader
        title="Capacity Planning"
        subtitle="Uso real contra los límites de cada plan, colas de workers y simulación de crecimiento."
        actions={
          <Button
            variant="secondary"
            leadingIcon={Rocket}
            onClick={() => (autoScale ? void toggleAutoScale(false) : setConfirmScale(true))}
          >
            <StatusDot tone={autoScale ? "warn" : "neutral"} />
            Auto-scaling {autoScale ? "activo" : "inactivo"}
          </Button>
        }
      />
      <ErrorInline message={error} />
      {autoScale && (
        <p className="flex items-center gap-2 text-xs text-warn" role="status">
          <Warning size={13} aria-hidden />
          Auto-scaling activo: el orquestador ajusta workers por su cuenta.
        </p>
      )}
      {loading ? (
        <Panel className="overflow-hidden">
          <SkeletonTable rows={5} cols={4} />
        </Panel>
      ) : (
        <>
          <Panel className="p-4">
            {worst ? (
              <div className="flex flex-wrap items-start justify-between gap-x-8 gap-y-4">
                <div className="min-w-0">
                  <p className="eyebrow">Mayor uso de límite de plan</p>
                  <p className="mt-2 text-[30px] leading-none font-semibold tracking-[-0.025em] tabular-nums text-text">
                    {worst.utilization_pct.requests.toFixed(1)}%
                  </p>
                  <p className="mt-2 max-w-[68ch] text-[13px] leading-relaxed text-muted">
                    <span className="mono">{worst.organization_id.slice(0, 13)}…</span> usó{" "}
                    {worst.usage.used_requests.toLocaleString()} de{" "}
                    {worst.plan_limits.requests_per_month.toLocaleString()} requests del plan
                    {worst.days_until_limit != null ? ` · ${worst.days_until_limit} día(s) al límite` : ""}.
                  </p>
                </div>
                <div className="min-w-[220px] flex-1 sm:max-w-sm">
                  <Progress
                    value={worst.utilization_pct.requests}
                    tone={worstTone}
                    label="Uso del límite mensual de requests"
                    showValue
                  />
                </div>
              </div>
            ) : (
              <EmptyState
                icon={ChartLineUp}
                compact
                tone="accent"
                title="Sin tenants cerca del límite"
                body={`Ningún plan supera ${SOFT_LIMIT_PCT}% de uso ni proyecta alcanzar el límite en ${NEAR_DAYS} días.`}
              />
            )}
          </Panel>

          <MetricGrid cols={4}>
            <Metric
              size="md"
              label="Tenants en presión"
              value={nearLimit.length.toLocaleString()}
              tone={nearLimit.length > 0 ? "warn" : "default"}
              hint={`Umbral: ≥${SOFT_LIMIT_PCT}% o ≤${NEAR_DAYS} días`}
            />
            <Metric
              size="md"
              label="Cola knowledge"
              value={(knowledgeQueue?.depth ?? 0).toLocaleString()}
              tone={(knowledgeQueue?.depth ?? 0) >= QUEUE_DEPTH_ALERT ? "warn" : "default"}
              hint={knowledgeQueue ? `Backend ${knowledgeQueue.backend}` : "Sin lectura"}
            />
            <Metric
              size="md"
              label="Ingestión pending"
              value={(ingestionQueue?.depth ?? 0).toLocaleString()}
              tone={(ingestionQueue?.depth ?? 0) >= QUEUE_DEPTH_ALERT ? "warn" : "default"}
              hint={ingestionQueue ? `Backend ${ingestionQueue.backend}` : "Sin lectura"}
            />
            <Metric
              size="md"
              label="Eventos de escala"
              value={(summary?.scaling_events?.length ?? 0).toLocaleString()}
              hint="Registrados por el orquestador"
            />
          </MetricGrid>

          <section>
            <SectionHeader
              title="Tenants cerca del límite"
              description={`Se listan los que superan ${SOFT_LIMIT_PCT}% de uso, proyectan ese uso o están a ${NEAR_DAYS} días o menos del límite.`}
              className="mb-3"
            />
            <Panel className="overflow-x-auto">
              {nearLimit.length === 0 ? (
                <EmptyState
                  icon={ChartLineUp}
                  compact
                  title="Ningún tenant en presión"
                  body="No hay organizaciones que cumplan los criterios de alerta de capacidad."
                />
              ) : (
                <table className="table min-w-[880px]">
                  <thead>
                    <tr>
                      <th>Organización</th>
                      <th className="text-right">Requests usados</th>
                      <th className="w-44">Uso del plan</th>
                      <th>Límites</th>
                      <th className="text-right">Forecast 30d</th>
                      <th className="text-right">Días al límite</th>
                    </tr>
                  </thead>
                  <tbody>
                    {nearLimit.map((o) => {
                      const tone = utilizationTone(o.utilization_pct.requests);
                      return (
                        <tr key={o.organization_id}>
                          <td className="mono text-xs text-faint" title={o.organization_id}>
                            {o.organization_id.slice(0, 13)}…
                          </td>
                          <td className="text-right tabular-nums">
                            {o.usage.used_requests.toLocaleString()}{" "}
                            <span className="text-faint">/ {o.plan_limits.requests_per_month.toLocaleString()}</span>
                          </td>
                          <td>
                            <Progress
                              value={o.utilization_pct.requests}
                              tone={tone}
                              label={`Uso de requests de ${o.organization_id.slice(0, 8)}`}
                              showValue
                            />
                          </td>
                          <td>
                            <span className="flex flex-wrap items-center gap-1">
                              <Badge tone={o.soft_limit_exceeded ? "warn" : "neutral"} dot>
                                {o.soft_limit_exceeded ? "Soft superado" : "Soft OK"}
                              </Badge>
                              <Badge tone={o.hard_limit_exceeded ? "danger" : "neutral"} dot>
                                {o.hard_limit_exceeded ? "Hard superado" : "Hard OK"}
                              </Badge>
                            </span>
                          </td>
                          <td
                            className={`text-right tabular-nums ${
                              o.forecast_30d.utilization_pct >= SOFT_LIMIT_PCT ? "text-warn" : "text-muted"
                            }`}
                            title="Proyección calculada por el backend con el consumo actual"
                          >
                            {o.forecast_30d.utilization_pct}%
                          </td>
                          <td
                            className={`text-right tabular-nums ${
                              o.days_until_limit != null && o.days_until_limit <= NEAR_DAYS ? "text-warn" : "text-muted"
                            }`}
                          >
                            {o.days_until_limit ?? "—"}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </Panel>
            {nearLimit.some((o) => o.projected_exceed_date) && (
              <p className="mt-2 text-xs text-faint">
                Fechas proyectadas por el backend:{" "}
                {nearLimit
                  .filter((o) => o.projected_exceed_date)
                  .map((o) => `${o.organization_id.slice(0, 8)} → ${new Date(o.projected_exceed_date as string).toLocaleDateString("es-PE")}`)
                  .join(" · ")}
              </p>
            )}
          </section>

          <section>
            <SectionHeader
              title="Colas de workers"
              description={`Profundidad en vivo. Se marca en rojo desde ${QUEUE_DEPTH_ALERT} trabajos pendientes.`}
              className="mb-3"
            />
            <Panel className="overflow-x-auto">
              <table className="table">
                <thead>
                  <tr>
                    <th>Cola</th>
                    <th>Backend</th>
                    <th className="text-right">Profundidad</th>
                  </tr>
                </thead>
                <tbody>
                  {queues.map((q) => (
                    <tr key={q.queue}>
                      <td className="mono text-xs">{q.queue}</td>
                      <td className="text-xs text-muted">
                        {q.backend}
                        {q.error ? ` · ${q.error}` : ""}
                      </td>
                      <td
                        className={`text-right tabular-nums ${
                          q.depth >= QUEUE_DEPTH_ALERT ? "font-medium text-danger" : ""
                        }`}
                      >
                        {q.depth.toLocaleString()}
                      </td>
                    </tr>
                  ))}
                  {queues.length === 0 && (
                    <tr>
                      <td colSpan={3}>
                        <EmptyState
                          icon={Queue}
                          compact
                          title="Sin colas reportadas"
                          body="El orquestador no devolvió profundidades de cola en esta lectura."
                        />
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </Panel>
          </section>

          <section>
            <SectionHeader
              title="Simulación de crecimiento"
              description="Escenario calculado por el backend: no reemplaza el uso real."
              className="mb-3"
            />
            <Panel className="p-4">
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4 lg:items-end">
                <Field label="Organización">
                  <Select
                    value={simulate.org}
                    placeholder="Organización…"
                    onChange={(e) => setSimulate((f) => ({ ...f, org: e.target.value }))}
                  >
                    {orgs.map((o) => (
                      <option key={o.id} value={o.id}>
                        {o.id.slice(0, 8)}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Field label="Crecimiento %">
                  <Input
                    type="number"
                    value={simulate.growth_pct}
                    onChange={(e) => setSimulate((f) => ({ ...f, growth_pct: Number(e.target.value) }))}
                  />
                </Field>
                <Field label="Días">
                  <Input
                    type="number"
                    value={simulate.days}
                    onChange={(e) => setSimulate((f) => ({ ...f, days: Number(e.target.value) }))}
                  />
                </Field>
                <Button
                  variant="secondary"
                  loading={busy === "sim"}
                  disabled={!simulate.org}
                  onClick={() => void doSimulate()}
                >
                  Simular
                </Button>
              </div>
              {simResult ? (
                <CodeBlock className="mt-4" code={simResult} language="json" filename="Resultado de la simulación" maxHeight={320} />
              ) : (
                <p className="mt-3 text-xs text-faint">
                  Elegí una organización y corré la simulación para ver el escenario que devuelve el backend.
                </p>
              )}
            </Panel>
          </section>
        </>
      )}

      <ConfirmDialog
        open={confirmScale}
        onOpenChange={setConfirmScale}
        title="Activar auto-scaling"
        body="El orquestador podrá crear y liberar workers según la carga real. Revisá las colas y los límites antes de activarlo."
        confirmLabel="Activar"
        tone="primary"
        onConfirm={() => void toggleAutoScale(true)}
      />
    </div>
  );
}
