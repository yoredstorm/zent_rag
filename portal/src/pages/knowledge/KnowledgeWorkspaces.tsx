import { Plus, SquaresFour } from "@phosphor-icons/react";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import {
  EmptyState,
  ErrorInline,
  PageHeader,
  SkeletonBlock,
  Spinner,
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
    api<CorpusList>("/api/v1/knowledge/workspaces", {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then((data) => setCorpora(data.corpora ?? []))
      .catch((err) => setError(err instanceof Error ? err.message : "Error"))
      .finally(() => setLoading(false));
  }, [session]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <PageHeader
        title="Knowledge Workspaces"
        subtitle="El centro del conocimiento de tu organización."
      />

      {/* Hero amigable */}
      <div className="mb-6 flex flex-col gap-4 rounded-2xl border border-indigo-100 bg-gradient-to-br from-indigo-50 via-white to-white p-6 sm:flex-row sm:items-center">
        <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-indigo-600 text-white">
          <SquaresFour size={22} />
        </div>
        <div className="min-w-0 flex-1">
          <h2 className="text-base font-semibold text-zinc-900">
            Aquí se carga todo tu conocimiento
          </h2>
          <p className="mt-0.5 text-sm text-zinc-500">
            Agrupa contratos, manuales, databases y APIs en un mismo universo.
            Pregunta con citas verificables, estudia cada fuente e inspírate
            con artefactos reales.
          </p>
        </div>
        <NewWorkspaceModal session={session} onCreated={load} />
      </div>

      {error && <ErrorInline message={error} />}

      {loading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <SkeletonBlock rows={4} className="h-36" />
          <SkeletonBlock rows={4} className="h-36" />
        </div>
      ) : corpora.length === 0 ? (
        <EmptyState
          icon={SquaresFour}
          title="Empieza en 3 pasos"
          body="Crea un Knowledge Workspace, sube tus fuentes (PDF, Word, texto) y haz tu primera pregunta. Las respuestas llegan con la página y la sección exactas."
          action={
            <div className="flex flex-col items-center gap-2">
              <NewWorkspaceModal session={session} onCreated={load} />
              <Link
                to="/knowledge/sources"
                className="text-sm font-medium text-indigo-600 hover:text-indigo-500"
              >
                o añade fuentes primero (¿PDF? ¿DOCX? ¿texto?) →
              </Link>
            </div>
          }
        />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {corpora.map((corpus) => (
            <Link
              key={corpus.id}
              to={`/knowledge/workspaces/${corpus.id}`}
              className="group rounded-xl border border-zinc-200 bg-white p-5 shadow-sm transition hover:border-indigo-300 hover:shadow-md"
            >
              <div className="flex items-start justify-between gap-3">
                <h3 className="text-base font-semibold text-zinc-900 group-hover:text-indigo-700">
                  {corpus.name}
                </h3>
                <StatusBadge status={corpus.status} />
              </div>
              {corpus.description ? (
                <p className="mt-1 text-sm text-zinc-500">{corpus.description}</p>
              ) : (
                <p className="mt-1 text-sm text-zinc-400">
                  {corpus.source_count === 0
                    ? "Comienza adjuntando fuentes."
                    : "Workspace de conocimiento."}
                </p>
              )}
              <div className="mt-4 flex items-center gap-4 text-xs text-zinc-500">
                <span>
                  <strong className="text-zinc-800">{corpus.source_count}</strong>{" "}
                  sources
                </span>
                {corpus.coverage !== null ? (
                  <span>
                    <strong className="text-zinc-800">{corpus.coverage}%</strong>{" "}
                    knowledge
                  </span>
                ) : (
                  <span className="text-zinc-400">knowledge —</span>
                )}
                <span
                  className={
                    corpus.conflicts > 0 ? "font-medium text-red-600" : undefined
                  }
                >
                  {corpus.conflicts > 0
                    ? `${corpus.conflicts} ${corpus.conflicts === 1 ? "conflicto" : "conflictos"}`
                    : "sin conflictos"}
                </span>
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
        setError(err instanceof Error ? err.message : "Error al crear")
      )
      .finally(() => setCreating(false));
  };

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white shadow-sm hover:bg-indigo-500"
      >
        <Plus size={14} weight="bold" /> New Knowledge Workspace
      </button>
      {open ? (
        <div
          className="fixed inset-0 z-40 flex items-center justify-center bg-black/30 p-4"
          onClick={() => setOpen(false)}
        >
          <div
            className="w-full max-w-sm rounded-xl bg-white p-5 shadow-lg"
            onClick={(event) => event.stopPropagation()}
          >
            <h3 className="text-base font-semibold text-zinc-900">
              New Knowledge Workspace
            </h3>
            <label className="mt-4 block text-sm font-medium text-zinc-700">
              Nombre
              <input
                autoFocus
                className="mt-1 w-full rounded-lg border border-zinc-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none"
                placeholder="Ej. Operaciones Aeroméxico"
                value={name}
                onChange={(event) => setName(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") create();
                }}
              />
            </label>
            {error && (
              <p className="mt-2 text-sm text-red-600">{error}</p>
            )}
            <div className="mt-4 flex justify-end gap-2">
              <button
                onClick={() => setOpen(false)}
                className="rounded-lg border border-zinc-300 px-3 py-1.5 text-sm font-medium text-zinc-700 hover:bg-zinc-50"
              >
                Cancelar
              </button>
              <button
                disabled={!name.trim() || creating}
                onClick={create}
                className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
              >
                {creating ? <Spinner size={14} /> : "Crear"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}