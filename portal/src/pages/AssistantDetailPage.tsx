/**
 * Detalle de asistente: el mismo agente visto en operación.
 * Tres secciones: Qué hace / Automatizaciones / Actividad.
 */
import { ArrowLeft, ChatCircleDots, PencilSimple } from "@phosphor-icons/react";
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { Breadcrumb } from "../components/Breadcrumb";
import { ErrorInline, PageHeader, SkeletonBlock } from "../components/ui";
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

  if (loading) return <div className="panel p-5"><SkeletonBlock rows={6} /></div>;
  if (error || !agent) return <div className="panel p-5"><ErrorInline message={error || "Asistente no encontrado"} /></div>;

  return (
    <div className="space-y-4">
      <Breadcrumb
        items={[
          { label: "Operar", to: "/assistants" },
          { label: "Asistentes", to: "/assistants" },
          { label: agent.name },
        ]}
      />
      <PageHeader
        title={agent.name}
        subtitle={COPY.tagline}
        actions={
          <div className="flex flex-wrap gap-2">
            <Link
              to={`/chat?target=agent&id=${agent.id}`}
              className="btn btn-secondary min-h-11 text-xs"
            >
              <ChatCircleDots size={14} aria-hidden className="mr-1" /> {COPY.playground}
            </Link>
            <Link to={`/agents/${agent.id}`} className="btn btn-secondary min-h-11 text-xs">
              <PencilSimple size={14} aria-hidden className="mr-1" /> {COPY.editAgent}
            </Link>
            <Link to="/assistants" className="btn btn-ghost min-h-11 text-xs">
              <ArrowLeft size={14} aria-hidden className="mr-1" /> Volver
            </Link>
          </div>
        }
      />
      <ErrorInline message={error} />

      <div className="flex flex-wrap gap-1 rounded-md border border-border p-0.5" role="tablist" aria-label="Secciones del asistente">
        {ASSISTANT_TABS.map((key) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={tab === key}
            className={`rounded px-2.5 py-1.5 text-[11px] ${tab === key ? "bg-accent/15 font-medium text-text" : "text-faint hover:text-muted"}`}
            data-testid={`assistant-tab-${key}`}
            onClick={() => setTab(key)}
          >
            {ASSISTANT_TAB_LABEL[key]}
          </button>
        ))}
      </div>

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
  );
}
