import { Database, Files } from "@phosphor-icons/react";
import { Link } from "react-router-dom";
import { EmptyState, SkeletonBlock } from "../ui";
import type { IngestionJob, KnowledgeSource } from "./types";

export const INDEXING_COPY =
  "Zent está leyendo el PDF, troceándolo y pasándolo a vectores. Hasta que haya documentos, el agente no puede citarlo.";

const ACTIVE_JOB = new Set(["pending", "running"]);

export function latestJobForSource(sourceId: string, jobs: IngestionJob[]): IngestionJob | undefined {
  return jobs.find((job) => job.source_id === sourceId);
}

function humanStatus(source: KnowledgeSource, job: IngestionJob | undefined): string {
  if (source.document_count > 0) return `${source.document_count} docs`;
  if (job?.status === "pending") return "En cola";
  if (job?.status === "running") return "Indexando";
  if (job?.status === "failed" || job?.status === "dead") return "Falló el indexado";
  return "Sin indexar";
}

export function AgentSourcePicker({
  sources,
  selectedIds,
  jobs,
  loading,
  indexingId,
  onToggle,
  onIndex,
}: {
  sources: KnowledgeSource[];
  selectedIds: string[];
  jobs: IngestionJob[];
  loading: boolean;
  indexingId?: string;
  onToggle: (id: string) => void;
  onIndex: (id: string) => void;
}) {
  if (loading) {
    return (
      <div className="panel p-4">
        <SkeletonBlock rows={3} />
      </div>
    );
  }

  if (sources.length === 0) {
    return (
      <EmptyState
        icon={Database}
        title="Sin fuentes cargadas"
        body="Carga documentos o conectores en Fuentes y vuelve para asignarlos a este agente."
        action={
          <Link to="/knowledge/sources" className="btn btn-secondary min-h-11">
            Cargar fuentes
          </Link>
        }
      />
    );
  }

  const waiting = sources.some((source) => selectedIds.includes(source.id) && !source.document_count);

  return (
    <fieldset>
      <legend className="mb-2 text-sm font-medium text-text">Fuentes que ya cargaste</legend>
      <p className="mb-3 text-xs text-muted">Elige con qué material responde este agente.</p>
      {waiting && (
        <p className="mb-3 text-xs text-warn" data-testid="source-indexing-copy">
          {INDEXING_COPY}
        </p>
      )}
      <div className="grid gap-2">
        {sources.map((source) => {
          const checked = selectedIds.includes(source.id);
          const job = latestJobForSource(source.id, jobs);
          const empty = !source.document_count;
          const active = Boolean(job && ACTIVE_JOB.has(job.status));
          const progress = Math.max(0, Math.min(100, job?.progress ?? 0));
          return (
            <div
              key={source.id}
              className={`flex min-h-11 items-start gap-3 rounded-md border px-3 py-2.5 ${
                checked ? "border-accent bg-accent-soft/40" : "border-border"
              }`}
            >
              <label className="flex min-w-0 flex-1 cursor-pointer items-start gap-3">
                <input
                  type="checkbox"
                  className="mt-1"
                  checked={checked}
                  onChange={() => onToggle(source.id)}
                />
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-2 text-sm font-medium text-text">
                    <Files size={14} className="text-accent" aria-hidden />
                    {source.name}
                  </span>
                  <span className="mt-0.5 block text-xs text-faint">
                    {source.type} · {humanStatus(source, job)}
                  </span>
                  {empty && active && (
                    <div className="progress-track mt-2" data-testid={`source-progress-${source.id}`}>
                      {progress > 0 ? (
                        <div className="progress-fill" style={{ width: `${progress}%` }} />
                      ) : (
                        <div className="progress-fill w-1/3 animate-pulse" />
                      )}
                    </div>
                  )}
                  {empty && !active && (
                    <span className="mt-1 block text-xs text-warn">Aún no indexada</span>
                  )}
                </span>
              </label>
              {empty && !active && (
                <button
                  type="button"
                  className="btn btn-secondary min-h-9 shrink-0 px-2 text-xs"
                  disabled={indexingId === source.id}
                  data-testid={`source-index-${source.id}`}
                  onClick={() => onIndex(source.id)}
                >
                  Indexar ahora
                </button>
              )}
            </div>
          );
        })}
      </div>
    </fieldset>
  );
}
