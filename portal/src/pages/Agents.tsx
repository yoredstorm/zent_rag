import { PencilSimple, Play, Plus, Robot, Trash } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import {
  ButtonLink,
  ConfirmDialog,
  EmptyState,
  ErrorInline,
  IconButton,
  PageHeader,
  Panel,
  SkeletonBlock,
  StatusBadge,
  SuccessInline,
  Toolbar,
  ToolbarSpacer,
  WarningInline,
  cn,
} from "../components/ui";
import { fmtDateTime, timeAgo } from "../lib/format";
import { toolHumanLabel } from "./assistants/assistantCopy";

type Agent = {
  id: string;
  name: string;
  description: string | null;
  tools: string[];
  model: string | null;
  is_active: boolean;
  created_at: string;
  config?: { purpose?: string | null; source_ids?: string[] };
};

type Entitlements = { max_agents?: number | null };

/** Resumen operativo real que ya expone el backend por agente. */
type AgentActivity = {
  id: string;
  health: string;
  automations: number;
  active: number;
  actions_today: number;
  last_activity: string | null;
  automation_names: string[];
};

/** Estado real del agente para el activity rail. */
function railState(activity: AgentActivity | undefined, isActive: boolean) {
  if (activity?.health === "needs_attention") return "failed";
  if (activity?.health === "healthy") return "ready";
  if (activity?.health === "paused") return "queued";
  return isActive ? "ready" : "queued";
}

function countLabel(count: number, singular: string, plural: string) {
  return `${count} ${count === 1 ? singular : plural}`;
}

export default function AgentsPage() {
  const { session } = useAuth();
  const [agents, setAgents] = useState<Agent[]>([]);
  const [activityById, setActivityById] = useState<Record<string, AgentActivity>>({});
  const [maxAgents, setMaxAgents] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [pendingDelete, setPendingDelete] = useState<{ id: string; name: string } | null>(null);
  const [deleting, setDeleting] = useState(false);

  function load() {
    if (!session) return;
    setLoading(true);
    Promise.all([
      api<{ agents: Agent[] }>("/api/v1/agents", {
        token: session.token,
        organizationId: session.organizationId,
      }),
      api<{ entitlements: Entitlements }>("/api/v1/billing/entitlements", {
        token: session.token,
        organizationId: session.organizationId,
      }).catch(() => ({ entitlements: {} as Entitlements })),
      api<{ assistants: AgentActivity[] }>("/api/v1/agents/assistants", {
        token: session.token,
        organizationId: session.organizationId,
      }).catch(() => ({ assistants: [] as AgentActivity[] })),
    ])
      .then(([data, ents, operation]) => {
        setAgents(data.agents || []);
        const limit = ents.entitlements?.max_agents;
        setMaxAgents(typeof limit === "number" ? limit : null);
        setActivityById(
          Object.fromEntries((operation.assistants || []).map((item) => [item.id, item])),
        );
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Error"))
      .finally(() => setLoading(false));
  }

  useEffect(load, [session]);

  const atLimit = maxAgents !== null && agents.length >= maxAgents;

  async function confirmRemove() {
    if (!session || !pendingDelete) return;
    setDeleting(true);
    setError("");
    setMsg("");
    try {
      await api(`/api/v1/agents/${pendingDelete.id}`, {
        method: "DELETE",
        token: session.token,
        organizationId: session.organizationId,
      });
      setMsg(`Agente "${pendingDelete.name}" eliminado.`);
      setPendingDelete(null);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al eliminar");
    } finally {
      setDeleting(false);
    }
  }

  return (
    <div>
      <PageHeader
        title="Agentes"
        subtitle="Diles qué hacer, elige fuentes y pruébalos. Siempre puedes volver a editar."
        actions={
          atLimit ? undefined : (
            <ButtonLink to="/agents/new" variant="primary" leadingIcon={Plus}>
              Crear agente
            </ButtonLink>
          )
        }
      />
      <ErrorInline message={error} />
      <SuccessInline message={msg} />

      {atLimit && (
        <WarningInline
          message={`Alcanzaste el límite de agentes de tu plan${
            maxAgents !== null ? ` (${maxAgents})` : ""
          }. Mejora el plan en Facturación para crear más.`}
        />
      )}

      {loading ? (
        <Panel className="p-4">
          <SkeletonBlock rows={4} />
        </Panel>
      ) : agents.length === 0 ? (
        <Panel>
          <EmptyState
            icon={Robot}
            title="Sin agentes"
            body="Crea tu primer agente: propósito, fuentes y una prueba en el mismo sitio."
            action={
              atLimit ? undefined : (
                <ButtonLink to="/agents/new" variant="primary" leadingIcon={Plus}>
                  Crear agente
                </ButtonLink>
              )
            }
          />
        </Panel>
      ) : (
        <>
          <Toolbar className="mb-3">
            <p className="text-xs text-muted tabular-nums">
              {agents.length === 1 ? "1 agente" : `${agents.length} agentes`}
              {maxAgents !== null ? ` de ${maxAgents} del plan` : ""}
            </p>
            <ToolbarSpacer />
            <span className="text-xs text-faint">
              La última actividad viene de las automatizaciones de cada agente.
            </span>
          </Toolbar>

          <ul className="grid gap-3">
            {agents.map((a) => {
              const purpose = a.config?.purpose || a.description;
              const sourceCount = a.config?.source_ids?.length ?? 0;
              const activity = activityById[a.id];
              return (
                <li key={a.id}>
                  <article className="panel">
                    <div className="grid gap-4 p-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,16rem)] lg:items-start">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                          <Link
                            to={`/agents/${a.id}`}
                            className="flex min-w-0 items-center gap-2 text-[15px] font-semibold text-text transition-colors duration-150 hover:text-accent"
                          >
                            <Robot size={16} className="shrink-0 text-accent" aria-hidden />
                            <span className="truncate">{a.name}</span>
                          </Link>
                          <StatusBadge status={a.is_active ? "active" : "inactive"} />
                        </div>
                        <p className="mt-1 text-[13px] leading-relaxed text-muted">
                          {purpose || "Sin propósito todavía."}
                        </p>
                        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-faint">
                          <span>{sourceCount === 1 ? "1 fuente" : `${sourceCount} fuentes`}</span>
                          <span className="mono">{a.model || "zent-default"}</span>
                          <span>Creado {fmtDateTime(a.created_at)}</span>
                        </div>
                        {a.tools.length > 0 && (
                          <ul className="mt-2 flex flex-wrap gap-1.5">
                            {a.tools.map((tool) => (
                              <li key={tool} className="chip">
                                {toolHumanLabel(tool)}
                              </li>
                            ))}
                          </ul>
                        )}
                      </div>

                      <div
                        className={cn(
                          "state-rail rounded-md bg-raised px-3 py-2.5",
                          !activity && "opacity-80",
                        )}
                        data-state={railState(activity, a.is_active)}
                      >
                        <p className="eyebrow">Última actividad</p>
                        <p className="mt-1 text-[13px] text-text">
                          {activity?.last_activity ? timeAgo(activity.last_activity) : "Sin actividad todavía"}
                        </p>
                        <p className="mt-0.5 text-xs leading-relaxed text-faint">
                          {activity
                            ? `${countLabel(activity.actions_today, "acción", "acciones")} hoy · ${countLabel(
                                activity.active,
                                "automatización activa",
                                "automatizaciones activas",
                              )}`
                            : "Sin automatizaciones asociadas"}
                        </p>
                      </div>
                    </div>

                    <div className="panel-footer">
                      <span className="text-xs text-faint">
                        {activity && activity.automation_names.length > 0
                          ? `Vigila: ${activity.automation_names.join(" · ")}`
                          : "Sin automatizaciones todavía"}
                      </span>
                      <div className="flex flex-wrap items-center gap-2">
                        <ButtonLink to={`/agents/${a.id}`} size="sm" variant="secondary" leadingIcon={PencilSimple}>
                          Editar
                        </ButtonLink>
                        <ButtonLink
                          to={`/agents/${a.id}?panel=test`}
                          size="sm"
                          leadingIcon={Play}
                        >
                          Probar
                        </ButtonLink>
                        <IconButton
                          label={`Eliminar ${a.name}`}
                          icon={Trash}
                          variant="ghost"
                          onClick={() => setPendingDelete({ id: a.id, name: a.name })}
                        />
                      </div>
                    </div>
                  </article>
                </li>
              );
            })}
          </ul>
        </>
      )}

      <ConfirmDialog
        open={pendingDelete !== null}
        onOpenChange={(open) => {
          if (!open) setPendingDelete(null);
        }}
        title={pendingDelete ? `Eliminar el agente "${pendingDelete.name}"` : "Eliminar agente"}
        body="Se elimina el agente y sus publicaciones dejan de atender. Esta acción no se puede deshacer."
        confirmLabel="Eliminar"
        loading={deleting}
        onConfirm={() => void confirmRemove()}
      />
    </div>
  );
}
