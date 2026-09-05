import {
  ArrowLeft,
  ChartLineUp,
  Flask,
  PaperPlaneRight,
  Play,
  PencilSimple,
  Robot,
} from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { Breadcrumb } from "../components/Breadcrumb";
import {
  EmptyState,
  EnvironmentBadge,
  ErrorInline,
  PageHeader,
  ReadinessScore,
  SkeletonBlock,
  StatCard,
  StatusBadge,
  VersionBadge,
} from "../components/ui";
import { fmtDateTime, fmtLatency, fmtNum } from "../lib/format";

type Agent = {
  id: string;
  name: string;
  description: string | null;
  tools: string[];
  model: string | null;
  is_active: boolean;
  config: { knowledge_base_ids?: string[] };
  workspace_id?: string | null;
};

type AgentVersion = { id: string; version_number: number; status: string; created_at: string };
type Environment = { id: string; name: string; slug: string; is_default: boolean };
type Deployment = {
  id: string;
  agent_id: string;
  environment_id: string;
  agent_version_id: string;
  slug: string;
  status: string;
  endpoint: string | null;
  deployed_at: string | null;
};
type Readiness = {
  score: number;
  items: { key: string; label: string; met: boolean; weight: number; detail: string }[];
};
type UsageRow = {
  agent_id: string;
  requests: number;
  tokens: number;
  estimated_cost: number;
  avg_latency_ms: number;
};
type KB = { id: string; name: string };
type Workspace = { id: string; name: string };

export default function AgentOverviewPage() {
  const { id } = useParams<{ id: string }>();
  const { session } = useAuth();
  const [agent, setAgent] = useState<Agent | null>(null);
  const [versions, setVersions] = useState<AgentVersion[]>([]);
  const [environments, setEnvironments] = useState<Environment[]>([]);
  const [deployments, setDeployments] = useState<Deployment[]>([]);
  const [readiness, setReadiness] = useState<Readiness | null>(null);
  const [usage, setUsage] = useState<UsageRow | null>(null);
  const [kbs, setKbs] = useState<KB[]>([]);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!session || !id) return;
    (async () => {
      setLoading(true);
      setError("");
      try {
        const [a, v, d, e, r, u, kb, ws] = await Promise.all([
          api<Agent>(`/api/v1/agents/${id}`, {
            token: session.token,
            organizationId: session.organizationId,
          }),
          api<{ versions: AgentVersion[] }>(`/api/v1/agents/${id}/versions`, {
            token: session.token,
            organizationId: session.organizationId,
          }).catch(() => ({ versions: [] as AgentVersion[] })),
          api<{ deployments: Deployment[] }>("/api/v1/deployments", {
            token: session.token,
            organizationId: session.organizationId,
          }).catch(() => ({ deployments: [] as Deployment[] })),
          api<{ environments: Environment[] }>("/api/v1/environments", {
            token: session.token,
            organizationId: session.organizationId,
          }).catch(() => ({ environments: [] as Environment[] })),
          api<Readiness>(`/api/v1/agents/${id}/readiness`, {
            token: session.token,
            organizationId: session.organizationId,
          }).catch(() => null),
          api<{ agents: UsageRow[] }>("/api/v1/billing/usage/agents", {
            token: session.token,
            organizationId: session.organizationId,
          }).catch(() => ({ agents: [] as UsageRow[] })),
          api<{ knowledge_bases: KB[] }>("/api/v1/knowledge-bases", {
            token: session.token,
            organizationId: session.organizationId,
          }).catch(() => ({ knowledge_bases: [] as KB[] })),
          api<{ workspaces: Workspace[] }>("/api/v1/workspaces", {
            token: session.token,
            organizationId: session.organizationId,
          }).catch(() => ({ workspaces: [] as Workspace[] })),
        ]);
        setAgent(a);
        setVersions(v.versions || []);
        setDeployments((d.deployments || []).filter((x) => x.agent_id === id));
        setEnvironments(e.environments || []);
        setReadiness(r);
        setUsage((u.agents || []).find((row) => row.agent_id === id) || null);
        setKbs(kb.knowledge_bases || []);
        setWorkspaces(ws.workspaces || []);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Error cargando el agente");
      } finally {
        setLoading(false);
      }
    })();
  }, [session, id]);

  if (loading) {
    return (
      <div className="panel p-5">
        <SkeletonBlock rows={6} />
      </div>
    );
  }

  if (error || !agent) {
    return (
      <div className="panel p-5">
        <ErrorInline message={error || "No se encontró el agente."} />
      </div>
    );
  }

  const latestVersion =
    versions.find((v) => v.status === "production") ||
    versions.find((v) => v.status === "staging") ||
    versions.find((v) => v.status === "ready") ||
    versions[0] ||
    null;
  const healthyDeployment =
    deployments.find((d) => d.status === "healthy") || deployments[0] || null;
  const workspace = workspaces.find((w) => w.id === agent.workspace_id);
  const kbNames = (agent.config.knowledge_base_ids || [])
    .map((kbId) => kbs.find((kb) => kb.id === kbId)?.name || kbId.slice(0, 8));

  return (
    <div>
      <Breadcrumb
        items={[
          { label: "Agentes", to: "/agents" },
          { label: agent.name || "Agente" },
        ]}
      />
      <PageHeader
        title={agent.name || "Agente"}
        subtitle={agent.description || "Vista general del agente, su estado y su despliegue."}
        actions={
          <div className="flex flex-wrap gap-2">
            <Link to={`/agents/${agent.id}/builder`} className="btn btn-secondary min-h-11">
              <PencilSimple size={16} aria-hidden />
              Edit
            </Link>
            <Link to={`/agents/${agent.id}/builder?tab=playground`} className="btn btn-secondary min-h-11">
              <Play size={16} aria-hidden />
              Test
            </Link>
            <Link to="/evaluation/runs" className="btn btn-secondary min-h-11">
              <Flask size={16} aria-hidden />
              Evaluate
            </Link>
            <Link to={`/agents/${agent.id}/builder?tab=deployments`} className="btn btn-primary min-h-11">
              <PaperPlaneRight size={16} aria-hidden />
              Deploy
            </Link>
            <Link to="/developers" className="btn btn-secondary min-h-11">
              View API
            </Link>
            <Link to="/agents" className="btn btn-ghost min-h-11">
              <ArrowLeft size={16} aria-hidden />
              Volver
            </Link>
          </div>
        }
      />
      <ErrorInline message={error} />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <StatCard
          label="Estado"
          value={agent.is_active ? "Activo" : "Inactivo"}
          icon={Robot}
          tone={agent.is_active ? "ok" : "default"}
        />
        <StatCard label="Modelo" value={agent.model || "zent-default"} />
        <StatCard
          label="Versión actual"
          value={latestVersion ? <VersionBadge versionNumber={latestVersion.version_number} status={latestVersion.status} /> : "—"}
        />
        <StatCard
          label="Deployment"
          value={
            healthyDeployment ? (
              <span className="flex items-center gap-2">
                <StatusBadge status={healthyDeployment.status} />
                <EnvironmentBadge
                  name={environments.find((x) => x.id === healthyDeployment.environment_id)?.slug || "env"}
                />
              </span>
            ) : (
              "Sin desplegar"
            )
          }
        />
        <StatCard label="Workspace" value={workspace?.name || "default"} />
        <StatCard
          label="Última actualización"
          value={latestVersion ? fmtDateTime(latestVersion.created_at) : "—"}
        />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-3">
        <div className="xl:col-span-2">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <StatCard label="Requests" value={usage ? fmtNum(usage.requests) : "—"} icon={ChartLineUp} />
            <StatCard label="Tokens" value={usage ? fmtNum(usage.tokens) : "—"} />
            <StatCard
              label="Latencia media"
              value={usage ? fmtLatency(usage.avg_latency_ms) : "—"}
            />
            <StatCard
              label="Costo estimado"
              value={usage ? `$${usage.estimated_cost.toFixed(4)}` : "—"}
            />
          </div>

          <div className="mt-4">
            {readiness ? (
              <ReadinessScore score={readiness.score} items={readiness.items} />
            ) : (
              <div className="panel">
                <EmptyState
                  icon={ChartLineUp}
                  title="Sin readiness"
                  body="Guarda y configura el agente para calcular su puntaje de producción."
                />
              </div>
            )}
          </div>
        </div>

        <div className="flex flex-col gap-4">
          <div className="panel p-5">
            <h2 className="mb-2 text-sm font-semibold text-text">Conocimiento conectado</h2>
            {kbNames.length === 0 ? (
              <p className="text-sm text-muted">Sin knowledge bases asignadas.</p>
            ) : (
              <ul className="space-y-1.5">
                {kbNames.map((name) => (
                  <li key={name} className="flex items-center gap-2 text-[13px] text-text">
                    <span className="status-dot bg-accent" aria-hidden />
                    {name}
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="panel p-5">
            <h2 className="mb-2 text-sm font-semibold text-text">Tools</h2>
            {agent.tools.length === 0 ? (
              <p className="text-sm text-muted">Sin tools habilitadas.</p>
            ) : (
              <div className="flex flex-wrap gap-1.5">
                {agent.tools.map((t) => (
                  <span key={t} className="badge badge-muted">{t}</span>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="panel mt-4 overflow-x-auto">
        <div className="border-b border-border px-5 py-4">
          <h2 className="text-sm font-semibold text-text">Deployments</h2>
        </div>
        {deployments.length === 0 ? (
          <EmptyState
            icon={PaperPlaneRight}
            title="Sin deployments"
            body="Despliega una versión desde el builder para exponer el endpoint público."
          />
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Deployment</th>
                <th>Entorno</th>
                <th>Estado</th>
                <th>Endpoint</th>
                <th>Desplegado</th>
              </tr>
            </thead>
            <tbody>
              {deployments.map((d) => (
                <tr key={d.id}>
                  <td className="font-mono text-xs">{d.slug}</td>
                  <td>
                    <EnvironmentBadge
                      name={environments.find((x) => x.id === d.environment_id)?.name || d.environment_id}
                    />
                  </td>
                  <td>
                    <StatusBadge status={d.status} />
                  </td>
                  <td className="font-mono text-xs text-muted">{d.endpoint || "—"}</td>
                  <td className="text-sm text-muted">
                    {d.deployed_at ? fmtDateTime(d.deployed_at) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}