import { Link } from "react-router-dom";
import { fmtDateTime } from "../../lib/format";
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
    <section className="grid gap-4 md:grid-cols-2" data-testid="assistant-overview">
      <div className="panel space-y-2 p-4">
        <h2 className="text-sm font-semibold text-text">Propósito</h2>
        <p className="text-xs text-muted">{agent.config.purpose || "Sin propósito declarado."}</p>
        <h3 className="pt-1 text-[11px] font-medium text-text">{COPY.watchingTitle}</h3>
        <ul className="space-y-1 text-[11px] text-muted">
          {(automations?.automations.length ?? 0) === 0 && <li>{COPY.watchingEmpty}</li>}
          {automations?.automations.map((automation) => (
            <li key={automation.workflow_id}>· {automation.when}</li>
          ))}
        </ul>
      </div>
      <div className="panel space-y-2 p-4">
        <h2 className="text-sm font-semibold text-text">Estado</h2>
        <p className="text-xs text-muted">Salud: {HEALTH_STATUS[health] ?? health}</p>
        <p className="text-xs text-muted">{automations?.summary.active ?? 0} automatizaciones activas</p>
        <p className="text-xs text-muted">Acciones hoy: {automations?.summary.actions_today ?? 0}</p>
        <p className="text-xs text-muted">
          Última actividad: {fmtDateTime(automations?.summary.last_activity)}
        </p>
      </div>
      <div className="panel space-y-3 p-4 md:col-span-2">
        <h2 className="text-sm font-semibold text-text">Cómo está armado</h2>
        <p className="text-xs text-muted">Modelo: {modelHumanLabel(agent.model)}</p>
        <div>
          <h3 className="text-[11px] font-medium text-text">{COPY.toolsTitle}</h3>
          {tools.length === 0 ? (
            <p className="text-[11px] text-muted">{COPY.toolsEmpty}</p>
          ) : (
            <ul className="mt-1 flex flex-wrap gap-1.5">
              {tools.map((tool) => (
                <li key={tool} className="rounded-full border border-border px-2 py-0.5 text-[10px] text-muted">
                  {toolHumanLabel(tool)}
                </li>
              ))}
            </ul>
          )}
        </div>
        <div>
          <h3 className="text-[11px] font-medium text-text">{COPY.knowledgeTitle}</h3>
          {kbIds.length === 0 ? (
            <p className="text-[11px] text-muted">{COPY.knowledgeEmpty}</p>
          ) : (
            <ul className="mt-1 space-y-1 text-[11px] text-muted">
              {kbIds.map((kbId) => (
                <li key={kbId}>· {kbNames[kbId] || kbId.slice(0, 8)}</li>
              ))}
            </ul>
          )}
        </div>
        <div>
          <h3 className="text-[11px] font-medium text-text">Permisos</h3>
          {permissions.length === 0 ? (
            <p className="text-[11px] text-muted">{COPY.permissionsEmpty}</p>
          ) : (
            <ul className="mt-1 flex flex-wrap gap-1.5">
              {permissions.map((permission) => (
                <li key={permission} className="rounded-full border border-border px-2 py-0.5 text-[10px] text-muted">
                  {permission}
                </li>
              ))}
            </ul>
          )}
        </div>
        <p className="text-xs text-muted">{agent.is_active ? "Activo" : "Inactivo"}</p>
        <Link to={`/agents/${agent.id}`} className="text-xs font-medium text-accent hover:underline">
          {COPY.editAgent}
        </Link>
      </div>
    </section>
  );
}
