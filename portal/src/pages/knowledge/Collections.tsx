import { Database, Plus, Trash, X } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { api } from "../../api";
import { useAuth } from "../../auth";
import {
  Button,
  DataTable,
  EmptyState,
  ErrorInline,
  Field,
  FormActions,
  IconButton,
  Input,
  PageHeader,
  Panel,
  PanelHeader,
  ResultCount,
  StatusBadge,
  SuccessInline,
  type Column,
} from "../../components/ui";
import { fmtDateTime } from "../../lib/format";
import { KnowledgeLayout } from "../../components/KnowledgeLayout";
import { KNOWLEDGE_HEADINGS } from "../../lib/knowledgeNav";

type KB = {
  id: string;
  name: string;
  description: string | null;
  project_id: string | null;
  status: string;
  embedding_model: string | null;
  created_at: string;
};

export default function KnowledgeBasesPage() {
  const { session } = useAuth();
  const [kbs, setKbs] = useState<KB[]>([]);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [msg, setMsg] = useState("");
  const [showCreate, setShowCreate] = useState(false);

  function load() {
    if (!session) return;
    setLoading(true);
    setLoadError("");
    api<{ knowledge_bases: KB[] }>("/api/v1/knowledge-bases", {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then((data) => setKbs(data.knowledge_bases))
      .catch((err) => setLoadError(err instanceof Error ? err.message : "Error"))
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
      setMsg(`Colección «${kbName}» eliminada con sus vectores.`);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al eliminar");
    }
  }

  const columns: Column<KB>[] = [
    {
      key: "name",
      header: "Colección",
      render: (kb) => (
        <div className="min-w-0">
          <p className="truncate text-[13.5px] text-text">{kb.name}</p>
          {kb.description ? (
            <p className="mt-0.5 line-clamp-1 text-xs text-muted">{kb.description}</p>
          ) : null}
        </div>
      ),
    },
    {
      key: "status",
      header: "Estado",
      render: (kb) => <StatusBadge status={kb.status} />,
    },
    {
      key: "embedding_model",
      header: "Modelo",
      hideBelow: "md",
      render: (kb) =>
        kb.embedding_model ? (
          <span className="mono text-xs text-muted">{kb.embedding_model}</span>
        ) : (
          <span className="text-xs text-faint">—</span>
        ),
    },
    {
      key: "created_at",
      header: "Creada",
      hideBelow: "lg",
      render: (kb) => <span className="text-xs text-muted">{fmtDateTime(kb.created_at)}</span>,
    },
  ];

  return (
    <KnowledgeLayout>
      <PageHeader
        title={KNOWLEDGE_HEADINGS.collections}
        subtitle="Bases de conocimiento vectorizadas. Al eliminarlas se purgan sus vectores de Qdrant (solo los de tu organización)."
        actions={
          <Button
            variant="primary"
            leadingIcon={showCreate ? X : Plus}
            onClick={() => setShowCreate((s) => !s)}
          >
            {showCreate ? "Cerrar alta" : "Nueva colección"}
          </Button>
        }
      />

      <div className="flex flex-col gap-4">
        <ErrorInline message={error} className="mb-0" />
        <SuccessInline message={msg} className="mb-0" />

        {showCreate && (
          <Panel>
            <PanelHeader
              title="Crear colección"
              description="Agrupa documentos y vectores bajo un mismo contexto de recuperación."
              actions={
                <IconButton label="Cerrar alta de colección" icon={X} onClick={() => setShowCreate(false)} />
              }
            />
            <form
              className="panel-body flex flex-col gap-3"
              onSubmit={(e) => {
                e.preventDefault();
                void create();
              }}
            >
              <Field label="Nombre">
                <Input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  autoComplete="off"
                  required
                />
              </Field>
              <Field label="Descripción" hint="Opcional. Ayuda a elegir la colección al crear agentes.">
                <Input
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  autoComplete="off"
                />
              </Field>
              <FormActions>
                <Button
                  type="submit"
                  variant="primary"
                  leadingIcon={Plus}
                  loading={creating}
                  disabled={!name.trim()}
                >
                  Crear
                </Button>
              </FormActions>
            </form>
          </Panel>
        )}

        <DataTable
          columns={columns}
          rows={kbs}
          rowKey={(kb) => kb.id}
          caption="Colecciones de conocimiento"
          loading={loading}
          error={loadError || null}
          empty={
            <EmptyState
              icon={Database}
              title="Sin colecciones"
              body="Crea tu primera colección para organizar tus datos."
              action={
                <Button variant="primary" leadingIcon={Plus} onClick={() => setShowCreate(true)}>
                  Nueva colección
                </Button>
              }
            />
          }
          rowActions={(kb) => (
            <IconButton
              label={`Eliminar ${kb.name}`}
              icon={Trash}
              className="text-danger"
              onClick={() => void remove(kb.id, kb.name)}
            />
          )}
          footer={
            kbs.length > 0 ? (
              <ResultCount shown={kbs.length} total={kbs.length} noun="colecciones" />
            ) : undefined
          }
        />
      </div>
    </KnowledgeLayout>
  );
}
