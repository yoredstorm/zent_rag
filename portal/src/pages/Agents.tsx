import { Robot, Plus, Trash } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import {
  EmptyState,
  ErrorInline,
  PageHeader,
  SkeletonBlock,
  Spinner,
  SuccessInline,
} from "../components/ui";
import { fmtDateTime } from "../lib/format";

type Agent = {
  id: string;
  name: string;
  description: string | null;
  system_prompt: string | null;
  tools: string[];
  model: string | null;
  is_active: boolean;
  created_at: string;
};

export default function AgentsPage() {
  const { session } = useAuth();
  const [agents, setAgents] = useState<Agent[]>([]);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [model, setModel] = useState("");
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [showCreate, setShowCreate] = useState(false);

  function load() {
    if (!session) return;
    setLoading(true);
    api<{ agents: Agent[] }>("/api/v1/agents", {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then((data) => setAgents(data.agents))
      .catch((err) => setError(err instanceof Error ? err.message : "Error"))
      .finally(() => setLoading(false));
  }

  useEffect(load, [session]);

  async function create() {
    if (!session) return;
    setError("");
    setMsg("");
    setCreating(true);
    try {
      await api("/api/v1/agents", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({
          name: name.trim(),
          description: description.trim() || null,
          model: model.trim() || null,
          tools: ["rag"],
        }),
      });
      setMsg("Agente creado.");
      setName("");
      setDescription("");
      setModel("");
      setShowCreate(false);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al crear");
    } finally {
      setCreating(false);
    }
  }

  async function remove(agentId: string, agentName: string) {
    if (!session) return;
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
        subtitle="Agentes conversacionales de tu organización con prompt y modelo propios."
      />
      <ErrorInline message={error} />
      <SuccessInline message={msg} />

      <div className="mb-4 flex justify-end">
        <button
          className="btn btn-primary"
          type="button"
          onClick={() => setShowCreate((s) => !s)}
        >
          <Plus size={15} aria-hidden />
          Nuevo agente
        </button>
      </div>

      {showCreate && (
        <div className="panel mb-4 border-accent/30">
          <div className="border-b border-border px-5 py-4">
            <h2 className="text-sm font-semibold text-text">Crear agente</h2>
          </div>
          <div className="flex flex-col gap-3 p-5">
            <input
              className="w-full rounded-md border border-border bg-soft px-3 py-2.5 text-sm text-text outline-none focus:border-accent"
              placeholder="Nombre"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            <input
              className="w-full rounded-md border border-border bg-soft px-3 py-2.5 text-sm text-text outline-none focus:border-accent"
              placeholder="Descripción (opcional)"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
            <input
              className="w-full rounded-md border border-border bg-soft px-3 py-2.5 text-sm text-text outline-none focus:border-accent"
              placeholder="Modelo (opcional, ej. gpt-4o-mini)"
              value={model}
              onChange={(e) => setModel(e.target.value)}
            />
            <div>
              <button
                className="btn btn-primary"
                type="button"
                disabled={creating || !name.trim()}
                onClick={() => void create()}
              >
                {creating ? <Spinner size={14} /> : <Plus size={15} aria-hidden />}
                Crear
              </button>
            </div>
          </div>
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
            body="Crea tu primer agente para personalizar la experiencia RAG."
          />
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          {agents.map((a) => (
            <div key={a.id} className="panel p-5">
              <div className="mb-2 flex items-start justify-between gap-2">
                <h3 className="flex items-center gap-2 font-semibold text-text">
                  <Robot size={16} className="text-accent" aria-hidden />
                  {a.name}
                </h3>
                <button
                  type="button"
                  className="btn btn-ghost px-2 py-1.5 text-xs text-danger"
                  aria-label={`Eliminar ${a.name}`}
                  onClick={() => void remove(a.id, a.name)}
                >
                  <Trash size={14} aria-hidden />
                </button>
              </div>
              <p className="mb-3 text-sm text-muted">{a.description || "—"}</p>
              <div className="flex flex-wrap items-center gap-2 text-xs text-faint">
                <span className={`badge ${a.is_active ? "badge-ok" : "badge-muted"}`}>
                  {a.is_active ? "activo" : "inactivo"}
                </span>
                {a.model && <span className="mono">{a.model}</span>}
                <span className="mono">tools: {a.tools.join(", ") || "—"}</span>
                <span>Creado {fmtDateTime(a.created_at)}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
