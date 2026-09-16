/**
 * Detalle de asistente: el mismo agente visto en operación.
 * Tres secciones: Qué hace / Automatizaciones / Actividad.
 */
import { ArrowLeft, ChatCircleDots, PencilSimple } from "@phosphor-icons/react";
import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { Breadcrumb } from "../components/Breadcrumb";
import { ButtonLink, ErrorInline, PageHeader, Panel, SkeletonBlock } from "../components/ui";
import { AssistantActivity } from "./assistants/AssistantActivity";
import { AssistantAutomations } from "./assistants/AssistantAutomations";
import { AssistantOverview } from "./assistants/AssistantOverview";
import {
  ASSISTANT_TAB_LABEL,
  ASSISTANT_TABS,
  COPY,
  parseAssistantTab,
  type ActivityPayload,
  type AssistantAgent,
  type AssistantTab,
  type AutomationsPayload,
} from "./assistants/assistantCopy";

export default function AssistantDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { session } = useAuth();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const tab = parseAssistantTab(searchParams.get("tab"));
  const [agent, setAgent] = useState<AssistantAgent | null>(null);
  const [automations, setAutomations] = useState<AutomationsPayload | null>(null);
  const [activity, setActivity] = useState<ActivityPayload | null>(null);
  const [permissions, setPermissions] = useState<string[]>([]);
  const [kbNames, setKbNames] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [prompt, setPrompt] = useState("");
  const [openTech, setOpenTech] = useState<number | null>(null);

  const load = useCallback(async () => {
    if (!session || !id) return;
    try {
      const [agentData, automationData, activityData, permissionData, kbData] = await Promise.all([
        api<AssistantAgent>(`/api/v1/agents/${id}`, { token: session.token, organizationId: session.organizationId }),
        api<AutomationsPayload>(`/api/v1/agents/${id}/automations`, { token: session.token, organizationId: session.organizationId }).catch(() => null),
        api<ActivityPayload>(`/api/v1/agents/${id}/activity`, { token: session.token, organizationId: session.organizationId }).catch(() => null),
        api<{ permissions: string[] }>(`/api/v1/agents/${id}/permissions`, { token: session.token, organizationId: session.organizationId }).catch(() => ({ permissions: [] })),
        api<{ knowledge_bases: { id: string; name: string }[] }>("/api/v1/knowledge-bases", { token: session.token, organizationId: session.organizationId }).catch(() => ({ knowledge_bases: [] })),
      ]);
      setAgent(agentData);
      setAutomations(automationData);
      setActivity(activityData);
      setPermissions(permissionData.permissions || []);
      setKbNames(Object.fromEntries((kbData.knowledge_bases || []).map((kb) => [kb.id, kb.name])));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error cargando el asistente");
    } finally {
      setLoading(false);
    }
  }, [session, id]);

  useEffect(() => {
    void load();
  }, [load]);

  function setTab(next: AssistantTab) {
    setSearchParams(
      (prev) => {
        const nextParams = new URLSearchParams(prev);
        if (next === "resumen") nextParams.delete("tab");
        else nextParams.set("tab", next);
        return nextParams;
      },
      { replace: true },
    );
  }

  function addAutomation() {
    const query = new URLSearchParams({ agent: id || "", agent_name: agent?.name || "" });
    if (prompt.trim()) query.set("q", prompt.trim());
    navigate(`/workflows/new/ask?${query.toString()}`);
  }

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
        <ErrorInline message={error || "Asistente no encontrado"} className="mb-0" />
      </Panel>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <Breadcrumb
        items={[
          { label: "Operar", to: "/assistants" },
          { label: "Asistentes", to: "/assistants" },
          { label: agent.name },
        ]}
      />
      <PageHeader
        className="mb-0"
        title={agent.name}
        subtitle={COPY.tagline}
        actions={
          <>
            <ButtonLink to={`/chat?target=agent&id=${agent.id}`} size="sm" leadingIcon={ChatCircleDots}>
              {COPY.playground}
            </ButtonLink>
            <ButtonLink to={`/agents/${agent.id}`} size="sm" leadingIcon={PencilSimple}>
              {COPY.editAgent}
            </ButtonLink>
            <ButtonLink to="/assistants" size="sm" variant="ghost" leadingIcon={ArrowLeft}>
              Volver
            </ButtonLink>
          </>
        }
      />
      <ErrorInline message={error} className="mb-0" />

      <div className="tabs" role="tablist" aria-label="Secciones del asistente">
        {ASSISTANT_TABS.map((key) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={tab === key}
            className="tab"
            data-testid={`assistant-tab-${key}`}
            onClick={() => setTab(key)}
          >
            {ASSISTANT_TAB_LABEL[key]}
          </button>
        ))}
      </div>

      <div role="tabpanel" aria-label={ASSISTANT_TAB_LABEL[tab]}>
        {tab === "resumen" && (
          <AssistantOverview
            agent={agent}
            automations={automations}
            kbNames={kbNames}
            permissions={permissions}
          />
        )}
        {tab === "automatizaciones" && (
          <AssistantAutomations
            agentName={agent.name}
            automations={automations}
            prompt={prompt}
            onPromptChange={setPrompt}
            onAdd={addAutomation}
          />
        )}
        {tab === "actividad" && (
          <AssistantActivity activity={activity} openTech={openTech} onToggleTech={setOpenTech} />
        )}
      </div>
    </div>
  );
}
