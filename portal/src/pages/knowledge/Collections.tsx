import {
  Books,
  Database,
  Plus,
  Trash,
  type Icon,
} from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { api } from "../../api";
import { useAuth } from "../../auth";
import {
  EmptyState,
  ErrorInline,
  PageHeader,
  SkeletonBlock,
  Spinner,
  SuccessInline,
} from "../../components/ui";
import { fmtDateTime } from "../../lib/format";

type KB = {
  id: string;
  name: string;
  description: string | null;
  project_id: string | null;
  status: string;
  embedding_model: string | null;
  created_at: string;
};

function KBRow({
  kb,
  onDelete,
}: {
  kb: KB;
  onDelete: (id: string, name: string) => void;
}) {
  const IconEl: Icon = kb.status === "active" ? Database : Books;
  return (
    <div className="panel p-5">
      <div className="mb-2 flex items-start justify-between gap-2">
        <h3 className="flex items-center gap-2 font-semibold text-text">
          <IconEl size={16} className="text-accent" aria-hidden />
          {kb.name}
        </h3>
        <button
          type="button"
          className="btn btn-ghost px-2 py-1.5 text-xs text-danger"
          aria-label={`Eliminar ${kb.name}`}
          onClick={() => onDelete(kb.id, kb.name)}
        >
          <Trash size={14} aria-hidden />
        </button>
      </div>
      <p className="mb-3 text-sm text-muted">{kb.description || "—"}</p>
      <div className="flex flex-wrap items-center gap-2 text-xs text-faint">
        <span className="badge badge-ok">{kb.status}</span>
        {kb.embedding_model && <span className="mono">{kb.embedding_model}</span>}
        <span>Creada {fmtDateTime(kb.created_at)}</span>
      </div>
    </div>
  );
}

export default function KnowledgeBasesPage() {
  const { session } = useAuth();
  const [kbs, setKbs] = useState<KB[]>([]);
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
    api<{ knowledge_bases: KB[] }>("/api/v1/knowledge-bases", {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then((data) => setKbs(data.knowledge_bases))
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
      await api("/api/v1/knowledge-bases", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ name: name.trim(), description: description.trim() || null }),
      });
      setMsg("Colección creada.");
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

  async function remove(kbId: string, kbName: string) {
    if (!session) return;
    setError("");
    setMsg("");
    try {
      await api(`/api/v1/knowledge-bases/${kbId}`, {
        method: "DELETE",
        token: session.token,
        organizationId: session.organizationId,
      });
      setMsg(`Knowledge base "${kbName}" eliminada (incluye sus vectores).`);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al eliminar");
    }
  }

  return (
    <div>
      <PageHeader
        title="Colecciones"
        subtitle="Bases de conocimiento vectorizadas. Al eliminarlas se purgan sus vectores de Qdrant (solo los de tu organización)."
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
          Nueva colección
        </button>
      </div>

      {showCreate && (
        <div className="panel mb-4 border-accent/30">
          <div className="border-b border-border px-5 py-4">
            <h2 className="text-sm font-semibold text-text">Crear colección</h2>
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
      ) : kbs.length === 0 ? (
        <div className="panel">
          <EmptyState
            icon={Database}
            title="Sin colecciones"
            body="Crea tu primera colección para organizar tus datos."
          />
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          {kbs.map((kb) => (
            <KBRow key={kb.id} kb={kb} onDelete={remove} />
          ))}
        </div>
      )}
    </div>
  );
}
