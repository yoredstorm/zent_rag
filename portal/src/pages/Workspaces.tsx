import { Archive, Plus, SquaresFour, X } from "@phosphor-icons/react";
import { FormEvent, useEffect, useState } from "react";
import { api, type Session } from "../api";
import { useAuth } from "../auth";
import {
  Badge,
  Button,
  ConfirmDialog,
  DataTable,
  Drawer,
  EmptyState,
  ErrorInline,
  Field,
  FormActions,
  IconButton,
  Input,
  PageHeader,
  Panel,
  PanelHeader,
  Select,
  StatusBadge,
  SuccessInline,
  type Column,
} from "../components/ui";
import { fmtDateTime } from "../lib/format";

type Workspace = {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  status: string;
  created_at: string;
  counts: { agents: number; kbs: number; connectors: number };
};

function plural(count: number, singular: string, pluralForm: string): string {
  return `${count} ${count === 1 ? singular : pluralForm}`;
}

export default function Workspaces() {
  const { session } = useAuth();
  const [items, setItems] = useState<Workspace[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [selected, setSelected] = useState<Workspace | null>(null);
  const [toArchive, setToArchive] = useState<Workspace | null>(null);
  const [archiving, setArchiving] = useState(false);

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
      setShowCreate(false);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setBusy(false);
    }
  }

  async function archive() {
    if (!session || !toArchive) return;
    setArchiving(true);
    setError("");
    try {
      await api(`/api/v1/workspaces/${toArchive.id}`, {
        method: "DELETE",
        token: session.token,
        organizationId: session.organizationId,
      });
      setMsg(`Workspace "${toArchive.slug}" archivado.`);
      setToArchive(null);
      setSelected(null);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setArchiving(false);
    }
  }

  const columns: Column<Workspace>[] = [
    {
      key: "workspace",
      header: "Workspace",
      render: (w) => (
        <div className="min-w-0">
          <p className="truncate text-[13.5px] text-text">{w.name}</p>
          <p className="mono mt-0.5 truncate text-[11px] text-faint">{w.slug}</p>
          {w.description && (
            <p className="mt-1 line-clamp-1 max-w-[52ch] text-xs text-muted">{w.description}</p>
          )}
        </div>
      ),
    },
    {
      key: "resources",
      header: "Recursos",
      hideBelow: "md",
      render: (w) => (
        <span className="flex flex-wrap gap-1.5">
          <span className="chip">{plural(w.counts.agents, "agente", "agentes")}</span>
          <span className="chip">{plural(w.counts.kbs, "KB", "KBs")}</span>
          <span className="chip">
            {plural(w.counts.connectors, "conector", "conectores")}
          </span>
        </span>
      ),
    },
    {
      key: "status",
      header: "Estado",
      render: (w) => <StatusBadge status={w.status} />,
    },
    {
      key: "created_at",
      header: "Creado",
      hideBelow: "lg",
      render: (w) => <span className="text-xs text-muted">{fmtDateTime(w.created_at)}</span>,
    },
  ];

  return (
    <div>
      <PageHeader
        title="Workspaces"
        subtitle="Espacios de trabajo: agrupa agentes, knowledge bases y conectores."
        actions={
          <Button
            variant="primary"
            leadingIcon={showCreate ? X : Plus}
            onClick={() => setShowCreate((s) => !s)}
          >
            {showCreate ? "Cerrar alta" : "Nuevo workspace"}
          </Button>
        }
      />
      <div className="flex flex-col gap-4">
        <ErrorInline message={error} className="mb-0" />
        <SuccessInline message={msg} className="mb-0" />

        {showCreate && (
          <Panel>
            <PanelHeader
              title="Crear workspace"
              description="Los recursos que crees después pueden asignarse a este espacio."
            />
            <form
              className="panel-body flex flex-col gap-4"
              onSubmit={(e) => void create(e)}
            >
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="Nombre" hint="Se usa para generar el slug del workspace.">
                  <Input
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    autoComplete="off"
                    required
                  />
                </Field>
                <Field label="Descripción" hint="Opcional.">
                  <Input
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    autoComplete="off"
                  />
                </Field>
              </div>
              <FormActions>
                <Button
                  type="submit"
                  variant="primary"
                  leadingIcon={Plus}
                  loading={busy}
                  disabled={!name.trim()}
                >
                  Crear workspace
                </Button>
              </FormActions>
            </form>
          </Panel>
        )}

        <DataTable
          columns={columns}
          rows={items}
          rowKey={(w) => w.id}
          caption="Workspaces de la organización"
          loading={loading}
          empty={
            <EmptyState
              icon={SquaresFour}
              title="Sin workspaces"
              body="Creá tu primer workspace para separar agentes, conocimiento y conectores."
              action={
                <Button variant="primary" leadingIcon={Plus} onClick={() => setShowCreate(true)}>
                  Nuevo workspace
                </Button>
              }
            />
          }
          onRowClick={(w) => setSelected(w)}
          isRowSelected={(w) => selected?.id === w.id}
          rowActions={(w) => (
            <span className="flex items-center justify-end gap-1">
              <Button variant="ghost" size="sm" onClick={() => setSelected(w)}>
                Detalle
              </Button>
              {w.status === "active" && w.slug !== "default" && (
                <IconButton
                  label={`Archivar ${w.slug}`}
                  icon={Archive}
                  className="text-danger"
                  onClick={() => setToArchive(w)}
                />
              )}
            </span>
          )}
        />
      </div>

      <Drawer
        open={selected !== null}
        onOpenChange={(open) => {
          if (!open) setSelected(null);
        }}
        title={selected?.name ?? "Workspace"}
        description={selected?.slug}
        width={480}
      >
        {selected && <WorkspaceDetail workspace={selected} session={session} />}
      </Drawer>

      <ConfirmDialog
        open={toArchive !== null}
        onOpenChange={(open) => {
          if (!open) setToArchive(null);
        }}
        title="Archivar workspace"
        body={
          toArchive
            ? `El workspace "${toArchive.slug}" deja de estar activo. Los datos asociados se conservan según la política de retención.`
            : undefined
        }
        confirmLabel="Archivar"
        loading={archiving}
        onConfirm={() => void archive()}
      />
    </div>
  );
}

/** FASE 03 (S15): tasks + actividad del workspace (foundation colaborativo). */
function WorkspaceDetail({
  workspace,
  session,
}: {
  workspace: Workspace;
  session: Session | null;
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
    <div className="space-y-5">
      <section>
        <p className="eyebrow mb-2">Recursos</p>
        <div className="flex flex-wrap gap-1.5">
          <span className="chip">{plural(workspace.counts.agents, "agente", "agentes")}</span>
          <span className="chip">{plural(workspace.counts.kbs, "KB", "KBs")}</span>
          <span className="chip">
            {plural(workspace.counts.connectors, "conector", "conectores")}
          </span>
        </div>
        {workspace.description && (
          <p className="mt-2 text-[13px] leading-relaxed text-muted">{workspace.description}</p>
        )}
        <p className="mt-2 text-xs text-faint">Creado {fmtDateTime(workspace.created_at)}</p>
      </section>

      <section>
        <div className="mb-2 flex items-center justify-between gap-2">
          <p className="eyebrow">Tareas</p>
          <Badge tone="neutral">{tasks.length}</Badge>
        </div>
        {err && (
          <ErrorInline message={err} className="mb-3" />
        )}
        <div className="flex flex-wrap gap-2">
          <Input
            className="min-w-40 flex-1"
            aria-label="Nueva tarea"
            placeholder="Nueva tarea (ej. collect metrics)"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void create();
            }}
          />
          <Button
            variant="secondary"
            size="sm"
            disabled={busy || !title.trim()}
            onClick={() => void create()}
          >
            Crear
          </Button>
        </div>
        <div className="mt-3 space-y-1.5">
          {tasks.map((t) => (
            <div
              key={t.id}
              className="flex items-center gap-2 rounded-sm bg-soft px-2.5 py-2 text-[12px]"
            >
              <span className="min-w-0 flex-1 truncate text-text">{t.title}</span>
              {t.agent_id && <span className="mono text-[10px] text-faint">agente</span>}
              <Select
                className="min-h-8 w-auto text-[12px]"
                aria-label={`Estado de ${t.title}`}
                value={t.status}
                onChange={(e) => void setStatus(t.id, e.target.value)}
              >
                <option value="todo">Por hacer</option>
                <option value="in_progress">En curso</option>
                <option value="done">Hecho</option>
              </Select>
            </div>
          ))}
          {tasks.length === 0 && <p className="py-2 text-xs text-faint">Sin tareas.</p>}
        </div>
      </section>

      <section>
        <p className="eyebrow mb-2">Actividad</p>
        <div className="max-h-56 space-y-1.5 overflow-auto">
          {activity.map((a) => (
            <div key={a.id} className="rounded-sm bg-soft px-2.5 py-2 text-[11px]">
              <span className="text-text">{a.event_type}</span>
              {a.detail && <span className="block truncate text-faint">{a.detail}</span>}
              <span className="text-faint">{fmtDateTime(a.created_at)}</span>
            </div>
          ))}
          {activity.length === 0 && <p className="py-2 text-xs text-faint">Sin actividad.</p>}
        </div>
      </section>
    </div>
  );
}
