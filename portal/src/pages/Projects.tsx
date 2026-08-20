import { FolderPlus, Folders, Trash } from "@phosphor-icons/react";
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

type Project = {
  id: string;
  name: string;
  description: string | null;
  created_at: string;
};

export default function ProjectsPage() {
  const { session } = useAuth();
  const [projects, setProjects] = useState<Project[]>([]);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [showCreate, setShowCreate] = useState(false);

  function load() {
    if (!session) return;
    setLoading(true);
    api<{ projects: Project[] }>("/api/v1/projects", {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then((data) => setProjects(data.projects))
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
      await api("/api/v1/projects", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ name: name.trim(), description: description.trim() || null }),
      });
      setMsg("Proyecto creado.");
      setName("");
      setDescription("");
      setShowCreate(false);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al crear");
    } finally {
      setCreating(false);
    }
  }

  async function remove(projectId: string, projectName: string) {
    if (!session) return;
    setError("");
    setMsg("");
    try {
      await api(`/api/v1/projects/${projectId}`, {
        method: "DELETE",
        token: session.token,
        organizationId: session.organizationId,
      });
      setMsg(`Proyecto "${projectName}" eliminado.`);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al eliminar");
    }
  }

  return (
    <div>
      <PageHeader
        title="Proyectos"
        subtitle="Agrupa knowledge bases, agentes y conectores dentro de tu organización."
      />
      <ErrorInline message={error} />
      <SuccessInline message={msg} />

      <div className="mb-4 flex justify-end">
        <button
          className="btn btn-primary"
          type="button"
          onClick={() => setShowCreate((s) => !s)}
        >
          <FolderPlus size={15} aria-hidden />
          Nuevo proyecto
        </button>
      </div>

      {showCreate && (
        <div className="panel mb-4 border-accent/30">
          <div className="border-b border-border px-5 py-4">
            <h2 className="text-sm font-semibold text-text">Crear proyecto</h2>
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
            <div>
              <button
                className="btn btn-primary"
                type="button"
                disabled={creating || !name.trim()}
                onClick={() => void create()}
              >
                {creating ? <Spinner size={14} /> : <FolderPlus size={15} aria-hidden />}
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
      ) : projects.length === 0 ? (
        <div className="panel">
          <EmptyState
            icon={Folders}
            title="Sin proyectos"
            body="Crea tu primer proyecto para organizar tus recursos."
          />
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          {projects.map((p) => (
            <div key={p.id} className="panel p-5">
              <div className="mb-2 flex items-start justify-between gap-2">
                <h3 className="font-semibold text-text">{p.name}</h3>
                <button
                  type="button"
                  className="btn btn-ghost px-2 py-1.5 text-xs text-danger"
                  aria-label={`Eliminar ${p.name}`}
                  onClick={() => void remove(p.id, p.name)}
                >
                  <Trash size={14} aria-hidden />
                </button>
              </div>
              <p className="mb-3 text-sm text-muted">{p.description || "—"}</p>
              <p className="text-xs text-faint">Creado {fmtDateTime(p.created_at)}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
