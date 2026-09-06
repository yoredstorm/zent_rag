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

      {items.length > 0 && <WorkspaceTasksPanel workspace={items[0]} session={session} />}
    </div>
  );
}

/** FASE 03 (S15): tasks + actividad del workspace (foundation colaborativo). */
function WorkspaceTasksPanel({
  workspace,
  session,
}: {
  workspace: { id: string; name: string };
  session: ReturnType<typeof useAuth>["session"];
}) {
  const [tasks, setTasks] = useState<
    { id: string; title: string; status: string; agent_id: string | null; created_at: string }[]
  >([]);
  const [activity, setActivity] = useState<
    { id: string; event_type: string; detail: string | null; created_at: string }[]
  >([]);
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function load() {
    if (!session) return;
    try {
      const [t, a] = await Promise.all([
        api<{ tasks: typeof tasks }>(`/api/v1/workspaces/${workspace.id}/tasks`, {
          token: session.token,
          organizationId: session.organizationId,
        }).catch(() => ({ tasks: [] })),
        api<{ activity: typeof activity }>(`/api/v1/workspaces/${workspace.id}/activity`, {
          token: session.token,
          organizationId: session.organizationId,
        }).catch(() => ({ activity: [] })),
      ]);
      setTasks(t.tasks || []);
      setActivity(a.activity || []);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Error");
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspace.id, session]);

  async function create() {
    if (!session || !title.trim()) return;
    setBusy(true);
    setErr("");
    try {
      await api(`/api/v1/workspaces/${workspace.id}/tasks`, {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ title: title.trim() }),
      });
      setTitle("");
      await load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy(false);
    }
  }

  async function setStatus(id: string, status: string) {
    if (!session) return;
    try {
      await api(`/api/v1/workspaces/${workspace.id}/tasks/${id}`, {
        method: "PUT",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ status }),
      });
      await load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Error");
    }
  }

  return (
    <section className="panel mt-4 p-5">
      <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text">
        <SquaresFour size={15} aria-hidden /> Tasks · {workspace.name}
      </h2>
      <p className="mb-3 text-xs text-muted">
        Foundation de colaboración centrada en flujos de IA (humanos y agentes como asignables).
      </p>
      {err && <p className="mb-2 text-xs text-danger" role="alert">{err}</p>}
      <div className="mb-3 flex flex-wrap gap-2">
        <input
          className="min-w-56 flex-1 rounded-md border border-border bg-soft px-3 py-2 text-sm"
          placeholder="Nueva tarea (ej. collect metrics)"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void create();
          }}
        />
        <button type="button" className="btn btn-secondary min-h-10" disabled={busy || !title.trim()} onClick={() => void create()}>
          Crear
        </button>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <div>
          <h3 className="mb-1 text-xs font-semibold text-text">Tareas</h3>
          <div className="space-y-1">
            {tasks.map((t) => (
              <div key={t.id} className="flex items-center justify-between gap-2 rounded-md bg-soft px-2.5 py-1.5 text-[12px]">
                <span className="truncate text-text">{t.title}</span>
                {t.agent_id && <span className="mono text-faint">agente</span>}
                <select
                  className="rounded-md border border-border bg-bg px-1 py-0.5 text-[11px]"
                  value={t.status}
                  onChange={(e) => void setStatus(t.id, e.target.value)}
                >
                  <option value="todo">todo</option>
                  <option value="in_progress">in_progress</option>
                  <option value="done">done</option>
                </select>
              </div>
            ))}
            {tasks.length === 0 && <p className="py-2 text-center text-xs text-faint">Sin tareas.</p>}
          </div>
        </div>
        <div>
          <h3 className="mb-1 text-xs font-semibold text-text">Actividad</h3>
          <div className="max-h-56 space-y-1 overflow-auto">
            {activity.map((a) => (
              <div key={a.id} className="rounded-md bg-soft px-2.5 py-1.5 text-[11px]">
                <span className="text-text">{a.event_type}</span>
                <span className="block truncate text-faint">{a.detail}</span>
                <span className="text-faint">{a.created_at?.slice(0, 16)}</span>
              </div>
            ))}
            {activity.length === 0 && <p className="py-2 text-center text-xs text-faint">Sin actividad.</p>}
          </div>
        </div>
      </div>
    </section>
  );
}