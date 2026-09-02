import { Broadcast, Pulse, WarningCircle } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import {
  EmptyState,
  ErrorInline,
  PageHeader,
  SkeletonBlock,
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

function statusPill(status: string) {
  const cls =
    status === "ok" || status === "healthy"
      ? "badge-ok"
      : status === "down" || status === "failed"
        ? "badge-danger"
        : status === "degraded"
          ? "badge-pending"
          : "badge-muted";
  return <span className={`badge ${cls}`}>{status}</span>;
}

export default function AdminSystemStatusPage() {
  const { session } = usePlatformAuth();
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [slos, setSlos] = useState<DeploymentSlo[]>([]);
  const [alerts, setAlerts] = useState<IncidentAlert[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [orgId, setOrgId] = useState("");

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
    void load(orgId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session, orgId]);

  async function runChecks() {
    if (!session) return;
    try {
      const out = await platformApi<{ count: number }>("/api/v1/platform/obs/check", {
        method: "POST",
        token: session.token,
        body: "{}",
      });
      setError(`${out.count} alertas creadas`);
      await load(orgId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  async function resolve(alertId: string) {
    if (!session) return;
    try {
      await platformApi(`/api/v1/platform/obs/alerts/${alertId}/resolve`, {
        method: "POST",
        token: session.token,
        body: "{}",
      });
      await load(orgId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="System Status"
        subtitle="Salud de servicios, SLIs/SLOs por deployment y alertas de incidentes."
        actions={
          <button type="button" className="btn btn-primary min-h-11" onClick={() => void runChecks()}>
            <Pulse size={15} aria-hidden /> Ejecutar checks
          </button>
        }
      />
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading ? (
        <SkeletonBlock className="h-40" />
      ) : (
        <>
          <section>
            <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text">
              <Broadcast size={15} aria-hidden /> Servicios
            </h3>
            <div className="panel grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {(health?.checks ?? []).map((c) => (
                <div key={c.name} className="flex items-center justify-between gap-2 rounded-md border border-border p-3">
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-text">{c.name}</p>
                    <p className="truncate text-xs text-faint">{c.detail}</p>
                  </div>
                  <div className="flex items-center gap-2">
                    {statusPill(c.status)}
                    <span className="text-xs text-faint">{c.latency_ms.toFixed(0)}ms</span>
                  </div>
                </div>
              ))}
            </div>
          </section>

          <section>
            <h3 className="mb-2 text-sm font-semibold text-text">Alertas de incidentes</h3>
            <div className="panel">
              {alerts.length === 0 ? (
                <EmptyState icon={WarningCircle} title="Sin incidentes" body="No hay alertas abiertas o recientes." />
              ) : (
                <ul className="space-y-2">
                  {alerts.map((al) => (
                    <li
                      key={al.id}
                      className={`flex flex-wrap items-center justify-between gap-2 rounded-md border p-2.5 ${
                        al.status === "resolved" ? "border-border bg-soft" : "border-warn-soft bg-warn-soft/30"
                      }`}
                    >
                      <div className="min-w-0">
                        <p className="text-sm text-text">
                          {al.severity === "critical" && (
                            <WarningCircle size={14} className="mr-1 inline text-danger" aria-hidden />
                          )}
                          {al.message}
                        </p>
                        <p className="text-xs text-faint">
                          {al.alert_type} · {al.severity} ·{" "}
                          {new Date(al.created_at).toLocaleString("es-PE")}
                          {al.webhook_status ? ` · webhook: ${al.webhook_status}` : ""}
                        </p>
                      </div>
                      <div className="flex items-center gap-2">
                        {statusPill(al.status)}
                        {al.status !== "resolved" && (
                          <button type="button" className="btn btn-ghost min-h-8 text-xs" onClick={() => void resolve(al.id)}>
                            Resolver
                          </button>
                        )}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </section>

          <section>
            <h3 className="mb-2 text-sm font-semibold text-text">SLOs por deployment (tenant)</h3>
            {slos.length === 0 ? (
              <div className="panel">
                <EmptyState icon={Pulse} title="Sin deployments" body="Selecciona un tenant con deployments." />
              </div>
            ) : (
              <div className="panel overflow-x-auto">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Deployment</th>
                      <th>Estado</th>
                      <th>Ventana</th>
                      <th>Requests</th>
                      <th>Error rate</th>
                      <th>Disponibilidad</th>
                      <th>p50</th>
                      <th>p95</th>
                      <th>SLO</th>
                    </tr>
                  </thead>
                  <tbody>
                    {slos.map((d) =>
                      d.windows.map((w) => (
                        <tr key={`${d.deployment_id}-${w.window}`}>
                          <td className="text-sm text-text">{d.slug}</td>
                          <td>{statusPill(d.status)}</td>
                          <td className="text-xs text-muted">{w.window}</td>
                          <td className="text-xs text-muted">{w.requests}</td>
                          <td className="text-xs">{w.error_rate_pct}%</td>
                          <td className="text-xs">{w.availability_pct}%</td>
                          <td className="text-xs">{w.p50_ms.toFixed(0)}ms</td>
                          <td className="text-xs">{w.p95_ms.toFixed(0)}ms</td>
                          <td>{statusPill(w.status)}</td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}