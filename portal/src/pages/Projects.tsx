import { FolderPlus, Folders, Plus, Trash, X } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import {
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
  KeyValue,
  PageHeader,
  Panel,
  PanelHeader,
  SuccessInline,
  type Column,
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
  const [selected, setSelected] = useState<Project | null>(null);
  const [toRemove, setToRemove] = useState<Project | null>(null);
  const [removing, setRemoving] = useState(false);

  function load() {
    if (!session) return;
    setLoading(true);
    api<{ projects: Project[] }>("/api/v1/projects", {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then((data) => setProjects(data.projects || []))
      .catch((err) => setError(err instanceof Error ? err.message : "Error"))
      .finally(() => setLoading(false));
  }

  useEffect(load, [session]);

  async function create() {
    if (!session || !name.trim()) return;
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

  async function remove() {
    if (!session || !toRemove) return;
    setError("");
    setMsg("");
    setRemoving(true);
    try {
      await api(`/api/v1/projects/${toRemove.id}`, {
        method: "DELETE",
        token: session.token,
        organizationId: session.organizationId,
      });
      setMsg(`Proyecto "${toRemove.name}" eliminado.`);
      setToRemove(null);
      setSelected(null);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al eliminar");
    } finally {
      setRemoving(false);
    }
  }

  const columns: Column<Project>[] = [
    {
      key: "name",
      header: "Proyecto",
      render: (p) => (
        <div className="min-w-0">
          <p className="truncate text-[13.5px] text-text">{p.name}</p>
          {p.description && (
            <p className="mt-0.5 line-clamp-1 max-w-[60ch] text-xs text-muted">{p.description}</p>
          )}
        </div>
      ),
    },
    {
      key: "created_at",
      header: "Creado",
      hideBelow: "md",
      render: (p) => <span className="text-xs text-muted">{fmtDateTime(p.created_at)}</span>,
    },
  ];

  return (
    <div>
      <PageHeader
        title="Proyectos"
        subtitle="Agrupa knowledge bases, agentes y conectores dentro de tu organización."
        actions={
          <Button
            variant="primary"
            leadingIcon={showCreate ? X : FolderPlus}
            onClick={() => setShowCreate((s) => !s)}
          >
            {showCreate ? "Cerrar alta" : "Nuevo proyecto"}
          </Button>
        }
      />
      <div className="flex flex-col gap-4">
        <ErrorInline message={error} className="mb-0" />
        <SuccessInline message={msg} className="mb-0" />

        {showCreate && (
          <Panel className="border-accent/25">
            <PanelHeader
              title="Crear proyecto"
              description="Un proyecto agrupa recursos relacionados bajo el mismo alcance."
            />
            <form
              className="panel-body flex flex-col gap-4"
              onSubmit={(e) => {
                e.preventDefault();
                void create();
              }}
            >
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="Nombre">
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
                  loading={creating}
                  disabled={!name.trim()}
                >
                  Crear proyecto
                </Button>
              </FormActions>
            </form>
          </Panel>
        )}

        <DataTable
          columns={columns}
          rows={projects}
          rowKey={(p) => p.id}
          caption="Proyectos"
          loading={loading}
          empty={
            <EmptyState
              icon={Folders}
              title="Sin proyectos"
              body="Creá tu primer proyecto para organizar tus recursos."
              action={
                <Button variant="primary" leadingIcon={FolderPlus} onClick={() => setShowCreate(true)}>
                  Nuevo proyecto
                </Button>
              }
            />
          }
          onRowClick={(p) => setSelected(p)}
          isRowSelected={(p) => selected?.id === p.id}
          rowActions={(p) => (
            <span className="flex items-center justify-end gap-1">
              <Button variant="ghost" size="sm" onClick={() => setSelected(p)}>
                Detalle
              </Button>
              <IconButton
                label={`Eliminar ${p.name}`}
                icon={Trash}
                className="text-danger"
                onClick={() => setToRemove(p)}
              />
            </span>
          )}
        />
      </div>

      <Drawer
        open={selected !== null}
        onOpenChange={(open) => {
          if (!open) setSelected(null);
        }}
        title={selected?.name ?? "Proyecto"}
        description="Detalle del proyecto"
        width={440}
        footer={
          selected ? (
            <Button
              variant="danger"
              leadingIcon={Trash}
              onClick={() => setToRemove(selected)}
            >
              Eliminar proyecto
            </Button>
          ) : undefined
        }
      >
        {selected && (
          <KeyValue
            items={[
              { key: "Descripción", value: selected.description || "Sin descripción." },
              { key: "Creado", value: fmtDateTime(selected.created_at) },
              { key: "ID", value: selected.id, mono: true },
            ]}
          />
        )}
      </Drawer>

      <ConfirmDialog
        open={toRemove !== null}
        onOpenChange={(open) => {
          if (!open) setToRemove(null);
        }}
        title="Eliminar proyecto"
        body={
          toRemove
            ? `El proyecto "${toRemove.name}" y su agrupación se eliminan. Los recursos vinculados conservan sus datos.`
            : undefined
        }
        confirmLabel="Eliminar"
        loading={removing}
        onConfirm={() => void remove()}
      />
    </div>
  );
}
