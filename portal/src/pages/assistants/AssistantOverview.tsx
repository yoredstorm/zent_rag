import { Link } from "react-router-dom";
import { fmtDateTime } from "../../lib/format";
import { ButtonLink, Panel, PanelHeader, StatusBadge } from "../../components/ui";
import {
  COPY,
  HEALTH_STATUS,
  modelHumanLabel,
  toolHumanLabel,
  type AssistantAgent,
  type AutomationsPayload,
} from "./assistantCopy";

export function AssistantOverview({
  agent,
  automations,
  kbNames,
  permissions,
}: {
  agent: AssistantAgent;
  automations: AutomationsPayload | null;
  kbNames: Record<string, string>;
  permissions: string[];
}) {
  const health = automations?.summary.health ?? "idle";
  const kbIds = agent.config.knowledge_base_ids || [];
  const tools = agent.tools || [];

  return (
    <section className="grid gap-4 lg:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]" data-testid="assistant-overview">
      <div className="flex flex-col gap-4">
        <Panel>
          <PanelHeader title="Propósito" />
          <div className="p-4">
            <p className="prose-measure text-[13px] leading-relaxed text-muted">
              {agent.config.purpose || "Sin propósito declarado."}
            </p>
          </div>
        </Panel>

        <Panel>
          <PanelHeader
            title={COPY.watchingTitle}
            description="Cada automatización se dispara cuando ocurre esto."
          />
          <div className="p-4">
            {(automations?.automations.length ?? 0) === 0 ? (
              <p className="text-[13px] text-muted">{COPY.watchingEmpty}</p>
            ) : (
              <ul className="grid gap-2">
                {automations?.automations.map((automation) => (
                  <li
                    key={automation.workflow_id}
                    data-state={automation.status === "active" ? "ready" : "queued"}
                    className="state-rail flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px]"
                  >
                    <Link
                      to={`/workflows/${automation.workflow_id}`}
                      className="font-medium text-text hover:text-accent"
                    >
                      {automation.name}
                    </Link>
                    <span className="text-muted">{automation.when}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </Panel>
      </div>

      <div className="flex flex-col gap-4">
        <Panel>
          <PanelHeader
            title="En operación"
            actions={
              <StatusBadge status={health} label={HEALTH_STATUS[health] ?? health} />
            }
          />
          <dl className="grid gap-2 p-4 text-[13px]">
            <div className="flex items-baseline justify-between gap-3">
              <dt className="text-muted">Automatizaciones activas</dt>
              <dd className="tabular-nums text-text">{automations?.summary.active ?? 0}</dd>
            </div>
            <div className="flex items-baseline justify-between gap-3">
              <dt className="text-muted">Acciones hoy</dt>
              <dd className="tabular-nums text-text">{automations?.summary.actions_today ?? 0}</dd>
            </div>
            <div className="flex items-baseline justify-between gap-3">
              <dt className="text-muted">Última actividad</dt>
              <dd className="text-text">{fmtDateTime(automations?.summary.last_activity)}</dd>
            </div>
            <div className="flex items-baseline justify-between gap-3">
              <dt className="text-muted">Estado del agente</dt>
              <dd className="text-text">{agent.is_active ? "Activo" : "Inactivo"}</dd>
            </div>
          </dl>
        </Panel>

        <Panel>
          <PanelHeader title="Cómo está armado" />
          <div className="grid gap-4 p-4">
            <p className="text-[13px] text-muted">
              Modelo: <span className="text-text">{modelHumanLabel(agent.model)}</span>
            </p>

            <div>
              <p className="eyebrow">{COPY.toolsTitle}</p>
              {tools.length === 0 ? (
                <p className="mt-1 text-[13px] text-muted">{COPY.toolsEmpty}</p>
              ) : (
                <ul className="mt-1.5 flex flex-wrap gap-1.5">
                  {tools.map((tool) => (
                    <li key={tool} className="chip">
                      {toolHumanLabel(tool)}
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <div>
              <p className="eyebrow">{COPY.knowledgeTitle}</p>
              {kbIds.length === 0 ? (
                <p className="mt-1 text-[13px] text-muted">{COPY.knowledgeEmpty}</p>
              ) : (
                <ul className="mt-1 space-y-1 text-[13px] text-muted">
                  {kbIds.map((kbId) => (
                    <li key={kbId}>· {kbNames[kbId] || kbId.slice(0, 8)}</li>
                  ))}
                </ul>
              )}
            </div>

            <div>
              <p className="eyebrow">Permisos</p>
              {permissions.length === 0 ? (
                <p className="mt-1 text-[13px] text-muted">{COPY.permissionsEmpty}</p>
              ) : (
                <ul className="mt-1.5 flex flex-wrap gap-1.5">
                  {permissions.map((permission) => (
                    <li key={permission} className="chip mono">
                      {permission}
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <ButtonLink to={`/agents/${agent.id}`} size="sm" className="justify-self-start">
              {COPY.editAgent}
            </ButtonLink>
          </div>
        </Panel>
      </div>
    </section>
  );
}
