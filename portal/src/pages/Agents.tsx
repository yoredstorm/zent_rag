import { PencilSimple, Play, Plus, Robot, Trash } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import {
  EmptyState,
  ErrorInline,
  PageHeader,
  SkeletonBlock,
  SuccessInline,
} from "../components/ui";
import { fmtDateTime } from "../lib/format";

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

export default function AgentsPage() {
  const { session } = useAuth();
  const navigate = useNavigate();
  const [agents, setAgents] = useState<Agent[]>([]);
  const [maxAgents, setMaxAgents] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");

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
    ])
      .then(([data, ents]) => {
        setAgents(data.agents);
        const limit = ents.entitlements?.max_agents;
        setMaxAgents(typeof limit === "number" ? limit : null);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Error"))
      .finally(() => setLoading(false));
  }

  useEffect(load, [session]);

  const atLimit = maxAgents !== null && agents.length >= maxAgents;

  async function remove(agentId: string, agentName: string) {
    if (!session) return;
    if (!window.confirm(`¿Eliminar el agente "${agentName}"?`)) return;
    setError("");
    setMsg("");
    try {
      await api(`/api/v1/agents/${agentId}`, {
        method: "DELETE",
        token: session.token,
        organizationId: session.organizationId,
      });
      setMsg(`Agente "${agentName}" eliminado.`);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al eliminar");
    }
  }

  return (
    <div>
      <PageHeader
        title="Agentes"
        subtitle="Diles qué hacer, elige fuentes y pruébalos. Siempre puedes volver a editar."
        actions={
          atLimit ? undefined : (
            <Link to="/agents/new" className="btn btn-primary min-h-11">
              <Plus size={15} aria-hidden />
              Crear agente
            </Link>
          )
        }
      />
      <ErrorInline message={error} />
      <SuccessInline message={msg} />

      {atLimit && (
        <div
          className="mb-4 rounded-md border border-warn/30 bg-warn-soft px-4 py-3 text-sm text-text"
          role="status"
        >
          Alcanzaste el límite de agentes de tu plan
          {maxAgents !== null ? ` (${maxAgents})` : ""}. Mejora el plan en Facturación
          para crear más.
        </div>
      )}

      {loading ? (
        <div className="panel p-5">
          <SkeletonBlock rows={4} />
        </div>
      ) : agents.length === 0 ? (
        <div className="panel">
          <EmptyState
            icon={Robot}
            title="Sin agentes"
            body="Crea tu primer agente: propósito, fuentes y una prueba en el mismo sitio."
            action={
              atLimit ? undefined : (
                <Link to="/agents/new" className="btn btn-primary min-h-11">
                  <Plus size={15} aria-hidden />
                  Crear agente
                </Link>
              )
            }
          />
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          {agents.map((a) => {
            const purpose = a.config?.purpose || a.description;
            const sourceCount = a.config?.source_ids?.length ?? 0;
            return (
              <div
                key={a.id}
                className="panel cursor-pointer p-5"
                onClick={(event) => {
                  if ((event.target as HTMLElement).closest("a, button")) return;
                  navigate(`/agents/${a.id}`);
                }}
              >
                <div className="mb-2 flex items-start justify-between gap-2">
                  <Link
                    to={`/agents/${a.id}`}
                    className="flex items-center gap-2 font-semibold text-text hover:text-accent"
                  >
                    <Robot size={16} className="text-accent" aria-hidden />
                    {a.name}
                  </Link>
                  <button
                    type="button"
                    className="btn btn-ghost min-h-11 px-2 py-1.5 text-xs text-danger"
                    aria-label={`Eliminar ${a.name}`}
                    onClick={() => void remove(a.id, a.name)}
                  >
                    <Trash size={14} aria-hidden />
                  </button>
                </div>
                <p className="mb-3 text-sm text-muted">{purpose || "Sin propósito aún"}</p>
                <div className="mb-3 flex flex-wrap items-center gap-2 text-xs text-faint">
                  <span className={`badge ${a.is_active ? "badge-ok" : "badge-muted"}`}>
                    {a.is_active ? "activo" : "inactivo"}
                  </span>
                  <span>
                    {sourceCount === 1 ? "1 fuente" : `${sourceCount} fuentes`}
                  </span>
                  {a.model && <span className="mono">{a.model}</span>}
                  <span>Creado {fmtDateTime(a.created_at)}</span>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Link to={`/agents/${a.id}`} className="btn btn-secondary min-h-11">
                    <PencilSimple size={14} aria-hidden />
                    Editar
                  </Link>
                  <Link to={`/agents/${a.id}?panel=test`} className="btn btn-secondary min-h-11">
                    <Play size={14} aria-hidden />
                    Probar
                  </Link>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
