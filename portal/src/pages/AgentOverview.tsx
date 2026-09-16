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
import OutcomesPanel from "../components/OutcomesPanel";
import {
  Badge,
  ButtonLink,
  EmptyState,
  EnvironmentBadge,
  ErrorInline,
  Metric,
  MetricGrid,
  PageHeader,
  Panel,
  PanelHeader,
  ReadinessScore,
  SkeletonBlock,
  StatusBadge,
  VersionBadge,
  cn,
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

type AssistantAutomation = {
  workflow_id: string;
  name: string;
  status: string;
  when: string;
  runs_7d: number;
  failed_runs: number;
  success_rate: number | null;
  last_activity: string | null;
};

type AssistantAutomations = {
  assistant: { id: string; name: string; status: string };
  summary: { automations: number; active: number; actions_today: number; last_activity: string | null; health: string };
  automations: AssistantAutomation[];
};

const HEALTH_LABEL: Record<string, string> = {
  healthy: "Saludable",
  needs_attention: "Necesita atención",
  paused: "Pausado",
  idle: "Sin automatizaciones",
};

/** Estado real de una automatización para el activity rail. */
function automationRailState(status: string): "ready" | "queued" | "failed" {
  if (status === "active") return "ready";
  if (status === "failed" || status === "error") return "failed";
  return "queued";
}

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
  const [assistant, setAssistant] = useState<AssistantAutomations | null>(null);

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

  useEffect(() => {
    if (!session || !id) return;
    api<AssistantAutomations>(`/api/v1/agents/${id}/automations`, {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then(setAssistant)
      .catch(() => setAssistant(null));
  }, [session, id]);

  if (loading) {
    return (
      <Panel className="p-4">
        <SkeletonBlock rows={6} />
      </Panel>
    );
  }

  if (error || !agent) {
    return (
      <Panel className="p-4">
        <ErrorInline message={error || "No se encontró el agente."} className="mb-0" />
      </Panel>
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
  const environmentName = healthyDeployment
    ? environments.find((x) => x.id === healthyDeployment.environment_id)?.name ||
      healthyDeployment.environment_id
    : "";
  const workspace = workspaces.find((w) => w.id === agent.workspace_id);
  const kbNames = (agent.config.knowledge_base_ids || []).map(
    (kbId) => kbs.find((kb) => kb.id === kbId)?.name || kbId.slice(0, 8),
  );

  return (
    <div className="flex flex-col gap-4">
      <Breadcrumb
        items={[
          { label: "Agentes", to: "/agents" },
          { label: agent.name || "Agente" },
        ]}
      />
      <PageHeader
        className="mb-0"
        title={agent.name || "Agente"}
        subtitle={agent.description || "Vista general del agente, su estado y su despliegue."}
        actions={
          <>
            <ButtonLink to={`/agents/${agent.id}/builder`} leadingIcon={PencilSimple}>
              Editar
            </ButtonLink>
            <ButtonLink to={`/agents/${agent.id}/builder?tab=playground`} leadingIcon={Play}>
              Probar
            </ButtonLink>
            <ButtonLink to="/evaluation/runs" leadingIcon={Flask}>
              Evaluar
            </ButtonLink>
            <ButtonLink
              to={`/agents/${agent.id}/builder?tab=deployments`}
              variant="primary"
              leadingIcon={PaperPlaneRight}
            >
              Publicar
            </ButtonLink>
            <ButtonLink to="/developers">Ver API</ButtonLink>
            <ButtonLink to="/agents" variant="ghost" leadingIcon={ArrowLeft}>
              Volver
            </ButtonLink>
          </>
        }
      />
      <ErrorInline message={error} className="mb-0" />

      <Panel>
        <div className="flex flex-col gap-4 p-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="flex min-w-0 gap-3">
            <span
              className={cn(
                "flex h-10 w-10 shrink-0 items-center justify-center rounded-md border",
                agent.is_active
                  ? "border-ok/25 bg-ok-soft text-ok"
                  : "border-border bg-raised text-faint",
              )}
              aria-hidden
            >
              <Robot size={20} />
            </span>
            <div className="min-w-0">
              <h2 className="text-h2">{agent.is_active ? "Agente activo" : "Agente inactivo"}</h2>
              <p className="prose-measure mt-1.5 text-sm leading-relaxed text-muted">
                {healthyDeployment
                  ? `Atiende en ${environmentName} con la versión ${
                      latestVersion ? `v${latestVersion.version_number}` : "más reciente"
                    }.`
                  : "Todavía no tiene una publicación activa. Publica una versión lista para que empiece a atender."}
              </p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2 sm:justify-end">
            {healthyDeployment && <StatusBadge status={healthyDeployment.status} />}
            {healthyDeployment && <EnvironmentBadge name={environmentName} />}
            {latestVersion && (
              <VersionBadge versionNumber={latestVersion.version_number} status={latestVersion.status} />
            )}
            <Badge tone="neutral">{agent.model || "zent-default"}</Badge>
            {workspace?.name && <Badge tone="neutral">{workspace.name}</Badge>}
          </div>
        </div>
      </Panel>

      <MetricGrid cols={4}>
        <Metric size="md" label="Requests" value={usage ? fmtNum(usage.requests) : "—"} icon={ChartLineUp} />
        <Metric size="md" label="Tokens" value={usage ? fmtNum(usage.tokens) : "—"} />
        <Metric size="md" label="Latencia media" value={usage ? fmtLatency(usage.avg_latency_ms) : "—"} />
        <Metric
          size="md"
          label="Costo estimado"
          value={usage ? `$${usage.estimated_cost.toFixed(4)}` : "—"}
        />
      </MetricGrid>

      {assistant && (
        <Panel data-testid="agent-automations">
          <PanelHeader
            title="Asistente activo"
            description="Automatizaciones que mantienen este agente trabajando solo."
            actions={
              <>
                <Badge
                  tone={
                    assistant.summary.health === "healthy"
                      ? "ok"
                      : assistant.summary.health === "needs_attention"
                        ? "danger"
                        : "neutral"
                  }
                >
                  {HEALTH_LABEL[assistant.summary.health] ?? assistant.summary.health}
                </Badge>
                <ButtonLink to="/workflows/new/ask" size="sm">
                  Agregar automatización
                </ButtonLink>
              </>
            }
          />
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-border px-4 py-2.5 text-xs text-faint">
            <span className="tabular-nums">{assistant.summary.active} activas</span>
            <span className="tabular-nums">{assistant.summary.actions_today} ejecuciones hoy</span>
            {assistant.summary.last_activity && (
              <span>Última actividad {fmtDateTime(assistant.summary.last_activity)}</span>
            )}
          </div>
          {assistant.automations.length === 0 ? (
            <EmptyState
              icon={Robot}
              title="Sin automatizaciones"
              body="Este agente todavía no tiene automatizaciones. Cuéntale a Zent qué debe vigilar y quedará asociado."
              compact
            />
          ) : (
            <ul className="p-2">
              {assistant.automations.map((automation) => (
                <li
                  key={automation.workflow_id}
                  data-state={automationRailState(automation.status)}
                  className="state-rail flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md py-2.5 pr-2 pl-4 text-[13px]"
                >
                  <Link to={`/workflows/${automation.workflow_id}`} className="font-medium text-text hover:text-accent">
                    {automation.name}
                  </Link>
                  <StatusBadge status={automation.status} />
                  <span className="text-muted">Cuando {automation.when.toLowerCase()}</span>
                  <span className="ml-auto text-xs text-faint tabular-nums">
                    {automation.runs_7d} ejecuciones · {automation.success_rate ?? "—"}% éxito
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      )}

      <div className="grid gap-4 xl:grid-cols-3">
        <div className="flex flex-col gap-4 xl:col-span-2">
          {readiness ? (
            <ReadinessScore score={readiness.score} items={readiness.items} />
          ) : (
            <Panel>
              <EmptyState
                icon={ChartLineUp}
                title="Sin puntaje todavía"
                body="Guarda y configura el agente para calcular su puntaje de producción."
              />
            </Panel>
          )}
          <OutcomesPanel agentId={agent.id} session={session} />
        </div>

        <div className="flex flex-col gap-4">
          <Panel>
            <PanelHeader title="Conocimiento conectado" />
            <div className="p-4">
              {kbNames.length === 0 ? (
                <p className="text-[13px] text-muted">Sin knowledge bases asignadas.</p>
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
          </Panel>

          <Panel>
            <PanelHeader title="Herramientas" />
            <div className="p-4">
              {agent.tools.length === 0 ? (
                <p className="text-[13px] text-muted">Sin tools habilitadas.</p>
              ) : (
                <div className="flex flex-wrap gap-1.5">
                  {agent.tools.map((t) => (
                    <Badge key={t} tone="neutral">
                      {t}
                    </Badge>
                  ))}
                </div>
              )}
            </div>
          </Panel>
        </div>
      </div>

      <Panel>
        <PanelHeader title="Publicaciones" description="Versiones desplegadas y su endpoint." />
        {deployments.length === 0 ? (
          <EmptyState
            icon={PaperPlaneRight}
            title="Sin publicaciones"
            body="Despliega una versión desde el estudio para exponer el endpoint público."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Publicación</th>
                  <th scope="col">Entorno</th>
                  <th scope="col">Estado</th>
                  <th scope="col">Endpoint</th>
                  <th scope="col">Publicada</th>
                </tr>
              </thead>
              <tbody>
                {deployments.map((d) => (
                  <tr key={d.id}>
                    <td className="mono text-xs">{d.slug}</td>
                    <td>
                      <EnvironmentBadge
                        name={environments.find((x) => x.id === d.environment_id)?.name || d.environment_id}
                      />
                    </td>
                    <td>
                      <StatusBadge status={d.status} />
                    </td>
                    <td className="mono text-xs text-muted">{d.endpoint || "—"}</td>
                    <td className="text-muted">{d.deployed_at ? fmtDateTime(d.deployed_at) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}
