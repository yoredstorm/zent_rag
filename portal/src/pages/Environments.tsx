import { ArrowUpRight, CaretRight } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { ErrorInline, PageHeader, SkeletonBlock, StatusBadge } from "../components/ui";
import { fmtDateTime } from "../lib/format";

type Slos = {
  status: string;
  windows?: { window: string; p95_latency_ms?: number; error_rate?: number; availability?: number }[];
} | null;

type Environment = {
  id: string;
  name: string;
  slug: string;
  is_default: boolean;
  created_at: string;
  deployment: {
    id: string;
    status: string;
    slug: string;
    endpoint: string | null;
    deployed_at: string | null;
    version_number: number | null;
    agent_version_id: string | null;
    agent_name: string | null;
    traffic_pct: number;
    slos: Slos;
  } | null;
};

const ENV_TONE: Record<string, string> = {
  development: "badge-muted",
  staging: "badge-warning",
  production: "badge-ok",
};

export default function EnvironmentsPage() {
  const { session } = useAuth();
  const [envs, setEnvs] = useState<Environment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!session) return;
    api<{ environments: Environment[] }>("/api/v1/environments", {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then((d) => setEnvs(d.environments || []))
      .catch((e) => setError(e instanceof Error ? e.message : "Error"))
      .finally(() => setLoading(false));
  }, [session]);

  return (
    <div>
      <PageHeader
        title="Entornos"
        subtitle="Versión desplegada por entorno, salud y tráfico. Una versión es el snapshot congelado; un deployment es la ejecución de esa versión en un entorno."
      />
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading ? (
        <SkeletonBlock className="h-40" />
      ) : (
        <div className="grid gap-4 lg:grid-cols-3">
          {envs.map((env) => {
            const dep = env.deployment;
            return (
              <div key={env.id} className="panel p-5">
                <div className="flex items-center justify-between gap-2">
                  <h2 className="flex items-center gap-2 text-sm font-semibold text-text">
                    <span className={`badge ${ENV_TONE[env.slug] ?? "badge-muted"}`}>{env.name}</span>
                  </h2>
                  <span className="mono text-[10px] text-faint">{env.slug}</span>
                </div>
                {dep ? (
                  <div className="mt-4 space-y-2 text-[13px]">
                    <div className="flex items-center justify-between">
                      <span className="text-muted">Versión</span>
                      <span className="mono font-medium text-text">
                        {dep.version_number != null ? `v${dep.version_number}` : dep.agent_version_id?.slice(0, 8) ?? "—"}
                      </span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-muted">Estado</span>
                      <StatusBadge status={dep.status} />
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-muted">Desplegado</span>
                      <span className="text-text">{dep.deployed_at ? fmtDateTime(dep.deployed_at) : "—"}</span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-muted">Tráfico</span>
                      <span className="text-text">{dep.traffic_pct}%</span>
                    </div>
                    {dep.endpoint && (
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-muted">Endpoint</span>
                        <span className="mono truncate text-[11px] text-accent">{dep.endpoint}</span>
                      </div>
                    )}
                    {dep.slos && (
                      <div className="flex items-center justify-between">
                        <span className="text-muted">Salud (SLO)</span>
                        <span className={`badge ${dep.slos.status === "ok" ? "badge-ok" : dep.slos.status === "degraded" ? "badge-warning" : "badge-danger"}`}>
                          {dep.slos.status}
                        </span>
                      </div>
                    )}
                    <div className="pt-2">
                      <Link
                        to={`/deployments`}
                        className="inline-flex items-center gap-1 text-[12px] font-medium text-accent hover:underline"
                      >
                        Ver despliegues <CaretRight size={12} aria-hidden />
                      </Link>
                      {dep.endpoint && (
                        <Link
                          to={`/developers?deployment=${dep.slug}`}
                          className="ml-3 inline-flex items-center gap-1 text-[12px] font-medium text-accent hover:underline"
                        >
                          Consumir <ArrowUpRight size={12} aria-hidden />
                        </Link>
                      )}
                    </div>
                  </div>
                ) : (
                  <p className="mt-4 text-[13px] text-faint">Sin despliegue en este entorno.</p>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}