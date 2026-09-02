import { SquaresFour } from "@phosphor-icons/react";
import { FormEvent, useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import {
  EmptyState,
  ErrorInline,
  PageHeader,
  SkeletonBlock,
  StatusBadge,
  SuccessInline,
} from "../components/ui";

type Workspace = {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  status: string;
  created_at: string;
  counts: { agents: number; kbs: number; connectors: number };
};

export default function Workspaces() {
  const { session } = useAuth();
  const [items, setItems] = useState<Workspace[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    if (!session) return;
    try {
      const data = await api<{ workspaces: Workspace[] }>("/api/v1/workspaces", {
        token: session.token,
        organizationId: session.organizationId,
      });
      setItems(data.workspaces || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  async function create(e: FormEvent) {
    e.preventDefault();
    if (!session || !name.trim()) return;
    setBusy(true);
    setError("");
    setMsg("");
    try {
      await api("/api/v1/workspaces", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ name: name.trim(), description: description.trim() || null }),
      });
      setMsg("Workspace creado.");
      setName("");
      setDescription("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setBusy(false);
    }
  }

  async function archive(id: string, slug: string) {
    if (!session || !window.confirm(`¿Archivar el workspace "${slug}"?`)) return;
    setError("");
    try {
      await api(`/api/v1/workspaces/${id}`, {
        method: "DELETE",
        token: session.token,
        organizationId: session.organizationId,
      });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    }
  }

  return (
    <div>
      <PageHeader
        title="Workspaces"
        subtitle="Espacios de trabajo: agrupa agentes, knowledge bases y conectores."
      />
      {msg && <SuccessInline>{msg}</SuccessInline>}
      {error && <ErrorInline>{error}</ErrorInline>}
      <form className="panel mb-6" onSubmit={(e) => void create(e)}>
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-1 flex-col gap-1 text-xs text-muted">
            Nombre
            <input
              className="input"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Production AI"
              required
            />
          </label>
          <label className="flex flex-1 flex-col gap-1 text-xs text-muted">
            Descripción
            <input
              className="input"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Agentes de producción"
            />
          </label>
          <button type="submit" className="btn btn-primary min-h-10" disabled={busy || !name.trim()}>
            {busy ? "Creando…" : "Crear workspace"}
          </button>
        </div>
      </form>
      {loading ? (
        <SkeletonBlock className="h-40" />
      ) : items.length === 0 ? (
        <div className="panel">
          <EmptyState icon={SquaresFour} title="Sin workspaces" body="Crea tu primer workspace." />
        </div>
      ) : (
        <div className="panel overflow-x-auto">
          <table className="table">
            <thead>
              <tr>
                <th>Workspace</th>
                <th>Agentes</th>
                <th>KBs</th>
                <th>Connectors</th>
                <th>Estado</th>
                <th>Acciones</th>
              </tr>
            </thead>
            <tbody>
              {items.map((w) => (
                <tr key={w.id}>
                  <td>
                    <p className="text-sm font-medium text-text">{w.name}</p>
                    <p className="font-mono text-xs text-faint">{w.slug}</p>
                    {w.description && <p className="text-xs text-muted">{w.description}</p>}
                  </td>
                  <td className="text-sm text-muted">{w.counts.agents}</td>
                  <td className="text-sm text-muted">{w.counts.kbs}</td>
                  <td className="text-sm text-muted">{w.counts.connectors}</td>
                  <td>
                    <StatusBadge status={w.status} />
                  </td>
                  <td>
                    {w.status === "active" && w.slug !== "default" && (
                      <button
                        type="button"
                        className="btn btn-ghost min-h-8 text-xs"
                        onClick={() => void archive(w.id, w.slug)}
                      >
                        Archivar
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}