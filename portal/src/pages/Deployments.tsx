import {
  AppWindow,
  Globe,
  ListBullets,
  PlugsConnected,
  PuzzlePiece,
  RocketLaunch,
} from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { ComingSoonBadge } from "../components/ComingSoon";
import {
  EmptyState,
  ErrorInline,
  PageHeader,
  SkeletonBlock,
  StatusBadge,
} from "../components/ui";
import { fmtDateTime, fmtLatency, fmtNum } from "../lib/format";

type Deployment = {
  id: string;
  environment_id: string;
  agent_id: string;
  agent_version_id: string;
  slug: string;
  status: string;
  endpoint: string | null;
  deployed_by: string | null;
  deployed_at: string | null;
  rollback_from_id: string | null;
  created_at: string;
};

type ApiLog = {
  id: string;
  request_id: string;
  endpoint: string;
  status: number;
  latency_ms: number | null;
  tokens: number;
  created_at: string;
};

const TARGETS: { icon: typeof AppWindow; label: string; desc: string; ready: boolean; to?: string }[] = [
  {
    icon: Globe,
    label: "REST API",
    desc: "Consulta tus agentes desde cualquier sistema con una API pública.",
    ready: true,
    to: "/developers",
  },
  {
    icon: AppWindow,
    label: "Web Widget",
    desc: "Embeber tu asistente en sitios web y aplicaciones.",
    ready: false,
  },
  {
    icon: PuzzlePiece,
    label: "SDK",
    desc: "Integraciones en Python, JavaScript y otros lenguajes.",
    ready: true,
    to: "/developers/tools",
  },
  {
    icon: PlugsConnected,
    label: "Integración ERP",
    desc: "Conectores nativos para sistemas empresariales.",
    ready: false,
  },
  {
    icon: ListBullets,
    label: "MCP",
    desc: "Exponer tus agentes como herramientas para asistentes y agentes externos.",
    ready: false,
  },
];

export default function DeploymentsPage() {
  const { session } = useAuth();
  const [deployments, setDeployments] = useState<Deployment[]>([]);
  const [logs, setLogs] = useState<ApiLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!session) return;
    (async () => {
      setLoading(true);
      setError("");
      try {
        const [depData, logData] = await Promise.all([
          api<{ deployments: Deployment[] }>("/api/v1/deployments", {
            token: session.token,
            organizationId: session.organizationId,
          }).catch(() => ({ deployments: [] as Deployment[] })),
          api<{ logs: ApiLog[] }>("/api/v1/deployments/logs", {
            token: session.token,
            organizationId: session.organizationId,
          }).catch(() => ({ logs: [] as ApiLog[] })),
        ]);
        setDeployments(depData.deployments || []);
        setLogs(logData.logs || []);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Error cargando despliegues");
      } finally {
        setLoading(false);
      }
    })();
  }, [session]);

  return (
    <div>
      <PageHeader
        title="Despliegues"
        subtitle="Despliega tus experiencias de IA en aplicaciones, APIs y sistemas empresariales."
        actions={
          <Link to="/developers" className="btn btn-secondary">
            Centro de desarrolladores
          </Link>
        }
      />
      <ErrorInline message={error} />

      <div className="mb-6 grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-5">
        {TARGETS.map((t) => {
          const Content = (
            <>
              <span className="flex h-9 w-9 items-center justify-center rounded-md border border-border bg-soft text-accent">
                <t.icon size={18} aria-hidden />
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <p className="text-sm font-medium text-text">{t.label}</p>
                  {!t.ready && <ComingSoonBadge />}
                </div>
                <p className="mt-0.5 text-[12px] leading-relaxed text-muted">{t.desc}</p>
              </div>
            </>
          );
          return t.ready && t.to ? (
            <Link
              key={t.label}
              to={t.to}
              className="panel flex items-start gap-3 p-4 transition-colors duration-150 hover:border-border-strong"
            >
              {Content}
            </Link>
          ) : (
            <div key={t.label} className="panel flex items-start gap-3 p-4">
              {Content}
            </div>
          );
        })}
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <div className="panel xl:col-span-2">
          <div className="flex items-center gap-2 border-b border-border px-5 py-4">
            <RocketLaunch size={16} className="text-accent" aria-hidden />
            <h2 className="text-sm font-semibold text-text">Deployments ({deployments.length})</h2>
          </div>
          {loading ? (
            <div className="p-5">
              <SkeletonBlock rows={4} />
            </div>
          ) : deployments.length === 0 ? (
            <EmptyState
              icon={RocketLaunch}
              title="Sin deployments activos"
              body="Despliega un agente desde su editor para obtener un endpoint público y comenzar a integrarlo."
              action={
                <Link to="/agents" className="btn btn-secondary">
                  Ir a Agentes
                </Link>
              }
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="table min-w-[640px]">
                <thead>
                  <tr>
                    <th>Endpoint</th>
                    <th>Entorno</th>
                    <th>Estado</th>
                    <th>Desplegado</th>
                  </tr>
                </thead>
                <tbody>
                  {deployments.map((d) => (
                    <tr key={d.id}>
                      <td>
                        <span className="mono text-xs text-accent">{d.slug}</span>
                        {d.endpoint && (
                          <span className="block truncate font-mono text-[11px] text-faint" title={d.endpoint}>
                            {d.endpoint}
                          </span>
                        )}
                      </td>
                      <td className="mono text-xs text-muted">
                        {d.environment_id ? d.environment_id.slice(0, 8) : "—"}
                      </td>
                      <td>
                        <StatusBadge status={d.status} />
                      </td>
                      <td className="text-xs text-faint">
                        {d.deployed_at ? fmtDateTime(d.deployed_at) : fmtDateTime(d.created_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="panel">
          <div className="flex items-center gap-2 border-b border-border px-5 py-4">
            <ListBullets size={16} className="text-accent" aria-hidden />
            <h2 className="text-sm font-semibold text-text">Tráfico reciente</h2>
          </div>
          {logs.length === 0 ? (
            <EmptyState
              icon={ListBullets}
              title="Sin llamadas"
              body="Las consultas a tus endpoints públicos aparecerán aquí."
            />
          ) : (
            <div className="divide-y divide-border/60">
              {logs.slice(0, 8).map((l) => (
                <div key={l.id} className="flex items-center justify-between gap-2 px-5 py-2.5">
                  <div className="min-w-0">
                    <p className="mono truncate text-xs text-text">{l.request_id.slice(0, 8)}</p>
                    <p className="truncate text-[11px] text-faint">{l.endpoint}</p>
                  </div>
                  <div className="flex shrink-0 flex-col items-end">
                    <span
                      className={`badge ${l.status === 200 ? "badge-ok" : "badge-danger"}`}
                    >
                      {l.status}
                    </span>
                    <span className="mono mt-0.5 text-[11px] text-faint">
                      {fmtLatency(l.latency_ms ?? 0)} · {fmtNum(l.tokens)} tok
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}