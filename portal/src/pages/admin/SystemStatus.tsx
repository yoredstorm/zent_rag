import { Broadcast, Pulse, WarningCircle } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import {
  Badge,
  Button,
  ConfirmDialog,
  EmptyState,
  ErrorInline,
  Field,
  Metric,
  MetricGrid,
  PageHeader,
  Panel,
  Progress,
  SectionHeader,
  Select,
  SkeletonTable,
  StatusBadge,
  SuccessInline,
  statusLabel,
  type Tone,
} from "../../components/ui";
import { usePlatformAuth } from "../../platformAuth";

type Check = { name: string; status: string; latency_ms: number; detail: string };
type SystemHealth = { status: string; checked_at: string; total_ms: number; checks: Check[] };

type SloWindow = {
  window: string;
  requests: number;
  errors: number;
  error_rate_pct: number;
  availability_pct: number;
  p50_ms: number;
  p95_ms: number;
  status: string;
};
type DeploymentSlo = {
  deployment_id: string;
  slug: string;
  status: string;
  agent_name: string;
  windows: SloWindow[];
};

type IncidentAlert = {
  id: string;
  organization_id: string;
  deployment_id: string | null;
  alert_type: string;
  severity: string;
  message: string;
  status: string;
  webhook_status: string | null;
  created_at: string;
};

const SEVERITY_META: Record<string, { tone: Tone; label: string }> = {
  critical: { tone: "danger", label: "Crítico" },
  high: { tone: "danger", label: "Alto" },
  warning: { tone: "warn", label: "Aviso" },
  info: { tone: "neutral", label: "Informativo" },
};

/** El healthcheck responde ok/down además del vocabulario compartido. */
function normalizeServiceStatus(status: string): string {
  if (status === "ok") return "healthy";
  if (status === "down") return "failed";
  return status;
}

function formatDateTime(value: string | null | undefined) {
  return value ? new Date(value).toLocaleString("es-PE") : "—";
}

export default function AdminSystemStatusPage() {
  const { session } = usePlatformAuth();
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [slos, setSlos] = useState<DeploymentSlo[]>([]);
  const [alerts, setAlerts] = useState<IncidentAlert[]>([]);
  const [orgs, setOrgs] = useState<{ id: string }[]>([]);
  const [orgId, setOrgId] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState("");
  const [confirmAlert, setConfirmAlert] = useState<IncidentAlert | null>(null);

  async function load(oid = "") {
    if (!session) return;
    setError("");
    try {
      const [h, s, a] = await Promise.all([
        platformApi<SystemHealth>("/api/v1/platform/health", { token: session.token }),
        oid
          ? platformApi<{ deployments: DeploymentSlo[] }>(
              `/api/v1/platform/organizations/${oid}/slos`,
              { token: session.token }
            )
          : Promise.resolve({ deployments: [] as DeploymentSlo[] }),
        platformApi<{ alerts: IncidentAlert[] }>(
          `/api/v1/platform/obs/alerts?organization_id=${oid}`,
          { token: session.token }
        ),
      ]);
      setHealth(h);
      setSlos(s.deployments || []);
      setAlerts(a.alerts || []);
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
        const o = await platformApi<{ organizations: { id: string }[] }>(
          "/api/v1/platform/organizations",
          { token: session.token }
        );
        setOrgs(o.organizations || []);
      } catch {
        /* sin lista de organizaciones el selector de SLO queda vacío */
      }
    })();
  }, [session]);

  useEffect(() => {
    void load(orgId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session, orgId]);

  async function runChecks() {
    if (!session) return;
    setBusy("checks");
    setError("");
    setNote("");
    try {
      const out = await platformApi<{ count: number }>("/api/v1/platform/obs/check", {
        method: "POST",
        token: session.token,
        body: "{}",
      });
      setNote(out.count ? `${out.count} alerta(s) creada(s).` : "Sin alertas nuevas.");
      await load(orgId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function resolve(alertId: string) {
    if (!session) return;
    setBusy(alertId);
    setError("");
    setNote("");
    try {
      await platformApi(`/api/v1/platform/obs/alerts/${alertId}/resolve`, {
        method: "POST",
        token: session.token,
        body: "{}",
      });
      setConfirmAlert(null);
      setNote("Incidente resuelto.");
      await load(orgId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  const checks = health?.checks ?? [];
  const healthy = checks.filter((c) => normalizeServiceStatus(c.status) === "healthy");
  const degraded = checks.filter((c) => normalizeServiceStatus(c.status) === "degraded");
  const failedChecks = checks.filter((c) => normalizeServiceStatus(c.status) === "failed");
  const overall = failedChecks.length > 0 ? "failed" : degraded.length > 0 ? "degraded" : "healthy";
  const overallTone: Tone =
    failedChecks.length > 0 ? "danger" : degraded.length > 0 ? "warn" : checks.length > 0 ? "ok" : "neutral";
  const healthyPct = checks.length ? (healthy.length / checks.length) * 100 : 0;
  const openAlerts = alerts.filter((al) => al.status !== "resolved");
  const sloWindows = slos.flatMap((d) => d.windows.map((w) => ({ deployment: d, window: w })));
  const offTargetWindows = sloWindows.filter(
    (entry) => normalizeServiceStatus(entry.window.status) !== "healthy"
  );

  return (
    <div className="space-y-6">
      <PageHeader
        title="System Status"
        subtitle="Salud de servicios, SLIs/SLOs por deployment y alertas de incidentes."
        actions={
          <Button
            variant="primary"
            leadingIcon={Pulse}
            loading={busy === "checks"}
            onClick={() => void runChecks()}
          >
            Ejecutar checks
          </Button>
        }
      />
      <ErrorInline message={error} />
      {note && <SuccessInline>{note}</SuccessInline>}
      {loading ? (
        <Panel className="overflow-hidden">
          <SkeletonTable rows={6} cols={5} />
        </Panel>
      ) : (
        <>
          <Panel className={`p-4 ${failedChecks.length > 0 ? "border-danger/40" : ""}`}>
            <div className="flex flex-wrap items-start justify-between gap-x-8 gap-y-4">
              <div className="min-w-0">
                <p className="eyebrow">Estado general</p>
                <p
                  className={`mt-2 text-[30px] leading-none font-semibold tracking-[-0.025em] ${
                    overallTone === "danger"
                      ? "text-danger"
                      : overallTone === "warn"
                        ? "text-warn"
                        : overallTone === "ok"
                          ? "text-ok"
                          : "text-muted"
                  }`}
                >
                  {health ? statusLabel(overall) : "Sin lectura"}
                </p>
                <p className="mt-2 max-w-[68ch] text-[13px] leading-relaxed text-muted">
                  {health == null
                    ? "El endpoint de health no respondió en la última consulta. Volvé a ejecutar los checks."
                    : failedChecks.length > 0
                      ? `${failedChecks.length} servicio(s) no responden: ${failedChecks
                          .map((c) => c.name)
                          .join(", ")}.`
                      : degraded.length > 0
                        ? `${degraded.length} servicio(s) en estado degradado. Revisá la latencia por servicio antes de dar por sano el sistema.`
                        : `Los ${checks.length} servicios responden. Chequeo ${formatDateTime(health.checked_at)}.`}
                </p>
                {health && checks.length > 0 && (
                  <p className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-faint">
                    <span className="flex items-center gap-1.5">
                      <StatusBadge status="healthy" /> <span className="tabular-nums">{healthy.length}</span>
                    </span>
                    <span className="flex items-center gap-1.5">
                      <StatusBadge status="degraded" /> <span className="tabular-nums">{degraded.length}</span>
                    </span>
                    <span className="flex items-center gap-1.5">
                      <StatusBadge status="failed" /> <span className="tabular-nums">{failedChecks.length}</span>
                    </span>
                  </p>
                )}
              </div>
              <div className="min-w-[220px] flex-1 sm:max-w-sm">
                {checks.length > 0 ? (
                  <Progress
                    value={healthyPct}
                    tone={failedChecks.length > 0 ? "danger" : degraded.length > 0 ? "warn" : "ok"}
                    label="Servicios saludables"
                    showValue
                  />
                ) : (
                  <p className="text-xs text-faint">Sin servicios reportados por el healthcheck.</p>
                )}
              </div>
            </div>
          </Panel>

          <MetricGrid cols={4}>
            <Metric
              size="md"
              label="Servicios monitoreados"
              value={checks.length.toLocaleString()}
              hint="Último chequeo del backend"
            />
            <Metric
              size="md"
              label="Degradados"
              value={degraded.length.toLocaleString()}
              tone={degraded.length > 0 ? "warn" : "default"}
            />
            <Metric
              size="md"
              label="Caídos"
              value={failedChecks.length.toLocaleString()}
              tone={failedChecks.length > 0 ? "danger" : "default"}
            />
            <Metric
              size="md"
              label="Latencia total"
              value={health ? `${health.total_ms.toFixed(0)}ms` : "—"}
            />
          </MetricGrid>

          <section>
            <SectionHeader
              title="Servicios"
              description="Estado reportado por el healthcheck, con la latencia medida en la última pasada."
              className="mb-3"
            />
            <Panel className="overflow-x-auto">
              {checks.length === 0 ? (
                <EmptyState
                  icon={Broadcast}
                  compact
                  title="Sin servicios reportados"
                  body="El healthcheck no devolvió componentes en la última lectura."
                  hint="Ejecutá los checks para forzar una nueva lectura."
                />
              ) : (
                <table className="table min-w-[720px]">
                  <thead>
                    <tr>
                      <th>Servicio</th>
                      <th>Estado</th>
                      <th className="text-right">Latencia</th>
                      <th>Detalle</th>
                    </tr>
                  </thead>
                  <tbody>
                    {checks.map((c) => (
                      <tr key={c.name}>
                        <td className="font-medium">{c.name}</td>
                        <td>
                          <StatusBadge status={normalizeServiceStatus(c.status)} />
                        </td>
                        <td className="text-right tabular-nums">{c.latency_ms.toFixed(0)}ms</td>
                        <td className="max-w-96 truncate text-xs text-muted" title={c.detail}>
                          {c.detail || "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Panel>
          </section>

          <section>
            <SectionHeader
              title="Incidentes"
              description={`${openAlerts.length} sin resolver de ${alerts.length} alertas registradas.`}
              className="mb-3"
            />
            <Panel>
              {alerts.length === 0 ? (
                <EmptyState
                  icon={WarningCircle}
                  compact
                  tone="accent"
                  title="Sin incidentes"
                  body="No hay alertas abiertas o recientes en esta organización."
                />
              ) : (
                <ol className="p-4">
                  {alerts.map((al) => {
                    const sev = SEVERITY_META[al.severity] ?? {
                      tone: "neutral" as Tone,
                      label: al.severity,
                    };
                    const resolved = al.status === "resolved";
                    return (
                      <li
                        key={al.id}
                        className="relative border-l border-border-soft pb-5 pl-5 last:border-l-transparent last:pb-0"
                      >
                        <span
                          className={`absolute top-1 -left-[5px] h-2.5 w-2.5 rounded-full ${
                            resolved ? "bg-ok" : sev.tone === "danger" ? "bg-danger" : "bg-warn"
                          }`}
                          aria-hidden
                        />
                        <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-2">
                              <Badge tone={sev.tone} dot>
                                {sev.label}
                              </Badge>
                              <StatusBadge status={al.status} />
                              <span className="mono text-xs text-faint">{al.alert_type}</span>
                            </div>
                            <p className="mt-1.5 text-sm text-text">{al.message}</p>
                            <p className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-faint">
                              <time dateTime={al.created_at} className="tabular-nums">
                                {formatDateTime(al.created_at)}
                              </time>
                              {al.webhook_status && (
                                <>
                                  <span aria-hidden>·</span>
                                  <span>webhook: {al.webhook_status}</span>
                                </>
                              )}
                            </p>
                          </div>
                          {!resolved && (
                            <Button
                              size="sm"
                              variant="ghost"
                              loading={busy === al.id}
                              onClick={() => setConfirmAlert(al)}
                            >
                              Resolver
                            </Button>
                          )}
                        </div>
                      </li>
                    );
                  })}
                </ol>
              )}
            </Panel>
          </section>

          <section>
            <SectionHeader
              title="SLOs por deployment"
              description={
                orgId
                  ? `${sloWindows.length} ventana(s) evaluadas · ${offTargetWindows.length} fuera de objetivo.`
                  : "Elegí una organización para cargar sus ventanas de SLO."
              }
              className="mb-3"
              actions={
                <Field label="Organización" className="w-full sm:w-56">
                  <Select value={orgId} placeholder="Todas" onChange={(e) => setOrgId(e.target.value)}>
                    {orgs.map((o) => (
                      <option key={o.id} value={o.id}>
                        {o.id.slice(0, 8)}
                      </option>
                    ))}
                  </Select>
                </Field>
              }
            />
            {slos.length === 0 ? (
              <Panel>
                <EmptyState
                  icon={Pulse}
                  compact
                  title={orgId ? "Sin deployments con SLO" : "Sin organización seleccionada"}
                  body={
                    orgId
                      ? "La organización elegida no tiene deployments con ventanas de SLO registradas."
                      : "El backend expone los SLO por organización."
                  }
                />
              </Panel>
            ) : (
              <Panel className="overflow-x-auto">
                <table className="table min-w-[960px]">
                  <thead>
                    <tr>
                      <th>Deployment</th>
                      <th>Estado</th>
                      <th>Ventana</th>
                      <th className="text-right">Requests</th>
                      <th className="text-right">Errores</th>
                      <th className="text-right">Error rate</th>
                      <th className="text-right">Disponibilidad</th>
                      <th className="text-right">p50</th>
                      <th className="text-right">p95</th>
                      <th>SLO</th>
                    </tr>
                  </thead>
                  <tbody>
                    {slos.map((d) =>
                      d.windows.map((w) => (
                        <tr key={`${d.deployment_id}-${w.window}`}>
                          <td className="font-medium">{d.slug}</td>
                          <td>
                            <StatusBadge status={normalizeServiceStatus(d.status)} />
                          </td>
                          <td className="text-xs text-muted">{w.window}</td>
                          <td className="text-right tabular-nums">{w.requests.toLocaleString()}</td>
                          <td
                            className={`text-right tabular-nums ${w.errors > 0 ? "text-danger" : "text-muted"}`}
                          >
                            {w.errors.toLocaleString()}
                          </td>
                          <td className="text-right tabular-nums">{w.error_rate_pct}%</td>
                          <td className="text-right tabular-nums">{w.availability_pct}%</td>
                          <td className="text-right tabular-nums">{w.p50_ms.toFixed(0)}ms</td>
                          <td className="text-right tabular-nums">{w.p95_ms.toFixed(0)}ms</td>
                          <td>
                            <StatusBadge status={normalizeServiceStatus(w.status)} />
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </Panel>
            )}
          </section>
        </>
      )}

      <ConfirmDialog
        open={confirmAlert !== null}
        onOpenChange={(open) => !open && setConfirmAlert(null)}
        title="Resolver incidente"
        body={
          confirmAlert
            ? `"${confirmAlert.message}" pasa a resuelto y deja de contar como alerta abierta.`
            : undefined
        }
        confirmLabel="Resolver"
        tone="primary"
        loading={confirmAlert !== null && busy === confirmAlert.id}
        onConfirm={() => confirmAlert && void resolve(confirmAlert.id)}
      />
    </div>
  );
}
