/**
 * Detalle de asistente — tabs Resumen / Automatizaciones / Actividad /
 * Conocimiento / Permisos / Ajustes (misión §23-§28).
 *
 * La actividad se muestra en lenguaje de negocio; los ids, latencias y
 * correlación viven detrás de "Ver detalles técnicos".
 */
import { ArrowLeft, CaretDown, CaretRight, Gear, Plus, WarningCircle } from "@phosphor-icons/react";
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { Breadcrumb } from "../components/Breadcrumb";
import { ErrorInline, PageHeader, SkeletonBlock } from "../components/ui";

type Agent = {
  id: string;
  name: string;
  description: string | null;
  status: string;
  is_active: boolean;
  model: string | null;
  tools: string[];
  config: { purpose?: string | null; knowledge_base_ids?: string[] };
};

type Automation = {
  workflow_id: string;
  name: string;
  status: string;
  when: string;
  runs_7d: number;
  failed_runs: number;
  success_rate: number | null;
  last_activity: string | null;
};

type Automations = {
  summary: {
    automations: number;
    active: number;
    actions_today: number;
    last_activity: string | null;
    health: string;
  };
  automations: Automation[];
};

type ActivityItem = {
  kind: string;
  title: string;
  detail: string | null;
  at: string;
  status: string;
  tech: Record<string, unknown>;
};

type Activity = {
  items: ActivityItem[];
  run_count: number;
  automation_count: number;
};

const TABS = ["resumen", "automatizaciones", "actividad", "conocimiento", "permisos", "ajustes"] as const;
type TabKey = (typeof TABS)[number];

const TAB_LABEL: Record<TabKey, string> = {
  resumen: "Resumen",
  automatizaciones: "Automatizaciones",
  actividad: "Actividad",
  conocimiento: "Conocimiento",
  permisos: "Permisos",
  ajustes: "Ajustes",
};

export default function AssistantDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { session } = useAuth();
  const navigate = useNavigate();
  const [tab, setTab] = useState<TabKey>("resumen");
  const [agent, setAgent] = useState<Agent | null>(null);
  const [automations, setAutomations] = useState<Automations | null>(null);
  const [activity, setActivity] = useState<Activity | null>(null);
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
        api<Agent>(`/api/v1/agents/${id}`, { token: session.token, organizationId: session.organizationId }),
        api<Automations>(`/api/v1/agents/${id}/automations`, { token: session.token, organizationId: session.organizationId }).catch(() => null),
        api<Activity>(`/api/v1/agents/${id}/activity`, { token: session.token, organizationId: session.organizationId }).catch(() => null),
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

  function addAutomation() {
    const query = new URLSearchParams({ agent: id || "", agent_name: agent?.name || "" });
    if (prompt.trim()) query.set("q", prompt.trim());
    navigate(`/workflows/new/ask?${query.toString()}`);
  }

  if (loading) return <div className="panel p-5"><SkeletonBlock rows={6} /></div>;
  if (error || !agent) return <div className="panel p-5"><ErrorInline message={error || "Asistente no encontrado"} /></div>;

  const health = automations?.summary.health ?? "idle";
  const kbList = (agent.config.knowledge_base_ids || []).map((kbId) => kbNames[kbId] || kbId.slice(0, 8));

  return (
    <div className="space-y-4">
      <Breadcrumb items={[{ label: "Asistentes", to: "/assistants" }, { label: agent.name }]} />
      <PageHeader
        title={agent.name}
        subtitle={agent.description || "Asistente activo de Zent."}
        actions={
          <div className="flex flex-wrap gap-2">
            <Link to={`/agents/${agent.id}`} className="btn btn-secondary min-h-11 text-xs">
              <Gear size={14} aria-hidden className="mr-1" /> Abrir Agent Studio
            </Link>
            <Link to="/assistants" className="btn btn-ghost min-h-11 text-xs">
              <ArrowLeft size={14} aria-hidden className="mr-1" /> Volver
            </Link>
          </div>
        }
      />
      <ErrorInline message={error} />

      <div className="flex flex-wrap gap-1 rounded-md border border-border p-0.5" role="tablist" aria-label="Secciones del asistente">
        {TABS.map((key) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={tab === key}
            className={`rounded px-2.5 py-1.5 text-[11px] ${tab === key ? "bg-accent/15 font-medium text-text" : "text-faint hover:text-muted"}`}
            data-testid={`assistant-tab-${key}`}
            onClick={() => setTab(key)}
          >
            {TAB_LABEL[key]}
          </button>
        ))}
      </div>

      {tab === "resumen" && (
        <section className="grid gap-4 md:grid-cols-2" data-testid="assistant-overview">
          <div className="panel space-y-2 p-4">
            <h2 className="text-sm font-semibold text-text">Propósito</h2>
            <p className="text-xs text-muted">{agent.config.purpose || "Sin propósito declarado."}</p>
            <h3 className="pt-1 text-[11px] font-medium text-text">Fuentes que vigila</h3>
            <ul className="space-y-1 text-[11px] text-muted">
              {(automations?.automations.length ?? 0) === 0 && <li>Sin automatizaciones todavía.</li>}
              {automations?.automations.map((automation) => (
                <li key={automation.workflow_id}>· {automation.when}</li>
              ))}
            </ul>
          </div>
          <div className="panel space-y-2 p-4">
            <h2 className="text-sm font-semibold text-text">Estado</h2>
            <p className="text-xs text-muted">
              Salud: {health === "healthy" ? "Saludable" : health === "needs_attention" ? "Necesita atención" : health === "paused" ? "Pausado" : "Sin automatizaciones"}
            </p>
            <p className="text-xs text-muted">{automations?.summary.active ?? 0} automatizaciones activas</p>
            <p className="text-xs text-muted">Acciones hoy: {automations?.summary.actions_today ?? 0}</p>
            <p className="text-xs text-muted">
              Última actividad: {automations?.summary.last_activity ? new Date(automations.summary.last_activity).toLocaleString() : "—"}
            </p>
            <h3 className="pt-1 text-[11px] font-medium text-text">Capacidades</h3>
            <p className="text-[11px] text-muted">Modelo: {agent.model || "zent-default"} · Herramientas: {(agent.tools || []).join(", ") || "—"}</p>
          </div>
        </section>
      )}

      {tab === "automatizaciones" && (
        <section className="space-y-3" data-testid="assistant-automations">
          <div className="panel space-y-2 p-4">
            <h2 className="text-sm font-semibold text-text">¿Qué quieres que este asistente haga automáticamente?</h2>
            <textarea
              className="min-h-20 w-full resize-y rounded-md border border-border bg-soft px-3 py-2 text-xs"
              placeholder={'Cuando un producto se quede sin stock, analiza su nivel de ventas y avisa al gerente.'}
              value={prompt}
              data-testid="assistant-automation-prompt"
              onChange={(e) => setPrompt(e.target.value)}
            />
            <p className="text-[10px] text-faint">
              El copiloto propondrá el flujo y lo asociará a {agent.name}. Si no necesita razonamiento,
              te avisará que puede funcionar sin IA (costo casi cero).
            </p>
            <button
              type="button"
              className="btn btn-primary min-h-9 gap-1.5 text-xs"
              disabled={prompt.trim().length < 8}
              data-testid="assistant-add-automation"
              onClick={addAutomation}
            >
              <Plus size={13} aria-hidden /> Agregar automatización
            </button>
          </div>
          {(automations?.automations.length ?? 0) === 0 ? (
            <p className="panel p-4 text-xs text-muted">Aún no hay automatizaciones para este asistente.</p>
          ) : (
            <ul className="space-y-2">
              {automations?.automations.map((automation) => (
                <li key={automation.workflow_id} className="panel flex flex-wrap items-center gap-2 p-3 text-[11px]">
                  <Link to={`/workflows/${automation.workflow_id}`} className="font-medium text-text hover:text-accent">
                    {automation.name}
                  </Link>
                  <span className={`badge ${automation.status === "active" ? "badge-ok" : "badge-muted"}`}>{automation.status}</span>
                  <span className="text-muted">Cuando {automation.when.toLowerCase()}</span>
                  <span className="ml-auto text-faint">
                    {automation.runs_7d} ejecuciones · {automation.success_rate ?? "—"}% éxito
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {tab === "actividad" && (
        <section className="panel space-y-2 p-4" data-testid="assistant-activity">
          <h2 className="text-sm font-semibold text-text">Actividad reciente</h2>
          {(activity?.items.length ?? 0) === 0 && (
            <p className="text-xs text-muted">Sin actividad todavía. Cuando una automatización se active, verás aquí qué pasó.</p>
          )}
          <ul className="space-y-2">
            {activity?.items.map((item, index) => (
              <li key={`${item.at}-${index}`} className="rounded-md border border-border/60 bg-soft/40 p-2.5">
                <div className="flex flex-wrap items-baseline gap-2">
                  <span className="text-[10px] text-faint">{new Date(item.at).toLocaleString()}</span>
                  {item.status === "failed" && <WarningCircle size={12} className="text-danger" aria-hidden />}
                  <span className="text-[11px] font-medium text-text">{item.title}</span>
                </div>
                {item.detail && <p className="mt-0.5 text-[11px] text-muted">{item.detail}</p>}
                <button
                  type="button"
                  className="btn btn-ghost mt-1 min-h-5 gap-1 px-1 text-[9px] text-faint"
                  data-testid={`assistant-tech-${index}`}
                  onClick={() => setOpenTech(openTech === index ? null : index)}
                >
                  {openTech === index ? <CaretDown size={10} /> : <CaretRight size={10} />} Ver detalles técnicos
                </button>
                {openTech === index && (
                  <dl className="mt-1 grid grid-cols-2 gap-x-3 gap-y-0.5 rounded border border-border bg-surface p-2 font-mono text-[9px] text-muted">
                    {Object.entries(item.tech).map(([key, value]) => (
                      <div key={key} className="contents">
                        <dt className="text-faint">{key}</dt>
                        <dd className="truncate">{String(value ?? "—")}</dd>
                      </div>
                    ))}
                  </dl>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      {tab === "conocimiento" && (
        <section className="panel space-y-2 p-4" data-testid="assistant-knowledge">
          <h2 className="text-sm font-semibold text-text">Conocimiento del asistente</h2>
          {kbList.length === 0 ? (
            <p className="text-xs text-muted">Este asistente no tiene bases de conocimiento asociadas.</p>
          ) : (
            <ul className="space-y-1 text-xs text-muted">
              {kbList.map((name) => <li key={name}>· {name}</li>)}
            </ul>
          )}
        </section>
      )}

      {tab === "permisos" && (
        <section className="panel space-y-2 p-4" data-testid="assistant-permissions">
          <h2 className="text-sm font-semibold text-text">Permisos delegados</h2>
          {permissions.length === 0 ? (
            <p className="text-xs text-muted">Sin permisos explícitos: el asistente usa solo las capacidades de sus automatizaciones.</p>
          ) : (
            <ul className="flex flex-wrap gap-1.5">
              {permissions.map((permission) => (
                <li key={permission} className="rounded-full border border-border px-2 py-0.5 text-[10px] text-muted">{permission}</li>
              ))}
            </ul>
          )}
        </section>
      )}

      {tab === "ajustes" && (
        <section className="panel space-y-2 p-4" data-testid="assistant-settings">
          <h2 className="text-sm font-semibold text-text">Ajustes</h2>
          <p className="text-xs text-muted">Estado del agente: {agent.is_active ? "activo" : "inactivo"} · {agent.status}</p>
          <p className="text-xs text-muted">
            La configuración avanzada (modelo, prompt, herramientas) vive en el Agent Studio.
          </p>
          <Link to={`/agents/${agent.id}`} className="btn btn-secondary min-h-9 w-fit text-xs">
            <Gear size={13} aria-hidden className="mr-1" /> Editar en Agent Studio
          </Link>
        </section>
      )}
    </div>
  );
}
