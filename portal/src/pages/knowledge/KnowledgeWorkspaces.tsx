import { ArrowRight, Plus, SquaresFour } from "@phosphor-icons/react";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import {
  Badge,
  Button,
  EmptyState,
  ErrorInline,
  Field,
  Input,
  Modal,
  PageHeader,
  Panel,
  Skeleton,
  StatusBadge,
} from "../../components/ui";

type CorpusRow = {
  id: string;
  name: string;
  slug: string;
  description: string;
  status: string;
  source_count: number;
  coverage: number | null;
  conflicts: number;
  created_at: string;
};

type CorpusList = { corpora: CorpusRow[]; count: number };

export default function KnowledgeWorkspacesPage() {
  const { session } = useAuth();
  const [corpora, setCorpora] = useState<CorpusRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    if (!session) return;
    setLoading(true);
    setError("");
    api<CorpusList>("/api/v1/knowledge/workspaces", {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then((data) => setCorpora(data.corpora ?? []))
      .catch((err) =>
        setError(
          err instanceof Error
            ? err.message
            : "No pudimos cargar tus workspaces de conocimiento."
        )
      )
      .finally(() => setLoading(false));
  }, [session]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div>
      <PageHeader
        title="Knowledge Workspaces"
        subtitle="Agrupá contratos, manuales, bases de datos y APIs en universos separados. Cada workspace tiene sus propias fuentes, cobertura y conflictos."
        actions={<NewWorkspaceModal session={session} onCreated={load} />}
      />

      <ErrorInline message={error} />

      {loading ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3" aria-hidden>
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-[148px] rounded-lg" />
          ))}
        </div>
      ) : corpora.length === 0 ? (
        <Panel>
          <EmptyState
            icon={SquaresFour}
            tone="accent"
            title="Creá tu primer workspace de conocimiento"
            body="Un workspace agrupa las fuentes de un mismo tema o cliente. Dentro podés cargar PDF, Word, texto, base de datos o API, y preguntar con citas verificables."
            hint="Paso 1: creá el workspace. Paso 2: sumá fuentes. Paso 3: preguntá en el Playground."
            action={<NewWorkspaceModal session={session} onCreated={load} />}
            secondaryAction={
              <Link
                to="/knowledge/sources"
                className="text-[13px] font-medium text-muted transition-colors hover:text-text"
              >
                Ver mis fuentes
              </Link>
            }
          />
        </Panel>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {corpora.map((corpus) => (
            <Link
              key={corpus.id}
              to={`/knowledge/workspaces/${corpus.id}`}
              className="panel group flex flex-col gap-3 p-4 transition-[border-color,transform] duration-200 ease-[var(--ease-out)] hover:-translate-y-px hover:border-border-strong"
            >
              <div className="flex items-start justify-between gap-3">
                <h2 className="min-w-0 truncate text-h3">{corpus.name}</h2>
                <StatusBadge status={corpus.status} />
              </div>

              <p className="line-clamp-2 min-h-9 text-[12.5px] leading-relaxed text-muted">
                {corpus.description ||
                  (corpus.source_count === 0
                    ? "Todavía no tiene fuentes: empezá adjuntando una."
                    : "Workspace de conocimiento.")}
              </p>

              <div className="mt-auto flex flex-wrap items-center gap-x-4 gap-y-1.5 border-t border-border-soft pt-3 text-xs text-muted">
                <span>
                  <span className="mono text-text">{corpus.source_count}</span>{" "}
                  {corpus.source_count === 1 ? "fuente" : "fuentes"}
                </span>
                {corpus.coverage !== null ? (
                  <span>
                    cobertura <span className="mono text-text">{corpus.coverage}%</span>
                  </span>
                ) : (
                  <span className="text-faint">cobertura —</span>
                )}
                {corpus.conflicts > 0 ? (
                  <Badge tone="warn">
                    {corpus.conflicts} {corpus.conflicts === 1 ? "conflicto" : "conflictos"}
                  </Badge>
                ) : (
                  <span className="text-faint">sin conflictos</span>
                )}
                <ArrowRight
                  size={14}
                  className="ml-auto text-ghost transition-transform duration-200 group-hover:translate-x-0.5 group-hover:text-muted"
                  aria-hidden
                />
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

function NewWorkspaceModal({
  session,
  onCreated,
}: {
  session: { token?: string; organizationId: string } | null;
  onCreated: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");

  const create = () => {
    if (!session || !name.trim()) return;
    setCreating(true);
    setError("");
    api<{ corpus: CorpusRow }>("/api/v1/knowledge/workspaces", {
      token: session.token,
      organizationId: session.organizationId,
      method: "POST",
      body: JSON.stringify({ name: name.trim() }),
    })
      .then(() => {
        setName("");
        setOpen(false);
        onCreated();
      })
      .catch((err) =>
        setError(err instanceof Error ? err.message : "No pudimos crear el workspace.")
      )
      .finally(() => setCreating(false));
  };

  return (
    <>
      <Button variant="primary" leadingIcon={Plus} onClick={() => setOpen(true)}>
        Nuevo workspace
      </Button>
      <Modal
        open={open}
        onOpenChange={(next) => {
          setOpen(next);
          if (!next) setError("");
        }}
        title="Nuevo workspace de conocimiento"
        description="Después vas a poder sumarle fuentes y colecciones."
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={() => setOpen(false)} disabled={creating}>
              Cancelar
            </Button>
            <Button
              variant="primary"
              onClick={create}
              loading={creating}
              disabled={!name.trim()}
            >
              Crear
            </Button>
          </>
        }
      >
        <Field
          label="Nombre"
          hint="Usá un nombre que reconozcas, por ejemplo el cliente o el área."
          error={error || undefined}
        >
          <Input
            autoFocus
            placeholder="Ej. Operaciones Aeroméxico"
            value={name}
            onChange={(event) => setName(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") create();
            }}
          />
        </Field>
      </Modal>
    </>
  );
}
